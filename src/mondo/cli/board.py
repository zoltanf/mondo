"""`mondo board` command group: CRUD for monday boards.

Phase 2a — boards. Page-based pagination (not cursor). monday's `boards` query
has no server-side name filter, so `--name-contains` / `--name-matches` are
applied client-side after retrieval.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any

import typer

from mondo.api.errors import MondoError
from mondo.api.pagination import MAX_BOARDS_PAGE_SIZE
from mondo.api.queries import (
    BOARD_ARCHIVE,
    BOARD_CREATE,
    BOARD_DELETE,
    BOARD_DUPLICATE,
    BOARD_GET,
    BOARD_ITEMS_COUNT,
    BOARD_SET_PERMISSION,
    BOARD_UPDATE,
    BOARD_UPDATE_HIERARCHY,
)
from mondo.cli._examples import epilog_for
from mondo.cli._exec import client_or_exit, execute, execute_read, handle_mondo_error_or_exit
from mondo.cli._json_flag import parse_json_flag
from mondo.cli._resolve import resolve_required_id
from mondo.cli._url import MondayIdParam
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


class BoardKind(StrEnum):
    public = "public"
    private = "private"
    share = "share"


class BoardState(StrEnum):
    active = "active"
    archived = "archived"
    deleted = "deleted"
    all = "all"


class BoardOrderBy(StrEnum):
    used_at = "used_at"
    created_at = "created_at"


class BoardTypeFilter(StrEnum):
    """`--type` selector on `board list`.

    monday's `boards()` query returns both real boards and workdoc-backing
    boards (monday models every workdoc as a board with `type=="document"`).
    The CLI hides docs by default; pass `--type doc` to list only docs, or
    `--type all` to see everything including non-standard types such as
    `sub_items_board` and `custom_object`.
    """

    board = "board"
    doc = "doc"
    all = "all"


# Mapping from CLI filter → monday's `Board.type` server value.
_BOARD_TYPE_SERVER_VALUE: dict[BoardTypeFilter, str] = {
    BoardTypeFilter.board: "board",
    BoardTypeFilter.doc: "document",
}


def _type_matches(entry: dict[str, Any], type_filter: BoardTypeFilter) -> bool:
    """Return True when `entry` should pass the `--type` filter.

    Entries cached before schema_version 2 lack `type`; we don't want those
    to silently disappear under `--type board` (the common default). The
    schema_version bump forces a one-off refresh so this branch should only
    matter in the edge case of an in-memory fetch before the cache is warm.
    Treat missing as `"board"` to keep behavior predictable.
    """
    if type_filter is BoardTypeFilter.all:
        return True
    observed = entry.get("type") or "board"
    return observed == _BOARD_TYPE_SERVER_VALUE[type_filter]


class BoardAttribute(StrEnum):
    name = "name"
    description = "description"
    communication = "communication"
    item_nickname = "item_nickname"


class DuplicateType(StrEnum):
    with_structure = "duplicate_board_with_structure"
    with_pulses = "duplicate_board_with_pulses"
    with_pulses_and_updates = "duplicate_board_with_pulses_and_updates"


class BoardBasicRole(StrEnum):
    viewer = "viewer"
    contributor = "contributor"
    editor = "editor"


# ----- helpers -----


def _resolve_source_workspace(opts: GlobalOpts, board_id: int) -> int | None:
    """Look up the source board's workspace to default the duplicate destination."""
    data = execute_read(opts, BOARD_GET, {"id": board_id})
    boards = data.get("boards") or []
    if not boards:
        typer.secho(
            f"error: source board {board_id} not found (cannot resolve workspace).",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)
    ws = boards[0].get("workspace_id")
    if ws in (None, ""):
        return None
    try:
        return int(ws)
    except (TypeError, ValueError):
        return None


