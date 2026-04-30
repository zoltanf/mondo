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
from mondo.cli._confirm import confirm_or_abort as _confirm
from mondo.cli._examples import epilog_for
from mondo.cli._exec import client_or_exit, exec_or_exit, execute
from mondo.cli._resolve import resolve_required_id
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


MAX_UPDATES_PAGE_SIZE = 100


# ----- helpers -----


def _load_body(
    body: str | None,
    from_file: Path | None,
    from_stdin: bool,
    *,
    html_only: bool = False,
) -> str:
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
        raw = from_file.read_text()
    elif from_stdin:
        raw = sys.stdin.read()
    else:
        assert body is not None
        raw = body
    if html_only:
        return raw
    # Default: render as CommonMark markdown. Raw HTML in the input is passed
    # through unchanged by the CommonMark renderer, so existing scripts that
    # supplied ready-made HTML (e.g. `<p>FYI</p>`) keep working.
    from mondo.util.markdown import to_html

    return to_html(raw)


def _resolve_body_format(*, markdown: bool, html: bool) -> bool:
    """Return `html_only` for `_load_body`. Errors on conflicting flags.

    Default (neither flag): markdown → HTML conversion (most agent-friendly).
    --markdown: explicit opt-in (no-op now; kept for backward compatibility).
    --html:     opt out of conversion; the body is sent verbatim.
    """
    if markdown and html:
        typer.secho(
            "error: --markdown and --html are mutually exclusive.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    return html


# ----- read commands -----


@app.command("list", epilog=epilog_for("update list"))
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
        if opts.dry_run:
            opts.emit(
                {
                    "query": UPDATES_FOR_ITEM,
                    "variables": {"id": item_id, "limit": limit, "page": page},
                }
            )
            raise typer.Exit(0)
        client = client_or_exit(opts)
        try:
            with client:
                while True:
                    data = exec_or_exit(
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
        from mondo.cli._field_sets import update_list_fields

        opts.emit(collected, selected_fields=update_list_fields())
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
    client = client_or_exit(opts)
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
    from mondo.cli._field_sets import update_list_fields

    opts.emit(items, selected_fields=update_list_fields())


@app.command("get", epilog=epilog_for("update get"))
def get_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Update ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--update", help="Update ID (flag form)."),
) -> None:
    """Fetch a single update by ID with replies, likes, and pinning info."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    update_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="update")
    variables = {"id": update_id}
    data = execute(opts, UPDATE_GET, variables)
    updates = data.get("updates") or []
    if not updates:
        typer.secho(f"update {update_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
    from mondo.cli._field_sets import update_get_fields

    opts.emit(updates[0], selected_fields=update_get_fields())


# ----- write commands -----


@app.command("create", epilog=epilog_for("update create"))
def create_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--item", help="Item to post the update on."),
    body: str | None = typer.Option(
        None,
        "--body",
        help="Update body (CommonMark markdown by default — pass --html to send HTML "
        "verbatim).",
    ),
    from_file: Path | None = typer.Option(None, "--from-file", help="Load the body from a file."),
    from_stdin: bool = typer.Option(False, "--from-stdin", help="Load the body from stdin."),
    markdown: bool = typer.Option(
        False,
        "--markdown",
        help="No-op (markdown is the default). Kept for backward compatibility.",
    ),
    html: bool = typer.Option(
        False,
        "--html",
        help="Send the body verbatim as HTML, skipping markdown conversion. "
        "Use this when the input already includes monday-specific HTML "
        "(e.g. `<mention>` tags) you want to preserve exactly.",
    ),
) -> None:
    """Post a new update (comment) on an item."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    html_only = _resolve_body_format(markdown=markdown, html=html)
    payload = _load_body(body, from_file, from_stdin, html_only=html_only)
    variables = {"item": item_id, "parent": None, "body": payload}
    data = execute(opts, UPDATE_CREATE, variables)
    opts.emit(data.get("create_update") or {})


@app.command("reply", epilog=epilog_for("update reply"))
def reply_cmd(
    ctx: typer.Context,
    parent_id: int = typer.Option(
        ..., "--parent", help="Parent update ID (the reply attaches to it)."
    ),
    body: str | None = typer.Option(
        None,
        "--body",
        help="Reply body (CommonMark markdown by default — pass --html to send HTML "
        "verbatim).",
    ),
    from_file: Path | None = typer.Option(None, "--from-file", help="Load the body from a file."),
    from_stdin: bool = typer.Option(False, "--from-stdin", help="Load the body from stdin."),
    markdown: bool = typer.Option(
        False,
        "--markdown",
        help="No-op (markdown is the default). Kept for backward compatibility.",
    ),
    html: bool = typer.Option(
        False,
        "--html",
        help="Send the body verbatim as HTML, skipping markdown conversion.",
    ),
) -> None:
    """Post a reply to an existing update."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    html_only = _resolve_body_format(markdown=markdown, html=html)
    payload = _load_body(body, from_file, from_stdin, html_only=html_only)
    variables = {"item": None, "parent": parent_id, "body": payload}
    data = execute(opts, UPDATE_CREATE, variables)
    opts.emit(data.get("create_update") or {})


@app.command("edit", epilog=epilog_for("update edit"))
def edit_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Update ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--update", help="Update ID (flag form)."),
    body: str | None = typer.Option(
        None,
        "--body",
        help="New body (CommonMark markdown by default — pass --html to send HTML "
        "verbatim).",
    ),
    from_file: Path | None = typer.Option(
        None, "--from-file", help="Load the new body from a file."
    ),
    from_stdin: bool = typer.Option(False, "--from-stdin", help="Load the new body from stdin."),
    markdown: bool = typer.Option(
        False,
        "--markdown",
        help="No-op (markdown is the default). Kept for backward compatibility.",
    ),
    html: bool = typer.Option(
        False,
        "--html",
        help="Send the body verbatim as HTML, skipping markdown conversion.",
    ),
) -> None:
    """Edit an existing update."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    update_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="update")
    html_only = _resolve_body_format(markdown=markdown, html=html)
    payload = _load_body(body, from_file, from_stdin, html_only=html_only)
    variables = {"id": update_id, "body": payload}
    data = execute(opts, UPDATE_EDIT, variables)
    opts.emit(data.get("edit_update") or {})


@app.command("delete", epilog=epilog_for("update delete"))
def delete_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Update ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--update", help="Update ID (flag form)."),
) -> None:
    """Delete an update (permanent)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    update_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="update")
    _confirm(opts, f"Delete update {update_id}?")
    variables = {"id": update_id}
    data = execute(opts, UPDATE_DELETE, variables)
    opts.emit(data.get("delete_update") or {})


@app.command("like", epilog=epilog_for("update like"))
def like_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Update ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--update", help="Update ID (flag form)."),
) -> None:
    """Like an update."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    update_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="update")
    variables = {"id": update_id}
    data = execute(opts, UPDATE_LIKE, variables)
    opts.emit(data.get("like_update") or {})


