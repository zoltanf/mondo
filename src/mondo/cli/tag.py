"""`mondo tag` — tags (Phase 3h).

Per monday-api.md §14:
- `tags(ids)` is account-level only (public tags).
- For private/shareable boards, tags live nested under the board
  (`boards { tags { id name color } }`) — use `mondo board get` to see them.
- `create_or_get_tag(tag_name, board_id)` is the only creation path; it
  returns an existing tag if one matches, otherwise creates a new one.
"""

from __future__ import annotations

import typer

from mondo.api.errors import MondoError
from mondo.api.queries import CREATE_OR_GET_TAG, TAG_BY_BOARD, TAGS_LIST
from mondo.cli._examples import epilog_for
from mondo.cli._exec import client_or_exit, exec_or_exit, execute
from mondo.cli._resolve import resolve_required_id
from mondo.cli.context import GlobalOpts

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
) -> None:
    """List account-level tags (public). See `mondo board get` for board-level tags."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"ids": tag_id or None}
    data = execute(opts, TAGS_LIST, variables)
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
) -> None:
    """Fetch a single tag by ID.

    Monday's `tags(ids:)` only exposes account-level public tags. Tags created
    via `create_or_get_tag` on a shareable/private board (or, empirically, any
    board) are not visible there — pass `--board <id>` to look under
    `board.tags` as a fallback.
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    tag_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="tag")
    variables = {"ids": [tag_id]}
    if opts.dry_run:
        opts.emit({"query": TAGS_LIST, "variables": variables})
        raise typer.Exit(0)
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
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    if not tags:
        scope = "account" if board_id is None else f"account + board {board_id}"
        typer.secho(f"tag {tag_id} not found in {scope}.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
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
    opts.emit(data.get("create_or_get_tag") or {})
