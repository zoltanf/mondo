"""`mondo column` command group: list, get, set, set-many, clear.

Column values are dispatched through `mondo.columns` codecs keyed on the
column's `type` (fetched alongside the item). Read-only types (`mirror`,
`formula`, etc.) reject writes at the codec layer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError, NotFoundError
from mondo.api.queries import (
    CHANGE_COLUMN_VALUE,
    CHANGE_MULTIPLE_COLUMN_VALUES,
    COLUMN_CONTEXT,
    COLUMNS_ON_BOARD,
    CREATE_OR_GET_TAG,
)
from mondo.cli.column_doc import app as doc_app
from mondo.cli.context import GlobalOpts
from mondo.columns import (
    UnknownColumnTypeError,
    clear_payload_for,
    parse_value,
    render_value,
)

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
app.add_typer(doc_app, name="doc", help="Read/write the content of a `doc`-typed column.")


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


def _parse_settings(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _fetch_column_context(
    client: MondayClient, item_id: int, column_ids: list[str]
) -> tuple[int, dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return (board_id, {col_id: definition}, {col_id: current_value}).

    Raises NotFoundError if the item doesn't exist.
    `column_ids` must be non-empty.
    """
    data = _exec_or_exit(client, COLUMN_CONTEXT, {"id": item_id, "cols": column_ids})
    items = data.get("items") or []
    if not items:
        raise NotFoundError(f"item {item_id} not found")
    item = items[0]
    board = item.get("board") or {}
    board_id_raw = board.get("id")
    if board_id_raw is None:
        raise NotFoundError(f"item {item_id} has no associated board")
    board_id = int(board_id_raw)
    defs = {c["id"]: c for c in (board.get("columns") or [])}
    values = {v["id"]: v for v in (item.get("column_values") or [])}
    return board_id, defs, values


def _resolve_tag_names_to_ids(client: MondayClient, board_id: int, value: str) -> str:
    """If `value` contains tag names (non-integers), create/resolve them via
    `create_or_get_tag` and return a comma-joined ID list. Leaves pure-int
    inputs unchanged so TagsCodec.parse() can just consume the output."""
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not parts:
        return ""
    resolved_ids: list[int] = []
    for part in parts:
        if part.isdigit() or (part.startswith("-") and part[1:].isdigit()):
            resolved_ids.append(int(part))
            continue
        data = _exec_or_exit(client, CREATE_OR_GET_TAG, {"name": part, "board": board_id})
        tag = data.get("create_or_get_tag") or {}
        tag_id = tag.get("id")
        if tag_id is None:
            raise MondoError(f"create_or_get_tag returned no id for name {part!r}")
        resolved_ids.append(int(tag_id))
    return ",".join(str(i) for i in resolved_ids)


def _load_value(value: str | None, from_file: Path | None, from_stdin: bool) -> str:
    """Resolve --value / --from-file / --from-stdin into the raw input string."""
    sources = sum(x is not None and x is not False for x in (value, from_file, from_stdin))
    if sources == 0:
        typer.secho(
            "error: provide --value, --from-file @path, or --from-stdin",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    if sources > 1:
        typer.secho(
            "error: --value, --from-file, and --from-stdin are mutually exclusive",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    if from_file is not None:
        return from_file.read_text()
    if from_stdin:
        return sys.stdin.read()
    assert value is not None
    return value


# ----- commands -----


@app.command("list")
def list_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID."),
) -> None:
    """List all columns on a board with id, title, type."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, COLUMNS_ON_BOARD, {"board": board_id})
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    boards = data.get("boards") or []
    if not boards:
        typer.secho(f"board {board_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
    columns = boards[0].get("columns") or []
    # Strip settings_str from default output (noisy); it's still in raw JSON.
    simplified = [
        {
            "id": c.get("id"),
            "title": c.get("title"),
            "type": c.get("type"),
            "archived": c.get("archived"),
        }
        for c in columns
    ]
    opts.emit(simplified)


@app.command("get")
def get_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--item", help="Item ID."),
    column_id: str = typer.Option(..., "--column", help="Column ID."),
    raw: bool = typer.Option(
        False,
        "--raw",
        help="Return {id, type, value (JSON string), text} instead of human-rendered text.",
    ),
) -> None:
    """Read a single column value from an item."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    client = _client_or_exit(opts)
    try:
        with client:
            _, _defs, values = _fetch_column_context(client, item_id, [column_id])
    except NotFoundError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6) from e
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    current = values.get(column_id)
    if current is None:
        typer.secho(
            f"column {column_id!r} not set on item {item_id}", fg=typer.colors.YELLOW, err=True
        )
        raise typer.Exit(code=6)

    if raw:
        opts.emit(current)
        return

    col_type = current.get("type") or "text"
    value_payload: Any = None
    raw_value = current.get("value")
    if raw_value:
        try:
            value_payload = json.loads(raw_value)
        except (TypeError, ValueError):
            value_payload = raw_value
    try:
        rendered = render_value(col_type, value_payload, current.get("text"))
    except UnknownColumnTypeError:
        rendered = current.get("text") or ""
    opts.emit(rendered)


