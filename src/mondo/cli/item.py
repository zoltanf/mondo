"""`mondo item` command group: CRUD for monday items."""

from __future__ import annotations

import json
import sys
from contextlib import nullcontext
from enum import StrEnum
from pathlib import Path
from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import ColumnValueError, MondoError, NotFoundError, UsageError
from mondo.api.pagination import MAX_PAGE_SIZE, iter_items_page
from mondo.api.queries import (
    ITEM_ARCHIVE,
    ITEM_CREATE,
    ITEM_DELETE,
    ITEM_DUPLICATE,
    ITEM_GET,
    ITEM_GET_WITH_SUBITEMS,
    ITEM_GET_WITH_UPDATES,
    ITEM_MOVE_BOARD,
    ITEM_MOVE_GROUP,
    ITEM_RENAME,
)
from mondo.cli._batch import build_aliased_mutation, chunk_inputs, parse_aliased_response
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
from mondo.cli._resolve import resolve_by_filters, resolve_required_id
from mondo.cli._url import MondayIdParam
from mondo.cli.context import GlobalOpts
from mondo.columns import UnknownColumnTypeError, parse_value
from mondo.util.kvparse import parse_column_kv

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


def _execute_create_item(
    opts: GlobalOpts,
    query: str,
    variables: dict[str, Any],
    *,
    column_value_hint: str,
) -> dict[str, Any]:
    """Like `execute()` but adds a column-value hint to `ColumnValueError` messages."""
    if opts.dry_run:
        dry_run_and_exit(opts, query, variables)
    client = client_or_exit(opts)
    try:
        with client:
            result = client.execute(query, variables=variables)
            return result.get("data") or {}
    except ColumnValueError as e:
        handle_mondo_error_or_exit(e, human_suffix=column_value_hint or None)
    except MondoError as e:
        handle_mondo_error_or_exit(e)


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


def _fetch_column_defs(
    opts: GlobalOpts, client: MondayClient, board_id: int
) -> dict[str, dict[str, Any]]:
    """One-shot fetch of `{col_id: {type, settings_str, ...}}` for a board.

    Reads from the per-board columns cache when enabled; falls back to a live
    query otherwise. Silently returns `{}` when the board isn't visible — the
    caller's codec dispatch will treat unknown columns as raw passthroughs,
    mirroring the previous behavior when the API returned no boards.
    """
    try:
        columns = fetch_board_columns(opts, client, board_id)
    except NotFoundError:
        return {}
    return {c["id"]: c for c in columns}


