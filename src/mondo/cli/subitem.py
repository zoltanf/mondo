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

from mondo.api.errors import MondoError, NotFoundError, ValidationError
from mondo.api.queries import (
    ITEM_ARCHIVE,
    ITEM_DELETE,
    ITEM_GET,
    ITEM_MOVE_GROUP,
    ITEM_RENAME,
    SUBITEM_CREATE,
    SUBITEMS_LIST,
)
from mondo.cli._confirm import confirm_or_abort as _confirm
from mondo.cli._examples import epilog_for
from mondo.cli._exec import (
    client_or_exit,
    execute,
    handle_mondo_error_or_exit,
)
from mondo.cli._url import MondayIdParam
from mondo.cli.context import GlobalOpts
from mondo.domain.column_cache import invalidate_columns_cache
from mondo.domain.resolve import resolve_required_id
from mondo.services.items import build_column_values
from mondo.util.kvparse import parse_column_kv

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


# ----- read commands -----


@app.command("list", epilog=epilog_for("subitem list"))
def list_cmd(
    ctx: typer.Context,
    parent_id: int = typer.Option(..., "--parent", help="Parent item ID."),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Bypass the per-parent subitems cache; fetch live.",
        rich_help_panel="Cache",
    ),
    refresh_cache: bool = typer.Option(
        False,
        "--refresh-cache",
        help="Force-refresh the per-parent subitems cache before serving.",
        rich_help_panel="Cache",
    ),
    explain_cache: bool = typer.Option(
        False,
        "--explain-cache",
        help="Emit a verbose cache-hit line (path/ttl/fetched_at) on stderr.",
        rich_help_panel="Cache",
    ),
) -> None:
    """List all subitems of a parent item.

    Served from `subitems/<parent_id>.json` (default TTL 60s — set via
    `MONDO_CACHE_TTL_SUBITEMS`).
    """
    from mondo.api.errors import NotFoundError as _NotFoundError
    from mondo.cli._cache_flags import emit_cache_provenance, reject_mutually_exclusive

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    reject_mutually_exclusive(no_cache, refresh_cache)
    cfg = opts.resolve_cache_config()
    use_cache = cfg.enabled and not no_cache

    if opts.dry_run:
        opts.emit({"query": SUBITEMS_LIST, "variables": {"parent": parent_id}})
        raise typer.Exit(0)

    if use_cache:
        from mondo.cache.directory import get_subitems

        client = client_or_exit(opts)
        store = opts.build_cache_store("subitems", scope=str(parent_id))
        try:
            with client:
                cached = get_subitems(
                    client,
                    store=store,
                    parent_item_id=parent_id,
                    refresh=refresh_cache,
                )
        except _NotFoundError:
            handle_mondo_error_or_exit(NotFoundError(f"parent item {parent_id} not found."))
        except MondoError as e:
            handle_mondo_error_or_exit(e)
        emit_cache_provenance(opts, cached, store=store, explain=explain_cache)
        opts.emit(list(cached.entries))
        return

    variables = {"parent": parent_id}
    data = execute(opts, SUBITEMS_LIST, variables)
    items = data.get("items") or []
    if not items:
        handle_mondo_error_or_exit(NotFoundError(f"parent item {parent_id} not found."))
    opts.emit(items[0].get("subitems") or [])


