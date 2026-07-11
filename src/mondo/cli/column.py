"""`mondo column` command group: list, get, set, set-many, clear.

Column values are dispatched through `mondo.columns` codecs keyed on the
column's `type` (fetched alongside the item). Read-only types (`mirror`,
`formula`, etc.) reject writes at the codec layer.
"""

from __future__ import annotations

import json
import sys
from contextlib import nullcontext
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer

from mondo.api.errors import MondoError, NotFoundError, UsageError, ValidationError
from mondo.api.queries import (
    CHANGE_COLUMN_VALUE,
    CHANGE_MULTIPLE_COLUMN_VALUES,
    COLUMN_CHANGE_METADATA,
    COLUMN_CONTEXT,
    COLUMN_CREATE,
    COLUMN_DELETE,
    COLUMN_RENAME,
)
from mondo.cli._batch import build_batch_chunks_repr, run_aliased_batch
from mondo.cli._cache_flags import reject_mutually_exclusive
from mondo.cli._cache_invalidate import invalidate_board_items_cache, invalidate_entity
from mondo.cli._confirm import confirm_or_abort as _confirm
from mondo.cli._examples import epilog_for
from mondo.cli._exec import (
    client_or_exit,
    dry_run_and_exit,
    exec_or_exit,
    execute,
    handle_mondo_error_or_exit,
    usage_error_or_exit,
)
from mondo.cli._json_flag import parse_json_flag
from mondo.cli.column_doc import app as doc_app
from mondo.cli.context import GlobalOpts
from mondo.columns import (
    UnknownColumnTypeError,
    clear_payload_for,
    parse_value,
    render_entry,
)
from mondo.columns.dropdown import iter_dropdown_labels
from mondo.columns.status import iter_status_labels
from mondo.domain.column_cache import fetch_board_columns, invalidate_columns_cache
from mondo.domain.columns_resolve import parse_settings, resolve_tag_names_to_ids
from mondo.domain.resolve import resolve_by_filters, resolve_required_id
from mondo.services.items import fetch_column_defs, read_batch_rows

if TYPE_CHECKING:
    from collections.abc import Callable

    from mondo.api.client import MondayClient

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
        usage_error_or_exit("provide --value, --from-file @path, or --from-stdin")
    if sources > 1:
        usage_error_or_exit("--value, --from-file, and --from-stdin are mutually exclusive")
    if from_file is not None:
        return from_file.read_text()
    if from_stdin:
        return sys.stdin.read()
    assert value is not None
    return value


_CLEAR_SHAPED_JSON: tuple[Any, ...] = ({}, [], None, {"labels": []}, {"labels": None})


def _clear_hint(raw_input: str, item_id: int, column_id: str) -> str:
    """Return a `column clear` hint (#91) when `raw_input` looks like an
    attempt to empty a column, else an empty string.

    Clear-shaped inputs are the empty/whitespace string, the literals
    `{}` / `null` / `[]`, or JSON that parses to `{}`, `[]`, `null`, or
    `{"labels": []}` / `{"labels": null}`. Appended to a codec's
    ValueError so agents blindly passing an "empty" payload get pointed
    at the command that actually clears a column.
    """
    stripped = raw_input.strip()
    clear_shaped = stripped in ("", "{}", "null", "[]")
    if not clear_shaped:
        try:
            parsed = json.loads(stripped)
        except ValueError:
            return ""
        clear_shaped = any(parsed == candidate for candidate in _CLEAR_SHAPED_JSON)
    if not clear_shaped:
        return ""
    return f" To empty a column, use: mondo column clear --item {item_id} --column {column_id}"


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
                client,
                board_id,
                store=opts.columns_cache_store(board_id, no_cache=no_cache),
                refresh=refresh_cache,
            )
    except NotFoundError:
        handle_mondo_error_or_exit(NotFoundError(f"board {board_id} not found."))
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