def _decode_json_string_payload(value: Any) -> Any:
    """Parse monday's legacy stringified-JSON mutation payloads when possible."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


# ----- read commands -----


@app.command("list", epilog=epilog_for("board list"))
def list_cmd(
    ctx: typer.Context,
    state: BoardState | None = typer.Option(
        None,
        "--state",
        help="Filter by state (default: active).",
        case_sensitive=False,
        rich_help_panel="Filters",
    ),
    kind: BoardKind | None = typer.Option(
        None,
        "--kind",
        help="Filter by board kind.",
        case_sensitive=False,
        rich_help_panel="Filters",
    ),
    type_filter: BoardTypeFilter = typer.Option(
        BoardTypeFilter.board,
        "--type",
        help=(
            "Filter by Board.type — `board` (default) hides workdocs; "
            "`doc` lists only workdoc-backing boards; `all` includes every type."
        ),
        case_sensitive=False,
        rich_help_panel="Filters",
    ),
    workspace: list[int] | None = typer.Option(
        None,
        "--workspace",
        help="Restrict to workspace IDs (repeatable).",
        rich_help_panel="Filters",
    ),
    order_by: BoardOrderBy | None = typer.Option(
        None,
        "--order-by",
        help="Sort order.",
        case_sensitive=False,
        rich_help_panel="Filters",
    ),
    name_contains: str | None = typer.Option(
        None,
        "--name-contains",
        help="Client-side substring filter on board name (case-insensitive).",
        rich_help_panel="Filters",
    ),
    name_matches: str | None = typer.Option(
        None,
        "--name-matches",
        help="Client-side regex filter on board name.",
        rich_help_panel="Filters",
    ),
    name_fuzzy: str | None = typer.Option(
        None,
        "--name-fuzzy",
        help="Client-side fuzzy filter on board name (tolerates typos).",
        rich_help_panel="Filters",
    ),
    fuzzy_threshold: int | None = typer.Option(
        None,
        "--fuzzy-threshold",
        help="Minimum fuzzy match score (0-100). Defaults to config/70.",
        rich_help_panel="Filters",
    ),
    fuzzy_score_flag: bool = typer.Option(
        False,
        "--fuzzy-score",
        help="Include `_fuzzy_score` field and sort by score desc.",
        rich_help_panel="Filters",
    ),
    limit: int = typer.Option(
        MAX_BOARDS_PAGE_SIZE,
        "--limit",
        help=f"Page size for live fetches (max {MAX_BOARDS_PAGE_SIZE}); ignored when served from cache.",
        rich_help_panel="Pagination",
    ),
    max_items: int | None = typer.Option(
        None,
        "--max-items",
        help="Stop after this many boards total.",
        rich_help_panel="Pagination",
    ),
    with_item_counts: bool = typer.Option(
        False,
        "--with-item-counts",
        help="Include items_count per board (bypasses cache; ~500k complexity per 100 boards).",
    ),
    with_url: bool = typer.Option(
        False,
        "--with-url",
        help="Include a synthesized `url` field on every emitted board.",
    ),
    with_tags: bool = typer.Option(
        False,
        "--with-tags",
        help="Include each board's `tags { id name color }` (bypasses cache).",
    ),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Skip the local directory cache; fetch live.",
        rich_help_panel="Cache",
    ),
    refresh_cache: bool = typer.Option(
        False,
        "--refresh-cache",
        help="Force-refresh the local directory cache before serving.",
        rich_help_panel="Cache",
    ),
    explain_cache: bool = typer.Option(
        False,
        "--explain-cache",
        help="Print verbose cache provenance to stderr (path, ttl, fetched_at).",
        rich_help_panel="Cache",
    ),
) -> None:
    """List boards.

    Use --name-contains / --name-matches / --name-fuzzy to narrow down,
    --workspace to restrict to a workspace, and --state to include archived
    boards. Served from the local directory cache when available.
    """
    from mondo.api.errors import UsageError
    from mondo.api.pagination import iter_boards_page
    from mondo.api.queries import build_boards_list_query
    from mondo.cli._cache_flags import reject_mutually_exclusive, resolve_cache_prefs
    from mondo.cli._filters import apply_fuzzy, compile_name_filter
    from mondo.cli._filters import name_matches as _name_matches
    from mondo.cli._list_decorate import apply_board_urls, enrich_workspaces_best_effort
    from mondo.cli._normalize import normalize_board_entry

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    reject_mutually_exclusive(no_cache, refresh_cache)

    try:
        needle_lower, pattern = compile_name_filter(name_contains, name_matches, name_fuzzy)
    except UsageError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from e

    prefs = resolve_cache_prefs(
        opts,
        no_cache=no_cache,
        fuzzy_threshold=fuzzy_threshold,
        # `--with-tags` and `--with-item-counts` extend the selection set
        # past what the cache stores, so they always need a live fetch.
        extra_disable=with_item_counts or with_tags,
    )

    if prefs.use_cache:
        _list_via_cache(
            opts,
            state=state,
            kind=kind,
            type_filter=type_filter,
            workspace=workspace,
            order_by=order_by,
            needle_lower=needle_lower,
            pattern=pattern,
            name_fuzzy=name_fuzzy,
            fuzzy_threshold=prefs.fuzzy_threshold,
            fuzzy_score_flag=fuzzy_score_flag,
            max_items=max_items,
            refresh=refresh_cache,
            explain_cache=explain_cache,
            with_url=with_url,
        )
        return

    # Live path — preserves pre-cache behavior byte-for-byte.
    query, variables = build_boards_list_query(
        state=state.value if state else None,
        kind=kind.value if kind else None,
        workspace_ids=workspace or None,
        order_by=order_by.value if order_by else None,
        with_item_counts=with_item_counts,
        with_tags=with_tags,
    )

    if opts.dry_run:
        opts.emit(
            {
                "query": query,
                "variables": {
                    **variables,
                    "limit": limit,
                    "max_items": max_items,
                    "name_contains": name_contains,
                    "name_matches": name_matches,
                    "name_fuzzy": name_fuzzy,
                },
            }
        )
        raise typer.Exit(0)

    client = client_or_exit(opts)

    try:
        with client:
            boards = [
                b
                for b in (
                    normalize_board_entry(entry)
                    for entry in iter_boards_page(
                        client,
                        query=query,
                        variables=variables,
                        limit=limit,
                        max_items=None,  # client-side filters applied below
                    )
                )
                if _type_matches(b, type_filter) and _name_matches(b, needle_lower, pattern)
            ]
    except MondoError as e:
        handle_mondo_error_or_exit(e)

    if name_fuzzy is not None:
        boards = apply_fuzzy(
            boards,
            name_fuzzy,
            threshold=prefs.fuzzy_threshold,
            include_score=fuzzy_score_flag,
        )

    if max_items is not None:
        boards = boards[:max_items]

    # --no-cache opts the user out of cache writes, so skip the workspace
    # enrichment step (which would transparently populate workspaces.json).
    if prefs.cfg.enabled and not no_cache:
        enrich_workspaces_best_effort(boards, opts)

    if with_url:
        apply_board_urls(boards, opts)

    # Re-normalize last so optional decorators don't break key-order invariants.
    boards = [normalize_board_entry(b) for b in boards]
    from mondo.cli._field_sets import board_list_fields

    opts.emit(
        boards,
        selected_fields=board_list_fields(
            with_item_counts=with_item_counts, with_tags=with_tags
        ),
    )


def _list_via_cache(
    opts: GlobalOpts,
    *,
    state: BoardState | None,
    kind: BoardKind | None,
    type_filter: BoardTypeFilter,
    workspace: list[int] | None,
    order_by: BoardOrderBy | None,
    needle_lower: str | None,
    pattern: re.Pattern[str] | None,
    name_fuzzy: str | None,
    fuzzy_threshold: int,
    fuzzy_score_flag: bool,
    max_items: int | None,
    refresh: bool,
    explain_cache: bool,
    with_url: bool,
) -> None:
    """Serve `board list` from the local directory cache.

    The cache stores the full unfiltered directory; every filter here runs
    client-side against that list.
    """
    from mondo.cache.directory import get_boards as cache_get_boards
    from mondo.cli._filters import apply_fuzzy
    from mondo.cli._filters import name_matches as _name_matches
    from mondo.cli._list_decorate import apply_board_urls, enrich_workspaces_best_effort
    from mondo.cli._normalize import normalize_board_entry

    if opts.dry_run:
        opts.emit(
            {
                "cache": "boards",
                "refresh": refresh,
                "filters": {
                    "state": state.value if state else None,
                    "kind": kind.value if kind else None,
                    "type": type_filter.value,
                    "workspace_ids": workspace or None,
                    "order_by": order_by.value if order_by else None,
                    "name_fuzzy": name_fuzzy,
                    "fuzzy_threshold": fuzzy_threshold,
                    "max_items": max_items,
                },
            }
        )
        raise typer.Exit(0)

    client = client_or_exit(opts)
    try:
        store = opts.build_cache_store("boards")
    except MondoError as e:
        handle_mondo_error_or_exit(e)

    try:
        with client:
            cached = cache_get_boards(client, store=store, refresh=refresh)
    except MondoError as e:
        handle_mondo_error_or_exit(e)

    from mondo.cli._cache_flags import emit_cache_provenance

    emit_cache_provenance(opts, cached, store=store, explain=explain_cache)

    # Spec default for boards list is "active" when --state omitted. Preserve that
    # client-side since the cache holds all states.
    requested_state = state.value if state else "active"
    entries = cached.entries
    if requested_state != "all":
        entries = [b for b in entries if (b.get("state") or "active") == requested_state]
    if kind is not None:
        entries = [b for b in entries if (b.get("kind") or "") == kind.value]
    if type_filter is not BoardTypeFilter.all:
        entries = [b for b in entries if _type_matches(b, type_filter)]
    if workspace:
        wanted = {str(w) for w in workspace}
        entries = [b for b in entries if str(b.get("workspace_id") or "") in wanted]
    entries = [b for b in entries if _name_matches(b, needle_lower, pattern)]

    if order_by is not None:
        reverse = True
        key = order_by.value
        entries = sorted(entries, key=lambda b: b.get(key) or "", reverse=reverse)

    if name_fuzzy is not None:
        entries = apply_fuzzy(
            entries,
            name_fuzzy,
            threshold=fuzzy_threshold,
            include_score=fuzzy_score_flag,
        )

    if max_items is not None:
        entries = entries[:max_items]

    enrich_workspaces_best_effort(entries, opts)
    if with_url:
        apply_board_urls(entries, opts)

    # Re-normalize last so optional decorators don't break key-order invariants.
    entries = [normalize_board_entry(b) for b in entries]
    from mondo.cli._field_sets import board_list_fields

    opts.emit(entries, selected_fields=board_list_fields())


@app.command("get", epilog=epilog_for("board get"))
def get_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(
        None,
        metavar="[ID|URL]",
        help="Board ID or monday.com URL (positional).",
        click_type=MondayIdParam(),
    ),
    id_flag: int | None = typer.Option(
        None,
        "--id",
        "--board",
        help="Board ID or monday.com URL.",
        click_type=MondayIdParam(),
    ),
    with_url: bool = typer.Option(
        False,
        "--with-url",
        help="Include a synthesized `url` field in the emitted payload.",
    ),
    with_views: bool = typer.Option(
        False,
        "--with-views",
        help="Also fetch the board's `views { id name type settings_str }` array.",
    ),
) -> None:
    """Fetch a single board by ID with columns, groups, and subscribers."""
    from mondo.api.queries import BOARD_GET_WITH_VIEWS
    from mondo.cli._normalize import normalize_board_entry
    from mondo.cli._url import board_url, get_tenant_slug, warn_cross_type

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    board_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="board")
    query = BOARD_GET_WITH_VIEWS if with_views else BOARD_GET
    data = execute(opts, query, {"id": board_id})
    boards = data.get("boards") or []
    if not boards:
        typer.secho(f"board {board_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
    board = boards[0]
    warn_cross_type(board, expected="board", id_=board_id)
    if with_url:
        client = client_or_exit(opts)
        with client:
            board = {**board, "url": board_url(get_tenant_slug(client), board_id)}
    board = normalize_board_entry(board)
    from mondo.cli._field_sets import board_get_fields

    opts.emit(board, selected_fields=board_get_fields(with_views=with_views))


# ----- write commands -----


@app.command("create", epilog=epilog_for("board create"))
def create_cmd(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Board name."),
    kind: BoardKind = typer.Option(
        BoardKind.public,
        "--kind",
        help="Board kind (public/private/share).",
        case_sensitive=False,
    ),
    description: str | None = typer.Option(None, "--description"),
    workspace: int | None = typer.Option(None, "--workspace", help="Target workspace ID."),
    folder: int | None = typer.Option(None, "--folder", help="Target folder ID."),
    template: int | None = typer.Option(None, "--template", help="Clone from template board ID."),
    owner: list[int] | None = typer.Option(None, "--owner", help="Owner user ID (repeatable)."),
    owner_team: list[int] | None = typer.Option(
        None, "--owner-team", help="Owner team ID (repeatable)."
    ),
    subscriber: list[int] | None = typer.Option(
        None, "--subscriber", help="Subscriber user ID (repeatable)."
    ),
    subscriber_team: list[int] | None = typer.Option(
        None, "--subscriber-team", help="Subscriber team ID (repeatable)."
    ),
    empty: bool = typer.Option(
        False, "--empty", help="Create without the default group/column structure."
    ),
) -> None:
    """Create a new board."""
    from mondo.cli._cache_invalidate import invalidate_entity
    from mondo.cli._normalize import normalize_board_entry

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables: dict[str, Any] = {
        "name": name,
        "kind": kind.value,
        "description": description,
        "folder": folder,
        "workspace": workspace,
        "template": template,
        "ownerIds": owner or None,
        "ownerTeamIds": owner_team or None,
        "subscriberIds": subscriber or None,
        "subscriberTeamIds": subscriber_team or None,
        "empty": True if empty else None,
    }
    data = execute(opts, BOARD_CREATE, variables)
    invalidate_entity(opts, "boards")
    opts.emit(normalize_board_entry(data.get("create_board") or {}))


@app.command("update", epilog=epilog_for("board update"))
def update_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Board ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--board", help="Board ID (flag form)."),
    attribute: BoardAttribute = typer.Option(
        ...,
        "--attribute",
        help="Attribute to update (name/description/communication/item_nickname).",
        case_sensitive=False,
    ),
    value: str = typer.Option(..., "--value", help="New value for the attribute."),
) -> None:
    """Update a single board attribute."""
    from mondo.cli._cache_invalidate import invalidate_entity

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    board_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="board")
    data = execute(
        opts,
        BOARD_UPDATE,
        {"board": board_id, "attribute": attribute.value, "value": value},
    )
    invalidate_entity(opts, "boards")
    opts.emit(_decode_json_string_payload(data.get("update_board")))


@app.command("set-permission", epilog=epilog_for("board set-permission"))
def set_permission_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Board ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--board", help="Board ID (flag form)."),
    role: BoardBasicRole = typer.Option(
        ...,
        "--role",
        help="Default board role (viewer/contributor/editor).",
        case_sensitive=False,
    ),
) -> None:
    """Set the board's default permissions/role."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    board_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="board")
    data = execute(opts, BOARD_SET_PERMISSION, {"board": board_id, "role": role.value})
    opts.emit(data.get("set_board_permission") or {})


