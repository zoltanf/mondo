"""`mondo tag` — tags (Phase 3h).

Per monday-api.md §14:
- `tags(ids)` is account-level only (public tags).
- For private/shareable boards, tags live nested under the board
  (`boards { tags { id name color } }`) — use `mondo board get` to see them.
- `create_or_get_tag(tag_name, board_id)` is the only creation path; it
  returns an existing tag if one matches, otherwise creates a new one.
"""

from __future__ import annotations

from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError
from mondo.api.queries import CREATE_OR_GET_TAG, TAGS_LIST
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


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


@app.command("list")
def list_cmd(
    ctx: typer.Context,
    tag_id: list[int] | None = typer.Option(
        None, "--id", help="Filter to specific tag IDs (repeatable)."
    ),
) -> None:
    """List account-level tags (public). See `mondo board get` for board-level tags."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"ids": tag_id or None}
    if opts.dry_run:
        _dry_run(opts, TAGS_LIST, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, TAGS_LIST, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("tags") or [])


@app.command("get")
def get_cmd(
    ctx: typer.Context,
    tag_id: int = typer.Option(..., "--id", help="Tag ID."),
) -> None:
    """Fetch a single tag by ID."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"ids": [tag_id]}
    if opts.dry_run:
        _dry_run(opts, TAGS_LIST, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, TAGS_LIST, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    tags = data.get("tags") or []
    if not tags:
        typer.secho(f"tag {tag_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
    opts.emit(tags[0])


@app.command("create-or-get")
def create_or_get_cmd(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Tag name."),
    board_id: int = typer.Option(..., "--board", help="Board ID to scope the tag to."),
) -> None:
    """Create a tag (or return the existing one with the same name) on a board."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"name": name, "board": board_id}
    if opts.dry_run:
        _dry_run(opts, CREATE_OR_GET_TAG, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, CREATE_OR_GET_TAG, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("create_or_get_tag") or {})
