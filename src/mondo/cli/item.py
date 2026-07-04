"""`mondo item` command group: CRUD for monday items."""

from __future__ import annotations

from contextlib import nullcontext
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer

from mondo.api.errors import (
    ColumnValueError,
    MondoError,
    NotFoundError,
    UsageError,
    ValidationError,
)
from mondo.api.pagination import MAX_PAGE_SIZE, iter_items_page
from mondo.api.queries import (
    ITEM_ARCHIVE,
    ITEM_BOARD_LOOKUP,
    ITEM_CREATE,
    ITEM_DELETE,
    ITEM_DUPLICATE,
    ITEM_GET,
    ITEM_GET_WITH_COLUMNS,
    ITEM_GET_WITH_SUBITEMS,
    ITEM_GET_WITH_UPDATES,
    ITEM_MOVE_BOARD,
    ITEM_MOVE_GROUP,
    ITEM_RENAME,
    SUBITEMS_LIST,
    build_items_page_queries,
)
from mondo.cli._batch import build_aliased_mutation, chunk_inputs, parse_aliased_response
from mondo.cli._cache_invalidate import invalidate_board_items_cache, invalidate_entity
from mondo.cli._confirm import confirm_or_abort as _confirm
from mondo.cli._examples import epilog_for
from mondo.cli._exec import (
    PollIntervalOpt,
    PollTimeoutOpt,
    PollUntilOpt,
    client_or_exit,
    dry_run_and_exit,
    exec_or_exit,
    execute,
    handle_mondo_error_or_exit,
    poll_or_exit,
    usage_error_or_exit,
)
from mondo.cli._url import MondayIdParam
from mondo.cli.context import GlobalOpts
from mondo.domain.column_cache import invalidate_columns_cache
from mondo.domain.resolve import resolve_required_id
from mondo.services.items import (
    PositionRelative,
    build_create_variables_for_row,
    build_query_params,
    can_slim_column_values,
    fetch_column_defs,
    parse_column_mapping,
    parse_columns_csv,
    read_batch_input,
    resolve_item_target,
    split_filter_expr,
)
from mondo.util.kvparse import parse_column_kv

