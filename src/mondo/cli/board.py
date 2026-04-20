"""`mondo board` command group: CRUD for monday boards.

Phase 2a — boards. Page-based pagination (not cursor). monday's `boards` query
has no server-side name filter, so `--name-contains` / `--name-matches` are
applied client-side after retrieval.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError, UsageError
from mondo.api.pagination import MAX_BOARDS_PAGE_SIZE, iter_boards_page
from mondo.api.polling import wait_for_items_count_stable
from mondo.api.queries import (
    BOARD_ARCHIVE,
    BOARD_CREATE,
    BOARD_DELETE,
    BOARD_DUPLICATE,
    BOARD_GET,
    BOARD_ITEMS_COUNT,
    BOARD_UPDATE,
    build_boards_list_query,
)
from mondo.cache.directory import get_boards as cache_get_boards
from mondo.cache.fuzzy import fuzzy_score
from mondo.cli._confirm import confirm_or_abort as _confirm
from mondo.cli._examples import epilog_for
from mondo.cli._resolve import resolve_required_id
from mondo.cli._url import MondayIdParam, board_url, get_tenant_slug, warn_cross_type
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


# ----- helpers -----


def _dispatch_dry_run(opts: GlobalOpts, query: str, variables: dict[str, Any]) -> None:
    opts.emit({"query": query, "variables": variables})
    raise typer.Exit(0)


def _execute_mutation(opts: GlobalOpts, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    if opts.dry_run:
        _dispatch_dry_run(opts, query, variables)
    return _execute_query(opts, query, variables)


def _execute_query(opts: GlobalOpts, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    """Run a query unconditionally (read-only — bypasses dry-run short-circuit)."""
    try:
        client = opts.build_client()
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    try:
        with client:
            return _run(client, query, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e


def _resolve_source_workspace(opts: GlobalOpts, board_id: int) -> int | None:
    """Look up the source board's workspace to default the duplicate destination."""
    data = _execute_query(opts, BOARD_GET, {"id": board_id})
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


def _run(client: MondayClient, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    result = client.execute(query, variables=variables)
    return result.get("data") or {}


def _compile_name_filter(
    name_contains: str | None,
    name_matches: str | None,
    name_fuzzy: str | None = None,
) -> tuple[str | None, re.Pattern[str] | None]:
    """Validate mutex on the three name-filter flags and compile the regex.

    `name_fuzzy` is applied separately (see `_apply_fuzzy`); we only validate
    here that no more than one of the three name filters is active.
    """
    active = sum(bool(x) for x in (name_contains, name_matches, name_fuzzy))
    if active > 1:
        raise UsageError(
            "pass only one of --name-contains / --name-matches / --name-fuzzy."
        )
    pattern: re.Pattern[str] | None = None
    if name_matches:
        try:
            pattern = re.compile(name_matches)
        except re.error as exc:
            raise UsageError(f"invalid --name-matches regex: {exc}") from exc
    return (name_contains.lower() if name_contains else None, pattern)


def _name_matches(
    board: dict[str, Any],
    needle_lower: str | None,
    pattern: re.Pattern[str] | None,
) -> bool:
    name = board.get("name") or ""
    if needle_lower is not None and needle_lower not in name.lower():
        return False
    return not (pattern is not None and pattern.search(name) is None)


def _apply_fuzzy(
    entries: list[dict[str, Any]],
    query: str,
    *,
    threshold: int,
    include_score: bool,
) -> list[dict[str, Any]]:
    """Apply fuzzy name filter to cached entries.

    When `include_score` is True, a `_fuzzy_score` key is injected into each
    returned entry (shallow-copied so the cache isn't mutated) and the list is
    sorted by score descending. When False, entries are filtered by threshold
    but the caller's order is preserved.
    """
    scored = fuzzy_score(query, entries, threshold=threshold)
    if include_score:
        return [{**entry, "_fuzzy_score": score} for entry, score in scored]
    matching_ids = {id(entry) for entry, _ in scored}
    return [e for e in entries if id(e) in matching_ids]


def _invalidate_boards_cache(opts: GlobalOpts) -> None:
    """Drop the boards cache file after a successful mutation. Best-effort."""
    if opts.dry_run:
        return
    try:
        opts.build_cache_store("boards").invalidate()
    except Exception:
        # Cache is a perf optimization — never fail a mutation because of it.
        pass


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
) -> None:
    """List boards.

    Use --name-contains / --name-matches / --name-fuzzy to narrow down,
    --workspace to restrict to a workspace, and --state to include archived
    boards. Served from the local directory cache when available.
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)

    if no_cache and refresh_cache:
        typer.secho(
            "error: --no-cache and --refresh-cache are mutually exclusive.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    try:
        needle_lower, pattern = _compile_name_filter(name_contains, name_matches, name_fuzzy)
    except UsageError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from e

    cache_cfg = opts.resolve_cache_config()
    use_cache = (
        cache_cfg.enabled
        and not no_cache
        and not with_item_counts
    )
    effective_fuzzy_threshold = fuzzy_threshold if fuzzy_threshold is not None else cache_cfg.fuzzy_threshold

    if use_cache:
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
            fuzzy_threshold=effective_fuzzy_threshold,
            fuzzy_score_flag=fuzzy_score_flag,
            max_items=max_items,
            refresh=refresh_cache,
        )
        return

    # Live path — preserves pre-cache behavior byte-for-byte.
    query, variables = build_boards_list_query(
        state=state.value if state else None,
        kind=kind.value if kind else None,
        workspace_ids=workspace or None,
        order_by=order_by.value if order_by else None,
        with_item_counts=with_item_counts,
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

    try:
        client = opts.build_client()
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    try:
        with client:
            boards = [
                b
                for b in iter_boards_page(
                    client,
                    query=query,
                    variables=variables,
                    limit=limit,
                    max_items=None,  # client-side filters applied below
                )
                if _type_matches(b, type_filter) and _name_matches(b, needle_lower, pattern)
            ]
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    if name_fuzzy is not None:
        boards = _apply_fuzzy(
            boards,
            name_fuzzy,
            threshold=effective_fuzzy_threshold,
            include_score=fuzzy_score_flag,
        )

    if max_items is not None:
        boards = boards[:max_items]
    opts.emit(boards)


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
) -> None:
    """Serve `board list` from the local directory cache.

    The cache stores the full unfiltered directory; every filter here runs
    client-side against that list.
    """
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

    try:
        client = opts.build_client()
        store = opts.build_cache_store("boards")
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    try:
        with client:
            cached = cache_get_boards(client, store=store, refresh=refresh)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    # Spec default for boards list is "active" when --state omitted. Preserve that
    # client-side since the cache holds all states.
    requested_state = state.value if state else "active"
    entries = cached.entries
    if requested_state != "all":
        entries = [b for b in entries if (b.get("state") or "active") == requested_state]
    if kind is not None:
        entries = [b for b in entries if (b.get("board_kind") or "") == kind.value]
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
        entries = _apply_fuzzy(
            entries,
            name_fuzzy,
            threshold=fuzzy_threshold,
            include_score=fuzzy_score_flag,
        )

    if max_items is not None:
        entries = entries[:max_items]
    opts.emit(entries)


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
        help="Board ID or monday.com URL.",
        click_type=MondayIdParam(),
    ),
    with_url: bool = typer.Option(
        False,
        "--with-url",
        help="Include a synthesized `url` field in the emitted payload.",
    ),
) -> None:
    """Fetch a single board by ID with columns, groups, and subscribers."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    board_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="board")
    data = _execute_mutation(opts, BOARD_GET, {"id": board_id})
    boards = data.get("boards") or []
    if not boards:
        typer.secho(f"board {board_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
    board = boards[0]
    warn_cross_type(board, expected="board", id_=board_id)
    if with_url:
        try:
            client = opts.build_client()
        except MondoError as e:
            typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=int(e.exit_code)) from e
        with client:
            board = {**board, "url": board_url(get_tenant_slug(client), board_id)}
    opts.emit(board)


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
    data = _execute_mutation(opts, BOARD_CREATE, variables)
    _invalidate_boards_cache(opts)
    opts.emit(data.get("create_board") or {})


