"""`mondo group` command group: CRUD for monday groups.

Groups have no root query (§10) — `list` fetches them nested inside `boards`.
Group IDs are strings (`"topics"`, `"new_group_8A3F"`). `group_color`
accepts only the monday palette hex codes — we validate client-side.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError
from mondo.api.queries import (
    GROUP_ARCHIVE,
    GROUP_CREATE,
    GROUP_DELETE,
    GROUP_DUPLICATE,
    GROUP_UPDATE,
    GROUPS_LIST,
)
from mondo.cli._confirm import confirm_or_abort as _confirm
from mondo.cli._examples import epilog_for
from mondo.cli._resolve import resolve_required_id
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


# monday-api.md §10 — the exact hex palette monday accepts for group_color.
GROUP_PALETTE: frozenset[str] = frozenset(
    {
        "#037f4c",
        "#00c875",
        "#9cd326",
        "#cab641",
        "#ffcb00",
        "#784bd1",
        "#9d50dd",
        "#007eb5",
        "#579bfc",
        "#66ccff",
        "#bb3354",
        "#df2f4a",
        "#ff007f",
        "#ff5ac4",
        "#ff642e",
        "#fdab3d",
        "#7f5347",
        "#c4c4c4",
        "#757575",
    }
)


class PositionRelative(StrEnum):
    before_at = "before_at"
    after_at = "after_at"


class GroupAttribute(StrEnum):
    title = "title"  # type: ignore[assignment]
    color = "color"
    position = "position"
    relative_position_after = "relative_position_after"
    relative_position_before = "relative_position_before"


# ----- helpers -----


def _client_or_exit(opts: GlobalOpts) -> MondayClient:
    try:
        return opts.build_client()
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e


def _exec_or_exit(client: MondayClient, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    try:
        result = client.execute(query, variables=variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    return result.get("data") or {}


def _dry_run(opts: GlobalOpts, query: str, variables: dict[str, Any]) -> None:
    opts.emit({"query": query, "variables": variables})
    raise typer.Exit(0)


def _validate_color(color: str | None) -> str | None:
    if color is None:
        return None
    normalized = color.lower()
    if not normalized.startswith("#"):
        normalized = "#" + normalized
    if normalized not in GROUP_PALETTE:
        typer.secho(
            f"error: --color {color!r} is not in the monday group palette. "
            f"Valid values: {sorted(GROUP_PALETTE)}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    return normalized


# ----- read commands -----


@app.command("list", epilog=epilog_for("group list"))
def list_cmd(
    ctx: typer.Context,
    board_pos: int | None = typer.Argument(
        None, metavar="[BOARD_ID]", help="Board ID (positional)."
    ),
    board_flag: int | None = typer.Option(None, "--board", help="Board ID (flag form)."),
) -> None:
    """List all groups on a board (nested query — no standalone groups root)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    board_id = resolve_required_id(board_pos, board_flag, flag_name="--board", resource="board")
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, GROUPS_LIST, {"board": board_id})
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    boards = data.get("boards") or []
    if not boards:
        typer.secho(f"board {board_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
    opts.emit(boards[0].get("groups") or [])


# ----- write commands -----


@app.command("create", epilog=epilog_for("group create"))
def create_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID."),
    name: str = typer.Option(..., "--name", help="Group title."),
    color: str | None = typer.Option(
        None,
        "--color",
        help="Monday palette hex (e.g. #00c875). Full list in `mondo group create --help`.",
    ),
    relative_to: str | None = typer.Option(
        None, "--relative-to", help="Existing group ID to position relative to."
    ),
    position_relative_method: PositionRelative | None = typer.Option(
        None,
        "--position-relative-method",
        help="Whether to place before_at or after_at the --relative-to group.",
        case_sensitive=False,
    ),
    position: str | None = typer.Option(
        None,
        "--position",
        help="Absolute position (float as string). Prefer --relative-to for clarity.",
    ),
) -> None:
    """Create a new group on a board."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables: dict[str, Any] = {
        "board": board_id,
        "name": name,
        "color": _validate_color(color),
        "relativeTo": relative_to,
        "prm": position_relative_method.value if position_relative_method else None,
        "position": position,
    }
    if opts.dry_run:
        _dry_run(opts, GROUP_CREATE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, GROUP_CREATE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("create_group") or {})


@app.command("rename", epilog=epilog_for("group rename"))
def rename_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID."),
    group_id: str = typer.Option(..., "--id", help="Group ID."),
    title: str = typer.Option(..., "--title", help="New group title."),
) -> None:
    """Rename a group (shortcut for update --attribute title)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {
        "board": board_id,
        "group": group_id,
        "attribute": GroupAttribute.title.value,
        "value": title,
    }
    if opts.dry_run:
        _dry_run(opts, GROUP_UPDATE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, GROUP_UPDATE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("update_group") or {})