@app.command("move", epilog=epilog_for("board move"))
def move_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Board ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--board", help="Board ID (flag form)."),
    workspace: int | None = typer.Option(None, "--workspace", help="Target workspace ID."),
    folder: int | None = typer.Option(None, "--folder", help="Target folder ID."),
    product_id: int | None = typer.Option(
        None, "--product-id", help="Account product ID (if multi-product)."
    ),
    position: str | None = typer.Option(
        None,
        "--position",
        metavar="JSON",
        help='Position as JSON: `{"object_id":15,"object_type":"Overview","is_after":true}`.',
    ),
) -> None:
    """Move a board by updating its workspace, folder, product, or position."""
    from mondo.cli._cache_invalidate import invalidate_entity

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    board_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="board")
    position_obj: Any = None
    if position is not None:
        position_obj = parse_json_flag(position, flag_name="--position")
    attributes: dict[str, Any] = {}
    if workspace is not None:
        attributes["workspace_id"] = workspace
    if folder is not None:
        attributes["folder_id"] = folder
    if product_id is not None:
        attributes["account_product_id"] = product_id
    if position_obj is not None:
        attributes["position"] = position_obj
    if not attributes:
        typer.secho(
            "error: pass at least one of --workspace, --folder, --product-id, or --position.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    data = execute(opts, BOARD_UPDATE_HIERARCHY, {"board": board_id, "attributes": attributes})
    invalidate_entity(opts, "boards")
    opts.emit(data.get("update_board_hierarchy") or {})


@app.command("archive", epilog=epilog_for("board archive"))
def archive_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Board ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--board", help="Board ID (flag form)."),
) -> None:
    """Archive a board (reversible via monday UI within 30 days)."""
    from mondo.cli._cache_invalidate import invalidate_entity
    from mondo.cli._confirm import confirm_or_abort as _confirm

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    board_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="board")
    _confirm(opts, f"Archive board {board_id}?")
    data = execute(opts, BOARD_ARCHIVE, {"board": board_id})
    invalidate_entity(opts, "boards")
    opts.emit(data.get("archive_board") or {})


