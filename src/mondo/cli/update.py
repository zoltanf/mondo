"""`mondo update` command group — item comments (Phase 3d).

Per monday-api.md §13:
- `body` accepts **HTML**, not markdown. Mentions use `<mention>…</mention>`.
- Page size max is 100 (since 2025-04). We paginate via `iter_boards_page`.
- `create_update(parent_id:)` creates a **reply** instead of a top-level
  update; `mondo update reply` is a thin wrapper around the same mutation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError
from mondo.api.pagination import iter_boards_page
from mondo.api.queries import (
    UPDATE_CLEAR_ITEM,
    UPDATE_CREATE,
    UPDATE_DELETE,
    UPDATE_EDIT,
    UPDATE_GET,
    UPDATE_LIKE,
    UPDATE_PIN,
    UPDATE_UNLIKE,
    UPDATE_UNPIN,
    UPDATES_FOR_ITEM,
    UPDATES_LIST_PAGE,
)
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


MAX_UPDATES_PAGE_SIZE = 100


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


def _confirm(opts: GlobalOpts, prompt: str) -> None:
    if opts.yes:
        return
    if not typer.confirm(prompt, default=False):
        typer.echo("aborted.")
        raise typer.Exit(1)


def _load_body(body: str | None, from_file: Path | None, from_stdin: bool) -> str:
    sources = sum(x is not None and x is not False for x in (body, from_file, from_stdin))
    if sources == 0:
        typer.secho(
            "error: provide --body, --from-file @path, or --from-stdin",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    if sources > 1:
        typer.secho(
            "error: --body, --from-file, and --from-stdin are mutually exclusive",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    if from_file is not None:
        return from_file.read_text()
    if from_stdin:
        return sys.stdin.read()
    assert body is not None
    return body


# ----- read commands -----


@app.command("list")
def list_cmd(
    ctx: typer.Context,
    item_id: int | None = typer.Option(
        None,
        "--item",
        help="Restrict to a single item (uses the nested query; returns "
        "replies/likes/pinning info too).",
    ),
    limit: int = typer.Option(
        MAX_UPDATES_PAGE_SIZE, "--limit", help=f"Page size (max {MAX_UPDATES_PAGE_SIZE})."
    ),
    max_items: int | None = typer.Option(
        None, "--max-items", help="Stop after this many updates total."
    ),
) -> None:
    """List updates — account-wide or scoped to a single item."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)

    if item_id is not None:
        # Single-item path — nested query, single request per page.
        page = 1
        collected: list[dict[str, Any]] = []
        client = _client_or_exit(opts)
        if opts.dry_run:
            _dry_run(
                opts,
                UPDATES_FOR_ITEM,
                {"id": item_id, "limit": limit, "page": page},
            )
        try:
            with client:
                while True:
                    data = _exec_or_exit(
                        client,
                        UPDATES_FOR_ITEM,
                        {"id": item_id, "limit": limit, "page": page},
                    )
                    items = data.get("items") or []
                    if not items:
                        if page == 1:
                            typer.secho(
                                f"item {item_id} not found.",
                                fg=typer.colors.RED,
                                err=True,
                            )
                            raise typer.Exit(code=6)
                        break
                    updates = items[0].get("updates") or []
                    if not updates:
                        break
                    for u in updates:
                        if max_items is not None and len(collected) >= max_items:
                            break
                        collected.append(u)
                    if max_items is not None and len(collected) >= max_items:
                        break
                    if len(updates) < limit:
                        break
                    page += 1
        except MondoError as e:
            typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=int(e.exit_code)) from e
        opts.emit(collected)
        return

    # Account-wide path — root updates query with page-based pagination.
    if opts.dry_run:
        opts.emit(
            {
                "query": "<updates page iterator>",
                "variables": {"limit": limit, "max_items": max_items},
            }
        )
        raise typer.Exit(0)
    client = _client_or_exit(opts)
    try:
        with client:
            items = list(
                iter_boards_page(
                    client,
                    query=UPDATES_LIST_PAGE,
                    variables={"ids": None},
                    collection_key="updates",
                    limit=limit,
                    max_items=max_items,
                )
            )
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(items)