@app.command("update", epilog=epilog_for("group update"))
def update_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID."),
    group_id: str = typer.Option(..., "--id", help="Group ID."),
    attribute: GroupAttribute = typer.Option(
        ...,
        "--attribute",
        help="Attribute to change (title/color/position/relative_position_after/_before).",
        case_sensitive=False,
    ),
    value: str = typer.Option(
        ...,
        "--value",
        help=(
            "New value. NOTE: for `--attribute color`, monday's `update_group` "
            "mutation rejects hex codes and requires lowercase color NAMES "
            "(e.g. 'green', not '#00c875'). This diverges from `group create` / "
            "`group rename` which accept hex. Pass the name here."
        ),
    ),
) -> None:
    """Update a group attribute (color, position, relative position, or title)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    # NOTE: intentionally skip the hex-palette check for attribute=color on
    # update_group — monday wants color NAMES here, not hex codes, unlike
    # create/rename which take hex. Pass the user's value through as-is.
    variables = {
        "board": board_id,
        "group": group_id,
        "attribute": attribute.value,
        "value": value,
    }
    if opts.dry_run:
        _dry_run(opts, GROUP_UPDATE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, GROUP_UPDATE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("update_group") or {})


@app.command("reorder", epilog=epilog_for("group reorder"))
def reorder_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID."),
    group_id: str = typer.Option(..., "--id", help="Group ID to reorder."),
    after: str | None = typer.Option(
        None, "--after", help="Place this group after the given group ID."
    ),
    before: str | None = typer.Option(
        None, "--before", help="Place this group before the given group ID."
    ),
    position: str | None = typer.Option(
        None,
        "--position",
        help="Absolute position (float as string). Mutually exclusive with --after/--before.",
    ),
) -> None:
    """Reorder a group (relative to another group, or by absolute position)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    sources = [after, before, position]
    provided = [s for s in sources if s is not None]
    if len(provided) != 1:
        typer.secho(
            "error: provide exactly one of --after, --before, or --position.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    if after is not None:
        attribute = GroupAttribute.relative_position_after.value
        value = after
    elif before is not None:
        attribute = GroupAttribute.relative_position_before.value
        value = before
    else:
        attribute = GroupAttribute.position.value
        assert position is not None
        value = position
    variables = {"board": board_id, "group": group_id, "attribute": attribute, "value": value}
    if opts.dry_run:
        _dry_run(opts, GROUP_UPDATE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, GROUP_UPDATE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("update_group") or {})


@app.command("duplicate", epilog=epilog_for("group duplicate"))
def duplicate_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID."),
    group_id: str = typer.Option(..., "--id", help="Group ID to duplicate."),
    title: str | None = typer.Option(None, "--title", help="New group title."),
    add_to_top: bool = typer.Option(
        False, "--add-to-top", help="Place the copy at the top of the board."
    ),
) -> None:
    """Duplicate a group (40/min cap; does not duplicate item updates)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {
        "board": board_id,
        "group": group_id,
        "title": title,
        "addToTop": True if add_to_top else None,
    }
    if opts.dry_run:
        _dry_run(opts, GROUP_DUPLICATE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, GROUP_DUPLICATE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("duplicate_group") or {})


@app.command("archive", epilog=epilog_for("group archive"))
def archive_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID."),
    group_id: str = typer.Option(..., "--id", help="Group ID to archive."),
) -> None:
    """Archive a group."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    _confirm(opts, f"Archive group {group_id!r} on board {board_id}?")
    variables = {"board": board_id, "group": group_id}
    if opts.dry_run:
        _dry_run(opts, GROUP_ARCHIVE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, GROUP_ARCHIVE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("archive_group") or {})


@app.command("delete", epilog=epilog_for("group delete"))
def delete_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID."),
    group_id: str = typer.Option(..., "--id", help="Group ID to delete."),
    hard: bool = typer.Option(
        False, "--hard", help="Required for permanent deletion (cascades to items)."
    ),
) -> None:
    """Delete a group (permanent — cascades to all items inside it).

    monday rejects deletion of the last remaining group (DeleteLastGroupException).
    Prefer `archive` unless --hard is set.
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    if not hard:
        typer.secho(
            "refusing to delete without --hard. Use `mondo group archive` for "
            "reversible removal, or pass --hard to confirm permanent deletion.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=2)
    _confirm(
        opts,
        f"PERMANENTLY delete group {group_id!r} and all its items on board {board_id}?",
    )
    variables = {"board": board_id, "group": group_id}
    if opts.dry_run:
        _dry_run(opts, GROUP_DELETE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, GROUP_DELETE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("delete_group") or {})