@app.command("update", epilog=epilog_for("board update"))
def update_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Board ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", help="Board ID (flag form)."),
    attribute: BoardAttribute = typer.Option(
        ...,
        "--attribute",
        help="Attribute to update (name/description/communication/item_nickname).",
        case_sensitive=False,
    ),
    value: str = typer.Option(..., "--value", help="New value for the attribute."),
) -> None:
    """Update a single board attribute."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    board_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="board")
    data = _execute_mutation(
        opts,
        BOARD_UPDATE,
        {"board": board_id, "attribute": attribute.value, "value": value},
    )
    _invalidate_boards_cache(opts)
    # update_board returns a scalar (String) with a status JSON payload, not a Board.
    opts.emit({"update_board": data.get("update_board")})


@app.command("archive", epilog=epilog_for("board archive"))
def archive_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Board ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", help="Board ID (flag form)."),
) -> None:
    """Archive a board (reversible via monday UI within 30 days)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    board_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="board")
    _confirm(opts, f"Archive board {board_id}?")
    data = _execute_mutation(opts, BOARD_ARCHIVE, {"board": board_id})
    _invalidate_boards_cache(opts)
    opts.emit(data.get("archive_board") or {})


@app.command("delete", epilog=epilog_for("board delete"))
def delete_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Board ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", help="Board ID (flag form)."),
    hard: bool = typer.Option(
        False, "--hard", help="Required for permanent deletion (paired with --yes)."
    ),
) -> None:
    """Delete a board (permanent — prefer `archive` unless --hard is passed)."""
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
    data = _execute_mutation(opts, BOARD_DELETE, {"board": board_id})
    _invalidate_boards_cache(opts)
    opts.emit(data.get("delete_board") or {})


@app.command("duplicate", epilog=epilog_for("board duplicate"))
def duplicate_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Board ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", help="Board ID (flag form)."),
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
    data = _execute_mutation(opts, BOARD_DUPLICATE, variables)
    _invalidate_boards_cache(opts)
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
        source_items_count = _items_count_or_none(opts, board_id)
        try:
            client = opts.build_client()
        except MondoError as e:
            typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=int(e.exit_code)) from e
        try:
            with client:
                final_count = wait_for_items_count_stable(
                    client,
                    dup_id,
                    target=source_items_count,
                    timeout_s=float(timeout_s),
                    interval_s=poll_interval_s,
                )
        except MondoError as e:
            typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=int(e.exit_code)) from e
        duplicate_payload = {
            **duplicate_payload,
            "_wait": {"final_items_count": final_count, "source_items_count": source_items_count},
        }

    opts.emit(duplicate_payload)


def _items_count_or_none(opts: GlobalOpts, board_id: int) -> int | None:
    data = _execute_query(opts, BOARD_ITEMS_COUNT, {"ids": [board_id]})
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