@app.command("get")
def get_cmd(
    ctx: typer.Context,
    update_id: int = typer.Option(..., "--id", help="Update ID."),
) -> None:
    """Fetch a single update by ID with replies, likes, and pinning info."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"id": update_id}
    if opts.dry_run:
        _dry_run(opts, UPDATE_GET, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, UPDATE_GET, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    updates = data.get("updates") or []
    if not updates:
        typer.secho(f"update {update_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
    opts.emit(updates[0])


# ----- write commands -----


@app.command("create")
def create_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--item", help="Item to post the update on."),
    body: str | None = typer.Option(
        None, "--body", help="Update body (HTML — monday does not accept markdown)."
    ),
    from_file: Path | None = typer.Option(None, "--from-file", help="Load the body from a file."),
    from_stdin: bool = typer.Option(False, "--from-stdin", help="Load the body from stdin."),
) -> None:
    """Post a new update (comment) on an item."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    payload = _load_body(body, from_file, from_stdin)
    variables = {"item": item_id, "parent": None, "body": payload}
    if opts.dry_run:
        _dry_run(opts, UPDATE_CREATE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, UPDATE_CREATE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("create_update") or {})


@app.command("reply")
def reply_cmd(
    ctx: typer.Context,
    parent_id: int = typer.Option(
        ..., "--parent", help="Parent update ID (the reply attaches to it)."
    ),
    body: str | None = typer.Option(
        None, "--body", help="Reply body (HTML — monday does not accept markdown)."
    ),
    from_file: Path | None = typer.Option(None, "--from-file", help="Load the body from a file."),
    from_stdin: bool = typer.Option(False, "--from-stdin", help="Load the body from stdin."),
) -> None:
    """Post a reply to an existing update."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    payload = _load_body(body, from_file, from_stdin)
    variables = {"item": None, "parent": parent_id, "body": payload}
    if opts.dry_run:
        _dry_run(opts, UPDATE_CREATE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, UPDATE_CREATE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("create_update") or {})


@app.command("edit")
def edit_cmd(
    ctx: typer.Context,
    update_id: int = typer.Option(..., "--id", help="Update ID."),
    body: str | None = typer.Option(None, "--body", help="New body (HTML)."),
    from_file: Path | None = typer.Option(
        None, "--from-file", help="Load the new body from a file."
    ),
    from_stdin: bool = typer.Option(False, "--from-stdin", help="Load the new body from stdin."),
) -> None:
    """Edit an existing update."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    payload = _load_body(body, from_file, from_stdin)
    variables = {"id": update_id, "body": payload}
    if opts.dry_run:
        _dry_run(opts, UPDATE_EDIT, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, UPDATE_EDIT, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("edit_update") or {})


@app.command("delete")
def delete_cmd(
    ctx: typer.Context,
    update_id: int = typer.Option(..., "--id", help="Update ID to delete."),
) -> None:
    """Delete an update (permanent)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    _confirm(opts, f"Delete update {update_id}?")
    variables = {"id": update_id}
    if opts.dry_run:
        _dry_run(opts, UPDATE_DELETE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, UPDATE_DELETE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("delete_update") or {})


@app.command("like")
def like_cmd(
    ctx: typer.Context,
    update_id: int = typer.Option(..., "--id", help="Update ID to like."),
) -> None:
    """Like an update."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"id": update_id}
    if opts.dry_run:
        _dry_run(opts, UPDATE_LIKE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, UPDATE_LIKE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("like_update") or {})


@app.command("unlike")
def unlike_cmd(
    ctx: typer.Context,
    update_id: int = typer.Option(..., "--id", help="Update ID to unlike."),
) -> None:
    """Remove a like from an update."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"id": update_id}
    if opts.dry_run:
        _dry_run(opts, UPDATE_UNLIKE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, UPDATE_UNLIKE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("unlike_update") or {})


@app.command("clear")
def clear_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--item", help="Item whose updates will be cleared."),
) -> None:
    """Delete ALL updates on an item."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    _confirm(opts, f"Clear ALL updates on item {item_id}?")
    variables = {"item": item_id}
    if opts.dry_run:
        _dry_run(opts, UPDATE_CLEAR_ITEM, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, UPDATE_CLEAR_ITEM, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("clear_item_updates") or {})


@app.command("pin")
def pin_cmd(
    ctx: typer.Context,
    update_id: int = typer.Option(..., "--id", help="Update ID to pin."),
    item_id: int | None = typer.Option(
        None, "--item", help="Item the update belongs to (optional)."
    ),
) -> None:
    """Pin an update to the top of its item's feed."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"item": item_id, "update": update_id}
    if opts.dry_run:
        _dry_run(opts, UPDATE_PIN, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, UPDATE_PIN, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("pin_to_top") or {})


@app.command("unpin")
def unpin_cmd(
    ctx: typer.Context,
    update_id: int = typer.Option(..., "--id", help="Update ID to unpin."),
    item_id: int | None = typer.Option(
        None, "--item", help="Item the update belongs to (optional)."
    ),
) -> None:
    """Unpin an update."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"item": item_id, "update": update_id}
    if opts.dry_run:
        _dry_run(opts, UPDATE_UNPIN, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, UPDATE_UNPIN, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("unpin_from_top") or {})