def _build_column_values(
    opts: GlobalOpts,
    client: MondayClient,
    board_id: int,
    pairs: list[str],
    *,
    raw_mode: bool,
    create_labels: bool = False,
    tag_cache: dict[str, int] | None = None,
    column_defs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply codecs to `--column K=V` pairs, using live board column types.

    raw_mode=True disables codec dispatch (user's value used as-is after JSON
    parse-or-passthrough). Raw mode also skips the preflight query.

    `tag_cache` and `column_defs`, when provided, dedupe work across rows
    in a batch: a 50-row batch tagging "urgent" issues one
    `create_or_get_tag` instead of fifty, and `_fetch_column_defs` runs
    once per batch instead of once per row.
    """
    parsed_pairs = [parse_column_kv(p) for p in pairs]

    if raw_mode:
        return dict(parsed_pairs)

    defs = column_defs if column_defs is not None else _fetch_column_defs(opts, client, board_id)
    out: dict[str, Any] = {}
    for col_id, raw_value in parsed_pairs:
        definition = defs.get(col_id)
        # Non-string values mean the user passed JSON — honor it as raw.
        if definition is None or not isinstance(raw_value, str):
            out[col_id] = raw_value
            continue
        col_type = definition["type"]
        settings = parse_settings(definition.get("settings_str"))
        if col_type == "tags":
            raw_value = resolve_tag_names_to_ids(client, board_id, raw_value, cache=tag_cache)
        try:
            out[col_id] = parse_value(col_type, raw_value, settings, create_labels=create_labels)
        except UnknownColumnTypeError:
            # Unfamiliar column type → don't translate, send raw
            out[col_id] = raw_value
        except ValueError as e:
            raise ValueError(f"--column {col_id}={raw_value!r}: {e}") from e
    return out


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


@app.command("get", epilog=epilog_for("item get"))
def get_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(
        None,
        metavar="[ID|URL]",
        help="Item ID or monday.com /pulses/<id> URL (positional).",
        click_type=MondayIdParam(kind="item"),
    ),
    id_flag: int | None = typer.Option(
        None,
        "--id",
        "--item",
        help="Item ID or monday.com /pulses/<id> URL.",
        click_type=MondayIdParam(kind="item"),
    ),
    include_updates: bool = typer.Option(
        False, "--include-updates", help="Also fetch item updates (comments)."
    ),
    include_subitems: bool = typer.Option(False, "--include-subitems", help="Also fetch subitems."),
    with_url: bool = typer.Option(
        False,
        "--with-url",
        help="Include the item's canonical monday.com URL in the emitted payload.",
    ),
) -> None:
    """Fetch a single item by ID or pulses URL."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    item_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="item")
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

    data = execute(opts, query, {"id": item_id})
    items = data.get("items") or []
    if not items:
        typer.secho(f"item {item_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
    item = items[0]
    if not with_url:
        item.pop("url", None)
    from mondo.cli._field_sets import item_get_fields

    opts.emit(item, selected_fields=item_get_fields())


@app.command("list", epilog=epilog_for("item list"))
def list_cmd(
    ctx: typer.Context,
    board_pos: int | None = typer.Argument(
        None, metavar="[BOARD_ID]", help="Board ID (positional)."
    ),
    board_flag: int | None = typer.Option(None, "--board", help="Board ID (flag form)."),
    filter_expr: list[str] | None = typer.Option(
        None,
        "--filter",
        help="Filter rule like 'status=Done' or 'status!=Stuck' (repeatable).",
        rich_help_panel="Filters",
    ),
    order_by: str | None = typer.Option(
        None,
        "--order-by",
        help="Column to sort by, optionally with ',asc'/',desc' (default: asc).",
        rich_help_panel="Filters",
    ),
    limit: int = typer.Option(
        MAX_PAGE_SIZE,
        "--limit",
        help=f"Page size (max {MAX_PAGE_SIZE}).",
        rich_help_panel="Pagination",
    ),
    max_items: int | None = typer.Option(
        None,
        "--max-items",
        help="Stop after this many items total.",
        rich_help_panel="Pagination",
    ),
) -> None:
    """List items on a board (cursor pagination).

    Use --filter 'col=val' (repeatable) to narrow results server-side, and
    --order-by col[,asc|desc] to sort.
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    board_id = resolve_required_id(board_pos, board_flag, flag_name="--board", resource="board")

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
        handle_mondo_error_or_exit(e)
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
        handle_mondo_error_or_exit(e)

    from mondo.cli._field_sets import item_list_fields

    opts.emit(items, selected_fields=item_list_fields())


# ----- write commands -----


def _build_create_variables_for_row(
    opts: GlobalOpts,
    client: MondayClient | None,
    board_id: int,
    row: dict[str, Any],
    *,
    raw_columns: bool,
    create_labels_default: bool,
    tag_cache: dict[str, int] | None = None,
    column_defs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Render one batch row into the `ITEM_CREATE` variable dict.

    Reuses `_build_column_values` for codec dispatch — `client` is required
    when codec preflight is needed (`raw_columns=False` and the row carries
    `columns`). Raises `ValueError` (exit 5) for malformed column values
    and `MondoError` for upstream codec failures.
    """
    raw_columns_field = row.get("columns") or []
    if not isinstance(raw_columns_field, list):
        raise ValueError(
            f"row {row.get('name', '?')!r}: 'columns' must be a list of K=V strings."
        )
    create_labels = bool(row.get("create_labels", create_labels_default))
    col_values: dict[str, Any] = {}
    if raw_columns_field:
        if raw_columns:
            col_values = dict(parse_column_kv(p) for p in raw_columns_field)
        else:
            assert client is not None, "preflight requires a client"
            col_values = _build_column_values(
                opts,
                client,
                board_id,
                list(raw_columns_field),
                raw_mode=False,
                create_labels=create_labels,
                tag_cache=tag_cache,
                column_defs=column_defs,
            )
    prm = row.get("position_relative_method")
    if prm is not None:
        prm = PositionRelative(prm).value
    return {
        "board": board_id,
        "name": str(row["name"]),
        "group": row.get("group_id"),
        # monday's column_values wants a JSON-*string*, not a JSON object (§11.4).
        "values": json.dumps(col_values) if col_values else None,
        "create_labels": create_labels if create_labels else None,
        "prm": prm,
        "relto": row.get("relative_to"),
    }


def _read_batch_input(source: Path) -> list[dict[str, Any]]:
    """Read the `--batch` source and validate it's a JSON array of objects
    each carrying a `name`. Use `Path("-")` for stdin."""
    text = sys.stdin.read() if str(source) == "-" else source.read_text(encoding="utf-8")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise UsageError(f"--batch input is not valid JSON: {e}") from e
    if not isinstance(parsed, list):
        raise UsageError("--batch input must be a JSON array of objects.")
    if not parsed:
        raise UsageError("--batch input is an empty array — nothing to do.")
    for i, row in enumerate(parsed):
        if not isinstance(row, dict):
            raise UsageError(f"--batch row {i}: expected object, got {type(row).__name__}.")
        if not row.get("name"):
            raise UsageError(f"--batch row {i}: missing required 'name' field.")
    return parsed


@app.command("create", epilog=epilog_for("item create"))
def create_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID to create in."),
    name: str | None = typer.Option(
        None, "--name", help="Item title (single-item mode; omit when using --batch)."
    ),
    group_id: str | None = typer.Option(
        None, "--group", help="Target group ID (default: board's top group)."
    ),
    columns: list[str] | None = typer.Option(
        None,
        "--column",
        metavar="COL=VAL",
        help=(
            "Set a column value. Values are codec-parsed per column type "
            "(status=Done, due=2026-04-25, owner=42, tags=urgent,blocked). "
            "JSON objects pass through as-is. Repeatable."
        ),
    ),
    raw_columns: bool = typer.Option(
        False,
        "--raw-columns",
        help="Skip the codec pipeline; treat --column values as raw JSON or strings.",
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
    batch: Path | None = typer.Option(
        None,
        "--batch",
        help=(
            "Bulk-create from a JSON array (use '-' for stdin). Single-item "
            "flags (--name, --group, --column, --position-*) are not allowed "
            "with --batch — express them per-row instead."
        ),
    ),
    chunk_size: int = typer.Option(
        10,
        "--chunk-size",
        help="Items per HTTP call when --batch is used (default 10).",
    ),
) -> None:
    """Create a new item on a board.

    Two modes:
    - Single (default): pass --name (and optional --group, --column, ...).
    - Bulk: pass --batch <path|-> with a JSON array of objects each carrying
      `name` plus optional `group_id`, `columns`, `create_labels`,
      `position_relative_method`, `relative_to`. The chunk is fanned into
      one GraphQL document per chunk via aliasing — so 7 items = 1 HTTP
      call (with default --chunk-size 10).
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)

    if batch is not None:
        single_item_flags = (
            name is not None or group_id is not None or columns
            or position_relative_method is not None or relative_to is not None
        )
        if single_item_flags:
            typer.secho(
                "error: --batch is mutually exclusive with --name / --group / "
                "--column / --position-* / --relative-to. Move per-row "
                "settings into the JSON array.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=2)
        try:
            rows = _read_batch_input(batch)
        except UsageError as e:
            typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from e
        if chunk_size < 1:
            typer.secho("error: --chunk-size must be >= 1.", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)
        _run_batch(
            opts,
            board_id,
            rows,
            raw_columns=raw_columns,
            create_labels_default=create_labels_if_missing,
            chunk_size=chunk_size,
        )
        return

    if not name:
        typer.secho(
            "error: --name is required (or pass --batch <path|-> for bulk).",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    # Resolve column values — codec dispatch needs a live client for the
    # board-columns preflight and (for tags) create_or_get_tag.
    # `--raw-columns` skips the preflight, so `--dry-run --raw-columns` is fully offline.
    col_values: dict[str, Any] = {}
    if columns:
        if raw_columns:
            col_values = dict(parse_column_kv(p) for p in columns)
        else:
            try:
                client_for_preflight = opts.build_client()
            except MondoError as e:
                handle_mondo_error_or_exit(e)
            try:
                with client_for_preflight:
                    col_values = _build_column_values(
                        opts,
                        client_for_preflight,
                        board_id,
                        columns,
                        raw_mode=False,
                        create_labels=create_labels_if_missing,
                    )
            except ValueError as e:
                typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=5) from e
            except MondoError as e:
                handle_mondo_error_or_exit(e)

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
    col_ids = ", ".join(col_values.keys()) if col_values else ""
    data = _execute_create_item(
        opts,
        ITEM_CREATE,
        variables,
        column_value_hint=(
            f"Columns passed: {col_ids}\nHint: see `mondo help codecs` for expected value formats."
            if col_ids
            else ""
        ),
    )
    if create_labels_if_missing:
        # May have minted a status/dropdown label in settings_str; drop the
        # cached column defs so the next read sees the new labels.
        invalidate_columns_cache(opts, board_id)
    opts.emit(data.get("create_item") or {})


def _run_batch(
    opts: GlobalOpts,
    board_id: int,
    rows: list[dict[str, Any]],
    *,
    raw_columns: bool,
    create_labels_default: bool,
    chunk_size: int,
) -> None:
    """Execute a batched item create. Fans each chunk into a single
    multi-mutation GraphQL document via aliasing; aggregates per-row
    success/failure into one envelope."""
    needs_preflight = not raw_columns and any(row.get("columns") for row in rows)
    client: MondayClient | None = None
    if needs_preflight or not opts.dry_run:
        client = client_or_exit(opts)

    try:
        # Per-batch caches dedupe work across rows: column defs are fetched
        # once instead of once per row, and `urgent` tagged in 50 rows
        # issues one create_or_get_tag instead of fifty.
        column_defs: dict[str, dict[str, Any]] | None = None
        tag_cache: dict[str, int] = {}
        if needs_preflight and client is not None:
            column_defs = _fetch_column_defs(opts, client, board_id)

        ctx_mgr: Any = client if client is not None else nullcontext()
        per_row_vars: list[dict[str, Any]] = []
        try:
            with ctx_mgr:
                for row in rows:
                    per_row_vars.append(
                        _build_create_variables_for_row(
                            opts,
                            client,
                            board_id,
                            row,
                            raw_columns=raw_columns,
                            create_labels_default=create_labels_default,
                            tag_cache=tag_cache,
                            column_defs=column_defs,
                        )
                    )
                if opts.dry_run:
                    chunks_repr: list[dict[str, Any]] = []
                    for chunk_idx, vars_chunk in enumerate(chunk_inputs(per_row_vars, chunk_size)):
                        query, var_names = build_aliased_mutation(ITEM_CREATE, len(vars_chunk))
                        flat: dict[str, Any] = {}
                        base = chunk_idx * chunk_size
                        for i, vars_row in enumerate(vars_chunk):
                            for name_ in var_names:
                                flat[f"{name_}_{i}"] = vars_row[name_]
                        chunks_repr.append(
                            {
                                "query": query,
                                "variables": flat,
                                "row_indices": list(range(base, base + len(vars_chunk))),
                            }
                        )
                    opts.emit({"chunks": chunks_repr})
                    raise typer.Exit(0)

                results: list[dict[str, Any]] = []
                assert client is not None
                row_chunks = chunk_inputs(rows, chunk_size)
                vars_chunks = chunk_inputs(per_row_vars, chunk_size)
                for chunk_idx, (row_chunk, vars_chunk) in enumerate(
                    zip(row_chunks, vars_chunks, strict=True)
                ):
                    query, var_names = build_aliased_mutation(ITEM_CREATE, len(vars_chunk))
                    flat = {}
                    for i, vars_row in enumerate(vars_chunk):
                        for name_ in var_names:
                            flat[f"{name_}_{i}"] = vars_row[name_]
                    response = client.execute(
                        query, variables=flat, surface_partial_errors=True
                    )
                    base = chunk_idx * chunk_size
                    results.extend(
                        parse_aliased_response(response, row_chunk, base_index=base)
                    )
        except ValueError as e:
            typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=5) from e
    except MondoError as e:
        handle_mondo_error_or_exit(e)

    if create_labels_default or any(row.get("create_labels") for row in rows):
        invalidate_columns_cache(opts, board_id)

    failed = sum(1 for r in results if not r["ok"])
    summary = {
        "requested": len(rows),
        "created": len(results) - failed,
        "failed": failed,
    }
    opts.emit({"summary": summary, "results": results})
    if failed:
        raise typer.Exit(code=1)


def _resolve_item_target(
    client: MondayClient,
    board_id: int,
    *,
    item_id: int | None,
    name_contains: str | None,
    name_matches_re: str | None,
    name_fuzzy: str | None,
    first: bool,
    fuzzy_threshold: int,
) -> int:
    """Pick a single item id for the mutation. Items aren't cached (volatile),
    so the filter path streams `items_page` and matches client-side."""
    if item_id is not None and not (name_contains or name_matches_re or name_fuzzy):
        return item_id
    items = list(iter_items_page(client, board_id=board_id))
    chosen = resolve_by_filters(
        items,
        explicit_id=item_id,
        name_contains=name_contains,
        name_matches_re=name_matches_re,
        name_fuzzy=name_fuzzy,
        first=first,
        fuzzy_threshold=fuzzy_threshold,
        key="name",
        resource="item",
    )
    return int(chosen["id"])


@app.command("rename", epilog=epilog_for("item rename"))
def rename_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Item ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--item", help="Item ID (flag form)."),
    board_id: int = typer.Option(..., "--board", help="Parent board ID."),
    name_contains: str | None = typer.Option(
        None, "--name-contains", help="Pick the item by case-insensitive name substring."
    ),
    name_matches_re: str | None = typer.Option(
        None, "--name-matches", help="Pick the item by Python regex over its name."
    ),
    name_fuzzy: str | None = typer.Option(
        None, "--name-fuzzy", help="Pick the item by fuzzy match over its name."
    ),
    fuzzy_threshold: int = typer.Option(
        70, "--fuzzy-threshold", help="Minimum 0-100 fuzzy score (default 70)."
    ),
    first: bool = typer.Option(
        False, "--first", help="If a filter matches >1 item, pick the first one."
    ),
    name: str = typer.Option(..., "--name", help="New title."),
) -> None:
    """Rename an item.

    Pick the target by id (positional / `--id` / `--item`) or by client-side
    name match (`--name-contains` / `--name-matches` / `--name-fuzzy`). The
    filter path streams the board's items via `items_page` and is unsuitable
    for huge boards — pass an id directly when the target is known.
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    explicit_id: int | None
    if id_pos is not None and id_flag is not None and id_pos != id_flag:
        raise typer.BadParameter(
            "pass the item ID as a positional argument or via --id, not both."
        )
    explicit_id = id_pos if id_pos is not None else id_flag
    client = client_or_exit(opts)
    try:
        with client:
            resolved_item = _resolve_item_target(
                client,
                board_id,
                item_id=explicit_id,
                name_contains=name_contains,
                name_matches_re=name_matches_re,
                name_fuzzy=name_fuzzy,
                first=first,
                fuzzy_threshold=fuzzy_threshold,
            )
            variables = {"board": board_id, "id": resolved_item, "name": name}
            if opts.dry_run:
                dry_run_and_exit(opts, ITEM_RENAME, variables)
            data = exec_or_exit(client, ITEM_RENAME, variables)
    except MondoError as e:
        handle_mondo_error_or_exit(e)
    opts.emit(data.get("change_simple_column_value") or {})


@app.command("duplicate", epilog=epilog_for("item duplicate"))
def duplicate_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Item ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--item", help="Item ID (flag form)."),
    board_id: int = typer.Option(..., "--board", help="Parent board ID."),
    with_updates: bool = typer.Option(
        False, "--with-updates", help="Also duplicate the item's updates (comments)."
    ),
) -> None:
    """Duplicate an item in place."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    item_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="item")
    data = execute(
        opts,
        ITEM_DUPLICATE,
        {"board": board_id, "id": item_id, "with_updates": with_updates},
    )
    opts.emit(data.get("duplicate_item") or {})


@app.command("archive", epilog=epilog_for("item archive"))
def archive_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Item ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--item", help="Item ID (flag form)."),
) -> None:
    """Archive an item (reversible via monday UI within 30 days)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    item_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="item")
    _confirm(opts, f"Archive item {item_id}?")
    data = execute(opts, ITEM_ARCHIVE, {"id": item_id})
    opts.emit(data.get("archive_item") or {})


