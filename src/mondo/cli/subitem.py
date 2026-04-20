"""`mondo subitem` command group — subitem CRUD (Phase 3c).

Subitems are full `Item`s living on a hidden auto-generated board (§12);
their column IDs are distinct from the parent board's. `subitem list`
uses the nested `items(ids:[parent]).subitems` field, and `create_subitem`
writes to the subitems board. All other operations (archive / delete /
move / rename) are ordinary item mutations against the subitem's own ID;
users can either route through this command group (convenience) or call
`mondo item archive/delete/...` directly.

Note on codec dispatch: subitem columns are independent. For `subitem
create --column K=V`, pass `--subitems-board <id>` to enable codec
dispatch (the id surfaces on any existing `mondo subitem list` output).
Without it, `--column` values are sent as raw strings/JSON.
"""

from __future__ import annotations

import json
from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError, NotFoundError
from mondo.api.queries import (
    ITEM_ARCHIVE,
    ITEM_DELETE,
    ITEM_GET,
    ITEM_MOVE_GROUP,
    ITEM_RENAME,
    SUBITEM_CREATE,
    SUBITEMS_LIST,
)
from mondo.cli._column_cache import fetch_board_columns, invalidate_columns_cache
from mondo.cli._confirm import confirm_or_abort as _confirm
from mondo.cli._examples import epilog_for
from mondo.cli._resolve import resolve_required_id
from mondo.cli.context import GlobalOpts
from mondo.columns import UnknownColumnTypeError, parse_value
from mondo.util.kvparse import parse_column_kv

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


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


