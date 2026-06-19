"""`mondo tag` — tags (Phase 3h).

Per monday-api.md §14:
- `tags(ids)` is account-level only (public tags).
- For private/shareable boards, tags live nested under the board
  (`boards { tags { id name color } }`) — use `mondo board get` to see them.
- `create_or_get_tag(tag_name, board_id)` is the only creation path; it
  returns an existing tag if one matches, otherwise creates a new one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import typer

from mondo.api.errors import MondoError, NotFoundError
from mondo.api.queries import CREATE_OR_GET_TAG, TAG_BY_BOARD, TAGS_LIST
from mondo.cli._cache_flags import emit_cache_provenance, reject_mutually_exclusive
from mondo.cli._cache_invalidate import invalidate_entity
from mondo.cli._examples import epilog_for
from mondo.cli._exec import client_or_exit, exec_or_exit, execute, handle_mondo_error_or_exit
from mondo.cli._resolve import resolve_required_id
from mondo.cli.context import GlobalOpts

if TYPE_CHECKING:
    from mondo.api.client import MondayClient

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.command("list", epilog=epilog_for("tag list"))
def list_cmd(
    ctx: typer.Context,
    tag_id: list[int] | None = typer.Option(
        None, "--id", help="Filter to specific tag IDs (repeatable)."
    ),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Bypass the local tags cache; fetch live.",
        rich_help_panel="Cache",
    ),
    refresh_cache: bool = typer.Option(
        False,
        "--refresh-cache",
        help="Force-refresh the local tags cache before serving.",
        rich_help_panel="Cache",
    ),
    explain_cache: bool = typer.Option(
        False,
        "--explain-cache",
        help="Emit a verbose cache-hit line (path/ttl/fetched_at) on stderr.",
        rich_help_panel="Cache",
    ),
) -> None:
    """List account-level tags (public). See `mondo board get` for board-level tags."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    reject_mutually_exclusive(no_cache, refresh_cache)
    cfg = opts.resolve_cache_config()
    use_cache = cfg.enabled and not no_cache

    if opts.dry_run:
        opts.emit({"query": TAGS_LIST, "variables": {"ids": tag_id or None}})
        raise typer.Exit(0)

    wanted = {str(t) for t in tag_id} if tag_id else None

    if use_cache:
        from mondo.cache.directory import get_tags as cache_get_tags

        store = opts.build_cache_store("tags")
        client = client_or_exit(opts)
        try:
            with client:
                cached = cache_get_tags(client, store=store, refresh=refresh_cache)
        except MondoError as e:
            handle_mondo_error_or_exit(e)
        emit_cache_provenance(opts, cached, store=store, explain=explain_cache)
        tags = cached.entries
        if wanted is not None:
            tags = [t for t in tags if str(t.get("id")) in wanted]
        opts.emit(tags)
        return

    data = execute(opts, TAGS_LIST, {"ids": tag_id or None})
    opts.emit(data.get("tags") or [])


@app.command("get", epilog=epilog_for("tag get"))
def get_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Tag ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--tag", help="Tag ID (flag form)."),
    board_id: int | None = typer.Option(
        None,
        "--board",
        help="Board ID to scope the lookup to (required for board-private tags "
        "— `create_or_get_tag` returns IDs that are NOT in the account-level "
        "`tags()` collection).",
    ),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Bypass the local tags cache; fetch live.",
        rich_help_panel="Cache",
    ),
    refresh_cache: bool = typer.Option(
        False,
        "--refresh-cache",
        help="Force-refresh the local tags cache before serving.",
        rich_help_panel="Cache",
    ),
    explain_cache: bool = typer.Option(
        False,
        "--explain-cache",
        help="Emit a verbose cache-hit line (path/ttl/fetched_at) on stderr.",
        rich_help_panel="Cache",
    ),
) -> None:
    """Fetch a single tag by ID.

    Monday's `tags(ids:)` only exposes account-level public tags. Tags created
    via `create_or_get_tag` on a shareable/private board (or, empirically, any
    board) are not visible there — pass `--board <id>` to look under
    `board.tags` as a fallback. `--board` paths always bypass the cache.
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    reject_mutually_exclusive(no_cache, refresh_cache)
    tag_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="tag")
    cfg = opts.resolve_cache_config()
    use_cache = cfg.enabled and not no_cache and board_id is None
    variables = {"ids": [tag_id]}

    if opts.dry_run:
        opts.emit({"query": TAGS_LIST, "variables": variables})
        raise typer.Exit(0)

    if use_cache:
        from mondo.cache.directory import get_tags as cache_get_tags
        from mondo.cli._dir_lookup import lookup_entity_in_directory

        def _fetch_live_account(client: MondayClient) -> dict[str, Any] | None:
            data = exec_or_exit(client, TAGS_LIST, variables)
            tags = data.get("tags") or []
            return tags[0] if tags else None

        entry = lookup_entity_in_directory(
            opts,
            entity_type="tags",
            target_id=tag_id,
            no_cache=no_cache,
            refresh=refresh_cache,
            fetcher=cache_get_tags,
            fetch_live=_fetch_live_account,
            explain_cache=explain_cache,
        )
        if entry is None:
            handle_mondo_error_or_exit(
                NotFoundError(f"tag {tag_id} not found in account.")
            )
        opts.emit(entry)
        return

    client = client_or_exit(opts)
    try:
        with client:
            data = exec_or_exit(client, TAGS_LIST, variables)
            tags = data.get("tags") or []
            if not tags and board_id is not None:
                board_data = exec_or_exit(client, TAG_BY_BOARD, {"board": board_id})
                boards = board_data.get("boards") or []
                board_tags = (boards[0].get("tags") or []) if boards else []
                tags = [t for t in board_tags if str(t.get("id")) == str(tag_id)]
    except MondoError as e:
        handle_mondo_error_or_exit(e)
    if not tags:
        scope = "account" if board_id is None else f"account + board {board_id}"
        handle_mondo_error_or_exit(NotFoundError(f"tag {tag_id} not found in {scope}."))
    opts.emit(tags[0])


@app.command("create-or-get", epilog=epilog_for("tag create-or-get"))
def create_or_get_cmd(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Tag name."),
    board_id: int = typer.Option(..., "--board", help="Board ID to scope the tag to."),
) -> None:
    """Create a tag (or return the existing one with the same name) on a board."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"name": name, "board": board_id}
    data = execute(opts, CREATE_OR_GET_TAG, variables)
    # Best-effort: drop the account-level tags cache (a new public tag may
    # have been minted) and the per-board details cache (BOARD_GET projects
    # nested `tags { id name color }` on the board record).
    invalidate_entity(opts, "tags")
    invalidate_entity(opts, "board_details", scope=str(board_id))
    opts.emit(data.get("create_or_get_tag") or {})