@app.command("set")
def set_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--item", help="Item ID."),
    column_id: str = typer.Option(..., "--column", help="Column ID."),
    value: str | None = typer.Option(None, "--value", help="Value (codec-parsed)."),
    from_file: Path | None = typer.Option(None, "--from-file", help="Read value from a file."),
    from_stdin: bool = typer.Option(False, "--from-stdin", help="Read value from stdin."),
    create_labels_if_missing: bool = typer.Option(
        False,
        "--create-labels-if-missing",
        help="Auto-create status/dropdown labels that don't exist yet.",
    ),
    column_raw: bool = typer.Option(
        False,
        "--raw",
        help="Treat --value as pre-parsed raw JSON; skip the codec.",
    ),
) -> None:
    """Set a single column value, using the registered codec for the column's type."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    raw_input = _load_value(value, from_file, from_stdin)

    client = _client_or_exit(opts)
    try:
        with client:
            board_id, defs, _current = _fetch_column_context(client, item_id, [column_id])
            definition = defs.get(column_id)
            if not definition:
                typer.secho(
                    f"column {column_id!r} not found on item {item_id}'s board.",
                    fg=typer.colors.RED,
                    err=True,
                )
                raise typer.Exit(code=6)

            col_type = definition["type"]
            settings = _parse_settings(definition.get("settings_str"))

            if column_raw:
                try:
                    parsed: Any = json.loads(raw_input)
                except json.JSONDecodeError as e:
                    typer.secho(
                        f"error: --raw value is not valid JSON: {e}",
                        fg=typer.colors.RED,
                        err=True,
                    )
                    raise typer.Exit(code=2) from e
            else:
                if col_type == "tags":
                    # Resolve tag names to IDs before the codec sees them.
                    raw_input = _resolve_tag_names_to_ids(client, board_id, raw_input)
                try:
                    parsed = parse_value(col_type, raw_input, settings)
                except ValueError as e:
                    typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
                    raise typer.Exit(code=5) from e
                except UnknownColumnTypeError as e:
                    typer.secho(
                        f"error: no codec for column type {col_type!r}. "
                        f"Use --raw to send a literal JSON payload. Details: {e}",
                        fg=typer.colors.RED,
                        err=True,
                    )
                    raise typer.Exit(code=5) from e

            if opts.dry_run:
                opts.emit(
                    {
                        "query": CHANGE_COLUMN_VALUE,
                        "variables": {
                            "item": item_id,
                            "board": board_id,
                            "col": column_id,
                            "value": json.dumps(parsed),
                            "create_labels": create_labels_if_missing or None,
                        },
                    }
                )
                raise typer.Exit(0)

            data = _exec_or_exit(
                client,
                CHANGE_COLUMN_VALUE,
                {
                    "item": item_id,
                    "board": board_id,
                    "col": column_id,
                    "value": json.dumps(parsed),
                    "create_labels": create_labels_if_missing or None,
                },
            )
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    opts.emit(data.get("change_column_value") or {})


@app.command("set-many")
def set_many_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--item", help="Item ID."),
    values: str = typer.Option(
        ...,
        "--values",
        help=(
            "JSON object mapping column_id → write payload. "
            'Example: \'{"status":{"label":"Done"},"text":"Hi"}\''
        ),
    ),
    create_labels_if_missing: bool = typer.Option(
        False, "--create-labels-if-missing", help="Auto-create labels on the fly."
    ),
) -> None:
    """Write multiple column values in one mutation (change_multiple_column_values).

    Values are passed as raw JSON — this command is for scripts and agents.
    Humans usually want `column set` which dispatches via codecs.
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    try:
        parsed: Any = json.loads(values)
    except json.JSONDecodeError as e:
        typer.secho(f"error: --values is not valid JSON: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from e
    if not isinstance(parsed, dict) or not parsed:
        typer.secho(
            "error: --values must be a non-empty JSON object", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(code=2)

    client = _client_or_exit(opts)
    try:
        with client:
            board_id, _defs, _values = _fetch_column_context(client, item_id, list(parsed.keys()))
            if opts.dry_run:
                opts.emit(
                    {
                        "query": CHANGE_MULTIPLE_COLUMN_VALUES,
                        "variables": {
                            "item": item_id,
                            "board": board_id,
                            "values": json.dumps(parsed),
                            "create_labels": create_labels_if_missing or None,
                        },
                    }
                )
                raise typer.Exit(0)
            data = _exec_or_exit(
                client,
                CHANGE_MULTIPLE_COLUMN_VALUES,
                {
                    "item": item_id,
                    "board": board_id,
                    "values": json.dumps(parsed),
                    "create_labels": create_labels_if_missing or None,
                },
            )
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    opts.emit(data.get("change_multiple_column_values") or {})


@app.command("clear")
def clear_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--item", help="Item ID."),
    column_id: str = typer.Option(..., "--column", help="Column ID."),
) -> None:
    """Clear a column value, using the correct empty payload for the column's type."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    client = _client_or_exit(opts)
    try:
        with client:
            board_id, defs, _current = _fetch_column_context(client, item_id, [column_id])
            definition = defs.get(column_id)
            if not definition:
                typer.secho(
                    f"column {column_id!r} not found on item {item_id}'s board.",
                    fg=typer.colors.RED,
                    err=True,
                )
                raise typer.Exit(code=6)

            try:
                payload = clear_payload_for(definition["type"])
            except UnknownColumnTypeError:
                payload = {}  # safe default for unfamiliar types

            if opts.dry_run:
                opts.emit(
                    {
                        "query": CHANGE_COLUMN_VALUE,
                        "variables": {
                            "item": item_id,
                            "board": board_id,
                            "col": column_id,
                            "value": json.dumps(payload),
                            "create_labels": None,
                        },
                    }
                )
                raise typer.Exit(0)

            data = _exec_or_exit(
                client,
                CHANGE_COLUMN_VALUE,
                {
                    "item": item_id,
                    "board": board_id,
                    "col": column_id,
                    "value": json.dumps(payload),
                    "create_labels": None,
                },
            )
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    opts.emit(data.get("change_column_value") or {})
