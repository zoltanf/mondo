"""`mondo item` command group: CRUD for monday items."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError, UsageError
from mondo.api.pagination import MAX_PAGE_SIZE, iter_items_page
from mondo.api.queries import (
    ITEM_ARCHIVE,
    ITEM_CREATE,
    ITEM_DELETE,
    ITEM_DUPLICATE,
    ITEM_GET,
    ITEM_GET_WITH_SUBITEMS,
    ITEM_GET_WITH_UPDATES,
    ITEM_MOVE_GROUP,
    ITEM_RENAME,
)
from mondo.cli.context import GlobalOpts
from mondo.util.kvparse import parse_columns

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


class PositionRelative(StrEnum):
    before_at = "before_at"
    after_at = "after_at"


class OrderDir(StrEnum):
    asc = "asc"
    desc = "desc"


# ----- helpers -----


def _dispatch_dry_run(opts: GlobalOpts, query: str, variables: dict[str, Any]) -> None:
    """For `--dry-run`: emit the mutation + variables as structured data and exit 0."""
    opts.emit({"query": query, "variables": variables})
    raise typer.Exit(0)


def _confirm(opts: GlobalOpts, prompt: str) -> None:
    """Interactive confirmation unless `--yes` is set. Exit 1 on refusal."""
    if opts.yes:
        return
    ok = typer.confirm(prompt, default=False)
    if not ok:
        typer.echo("aborted.")
        raise typer.Exit(1)


def _execute_mutation(opts: GlobalOpts, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    """Build the client, run the mutation, return the `data` payload or raise."""
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


def _parse_filter(expr: str) -> dict[str, Any]:
    """Parse `--filter COL=VAL` into an items_page rule.

    Supports:
      status=Done           → any_of ["Done"]
      status!=Done          → not_any_of ["Done"]
      status=Done,Working   → any_of ["Done","Working"]
    """
    if "!=" in expr:
        col, _, raw = expr.partition("!=")
        operator = "not_any_of"
    elif "=" in expr:
        col, _, raw = expr.partition("=")
        operator = "any_of"
    else:
        raise UsageError(f"invalid --filter {expr!r}: expected COL=VAL or COL!=VAL")
    values = [v.strip() for v in raw.split(",")]
    return {"column_id": col.strip(), "compare_value": values, "operator": operator}


def _build_query_params(filters: list[str] | None, order_by: str | None) -> dict[str, Any] | None:
    qp: dict[str, Any] = {}
    if filters:
        qp["rules"] = [_parse_filter(f) for f in filters]
        qp["operator"] = "and"
    if order_by:
        # Syntax: "column_id" or "column_id,asc" / "column_id,desc"
        col, _, direction = order_by.partition(",")
        qp["order_by"] = [{"column_id": col.strip(), "direction": (direction or "asc").strip()}]
    return qp or None


# ----- read commands -----


@app.command("get")
def get_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--id", help="Item ID."),
    include_updates: bool = typer.Option(
        False, "--include-updates", help="Also fetch item updates (comments)."
    ),
    include_subitems: bool = typer.Option(False, "--include-subitems", help="Also fetch subitems."),
) -> None:
    """Fetch a single item by ID."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    if include_updates and include_subitems:
        typer.secho(
            "error: --include-updates and --include-subitems are mutually exclusive for now.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    if include_updates:
        query = ITEM_GET_WITH_UPDATES
    elif include_subitems:
        query = ITEM_GET_WITH_SUBITEMS
    else:
        query = ITEM_GET

    data = _execute_mutation(opts, query, {"id": item_id})
    items = data.get("items") or []
    if not items:
        typer.secho(f"item {item_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
    opts.emit(items[0])


@app.command("list")
def list_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID to list items from."),
    limit: int = typer.Option(MAX_PAGE_SIZE, "--limit", help=f"Page size (max {MAX_PAGE_SIZE})."),
    max_items: int | None = typer.Option(
        None, "--max-items", help="Stop after this many items total."
    ),
    filter_expr: list[str] | None = typer.Option(
        None,
        "--filter",
        help="Filter rule like 'status=Done' or 'status!=Stuck' (repeatable).",
    ),
    order_by: str | None = typer.Option(
        None,
        "--order-by",
        help="Column to sort by, optionally with ',asc'/',desc' (default: asc).",
    ),
) -> None:
    """List items on a board (cursor pagination)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)

    if opts.dry_run:
        opts.emit(
            {
                "query": "<items_page iterator>",
                "variables": {
                    "boards": [board_id],
                    "limit": limit,
                    "qp": _build_query_params(filter_expr, order_by),
                    "max_items": max_items,
                },
            }
        )
        raise typer.Exit(0)

    try:
        client = opts.build_client()
        qp = _build_query_params(filter_expr, order_by)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    except UsageError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from e

    try:
        with client:
            items = list(
                iter_items_page(
                    client,
                    board_id=board_id,
                    limit=limit,
                    query_params=qp,
                    max_items=max_items,
                )
            )
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    opts.emit(items)


# ----- write commands -----


@app.command("create")
def create_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID to create in."),
    name: str = typer.Option(..., "--name", help="Item title."),
    group_id: str | None = typer.Option(
        None, "--group", help="Target group ID (default: board's top group)."
    ),
    columns: list[str] | None = typer.Option(
        None,
        "--column",
        metavar="COL=VAL",
        help=(
            "Set a column value as raw JSON or bare string. Repeatable. "
            'Example: --column status=\'{"label":"Done"}\' --column text=Hi'
        ),
    ),
    create_labels_if_missing: bool = typer.Option(
        False,
        "--create-labels-if-missing",
        help="Auto-create status/dropdown labels that don't exist yet.",
    ),
    position_relative_method: PositionRelative | None = typer.Option(
        None,
        "--position-relative-method",
        help="Position new item before/after an existing item.",
        case_sensitive=False,
    ),
    relative_to: int | None = typer.Option(
        None, "--relative-to", help="Reference item ID for position-relative placement."
    ),
) -> None:
    """Create a new item on a board."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)

    try:
        col_values = parse_columns(columns or [])
    except ValueError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from e

    variables: dict[str, Any] = {
        "board": board_id,
        "name": name,
        "group": group_id,
        # monday's column_values wants a JSON-*string*, not a JSON object (§11.4).
        "values": json.dumps(col_values) if col_values else None,
        "create_labels": create_labels_if_missing if create_labels_if_missing else None,
        "prm": position_relative_method.value if position_relative_method else None,
        "relto": relative_to,
    }
    data = _execute_mutation(opts, ITEM_CREATE, variables)
    opts.emit(data.get("create_item") or {})


@app.command("rename")
def rename_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--id", help="Item ID."),
    board_id: int = typer.Option(..., "--board", help="Parent board ID."),
    name: str = typer.Option(..., "--name", help="New title."),
) -> None:
    """Rename an item."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    data = _execute_mutation(opts, ITEM_RENAME, {"board": board_id, "id": item_id, "name": name})
    opts.emit(data.get("change_item_name") or {})


@app.command("duplicate")
def duplicate_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--id", help="Item ID to duplicate."),
    board_id: int = typer.Option(..., "--board", help="Parent board ID."),
    with_updates: bool = typer.Option(
        False, "--with-updates", help="Also duplicate the item's updates (comments)."
    ),
) -> None:
    """Duplicate an item in place."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    data = _execute_mutation(
        opts,
        ITEM_DUPLICATE,
        {"board": board_id, "id": item_id, "with_updates": with_updates},
    )
    opts.emit(data.get("duplicate_item") or {})