if TYPE_CHECKING:
    from mondo.api.client import MondayClient

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


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
    columns_sel: str | None = typer.Option(
        None,
        "--columns",
        metavar="COL1,COL2",
        help="Fetch only these column values, server-side (cheaper than the "
        "full column_values selection). Bypasses the per-item cache. "
        "Unknown/typo'd column ids are silently omitted by the API (no error).",
    ),
    with_url: bool = typer.Option(
        False,
        "--with-url",
        help="Include the item's canonical monday.com URL in the emitted payload.",
    ),
    poll_until: PollUntilOpt = None,
    poll_interval: PollIntervalOpt = "2s",
    poll_timeout: PollTimeoutOpt = "60s",
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Bypass the per-item cache; fetch live.",
        rich_help_panel="Cache",
    ),
    refresh_cache: bool = typer.Option(
        False,
        "--refresh-cache",
        help="Force-refresh the per-item cache before serving.",
        rich_help_panel="Cache",
    ),
    explain_cache: bool = typer.Option(
        False,
        "--explain-cache",
        help="Emit a verbose cache-hit line (path/ttl/fetched_at) on stderr.",
        rich_help_panel="Cache",
    ),
) -> None:
    """Fetch a single item by ID or pulses URL.

    Plain `item get` is served from a short-TTL per-item cache
    (`items/<item_id>.json`, default TTL 60s — set via
    `MONDO_CACHE_TTL_ITEMS`). `--include-updates`, `--include-subitems`,
    and `--poll-until` bypass the cache (different shape / live observation).
    """
    from mondo.cli._cache_flags import emit_cache_provenance, reject_mutually_exclusive

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    reject_mutually_exclusive(no_cache, refresh_cache)
    item_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="item")
    if include_updates and include_subitems:
        usage_error_or_exit(
            "--include-updates and --include-subitems are mutually exclusive for now."
        )
    if columns_sel is not None and (include_updates or include_subitems):
        usage_error_or_exit(
            "--columns cannot be combined with --include-updates / --include-subitems."
        )
    variables: dict[str, Any] = {"id": item_id}
    if columns_sel is not None:
        try:
            variables["cols"] = parse_columns_csv(columns_sel)
        except UsageError as e:
            usage_error_or_exit(str(e))
        query = ITEM_GET_WITH_COLUMNS
    elif include_updates:
        query = ITEM_GET_WITH_UPDATES
    elif include_subitems:
        query = ITEM_GET_WITH_SUBITEMS
    else:
        query = ITEM_GET

    cfg = opts.resolve_cache_config()
    bypass_cache = (
        not cfg.enabled
        or no_cache
        or include_updates
        or include_subitems
        or columns_sel is not None
        or poll_until is not None
    )

    def _fetch_once() -> dict[str, Any] | None:
        data = execute(opts, query, variables)
        items = data.get("items") or []
        return items[0] if items else None

    item: dict[str, Any] | None
    if bypass_cache:
        if poll_until is not None:
            item = poll_or_exit(
                _fetch_once,
                expression=poll_until,
                interval=poll_interval,
                timeout=poll_timeout,
            )
        else:
            item = _fetch_once()
    else:
        if opts.dry_run:
            opts.emit({"query": query, "variables": {"id": item_id}})
            raise typer.Exit(0)
        from mondo.cache.directory import get_item

        client = client_or_exit(opts)
        store = opts.build_cache_store("items", scope=str(item_id))
        try:
            with client:
                cached = get_item(client, store=store, item_id=item_id, refresh=refresh_cache)
                emit_cache_provenance(opts, cached, store=store, explain=explain_cache)
                item = cached.entries[0] if cached.entries else None
        except NotFoundError:
            item = None
        except MondoError as e:
            handle_mondo_error_or_exit(e)

    if item is None:
        handle_mondo_error_or_exit(NotFoundError(f"item {item_id} not found."))
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
    group_id: str | None = typer.Option(
        None,
        "--group",
        help="Filter to a single group (alias for --filter group=<id>).",
        rich_help_panel="Filters",
    ),
    parent_id: int | None = typer.Option(
        None,
        "--parent",
        help="List subitems of this parent item ID instead of board items. "
        "When set, --board is ignored.",
        rich_help_panel="Filters",
    ),
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
    columns_sel: str | None = typer.Option(
        None,
        "--columns",
        metavar="COL1,COL2",
        help="Fetch only these column values, server-side. The full "
        "column_values selection is ~3x the per-page cost on big boards. "
        "Unknown/typo'd column ids are silently omitted by the API (no error).",
        rich_help_panel="Filters",
    ),
    with_url: bool = typer.Option(
        False,
        "--with-url",
        help="Include a synthesized monday.com `url` on every emitted item "
        "(one extra account-slug query; not supported with --parent).",
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
    poll_until: PollUntilOpt = None,
    poll_interval: PollIntervalOpt = "2s",
    poll_timeout: PollTimeoutOpt = "60s",
    refresh_cache: bool = typer.Option(
        False,
        "--refresh-cache",
        help="Force-refresh the short-TTL board-items cache (and the cached "
        "column definitions used to resolve `--filter` labels).",
        rich_help_panel="Cache",
    ),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Bypass the short-TTL board-items cache and the cached column "
        "definitions; fetch live.",
        rich_help_panel="Cache",
    ),
) -> None:
    """List items on a board (cursor pagination).

    Use --filter 'col=val' (repeatable) to narrow results server-side, and
    --order-by col[,asc|desc] to sort.

    Bare `item list --board X` (and the `--group` variant) is served from a
    short-TTL per-board cache (`board_items/<board_id>.json`, default TTL
    60s — set via `MONDO_CACHE_TTL_BOARD_ITEMS`). Filtered / ordered /
    column-narrowed variants always fetch live.
    """
    from mondo.cli._cache_flags import reject_mutually_exclusive

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    reject_mutually_exclusive(no_cache, refresh_cache)
    _list_items_impl(
        opts,
        board_pos=board_pos,
        board_flag=board_flag,
        group_id=group_id,
        parent_id=parent_id,
        filter_expr=filter_expr,
        order_by=order_by,
        columns_sel=columns_sel,
        with_url=with_url,
        limit=limit,
        max_items=max_items,
        poll_until=poll_until,
        poll_interval=poll_interval,
        poll_timeout=poll_timeout,
        refresh_cache=refresh_cache,
        no_cache=no_cache,
    )


