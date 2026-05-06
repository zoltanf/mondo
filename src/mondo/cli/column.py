"""`mondo column` command group: list, get, set, set-many, clear.

Column values are dispatched through `mondo.columns` codecs keyed on the
column's `type` (fetched alongside the item). Read-only types (`mirror`,
`formula`, etc.) reject writes at the codec layer.
"""

from __future__ import annotations

import json
import sys
from enum import StrEnum
from pathlib import Path
from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError, NotFoundError
from mondo.api.queries import (
    CHANGE_COLUMN_VALUE,
    CHANGE_MULTIPLE_COLUMN_VALUES,
    COLUMN_CHANGE_METADATA,
    COLUMN_CONTEXT,
    COLUMN_CREATE,
    COLUMN_DELETE,
    COLUMN_RENAME,
)
from mondo.cli._cache_flags import reject_mutually_exclusive
from mondo.cli._column_cache import fetch_board_columns, invalidate_columns_cache
from mondo.cli._columns import parse_settings, resolve_tag_names_to_ids
from mondo.cli._confirm import confirm_or_abort as _confirm
from mondo.cli._examples import epilog_for
from mondo.cli._exec import (
    client_or_exit,
    dry_run_and_exit,
    exec_or_exit,
    execute,
    handle_mondo_error_or_exit,
)
from mondo.cli._json_flag import parse_json_flag
from mondo.cli._resolve import resolve_by_filters, resolve_required_id
from mondo.cli.column_doc import app as doc_app
from mondo.cli.context import GlobalOpts
from mondo.columns import (
    UnknownColumnTypeError,
    clear_payload_for,
    parse_value,
    render_value,
)
from mondo.columns.dropdown import iter_dropdown_labels
from mondo.columns.status import iter_status_labels

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
app.add_typer(doc_app, name="doc", help="Read/write the content of a `doc`-typed column.")


# ----- helpers -----