@app.command("unlike", epilog=epilog_for("update unlike"))
def unlike_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Update ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--update", help="Update ID (flag form)."),
) -> None:
    """Remove a like from an update."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    update_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="update")
    variables = {"id": update_id}
    data = execute(opts, UPDATE_UNLIKE, variables)
    opts.emit(data.get("unlike_update") or {})


@app.command("clear", epilog=epilog_for("update clear"))
def clear_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--item", help="Item whose updates will be cleared."),
) -> None:
    """Delete ALL updates on an item."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    _confirm(opts, f"Clear ALL updates on item {item_id}?")
    variables = {"item": item_id}
    data = execute(opts, UPDATE_CLEAR_ITEM, variables)
    opts.emit(data.get("clear_item_updates") or {})


@app.command("pin", epilog=epilog_for("update pin"))
def pin_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Update ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--update", help="Update ID (flag form)."),
    item_id: int | None = typer.Option(
        None, "--item", help="Item the update belongs to (optional)."
    ),
) -> None:
    """Pin an update to the top of its item's feed."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    update_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="update")
    variables = {"item": item_id, "update": update_id}
    data = execute(opts, UPDATE_PIN, variables)
    opts.emit(data.get("pin_to_top") or {})


@app.command("unpin", epilog=epilog_for("update unpin"))
def unpin_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Update ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--update", help="Update ID (flag form)."),
    item_id: int | None = typer.Option(
        None, "--item", help="Item the update belongs to (optional)."
    ),
) -> None:
    """Unpin an update."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    update_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="update")
    variables = {"item": item_id, "update": update_id}
    data = execute(opts, UPDATE_UNPIN, variables)
    opts.emit(data.get("unpin_from_top") or {})