@app.command("delete", epilog=epilog_for("item delete"))
def delete_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Item ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--item", help="Item ID (flag form)."),
    hard: bool = typer.Option(
        False, "--hard", help="Required for permanent deletion (paired with --yes)."
    ),
) -> None:
    """Delete an item (permanent — prefer `archive` unless --hard is passed)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    item_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="item")
    if not hard:
        typer.secho(
            "refusing to delete without --hard. Use `mondo item archive` for "
            "reversible removal, or pass --hard to confirm permanent deletion.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=2)
    _confirm(opts, f"PERMANENTLY delete item {item_id}?")
    data = execute(opts, ITEM_DELETE, {"id": item_id})
    opts.emit(data.get("delete_item") or {})


@app.command("move", epilog=epilog_for("item move"))
def move_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--id", "--item", help="Item ID to move."),
    group_id: str = typer.Option(..., "--group", help="Target group ID within the same board."),
) -> None:
    """Move an item to a different group within the same board."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    data = execute(opts, ITEM_MOVE_GROUP, {"id": item_id, "group": group_id})
    opts.emit(data.get("move_item_to_group") or {})


def _parse_column_mapping(tokens: list[str]) -> list[dict[str, Any]]:
    """Parse `source[=target]` tokens into ColumnMappingInput dicts.

    `src=dst` maps source column `src` to dest column `dst`.
    `src=` (empty target) or bare `src` drops the column on the destination
    (monday treats a null `target` as "don't carry this column over").
    """
    out: list[dict[str, Any]] = []
    for tok in tokens:
        raw = tok.strip()
        if not raw:
            continue
        if "=" in raw:
            src, _, tgt = raw.partition("=")
            src = src.strip()
            tgt = tgt.strip()
        else:
            src, tgt = raw, ""
        if not src:
            raise UsageError(
                f"--column-mapping {tok!r}: source column id is required "
                "(use 'src=dst' or 'src=' to drop)."
            )
        out.append({"source": src, "target": tgt or None})
    return out