def _fetch_column_context(
    client: MondayClient, item_id: int, column_ids: list[str]
) -> tuple[int, dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return (board_id, {col_id: definition}, {col_id: current_value}).

    Raises NotFoundError if the item doesn't exist.
    `column_ids` must be non-empty.
    """
    data = exec_or_exit(client, COLUMN_CONTEXT, {"id": item_id, "cols": column_ids})
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


@app.command("list", epilog=epilog_for("column list"))
def list_cmd(
    ctx: typer.Context,
    board_pos: int | None = typer.Argument(
        None, metavar="[BOARD_ID]", help="Board ID (positional)."
    ),
    board_flag: int | None = typer.Option(None, "--board", help="Board ID (flag form)."),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Skip the local columns cache; fetch live.",
        rich_help_panel="Cache",
    ),
    refresh_cache: bool = typer.Option(
        False,
        "--refresh-cache",
        help="Force-refresh the local columns cache before serving.",
        rich_help_panel="Cache",
    ),
) -> None:
    """List all columns on a board with id, title, type."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    board_id = resolve_required_id(board_pos, board_flag, flag_name="--board", resource="board")
    reject_mutually_exclusive(no_cache, refresh_cache)
    client = client_or_exit(opts)
    try:
        with client:
            columns = fetch_board_columns(
                opts, client, board_id, no_cache=no_cache, refresh=refresh_cache
            )
    except NotFoundError:
        typer.secho(f"board {board_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6) from None
    except MondoError as e:
        handle_mondo_error_or_exit(e)
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


@app.command("labels", epilog=epilog_for("column labels"))
def labels_cmd(
    ctx: typer.Context,
    board_pos: int | None = typer.Argument(
        None, metavar="[BOARD_ID]", help="Board ID (positional)."
    ),
    board_flag: int | None = typer.Option(None, "--board", help="Board ID (flag form)."),
    column_id: str = typer.Option(..., "--column", help="Column ID (status or dropdown)."),
) -> None:
    """List the known labels for a status or dropdown column on a board.

    For status columns, emits `{index, label}` tuples. For dropdown columns,
    emits `{id, name}` tuples. Other column types are rejected with a clear
    error.
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    board_id = resolve_required_id(board_pos, board_flag, flag_name="--board", resource="board")
    client = client_or_exit(opts)
    try:
        with client:
            columns = fetch_board_columns(opts, client, board_id)
    except NotFoundError:
        typer.secho(f"board {board_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6) from None
    except MondoError as e:
        handle_mondo_error_or_exit(e)
    column = next((c for c in columns if c.get("id") == column_id), None)
    if column is None:
        typer.secho(
            f"column {column_id!r} not found on board {board_id}.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=6)
    col_type = column.get("type")
    settings = parse_settings(column.get("settings_str"))
    if col_type == "status":
        opts.emit(iter_status_labels(settings))
        return
    if col_type == "dropdown":
        opts.emit(iter_dropdown_labels(settings))
        return
    typer.secho(
        f"error: column labels only supported for status/dropdown columns "
        f"(column {column_id!r} is type {col_type!r}).",
        fg=typer.colors.RED,
        err=True,
    )
    raise typer.Exit(code=2)


@app.command("get", epilog=epilog_for("column get"))
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
    client = client_or_exit(opts)
    try:
        with client:
            _, _defs, values = _fetch_column_context(client, item_id, [column_id])
    except NotFoundError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6) from e
    except MondoError as e:
        handle_mondo_error_or_exit(e)

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
        except ValueError:
            value_payload = raw_value
    try:
        rendered = render_value(col_type, value_payload, current.get("text"))
    except UnknownColumnTypeError:
        rendered = current.get("text") or ""
    opts.emit(rendered)


@app.command("set", epilog=epilog_for("column set"))
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

    client = client_or_exit(opts)
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
            settings = parse_settings(definition.get("settings_str"))

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
                    raw_input = resolve_tag_names_to_ids(client, board_id, raw_input)
                try:
                    parsed = parse_value(
                        col_type, raw_input, settings, create_labels=create_labels_if_missing
                    )
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

            data = exec_or_exit(
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
        handle_mondo_error_or_exit(e)

    if create_labels_if_missing:
        # `create_labels_if_missing=True` may have minted a new status/dropdown
        # label inside the column's settings_str — drop the cached copy.
        invalidate_columns_cache(opts, board_id)
    opts.emit(data.get("change_column_value") or {})


@app.command("set-many", epilog=epilog_for("column set-many"))
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
    parsed: Any = parse_json_flag(values, flag_name="--values")
    if not isinstance(parsed, dict) or not parsed:
        typer.secho(
            "error: --values must be a non-empty JSON object", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(code=2)

    client = client_or_exit(opts)
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
            data = exec_or_exit(
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
        handle_mondo_error_or_exit(e)

    if create_labels_if_missing:
        # May have minted a label in a status/dropdown column's settings_str.
        invalidate_columns_cache(opts, board_id)
    opts.emit(data.get("change_multiple_column_values") or {})


@app.command("clear", epilog=epilog_for("column clear"))
def clear_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--item", help="Item ID."),
    column_id: str = typer.Option(..., "--column", help="Column ID."),
) -> None:
    """Clear a column value, using the correct empty payload for the column's type."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    client = client_or_exit(opts)
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

            data = exec_or_exit(
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
        handle_mondo_error_or_exit(e)

    opts.emit(data.get("change_column_value") or {})


# ----- structural mutations (2b) -----


class ColumnProperty(StrEnum):
    """Attributes settable via `change_column_metadata`.

    monday only allows `title` and `description` through this mutation; status
    labels / dropdown options are seeded via `create_column --defaults` or
    added at write-time with `create_labels_if_missing`.
    """

    title = "title"  # type: ignore[assignment]  # StrEnum value shadows str.title method
    description = "description"


def _parse_defaults(raw: str | None) -> str | None:
    """Validate `--defaults '<json>'` as JSON and return it as a JSON-*string*.

    monday's `defaults` argument is typed `JSON` but expects a JSON-encoded
    string (same double-JSON convention as `column_values`, §11.4). Returning
    `None` leaves the argument unset.
    """
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        typer.secho(f"error: --defaults is not valid JSON ({exc}).", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    return json.dumps(parsed)


@app.command("create", epilog=epilog_for("column create"))
def create_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID to add the column to."),
    title: str = typer.Option(..., "--title", help="Column title (shown in the UI)."),
    column_type: str = typer.Option(
        ...,
        "--type",
        help=(
            "Column type (e.g. status, date, numbers, dropdown, people, text, "
            "long_text, link, email, phone, checkbox, rating, tags, timeline, "
            "week, hour, country, location, board_relation, dependency, doc). "
            "See monday-api.md §11.5 for the full catalog."
        ),
    ),
    description: str | None = typer.Option(None, "--description"),
    defaults: str | None = typer.Option(
        None,
        "--defaults",
        metavar="JSON",
        help=(
            'Type-specific defaults as JSON (e.g. status: \'{"labels":{"1":"High"}}\', '
            'dropdown: \'{"settings":{"labels":[...]}}\').'
        ),
    ),
    custom_id: str | None = typer.Option(
        None,
        "--id",
        help=(
            "Custom column ID (1-20 chars, lowercase alphanumeric + underscores, unique per board)."
        ),
    ),
    after: str | None = typer.Option(
        None, "--after", help="Position the new column after this column ID."
    ),
) -> None:
    """Create a new column on a board."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    defaults_str = _parse_defaults(defaults)
    variables: dict[str, Any] = {
        "board": board_id,
        "title": title,
        "type": column_type,
        "description": description,
        "defaults": defaults_str,
        "id": custom_id,
        "after": after,
    }
    data = execute(opts, COLUMN_CREATE, variables)
    invalidate_columns_cache(opts, board_id)
    opts.emit(data.get("create_column") or {})


def _resolve_column_target(
    opts: GlobalOpts,
    client: MondayClient,
    board_id: int,
    *,
    column_id: str | None,
    name_contains: str | None,
    name_matches_re: str | None,
    name_fuzzy: str | None,
    first: bool,
    fuzzy_threshold: int,
) -> str:
    """Pick a single column id for the mutation. Mirrors the group helper."""
    if column_id is not None and not (name_contains or name_matches_re or name_fuzzy):
        return column_id
    columns = fetch_board_columns(opts, client, board_id)
    chosen = resolve_by_filters(
        columns,
        explicit_id=column_id,
        name_contains=name_contains,
        name_matches_re=name_matches_re,
        name_fuzzy=name_fuzzy,
        first=first,
        fuzzy_threshold=fuzzy_threshold,
        key="title",
        resource="column",
    )
    return str(chosen["id"])


@app.command("rename", epilog=epilog_for("column rename"))
def rename_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID."),
    column_id: str | None = typer.Option(
        None, "--id", "--column", help="Column ID (or use --name-* selectors)."
    ),
    name_contains: str | None = typer.Option(
        None, "--name-contains", help="Pick the column by case-insensitive title substring."
    ),
    name_matches_re: str | None = typer.Option(
        None, "--name-matches", help="Pick the column by Python regex over its title."
    ),
    name_fuzzy: str | None = typer.Option(
        None, "--name-fuzzy", help="Pick the column by fuzzy match over its title."
    ),
    fuzzy_threshold: int = typer.Option(
        70, "--fuzzy-threshold", help="Minimum 0-100 fuzzy score (default 70)."
    ),
    first: bool = typer.Option(
        False, "--first", help="If a filter matches >1 column, pick the first one."
    ),
    title: str = typer.Option(..., "--title", help="New column title."),
) -> None:
    """Rename a column (shortcut for change-metadata --property title).

    Pick the target by id (`--id`/`--column`) or by client-side title match
    (`--name-contains` / `--name-matches` / `--name-fuzzy`). Pass `--first`
    to auto-pick the first match when the filter is ambiguous.
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    client = client_or_exit(opts)
    try:
        with client:
            resolved_column = _resolve_column_target(
                opts,
                client,
                board_id,
                column_id=column_id,
                name_contains=name_contains,
                name_matches_re=name_matches_re,
                name_fuzzy=name_fuzzy,
                first=first,
                fuzzy_threshold=fuzzy_threshold,
            )
            variables = {"board": board_id, "col": resolved_column, "title": title}
            if opts.dry_run:
                dry_run_and_exit(opts, COLUMN_RENAME, variables)
            data = exec_or_exit(client, COLUMN_RENAME, variables)
    except MondoError as e:
        handle_mondo_error_or_exit(e)
    invalidate_columns_cache(opts, board_id)
    opts.emit(data.get("change_column_title") or {})


@app.command("change-metadata", epilog=epilog_for("column change-metadata"))
def change_metadata_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID."),
    column_id: str = typer.Option(..., "--id", "--column", help="Column ID."),
    column_property: ColumnProperty = typer.Option(
        ...,
        "--property",
        help="Which metadata field to set. monday only allows title and description.",
        case_sensitive=False,
    ),
    value: str = typer.Option(..., "--value", help="New value for the chosen property."),
) -> None:
    """Change a column's title or description."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {
        "board": board_id,
        "col": column_id,
        "property": column_property.value,
        "value": value,
    }
    data = execute(opts, COLUMN_CHANGE_METADATA, variables)
    invalidate_columns_cache(opts, board_id)
    opts.emit(data.get("change_column_metadata") or {})


@app.command("delete", epilog=epilog_for("column delete"))
def delete_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID."),
    column_id: str = typer.Option(..., "--id", "--column", help="Column ID to delete."),
) -> None:
    """Delete a column (permanent — destroys all values stored in it)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    _confirm(opts, f"PERMANENTLY delete column {column_id!r} on board {board_id}?")
    variables = {"board": board_id, "col": column_id}
    data = execute(opts, COLUMN_DELETE, variables)
    invalidate_columns_cache(opts, board_id)
    opts.emit(data.get("delete_column") or {})