@app.command("archive")
def archive_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--id", help="Item ID to archive."),
) -> None:
    """Archive an item (reversible via monday UI within 30 days)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    _confirm(opts, f"Archive item {item_id}?")
    data = _execute_mutation(opts, ITEM_ARCHIVE, {"id": item_id})
    opts.emit(data.get("archive_item") or {})


@app.command("delete")
def delete_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--id", help="Item ID to delete."),
    hard: bool = typer.Option(
        False, "--hard", help="Required for permanent deletion (paired with --yes)."
    ),
) -> None:
    """Delete an item (permanent — prefer `archive` unless --hard is passed)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    if not hard:
        typer.secho(
            "refusing to delete without --hard. Use `mondo item archive` for "
            "reversible removal, or pass --hard to confirm permanent deletion.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=2)
    _confirm(opts, f"PERMANENTLY delete item {item_id}?")
    data = _execute_mutation(opts, ITEM_DELETE, {"id": item_id})
    opts.emit(data.get("delete_item") or {})


@app.command("move")
def move_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--id", help="Item ID to move."),
    group_id: str = typer.Option(..., "--group", help="Target group ID within the same board."),
) -> None:
    """Move an item to a different group within the same board."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    data = _execute_mutation(opts, ITEM_MOVE_GROUP, {"id": item_id, "group": group_id})
    opts.emit(data.get("move_item_to_group") or {})