def _list_items_impl(
    opts: GlobalOpts,
    *,
    board_pos: int | None = None,
    board_flag: int | None = None,
    group_id: str | None = None,
    parent_id: int | None = None,
    filter_expr: list[str] | None = None,
    order_by: str | None = None,
    columns_sel: str | None = None,
    with_url: bool = False,
    limit: int = MAX_PAGE_SIZE,
    max_items: int | None = None,
    poll_until: str | None = None,
    poll_interval: str = "2s",
    poll_timeout: str = "60s",
    refresh_cache: bool = False,
    no_cache: bool = False,
) -> None:
    """Core body shared by `item list` and `item find`.

    Resolves the board id, fetches the items_page (or subitems on --parent),
    optionally polls, then emits. Keeping this off the Typer command callbacks
    means `item find` doesn't have to restate every `list` default.
    """
    # --parent <id> shortcircuits the items_page path: it delegates to the
    # same SUBITEMS_LIST query that `mondo subitem list --parent` uses, so
    # both commands return identical shapes.
    if parent_id is not None:
        if columns_sel is not None:
            usage_error_or_exit("--columns is not supported with --parent (subitem listing).")
        if with_url:
            usage_error_or_exit(
                "--with-url is not supported with --parent (subitems live on a separate board)."
            )
        data = execute(opts, SUBITEMS_LIST, {"parent": parent_id})
        items = data.get("items") or []
        if not items:
            handle_mondo_error_or_exit(NotFoundError(f"parent item {parent_id} not found."))
        opts.emit(items[0].get("subitems") or [])
        return

    board_id = resolve_required_id(board_pos, board_flag, flag_name="--board", resource="board")

    def _decorate_and_emit(items: list[dict[str, Any]]) -> None:
        """Shared emit tail for the cache-hit and live paths: optional
        --with-url decoration, then the field-selected emit."""
        if with_url:
            from mondo.cli._list_decorate import apply_item_urls

            apply_item_urls(items, opts, board_id=board_id)
        from mondo.cli._field_sets import item_list_fields

        opts.emit(items, selected_fields=item_list_fields())

    # Cache eligibility (#21) keys off the *user's* filters; the --group
    # sugar is served from the cached full-board list by filtering
    # client-side, so it must not count as a filter here.
    user_filters = bool(filter_expr)

    # --group <id> is sugar over --filter group=<id>; merge it in.
    if group_id is not None:
        filter_expr = [*(filter_expr or []), f"group={group_id}"]

    # Fail fast on malformed `--filter` syntax before opening the client or
    # fetching board metadata, so usage errors stay exit 2. Reuse the parsed
    # tuples below instead of re-splitting each expression in the rule builder.
    parsed_filters: list[tuple[str, str, str]] = []
    if filter_expr:
        try:
            parsed_filters = [split_filter_expr(f) for f in filter_expr]
        except UsageError as e:
            usage_error_or_exit(str(e))

    # Server-side column_values narrowing: an explicit `--columns` wins;
    # otherwise drop column_values entirely when `--fields` provably never
    # reads them (`--fields id,name` and friends). `--poll-until` evaluates
    # against the raw fetched rows, so its expression may read column_values
    # even when `--fields` doesn't — never slim while polling.
    extra_vars: dict[str, Any] | None = None
    slim = False
    if columns_sel is not None:
        try:
            extra_vars = {"cols": parse_columns_csv(columns_sel)}
        except UsageError as e:
            usage_error_or_exit(str(e))
        query_initial, query_next = build_items_page_queries(column_values="ids")
    else:
        slim = poll_until is None and can_slim_column_values(opts)
        query_initial, query_next = build_items_page_queries(
            column_values="none" if slim else "full"
        )

    # --- board_items cache (#21): short-TTL (60s) cache of the bare
    # full-board list. Only the bare `--board` (and `--board --group`,
    # filtered client-side off the same file) variants are served from it;
    # anything with filters / ordering / column narrowing stays live.
    # Same stale-data contract as the per-item caches — see docs/caching.md.
    from mondo.cli._cache_flags import resolve_cache_prefs

    prefs = resolve_cache_prefs(
        opts,
        no_cache=no_cache,
        fuzzy_threshold=None,
        extra_disable=(
            opts.dry_run
            or poll_until is not None
            or user_filters
            or order_by is not None
            or columns_sel is not None
            # A comma in --group means multiple ids on the live path (the
            # raw-filter fallback comma-splits); the cached path matches
            # the id exactly, so don't serve it from the cache.
            or (group_id is not None and "," in group_id)
        ),
    )
    store = opts.build_cache_store("board_items", scope=str(board_id)) if prefs.use_cache else None
    if store is not None and not refresh_cache:
        cached = store.read()
        if cached is not None:
            from mondo.cli._cache_flags import emit_cache_provenance

            emit_cache_provenance(opts, cached, store=store)
            items = cached.entries
            if group_id is not None:
                items = [it for it in items if (it.get("group") or {}).get("id") == group_id]
            if max_items is not None:
                items = items[:max_items]
            _decorate_and_emit(items)
            return
    # Only the full-board, full-shape result may be written back — a group
    # slice, a max-items prefix, or a slimmed selection would poison the
    # cache for the next full reader.
    cache_writable = store is not None and group_id is None and max_items is None and not slim

    try:
        client = opts.build_client()
        with client:
            # Codec dispatch needs the board's column types/settings — fetch
            # them whenever a `--filter` is in play. Cheap on cache hit;
            # required for status/dropdown to translate labels → integer
            # indices/ids.
            column_defs: dict[str, dict[str, Any]] = {}
            if parsed_filters:
                column_defs = fetch_column_defs(
                    opts,
                    client,
                    board_id,
                    no_cache=no_cache,
                    refresh=refresh_cache,
                )
            qp = build_query_params(parsed_filters, order_by, column_defs, board_id=board_id)

            if opts.dry_run:
                opts.emit(
                    {
                        "query": query_initial,
                        "variables": {
                            "boards": [board_id],
                            "limit": limit,
                            "qp": qp,
                            "max_items": max_items,
                            **(extra_vars or {}),
                        },
                    }
                )
                raise typer.Exit(0)

            def _fetch_items_once() -> list[dict[str, Any]]:
                return list(
                    iter_items_page(
                        client,
                        board_id=board_id,
                        limit=limit,
                        query_params=qp,
                        max_items=max_items,
                        query_initial=query_initial,
                        query_next=query_next,
                        extra_vars=extra_vars,
                    )
                )

            if poll_until is not None:
                items = poll_or_exit(
                    _fetch_items_once,
                    expression=poll_until,
                    interval=poll_interval,
                    timeout=poll_timeout,
                )
            else:
                items = _fetch_items_once()
                if cache_writable and store is not None:
                    store.write(items)
    except MondoError as e:
        handle_mondo_error_or_exit(e)
    except UsageError as e:
        usage_error_or_exit(str(e))

    # Decorate after the cache write above so the synthesized `url` never
    # poisons the cached full-board list.
    _decorate_and_emit(items)


