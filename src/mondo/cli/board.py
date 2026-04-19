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


def _run(client: MondayClient, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    result = client.execute(query, variables=variables)
    return result.get("data") or {}


def _compile_name_filter(
    name_contains: str | None, name_matches: str | None
) -> tuple[str | None, re.Pattern[str] | None]:
    if name_contains and name_matches:
        raise UsageError("pass only one of --name-contains / --name-matches.")
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
    limit: int = typer.Option(
        MAX_BOARDS_PAGE_SIZE,
        "--limit",
        help=f"Page size (max {MAX_BOARDS_PAGE_SIZE}).",
    ),
    max_items: int | None = typer.Option(
        None, "--max-items", help="Stop after this many boards total."
    ),
    with_item_counts: bool = typer.Option(
        False,
        "--with-item-counts",
        help="Include items_count per board (adds ~500k complexity per 100 boards).",
    ),
) -> None:
    """List boards (page-based pagination)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)

    try:
        needle_lower, pattern = _compile_name_filter(name_contains, name_matches)
    except UsageError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from e

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

    if max_items is not None:
        boards = boards[:max_items]
    opts.emit(boards)


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
    workspace: int | None = typer.Option(None, "--workspace", help="Target workspace ID."),
    folder: int | None = typer.Option(None, "--folder", help="Target folder ID."),
    keep_subscribers: bool = typer.Option(
        False, "--keep-subscribers", help="Carry subscribers over to the copy."
    ),
) -> None:
    """Duplicate a board (async — response may be partial)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables: dict[str, Any] = {
        "board": board_id,
        "duplicateType": duplicate_type.value,
        "name": name,
        "workspace": workspace,
        "folder": folder,
        "keepSubscribers": True if keep_subscribers else None,
    }
    data = _execute_mutation(opts, BOARD_DUPLICATE, variables)
    opts.emit(data.get("duplicate_board") or {})