def _parse_settings(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _build_column_values(
    opts: GlobalOpts,
    client: MondayClient,
    subitems_board_id: int | None,
    pairs: list[str],
    *,
    create_labels: bool = False,
) -> dict[str, Any]:
    """Turn `--column K=V` pairs into the write JSON shape.

    With `subitems_board_id` set, does codec dispatch via the subitems-board
    column types. Without it, values pass through verbatim.
    """
    parsed_pairs = [parse_column_kv(p) for p in pairs]
    if subitems_board_id is None:
        return dict(parsed_pairs)
    try:
        columns = fetch_board_columns(opts, client, subitems_board_id)
    except NotFoundError:
        return dict(parsed_pairs)
    defs = {c["id"]: c for c in columns}
    out: dict[str, Any] = {}
    for col_id, raw_value in parsed_pairs:
        definition = defs.get(col_id)
        if definition is None or not isinstance(raw_value, str):
            out[col_id] = raw_value
            continue
        col_type = definition.get("type")
        if not isinstance(col_type, str):
            out[col_id] = raw_value
            continue
        settings = _parse_settings(definition.get("settings_str"))
        try:
            out[col_id] = parse_value(col_type, raw_value, settings, create_labels=create_labels)
        except UnknownColumnTypeError:
            out[col_id] = raw_value
        except ValueError as e:
            raise ValueError(f"--column {col_id}={raw_value!r}: {e}") from e
    return out


# ----- read commands -----


@app.command("list", epilog=epilog_for("subitem list"))
def list_cmd(
    ctx: typer.Context,
    parent_id: int = typer.Option(..., "--parent", help="Parent item ID."),
) -> None:
    """List all subitems of a parent item."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"parent": parent_id}
    if opts.dry_run:
        _dry_run(opts, SUBITEMS_LIST, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, SUBITEMS_LIST, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    items = data.get("items") or []
    if not items:
        typer.secho(f"parent item {parent_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
    opts.emit(items[0].get("subitems") or [])


@app.command("get", epilog=epilog_for("subitem get"))
def get_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Subitem ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", help="Subitem ID (flag form)."),
) -> None:
    """Fetch a single subitem by ID (same shape as `item get`)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    subitem_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="subitem")
    variables = {"id": subitem_id}
    if opts.dry_run:
        _dry_run(opts, ITEM_GET, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, ITEM_GET, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    items = data.get("items") or []
    if not items:
        typer.secho(f"subitem {subitem_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
    opts.emit(items[0])


# ----- write commands -----


@app.command("create", epilog=epilog_for("subitem create"))
def create_cmd(
    ctx: typer.Context,
    parent_id: int = typer.Option(..., "--parent", help="Parent item ID."),
    name: str = typer.Option(..., "--name", help="Subitem title."),
    columns: list[str] | None = typer.Option(
        None,
        "--column",
        metavar="COL=VAL",
        help=(
            "Set a subitem column. Without --subitems-board, values pass "
            "through as-is; with --subitems-board set, codec dispatch kicks "
            "in (same smart parsing as `item create`)."
        ),
    ),
    subitems_board: int | None = typer.Option(
        None,
        "--subitems-board",
        help=(
            "Subitems board ID for codec dispatch on --column values. "
            "Find it via `mondo subitem list --parent <id>` → .[0].board.id."
        ),
    ),
    create_labels_if_missing: bool = typer.Option(
        False,
        "--create-labels-if-missing",
        help="Auto-create missing status/dropdown labels.",
    ),
) -> None:
    """Create a subitem under an existing parent item."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)

    col_values: dict[str, Any] = {}
    if columns:
        if subitems_board is None:
            # No codec dispatch — send values verbatim.
            col_values = dict(parse_column_kv(p) for p in columns)
        else:
            client = _client_or_exit(opts)
            try:
                with client:
                    col_values = _build_column_values(
                        opts,
                        client,
                        subitems_board,
                        columns,
                        create_labels=create_labels_if_missing,
                    )
            except MondoError as e:
                typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=int(e.exit_code)) from e
            except ValueError as e:
                # Codec validation (e.g. unknown status label) — surface as a
                # clean CLI error rather than a Python traceback.
                typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=5) from e

    variables = {
        "parent": parent_id,
        "name": name,
        "values": json.dumps(col_values) if col_values else None,
        "create_labels": create_labels_if_missing if create_labels_if_missing else None,
    }
    if opts.dry_run:
        _dry_run(opts, SUBITEM_CREATE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, SUBITEM_CREATE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    if create_labels_if_missing and subitems_board is not None:
        # May have minted a status/dropdown label on the subitems board.
        invalidate_columns_cache(opts, subitems_board)
    opts.emit(data.get("create_subitem") or {})


@app.command("rename", epilog=epilog_for("subitem rename"))
def rename_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Subitem ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", help="Subitem ID (flag form)."),
    board_id: int = typer.Option(..., "--board", help="Parent subitems board ID."),
    name: str = typer.Option(..., "--name", help="New title."),
) -> None:
    """Rename a subitem (writes the `name` column via change_simple_column_value)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    subitem_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="subitem")
    variables = {"board": board_id, "id": subitem_id, "name": name}
    if opts.dry_run:
        _dry_run(opts, ITEM_RENAME, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, ITEM_RENAME, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("change_simple_column_value") or {})


@app.command("move", epilog=epilog_for("subitem move"))
def move_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Subitem ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", help="Subitem ID (flag form)."),
    group_id: str = typer.Option(
        ...,
        "--group",
        help=(
            "Target subitems-board group ID. monday auto-names groups "
            "`subitems_of_<parent_item_id>`."
        ),
    ),
) -> None:
    """Move a subitem to a different subitems group."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    subitem_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="subitem")
    variables = {"id": subitem_id, "group": group_id}
    if opts.dry_run:
        _dry_run(opts, ITEM_MOVE_GROUP, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, ITEM_MOVE_GROUP, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("move_item_to_group") or {})


@app.command("archive", epilog=epilog_for("subitem archive"))
def archive_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Subitem ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", help="Subitem ID (flag form)."),
) -> None:
    """Archive a subitem (reversible)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    subitem_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="subitem")
    _confirm(opts, f"Archive subitem {subitem_id}?")
    variables = {"id": subitem_id}
    if opts.dry_run:
        _dry_run(opts, ITEM_ARCHIVE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, ITEM_ARCHIVE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("archive_item") or {})


@app.command("delete", epilog=epilog_for("subitem delete"))
def delete_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Subitem ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", help="Subitem ID (flag form)."),
    hard: bool = typer.Option(False, "--hard", help="Required for permanent deletion."),
) -> None:
    """Delete a subitem (permanent — prefer `archive` unless --hard is passed)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    subitem_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="subitem")
    if not hard:
        typer.secho(
            "refusing to delete without --hard. Use `mondo subitem archive` for "
            "reversible removal.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=2)
    _confirm(opts, f"PERMANENTLY delete subitem {subitem_id}?")
    variables = {"id": subitem_id}
    if opts.dry_run:
        _dry_run(opts, ITEM_DELETE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, ITEM_DELETE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("delete_item") or {})