@app.command("delete", epilog=epilog_for("board delete"))
def delete_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Board ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--board", help="Board ID (flag form)."),
    hard: bool = typer.Option(
        False, "--hard", help="Required for permanent deletion (paired with --yes)."
    ),
) -> None:
    """Delete a board (permanent — prefer `archive` unless --hard is passed)."""
    from mondo.cli._cache_invalidate import invalidate_entity
    from mondo.cli._confirm import confirm_or_abort as _confirm

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    board_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="board")
    if not hard:
        typer.secho(
            "refusing to delete without --hard. Use `mondo board archive` for "
            "reversible removal, or pass --hard to confirm permanent deletion.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=2)
    _confirm(opts, f"PERMANENTLY delete board {board_id}?")
    data = execute(opts, BOARD_DELETE, {"board": board_id})
    invalidate_entity(opts, "boards")
    opts.emit(data.get("delete_board") or {})


@app.command("duplicate", epilog=epilog_for("board duplicate"))
def duplicate_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Board ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--board", help="Board ID (flag form)."),
    duplicate_type: DuplicateType = typer.Option(
        DuplicateType.with_structure,
        "--type",
        help="What to copy: structure only, +pulses, or +pulses+updates.",
        case_sensitive=False,
    ),
    name: str | None = typer.Option(None, "--name", help="Name of the new board."),
    workspace: int | None = typer.Option(
        None,
        "--workspace",
        help="Target workspace ID (defaults to the source board's workspace).",
    ),
    folder: int | None = typer.Option(None, "--folder", help="Target folder ID."),
    keep_subscribers: bool = typer.Option(
        False, "--keep-subscribers", help="Carry subscribers over to the copy."
    ),
    wait: bool = typer.Option(
        False,
        "--wait",
        help="Poll the new board's items_count until it stabilises (matches the "
        "source board's count, or stops growing). Exits with code 8 on timeout.",
    ),
    timeout_s: int = typer.Option(
        300,
        "--timeout",
        metavar="SECONDS",
        help="Timeout for --wait (default: 300s).",
    ),
    poll_interval_s: float = typer.Option(
        2.0,
        "--poll-interval",
        metavar="SECONDS",
        help="Poll interval for --wait (default: 2s).",
    ),
) -> None:
    """Duplicate a board (async — response may be partial).

    When --workspace is omitted, the copy lands in the source board's workspace.
    (monday's API default otherwise drops it into the caller's main workspace.)
    Pass --wait to block until the copy's items_count stabilises; useful in
    scripts that depend on the copy being fully populated before the next step.
    """
    from mondo.cli._cache_invalidate import invalidate_entity
    from mondo.cli._normalize import normalize_board_entry

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    board_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="board")
    if workspace is None:
        workspace = _resolve_source_workspace(opts, board_id)
    variables: dict[str, Any] = {
        "board": board_id,
        "duplicateType": duplicate_type.value,
        "name": name,
        "workspace": workspace,
        "folder": folder,
        "keepSubscribers": True if keep_subscribers else None,
    }
    data = execute(opts, BOARD_DUPLICATE, variables)
    invalidate_entity(opts, "boards")
    duplicate_payload = data.get("duplicate_board") or {}

    if wait:
        board_payload = (duplicate_payload.get("board") or {}) if duplicate_payload else {}
        dup_id_raw = board_payload.get("id")
        if dup_id_raw is None:
            typer.secho(
                "error: duplicate_board returned no board id — cannot poll for completion.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=1)
        try:
            dup_id = int(dup_id_raw)
        except (TypeError, ValueError):
            typer.secho(
                f"error: duplicate_board returned non-integer id {dup_id_raw!r}.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=1) from None
        # Structure-only duplicates never copy items, so the target is 0 by
        # definition — using the source's count would mismatch and force the
        # stall-counter path to terminate the wait, which is correct but
        # confusing for callers reading the response.
        if duplicate_type is DuplicateType.with_structure:
            expected_count: int | None = 0
        else:
            expected_count = _items_count_or_none(opts, board_id)
        client = client_or_exit(opts)
        try:
            from mondo.api.polling import wait_for_items_count_stable

            with client:
                final_count = wait_for_items_count_stable(
                    client,
                    dup_id,
                    target=expected_count,
                    timeout_s=float(timeout_s),
                    interval_s=poll_interval_s,
                )
        except MondoError as e:
            handle_mondo_error_or_exit(e)
        matched = expected_count is not None and final_count == expected_count
        duplicate_payload = {
            **duplicate_payload,
            "_wait": {
                "final_items_count": final_count,
                "expected": expected_count,
                "matched": matched,
            },
        }

    board_payload = duplicate_payload.get("board")
    if isinstance(board_payload, dict):
        duplicate_payload["board"] = normalize_board_entry(board_payload)

    opts.emit(duplicate_payload)


def _items_count_or_none(opts: GlobalOpts, board_id: int) -> int | None:
    data = execute_read(opts, BOARD_ITEMS_COUNT, {"ids": [board_id]})
    boards = data.get("boards") or []
    if not boards:
        return None
    raw = boards[0].get("items_count")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
