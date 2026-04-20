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
from mondo.api.queries import (
    BOARD_ARCHIVE,
    BOARD_CREATE,
    BOARD_DELETE,
    BOARD_DUPLICATE,
    BOARD_GET,
    BOARD_UPDATE,
    build_boards_list_query,
)
from mondo.cache.directory import get_boards as cache_get_boards
from mondo.cache.fuzzy import fuzzy_score
from mondo.cli._confirm import confirm_or_abort as _confirm
from mondo.cli._examples import epilog_for
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
        None, "--state", help="Filter by state (default: active).", case_sensitive=False
    ),
    kind: BoardKind | None = typer.Option(
        None, "--kind", help="Filter by board kind.", case_sensitive=False
    ),
    workspace: list[int] | None = typer.Option(
        None, "--workspace", help="Restrict to workspace IDs (repeatable)."
    ),
    order_by: BoardOrderBy | None = typer.Option(
        None, "--order-by", help="Sort order.", case_sensitive=False
    ),
    name_contains: str | None = typer.Option(
        None,
        "--name-contains",
        help="Client-side substring filter on board name (case-insensitive).",
    ),
    name_matches: str | None = typer.Option(
        None,
        "--name-matches",
        help="Client-side regex filter on board name.",
    ),
    name_fuzzy: str | None = typer.Option(
        None,
        "--name-fuzzy",
        help="Client-side fuzzy filter on board name (tolerates typos).",
    ),
    fuzzy_threshold: int | None = typer.Option(
        None,
        "--fuzzy-threshold",
        help="Minimum fuzzy match score (0-100). Defaults to config/70.",
    ),
    fuzzy_score_flag: bool = typer.Option(
        False,
        "--fuzzy-score",
        help="Include `_fuzzy_score` field and sort by score desc.",
    ),
    limit: int = typer.Option(
        MAX_BOARDS_PAGE_SIZE,
        "--limit",
        help=f"Page size for live fetches (max {MAX_BOARDS_PAGE_SIZE}); ignored when served from cache.",
    ),
    max_items: int | None = typer.Option(
        None, "--max-items", help="Stop after this many boards total."
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
    ),
    refresh_cache: bool = typer.Option(
        False,
        "--refresh-cache",
        help="Force-refresh the local directory cache before serving.",
    ),
) -> None:
    """List boards. Served from the local directory cache when available."""
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
                    max_items=None,  # client-side filter applied below
                )
                if _name_matches(b, needle_lower, pattern)
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
    board_id: int = typer.Option(..., "--id", help="Board ID."),
) -> None:
    """Fetch a single board by ID with columns, groups, and subscribers."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    data = _execute_mutation(opts, BOARD_GET, {"id": board_id})
    boards = data.get("boards") or []
    if not boards:
        typer.secho(f"board {board_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
    opts.emit(boards[0])


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
    board_id: int = typer.Option(..., "--id", help="Board ID."),
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
    board_id: int = typer.Option(..., "--id", help="Board ID to archive."),
) -> None:
    """Archive a board (reversible via monday UI within 30 days)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    _confirm(opts, f"Archive board {board_id}?")
    data = _execute_mutation(opts, BOARD_ARCHIVE, {"board": board_id})
    _invalidate_boards_cache(opts)
    opts.emit(data.get("archive_board") or {})


@app.command("delete", epilog=epilog_for("board delete"))
def delete_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--id", help="Board ID to delete."),
    hard: bool = typer.Option(
        False, "--hard", help="Required for permanent deletion (paired with --yes)."
    ),
) -> None:
    """Delete a board (permanent — prefer `archive` unless --hard is passed)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
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
    board_id: int = typer.Option(..., "--id", help="Board ID to duplicate."),
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
) -> None:
    """Duplicate a board (async — response may be partial).

    When --workspace is omitted, the copy lands in the source board's workspace.
    (monday's API default otherwise drops it into the caller's main workspace.)
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
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
    opts.emit(data.get("duplicate_board") or {})