@app.command("get-meta", epilog=epilog_for("column get-meta"))
def get_meta_cmd(
    ctx: typer.Context,
    board_pos: int | None = typer.Argument(
        None, metavar="[BOARD_ID]", help="Board ID (positional)."
    ),
    board_flag: int | None = typer.Option(None, "--board", help="Board ID (flag form)."),
    column_id: str = typer.Option(..., "--column", help="Column ID to inspect."),
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
    """Fetch metadata for a single column (id, title, type, settings_str, archived).

    Like `column list` but narrowed to one column — useful when you already
    know the column ID and only need its `settings_str` (e.g. to enumerate
    dropdown options or read a board_relation's target board ID). Unlike
    `column list`, the full `settings_str` is preserved in the output.
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    board_id = resolve_required_id(board_pos, board_flag, flag_name="--board", resource="board")
    reject_mutually_exclusive(no_cache, refresh_cache)
    client = client_or_exit(opts)
    try:
        with client:
            columns = fetch_board_columns(
                client,
                board_id,
                store=opts.columns_cache_store(board_id, no_cache=no_cache),
                refresh=refresh_cache,
            )
    except NotFoundError:
        handle_mondo_error_or_exit(NotFoundError(f"board {board_id} not found."))
    except MondoError as e:
        handle_mondo_error_or_exit(e)
    column = next((c for c in columns if c.get("id") == column_id), None)
    if column is None:
        handle_mondo_error_or_exit(
            NotFoundError(f"column {column_id!r} not found on board {board_id}.")
        )
    opts.emit(column)


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
            columns = fetch_board_columns(
                client, board_id, store=opts.columns_cache_store(board_id)
            )
    except NotFoundError:
        handle_mondo_error_or_exit(NotFoundError(f"board {board_id} not found."))
    except MondoError as e:
        handle_mondo_error_or_exit(e)
    column = next((c for c in columns if c.get("id") == column_id), None)
    if column is None:
        handle_mondo_error_or_exit(
            NotFoundError(f"column {column_id!r} not found on board {board_id}.")
        )
    col_type = column.get("type")
    settings = parse_settings(column.get("settings_str"))
    if col_type == "status":
        opts.emit(iter_status_labels(settings))
        return
    if col_type == "dropdown":
        opts.emit(iter_dropdown_labels(settings))
        return
    usage_error_or_exit(
        f"column labels only supported for status/dropdown columns "
        f"(column {column_id!r} is type {col_type!r})."
    )


@app.command("get", epilog=epilog_for("column get"))
def get_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--item", help="Item ID."),
    column_id: str = typer.Option(..., "--column", help="Column ID."),
    raw: bool = typer.Option(
        False,
        "--raw",
        help="Return the full column_values entry (id, type, value (JSON string), "
        "text, plus polymorphic fields like display_value/linked_item_ids on "
        "mirror & board_relation) instead of human-rendered text.",
    ),
) -> None:
    """Read a single column value from an item."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    client = client_or_exit(opts)
    try:
        with client:
            _, _defs, values = _fetch_column_context(client, item_id, [column_id])
    except NotFoundError as e:
        handle_mondo_error_or_exit(NotFoundError(str(e)))
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
    try:
        rendered = render_entry(col_type, current)
    except UnknownColumnTypeError:
        rendered = current.get("text") or ""
    opts.emit(rendered)


@app.command("set", epilog=epilog_for("column set"))
def set_cmd(
    ctx: typer.Context,
    item_id: int | None = typer.Option(
        None, "--item", help="Item ID (single-item mode; omit when using --batch)."
    ),
    column_id: str | None = typer.Option(
        None,
        "--column",
        help="Column ID (single-item mode; default column for --batch rows omitting one).",
    ),
    value: str | None = typer.Option(None, "--value", help="Value (codec-parsed)."),
    from_file: Path | None = typer.Option(None, "--from-file", help="Read value from a file."),
    from_stdin: bool = typer.Option(False, "--from-stdin", help="Read value from stdin."),
    board_flag: int | None = typer.Option(
        None,
        "--board",
        help="Board ID. Required with (and only valid with) --batch.",
    ),
    batch: Path | None = typer.Option(
        None,
        "--batch",
        help=(
            "Bulk-set from a JSON array (use '-' for stdin) of {item, value} or "
            "{item, column, value} rows. Requires --board. Mutually exclusive "
            "with --item / --value / --from-file / --from-stdin."
        ),
    ),
    chunk_size: int = typer.Option(
        10,
        "--chunk-size",
        help="Rows per HTTP call when --batch is used (default 10).",
    ),
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
    """Set a single column value, using the registered codec for the column's type.

    Two modes:
    - Single (default): pass --item and --column (+ --value/--from-file/--from-stdin).
    - Bulk: pass --board and --batch <path|-> with a JSON array of {item, value}
      or {item, column, value} rows. --column supplies the default column for
      rows omitting one. The chunk is fanned into one GraphQL document per
      chunk via aliasing, so N rows = one HTTP call (with --chunk-size 10).
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)

    if batch is not None:
        if item_id is not None or value is not None or from_file is not None or from_stdin:
            usage_error_or_exit(
                "--batch is mutually exclusive with --item / --value / "
                "--from-file / --from-stdin. Express per-row settings in the "
                "JSON array."
            )
        if board_flag is None:
            usage_error_or_exit("--board is required with --batch.")
        if chunk_size < 1:
            usage_error_or_exit("--chunk-size must be >= 1.")
        try:
            rows = read_batch_rows(batch)
        except UsageError as e:
            usage_error_or_exit(str(e))
        _run_column_set_batch(
            opts,
            board_flag,
            rows,
            default_column=column_id,
            raw=column_raw,
            create_labels=create_labels_if_missing,
            chunk_size=chunk_size,
        )
        return

    if board_flag is not None:
        usage_error_or_exit("--board is only valid with --batch.")
    if item_id is None:
        usage_error_or_exit("--item is required (or pass --board --batch <path|-> for bulk).")
    if column_id is None:
        usage_error_or_exit("--column is required.")
    raw_input = _load_value(value, from_file, from_stdin)

    client = client_or_exit(opts)
    try:
        with client:
            board_id, defs, _current = _fetch_column_context(client, item_id, [column_id])
            definition = defs.get(column_id)
            if not definition:
                handle_mondo_error_or_exit(
                    NotFoundError(f"column {column_id!r} not found on item {item_id}'s board.")
                )

            col_type = definition["type"]
            settings = parse_settings(definition.get("settings_str"))

            if column_raw:
                try:
                    parsed: Any = json.loads(raw_input)
                except json.JSONDecodeError as e:
                    usage_error_or_exit(f"--raw value is not valid JSON: {e}")
            else:
                if col_type == "tags":
                    if opts.dry_run:
                        # resolve_tag_names_to_ids mints tags via
                        # create_or_get_tag — a real mutation — so only accept
                        # values that are already ids; names need a live call.
                        if not _tags_value_all_ids(raw_input):
                            handle_mondo_error_or_exit(
                                ValidationError(
                                    "resolving tag names requires a live call; "
                                    "use tag ids in --dry-run."
                                )
                            )
                    else:
                        # Resolve tag names to IDs before the codec sees them.
                        raw_input = resolve_tag_names_to_ids(client, board_id, raw_input)
                try:
                    parsed = parse_value(
                        col_type, raw_input, settings, create_labels=create_labels_if_missing
                    )
                except ValueError as e:
                    hint = _clear_hint(raw_input, item_id, column_id)
                    handle_mondo_error_or_exit(ValidationError(f"{e}{hint}"))
                except UnknownColumnTypeError as e:
                    if col_type == "name":
                        # The item title masquerades as a `name` column in
                        # monday's UI but isn't settable via
                        # change_column_value — what `column set` sends,
                        # including --raw. Point at the real command.
                        handle_mondo_error_or_exit(
                            ValidationError(
                                "'name' is the item's title, not a settable "
                                "column. Use: mondo item rename "
                                f'{item_id} --board {board_id} --name "<new name>"'
                            )
                        )
                    handle_mondo_error_or_exit(
                        ValidationError(
                            f"no codec for column type {col_type!r}. "
                            f"Use --raw to send a literal JSON payload. Details: {e}"
                        )
                    )

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
        invalidate_columns_cache(opts.columns_cache_store_for_invalidation(board_id))
    invalidate_entity(opts, "items", scope=str(item_id))
    invalidate_board_items_cache(opts, board_id)
    opts.emit(data.get("change_column_value") or {})


def _tags_value_all_ids(raw: str) -> bool:
    """True when every comma-separated part of a tags value is already a
    numeric id, so no name→id resolution (a live `create_or_get_tag`
    mutation) is needed. Mirrors the pass-through check in
    `resolve_tag_names_to_ids`."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return all(p.isdigit() or (p.startswith("-") and p[1:].isdigit()) for p in parts)


def _build_column_set_row_vars(
    board_id: int,
    defs: dict[str, dict[str, Any]],
    row: dict[str, Any],
    index: int,
    *,
    default_column: str | None,
    raw: bool,
    create_labels: bool,
    dry_run: bool,
) -> tuple[dict[str, Any], int, str, Callable[[MondayClient, dict[str, int]], str] | None]:
    """Render one `column set --batch` row into CHANGE_COLUMN_VALUE variables.

    This is the batch's phase-1 validation: it parses/validates the row fully
    but never mints anything. Returns `(variables, item_id, column_id,
    finalizer)`. `finalizer` is `None` unless the row targets a `tags` column
    in a live (non-`--raw`, non-`--dry-run`) run: resolving tag names goes
    through `create_or_get_tag` (a real mutation), so it's deferred until every
    row has validated — the caller runs the finalizer in phase 2 to fill in the
    `value`, keeping a bad row from leaving half-minted tags behind.

    Raises `UsageError` (exit 2) for structural problems (missing/invalid item,
    no column, missing value) and `ValidationError` (exit 5) for codec parse
    failures and non-codec-able values (structured payloads / JSON null) — all
    naming the row index.
    """
    item_raw = row.get("item")
    if item_raw is None or (isinstance(item_raw, str) and not item_raw.strip()):
        raise UsageError(f"--batch row {index}: missing required 'item' field.")
    # Accept only genuine integer ids or digit-only strings. `int()` would
    # silently truncate 1.9 → 1 and coerce True → 1, which is dangerous for a
    # bulk writer (bool is an int subclass, so it must be rejected first).
    if isinstance(item_raw, bool):
        raise UsageError(f"--batch row {index}: 'item' must be an integer id, got {item_raw!r}.")
    if isinstance(item_raw, int):
        item_id = item_raw
    elif isinstance(item_raw, str) and item_raw.strip().isdigit():
        item_id = int(item_raw.strip())
    else:
        raise UsageError(f"--batch row {index}: 'item' must be an integer id, got {item_raw!r}.")

    column_id = row.get("column") or default_column
    if not column_id:
        raise UsageError(f"--batch row {index}: no 'column' in the row and no --column default.")
    if column_id == "name":
        # The item title masquerades as a `name` column but isn't settable via
        # change_column_value — including --raw. Guard both modes up front.
        raise ValidationError(
            f"--batch row {index}: 'name' is the item's title, not a settable "
            f'column. Use: mondo item rename {item_id} --board {board_id} --name "<new name>"'
        )

    if "value" not in row:
        raise UsageError(f"--batch row {index}: missing required 'value' field.")
    value = row["value"]

    finalizer: Callable[[MondayClient, dict[str, int]], str] | None = None
    if raw:
        json_value: str | None = json.dumps(value)
    else:
        definition = defs.get(column_id)
        if definition is None:
            raise ValidationError(
                f"--batch row {index}: column {column_id!r} not found on board {board_id}."
            )
        col_type = definition["type"]
        settings = parse_settings(definition.get("settings_str"))
        # Normalize the row value for codec input. Strings pass through; bare
        # scalars (int/float/bool) are codec shorthand and get stringified,
        # mirroring services.items.build_column_values. Structured payloads
        # (dict/list) and JSON null can't feed a codec — point at --raw (and,
        # when the value looks like an attempt to empty a column, at
        # `column clear` via the #91 hint).
        if isinstance(value, (dict, list)) or value is None:
            hint = _clear_hint(json.dumps(value), item_id, column_id)
            if isinstance(value, dict):
                detail = "a JSON object; pass --raw to send a literal JSON payload"
            elif isinstance(value, list):
                detail = "a JSON array; pass --raw to send a literal JSON payload"
            else:
                detail = "JSON null"
            raise ValidationError(
                f"--batch row {index}: value for column {column_id!r} is {detail}.{hint}"
            )
        str_value = value if isinstance(value, str) else json.dumps(value)
        if col_type == "tags" and not dry_run:
            # resolve_tag_names_to_ids mints tags via create_or_get_tag — a
            # real mutation. Defer it (and the codec) to phase 2 so it only
            # runs once the whole batch has validated.
            def _finalize_tags(
                cl: MondayClient,
                cache: dict[str, int],
                _str_value: str = str_value,
                _settings: dict[str, Any] = settings,
                _create_labels: bool = create_labels,
                _column_id: str = column_id,
                _index: int = index,
            ) -> str:
                resolved = resolve_tag_names_to_ids(cl, board_id, _str_value, cache=cache)
                try:
                    parsed_tags = parse_value(
                        "tags", resolved, _settings, create_labels=_create_labels
                    )
                except ValueError as e:
                    hint = _clear_hint(resolved, item_id, _column_id)
                    raise ValidationError(
                        f"--batch row {_index} (column {_column_id}): {e}{hint}"
                    ) from e
                return json.dumps(parsed_tags)

            finalizer = _finalize_tags
            json_value = None  # phase 2 fills this in
        else:
            # dry_run tags: resolve_tag_names_to_ids would write, so only
            # accept values that are already ids; names need a live call.
            if col_type == "tags" and not _tags_value_all_ids(str_value):
                raise ValidationError(
                    f"--batch row {index} (column {column_id}): resolving tag "
                    "names requires a live call; use tag ids in --dry-run."
                )
            try:
                parsed = parse_value(col_type, str_value, settings, create_labels=create_labels)
            except ValueError as e:
                hint = _clear_hint(str_value, item_id, column_id)
                raise ValidationError(f"--batch row {index} (column {column_id}): {e}{hint}") from e
            except UnknownColumnTypeError as e:
                raise ValidationError(
                    f"--batch row {index}: no codec for column type {col_type!r}. "
                    f"Use --raw to send a literal JSON payload. Details: {e}"
                ) from e
            json_value = json.dumps(parsed)

    variables = {
        "item": item_id,
        "board": board_id,
        "col": column_id,
        "value": json_value,
        "create_labels": create_labels or None,
    }
    return variables, item_id, column_id, finalizer


def _run_column_set_batch(
    opts: GlobalOpts,
    board_id: int,
    rows: list[dict[str, Any]],
    *,
    default_column: str | None,
    raw: bool,
    create_labels: bool,
    chunk_size: int,
) -> None:
    """Execute a batched `column set`. Column defs are fetched once for the
    whole board (the point of the batch), each chunk is fanned into a single
    multi-mutation document via aliasing, and per-row success/failure is
    aggregated into one envelope."""
    # Codec dispatch needs the board's column defs + a client for tag
    # resolution; --raw skips both, so `--dry-run --raw` is fully offline.
    needs_preflight = not raw
    client: MondayClient | None = None
    if needs_preflight or not opts.dry_run:
        client = client_or_exit(opts)

    results: list[dict[str, Any]] = []
    try:
        defs: dict[str, dict[str, Any]] = {}
        tag_cache: dict[str, int] = {}
        ctx_mgr: Any = client if client is not None else nullcontext()
        with ctx_mgr:
            if needs_preflight and client is not None:
                # Strict fetch: an inaccessible/missing board must surface as
                # a board-not-found (exit 6), not empty defs that make every
                # column look "not found" (a misleading exit 5).
                try:
                    defs = fetch_column_defs(opts, client, board_id, strict=True)
                except NotFoundError as e:
                    raise NotFoundError(f"board {board_id} not found.") from e
            # Phase 1: validate/parse every row without minting anything.
            per_row = [
                _build_column_set_row_vars(
                    board_id,
                    defs,
                    row,
                    i,
                    default_column=default_column,
                    raw=raw,
                    create_labels=create_labels,
                    dry_run=opts.dry_run,
                )
                for i, row in enumerate(rows)
            ]
            # Phase 2: now that the whole batch validated, run the deferred
            # tag-resolution finalizers (create_or_get_tag) and fill in values.
            for variables, _item, _col, finalizer in per_row:
                if finalizer is not None:
                    assert client is not None
                    variables["value"] = finalizer(client, tag_cache)
            per_row_vars = [v for v, _item, _col, _f in per_row]
            name_rows = [{"name": f"{item}:{col}"} for _v, item, col, _f in per_row]

            if opts.dry_run:
                opts.emit(
                    {
                        "chunks": build_batch_chunks_repr(
                            CHANGE_COLUMN_VALUE, per_row_vars, chunk_size
                        )
                    }
                )
                raise typer.Exit(0)

            assert client is not None
            results = run_aliased_batch(
                client, CHANGE_COLUMN_VALUE, per_row_vars, name_rows, chunk_size=chunk_size
            )
    except MondoError as e:
        handle_mondo_error_or_exit(e)

    if create_labels:
        invalidate_columns_cache(opts.columns_cache_store_for_invalidation(board_id))
    invalidate_board_items_cache(opts, board_id)
    for item_id in {item for _v, item, _col, _f in per_row}:
        invalidate_entity(opts, "items", scope=str(item_id))

    failed = sum(1 for r in results if not r["ok"])
    summary = {"requested": len(rows), "updated": len(results) - failed, "failed": failed}
    opts.emit({"summary": summary, "results": results})
    if failed:
        raise typer.Exit(code=1)


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
        usage_error_or_exit("--values must be a non-empty JSON object")

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
        invalidate_columns_cache(opts.columns_cache_store_for_invalidation(board_id))
    invalidate_entity(opts, "items", scope=str(item_id))
    invalidate_board_items_cache(opts, board_id)
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
                handle_mondo_error_or_exit(
                    NotFoundError(f"column {column_id!r} not found on item {item_id}'s board.")
                )

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

    invalidate_entity(opts, "items", scope=str(item_id))
    invalidate_board_items_cache(opts, board_id)
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
        usage_error_or_exit(f"--defaults is not valid JSON ({exc}).")
    return json.dumps(parsed)


def _labels_to_defaults(labels: str, column_type: str) -> str:
    """Build a `--defaults` JSON string from `--labels` for status/dropdown columns.

    status wants `{"labels": {"1": name, ...}}` (1-based string index keys);
    dropdown wants `{"settings": {"labels": [{"id": 1, "name": name}, ...]}}`.
    """
    names = [part.strip() for part in labels.split(",") if part.strip()]
    if not names:
        usage_error_or_exit("--labels is empty.")
    if column_type == "status":
        payload: dict[str, Any] = {"labels": {str(i): name for i, name in enumerate(names, 1)}}
    elif column_type == "dropdown":
        payload = {
            "settings": {"labels": [{"id": i, "name": name} for i, name in enumerate(names, 1)]}
        }
    else:
        usage_error_or_exit("--labels only applies to status/dropdown columns.")
    return json.dumps(payload)


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
            'dropdown: \'{"settings":{"labels":[...]}}\'). For initial status/dropdown '
            "labels, prefer --labels, which builds this for you. Mutually exclusive "
            "with --labels."
        ),
    ),
    labels: str | None = typer.Option(
        None,
        "--labels",
        help=(
            "Comma-separated initial labels for a status/dropdown column; builds "
            "--defaults for you. Mutually exclusive with --defaults."
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
    if labels is not None:
        if defaults is not None:
            usage_error_or_exit("--labels and --defaults are mutually exclusive.")
        defaults = _labels_to_defaults(labels, column_type)
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
    invalidate_columns_cache(opts.columns_cache_store_for_invalidation(board_id))
    invalidate_entity(opts, "board_details", scope=str(board_id))
    # A new column adds a column_values entry to every cached `item list` row.
    invalidate_board_items_cache(opts, board_id)
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
    columns = fetch_board_columns(client, board_id, store=opts.columns_cache_store(board_id))
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
    invalidate_columns_cache(opts.columns_cache_store_for_invalidation(board_id))
    invalidate_entity(opts, "board_details", scope=str(board_id))
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
    invalidate_columns_cache(opts.columns_cache_store_for_invalidation(board_id))
    invalidate_entity(opts, "board_details", scope=str(board_id))
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
    invalidate_columns_cache(opts.columns_cache_store_for_invalidation(board_id))
    invalidate_entity(opts, "board_details", scope=str(board_id))
    # Cached `item list` rows would keep serving the deleted column's values.
    invalidate_board_items_cache(opts, board_id)
    opts.emit(data.get("delete_column") or {})