@app.command("find", epilog=epilog_for("item find"))
def find_cmd(
    ctx: typer.Context,
    board_pos: int | None = typer.Argument(
        None, metavar="[BOARD_ID]", help="Board ID (positional)."
    ),
    board_flag: int | None = typer.Option(None, "--board", help="Board ID (flag form)."),
    column_id: str = typer.Option(..., "--column", help="Column ID to match on (e.g. 'status')."),
    value: str = typer.Option(
        ..., "--value", help="Column value to match (label, index #N, or CSV)."
    ),
    with_url: bool = typer.Option(
        False,
        "--with-url",
        help="Include a synthesized monday.com `url` on every emitted item "
        "(one extra account-slug query).",
    ),
) -> None:
    """Find items by column value.

    Sugar over `mondo item list --filter COL=VAL`. Returns the same shape as
    `item list` so projection with `--fields` / `-q '<jmespath>'` works the
    same way. Codec dispatch (status indices, dropdown ids) and the
    `mondo column labels` pointer on unknown labels are inherited.
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    _list_items_impl(
        opts,
        board_pos=board_pos,
        board_flag=board_flag,
        filter_expr=[f"{column_id}={value}"],
        with_url=with_url,
    )


# ----- write commands -----


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
    with_url: bool = typer.Option(
        False,
        "--with-url",
        help="Include the new item's canonical monday.com URL in the emitted payload.",
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
            name is not None
            or group_id is not None
            or columns
            or position_relative_method is not None
            or relative_to is not None
        )
        if single_item_flags:
            usage_error_or_exit(
                "--batch is mutually exclusive with --name / --group / "
                "--column / --position-* / --relative-to. Move per-row "
                "settings into the JSON array."
            )
        try:
            rows = read_batch_input(batch)
        except UsageError as e:
            usage_error_or_exit(str(e))
        if chunk_size < 1:
            usage_error_or_exit("--chunk-size must be >= 1.")
        _run_batch(
            opts,
            board_id,
            rows,
            raw_columns=raw_columns,
            create_labels_default=create_labels_if_missing,
            chunk_size=chunk_size,
            with_url=with_url,
        )
        return

    if not name:
        usage_error_or_exit("--name is required (or pass --batch <path|-> for bulk).")

    # Build the ITEM_CREATE variables via the same helper that the batch path
    # uses, so any future addition to the create shape lands in one place.
    # `--raw-columns` skips the preflight, so `--dry-run --raw-columns` is fully offline.
    row: dict[str, Any] = {
        "name": name,
        "group_id": group_id,
        "columns": list(columns) if columns else [],
        "create_labels": create_labels_if_missing,
        "position_relative_method": (
            position_relative_method.value if position_relative_method else None
        ),
        "relative_to": relative_to,
    }
    needs_preflight = not raw_columns and bool(columns)
    client_for_preflight: MondayClient | None = None
    if needs_preflight:
        try:
            client_for_preflight = opts.build_client()
        except MondoError as e:
            handle_mondo_error_or_exit(e)

    ctx_mgr: Any = client_for_preflight if client_for_preflight is not None else nullcontext()
    try:
        with ctx_mgr:
            variables = build_create_variables_for_row(
                opts,
                client_for_preflight,
                board_id,
                row,
                raw_columns=raw_columns,
                create_labels_default=create_labels_if_missing,
            )
    except ValueError as e:
        handle_mondo_error_or_exit(ValidationError(str(e)))
    except MondoError as e:
        handle_mondo_error_or_exit(e)

    col_ids = ", ".join(parse_column_kv(p)[0] for p in columns) if columns else ""
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
        invalidate_columns_cache(opts.columns_cache_store_for_invalidation(board_id))
    invalidate_board_items_cache(opts, board_id)
    payload = data.get("create_item") or {}
    if not with_url:
        payload.pop("url", None)
    opts.emit(payload)


def _run_batch(
    opts: GlobalOpts,
    board_id: int,
    rows: list[dict[str, Any]],
    *,
    raw_columns: bool,
    create_labels_default: bool,
    chunk_size: int,
    with_url: bool = False,
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
            column_defs = fetch_column_defs(opts, client, board_id)

        ctx_mgr: Any = client if client is not None else nullcontext()
        per_row_vars: list[dict[str, Any]] = []
        try:
            with ctx_mgr:
                for row in rows:
                    per_row_vars.append(
                        build_create_variables_for_row(
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
                    response = client.execute(query, variables=flat, surface_partial_errors=True)
                    base = chunk_idx * chunk_size
                    results.extend(parse_aliased_response(response, row_chunk, base_index=base))
        except ValueError as e:
            handle_mondo_error_or_exit(ValidationError(str(e)))
    except MondoError as e:
        handle_mondo_error_or_exit(e)

    if create_labels_default or any(row.get("create_labels") for row in rows):
        invalidate_columns_cache(opts.columns_cache_store_for_invalidation(board_id))
    invalidate_board_items_cache(opts, board_id)

    if not with_url:
        for row in results:
            row_data = row.get("data")
            if isinstance(row_data, dict):
                row_data.pop("url", None)

    failed = sum(1 for r in results if not r["ok"])
    summary = {
        "requested": len(rows),
        "created": len(results) - failed,
        "failed": failed,
    }
    opts.emit({"summary": summary, "results": results})
    if failed:
        raise typer.Exit(code=1)


@app.command("rename", epilog=epilog_for("item rename"))
def rename_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Item ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--item", help="Item ID (flag form)."),
    board_id: int | None = typer.Option(
        None,
        "--board",
        help="Parent board ID (auto-resolved from the item id when omitted; "
        "required for name-based selection).",
    ),
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

    With an explicit id, `--board` may be omitted: it is auto-resolved from
    the item with one cheap lookup query. Name-based selection still needs
    `--board` to scope the search.
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    explicit_id: int | None
    if id_pos is not None and id_flag is not None and id_pos != id_flag:
        raise typer.BadParameter("pass the item ID as a positional argument or via --id, not both.")
    explicit_id = id_pos if id_pos is not None else id_flag
    # All local selector validation runs before any network call, so usage
    # conflicts surface as exit 2 rather than a lookup/auth failure. Same
    # id-vs-filter mutex (and message) that resolve_by_filters enforces.
    if explicit_id is not None and (name_contains or name_matches_re or name_fuzzy):
        raise typer.BadParameter(
            "pass either an item id or one of "
            "--name-contains / --name-matches / --name-fuzzy, not both."
        )
    if board_id is None and explicit_id is None:
        usage_error_or_exit(
            "--board is required for name-based selection "
            "(--name-contains / --name-matches / --name-fuzzy). "
            "Pass an item id to have the board auto-resolved."
        )
    client = client_or_exit(opts)
    try:
        with client:
            if board_id is None:
                lookup = exec_or_exit(client, ITEM_BOARD_LOOKUP, {"id": explicit_id})
                found = lookup.get("items") or []
                if not found or not (found[0].get("board") or {}).get("id"):
                    raise NotFoundError(f"item {explicit_id} not found.")
                board_id = int(found[0]["board"]["id"])
            resolved_item = resolve_item_target(
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
    invalidate_entity(opts, "items", scope=str(resolved_item))
    invalidate_board_items_cache(opts, board_id)
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
    invalidate_board_items_cache(opts, board_id)
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
    invalidate_entity(opts, "items", scope=str(item_id))
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
    invalidate_entity(opts, "items", scope=str(item_id))
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
    invalidate_entity(opts, "items", scope=str(item_id))
    opts.emit(data.get("move_item_to_group") or {})


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
        columns = parse_column_mapping(column_mapping or [])
        subitem_columns = parse_column_mapping(subitem_column_mapping or [])
    except UsageError as e:
        usage_error_or_exit(str(e))
    variables: dict[str, Any] = {
        "id": item_id,
        "board": board_id,
        "group": group_id,
        "columns": columns or None,
        "subitemColumns": subitem_columns or None,
    }
    data = execute(opts, ITEM_MOVE_BOARD, variables)
    # The source board isn't known in-process — its 60s TTL covers it.
    invalidate_board_items_cache(opts, board_id)
    opts.emit(data.get("move_item_to_board") or {})