@app.command("get", epilog=epilog_for("subitem get"))
def get_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(
        None,
        metavar="[ID|URL]",
        help="Subitem ID or monday.com /pulses/<id> URL (positional).",
        click_type=MondayIdParam(kind="item"),
    ),
    id_flag: int | None = typer.Option(
        None,
        "--id",
        "--subitem",
        help="Subitem ID or monday.com /pulses/<id> URL.",
        click_type=MondayIdParam(kind="item"),
    ),
    with_url: bool = typer.Option(
        False,
        "--with-url",
        help="Include the subitem's canonical monday.com URL in the emitted payload.",
    ),
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
    """Fetch a single subitem by ID (same shape as `item get`).

    Reuses the `items/<id>.json` cache because monday's `ITEM_GET` returns
    the same shape for items and subitems.
    """
    from mondo.api.errors import NotFoundError as _NotFoundError
    from mondo.cli._cache_flags import emit_cache_provenance, reject_mutually_exclusive

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    reject_mutually_exclusive(no_cache, refresh_cache)
    subitem_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="subitem")
    variables = {"id": subitem_id}

    if opts.dry_run:
        opts.emit({"query": ITEM_GET, "variables": variables})
        raise typer.Exit(0)

    cfg = opts.resolve_cache_config()
    use_cache = cfg.enabled and not no_cache

    item: dict[str, Any] | None
    if use_cache:
        from mondo.cache.directory import get_item

        client = client_or_exit(opts)
        store = opts.build_cache_store("items", scope=str(subitem_id))
        try:
            with client:
                cached = get_item(client, store=store, item_id=subitem_id, refresh=refresh_cache)
                emit_cache_provenance(opts, cached, store=store, explain=explain_cache)
                item = cached.entries[0] if cached.entries else None
        except _NotFoundError:
            item = None
        except MondoError as e:
            handle_mondo_error_or_exit(e)
    else:
        data = execute(opts, ITEM_GET, variables)
        items = data.get("items") or []
        item = items[0] if items else None

    if item is None:
        handle_mondo_error_or_exit(NotFoundError(f"subitem {subitem_id} not found."))
    if not with_url:
        item.pop("url", None)
    opts.emit(item)


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
            client = client_or_exit(opts)
            try:
                with client:
                    col_values = build_column_values(
                        opts,
                        client,
                        subitems_board,
                        columns,
                        raw_mode=False,
                        create_labels=create_labels_if_missing,
                    )
            except MondoError as e:
                handle_mondo_error_or_exit(e)
            except ValueError as e:
                # Codec validation (e.g. unknown status label) — surface as a
                # clean CLI error rather than a Python traceback.
                handle_mondo_error_or_exit(ValidationError(str(e)))

    variables = {
        "parent": parent_id,
        "name": name,
        "values": json.dumps(col_values) if col_values else None,
        "create_labels": create_labels_if_missing if create_labels_if_missing else None,
    }
    data = execute(opts, SUBITEM_CREATE, variables)
    if create_labels_if_missing and subitems_board is not None:
        # May have minted a status/dropdown label on the subitems board.
        invalidate_columns_cache(opts.columns_cache_store_for_invalidation(subitems_board))
    from mondo.cli._cache_invalidate import invalidate_entity

    invalidate_entity(opts, "subitems", scope=str(parent_id))
    opts.emit(data.get("create_subitem") or {})


@app.command("rename", epilog=epilog_for("subitem rename"))
def rename_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Subitem ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--subitem", help="Subitem ID (flag form)."),
    board_id: int = typer.Option(..., "--board", help="Parent subitems board ID."),
    name: str = typer.Option(..., "--name", help="New title."),
) -> None:
    """Rename a subitem (writes the `name` column via change_simple_column_value)."""
    from mondo.cli._cache_invalidate import invalidate_entity

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    subitem_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="subitem")
    variables = {"board": board_id, "id": subitem_id, "name": name}
    data = execute(opts, ITEM_RENAME, variables)
    invalidate_entity(opts, "items", scope=str(subitem_id))
    opts.emit(data.get("change_simple_column_value") or {})


@app.command("move", epilog=epilog_for("subitem move"))
def move_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Subitem ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--subitem", help="Subitem ID (flag form)."),
    group_id: str = typer.Option(
        ...,
        "--group",
        help=(
            "Target subitems-board group ID (must already exist). monday "
            "rejects creating new groups on a subitems board "
            "(GroupActionOnSubitemBoardException), and subitems often share "
            "one default group, so a distinct target may not be available."
        ),
    ),
) -> None:
    """Move a subitem to a different subitems group."""
    from mondo.cli._cache_invalidate import invalidate_entity

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    subitem_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="subitem")
    variables = {"id": subitem_id, "group": group_id}
    data = execute(opts, ITEM_MOVE_GROUP, variables)
    invalidate_entity(opts, "items", scope=str(subitem_id))
    opts.emit(data.get("move_item_to_group") or {})


@app.command("archive", epilog=epilog_for("subitem archive"))
def archive_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Subitem ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--subitem", help="Subitem ID (flag form)."),
) -> None:
    """Archive a subitem (reversible)."""
    from mondo.cli._cache_invalidate import invalidate_entity

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    subitem_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="subitem")
    _confirm(opts, f"Archive subitem {subitem_id}?")
    variables = {"id": subitem_id}
    data = execute(opts, ITEM_ARCHIVE, variables)
    invalidate_entity(opts, "items", scope=str(subitem_id))
    opts.emit(data.get("archive_item") or {})


@app.command("delete", epilog=epilog_for("subitem delete"))
def delete_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Subitem ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--subitem", help="Subitem ID (flag form)."),
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
    data = execute(opts, ITEM_DELETE, variables)
    from mondo.cli._cache_invalidate import invalidate_entity

    invalidate_entity(opts, "items", scope=str(subitem_id))
    opts.emit(data.get("delete_item") or {})