@app.command("move-to-board", epilog=epilog_for("item move-to-board"))
def move_to_board_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--id", "--item", help="Item ID to move."),
    board_id: int = typer.Option(..., "--to-board", help="Destination board ID."),
    group_id: str = typer.Option(..., "--to-group", help="Destination group ID."),
    column_mapping: list[str] | None = typer.Option(
        None,
        "--column-mapping",
        metavar="SRC=DST",
        help=(
            "Map source column id → destination column id (repeatable). "
            "`SRC=` (empty) drops the source column on the destination. "
            "Required when source/dest schemas differ."
        ),
    ),
    subitem_column_mapping: list[str] | None = typer.Option(
        None,
        "--subitem-column-mapping",
        metavar="SRC=DST",
        help=(
            "Same as --column-mapping but for the subitems board "
            "(repeatable). Only needed if the item has subitems."
        ),
    ),
) -> None:
    """Move an item to a different board, optionally remapping columns.

    monday's `move_item_to_board` requires a destination group. If the
    source and target board schemas differ, pass `--column-mapping src=dst`
    (repeatable) so source columns land in the right destination columns;
    unmapped source columns are dropped.
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    try:
        columns = _parse_column_mapping(column_mapping or [])
        subitem_columns = _parse_column_mapping(subitem_column_mapping or [])
    except UsageError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from e
    variables: dict[str, Any] = {
        "id": item_id,
        "board": board_id,
        "group": group_id,
        "columns": columns or None,
        "subitemColumns": subitem_columns or None,
    }
    data = execute(opts, ITEM_MOVE_BOARD, variables)
    opts.emit(data.get("move_item_to_board") or {})
