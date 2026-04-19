"""`mondo folder` — folder CRUD (Phase 3h).

Per monday-api.md §14:
- Max 3 nesting levels.
- Only the creator can delete; `delete_folder` archives contained boards
  (30-day recovery) and deletes dashboards (30-day trash).
- `update_folder` can take a `position` object (`{object_id, object_type,
  is_after}`) to reorder within a workspace.
"""

from __future__ import annotations

import json
from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError
from mondo.api.pagination import iter_boards_page
from mondo.api.queries import (
    FOLDER_CREATE,
    FOLDER_DELETE,
    FOLDER_GET,
    FOLDER_UPDATE,
    FOLDERS_LIST_PAGE,
)
from mondo.cli._confirm import confirm_or_abort as _confirm
from mondo.cli._examples import epilog_for
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


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


# ----- read commands -----


@app.command("list", epilog=epilog_for("folder list"))
def list_cmd(
    ctx: typer.Context,
    workspace: list[int] | None = typer.Option(
        None, "--workspace", help="Restrict to workspace IDs (repeatable)."
    ),
    limit: int = typer.Option(100, "--limit", help="Page size."),
    max_items: int | None = typer.Option(
        None, "--max-items", help="Stop after this many folders total."
    ),
) -> None:
    """List folders (page-based)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables: dict[str, Any] = {
        "ids": None,
        "workspaceIds": workspace or None,
    }
    if opts.dry_run:
        opts.emit(
            {
                "query": "<folders page iterator>",
                "variables": {**variables, "limit": limit, "max_items": max_items},
            }
        )
        raise typer.Exit(0)
    client = _client_or_exit(opts)
    try:
        with client:
            items = list(
                iter_boards_page(
                    client,
                    query=FOLDERS_LIST_PAGE,
                    variables=variables,
                    collection_key="folders",
                    limit=limit,
                    max_items=max_items,
                )
            )
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(items)


@app.command("get", epilog=epilog_for("folder get"))
def get_cmd(
    ctx: typer.Context,
    folder_id: int = typer.Option(..., "--id", help="Folder ID."),
) -> None:
    """Fetch a single folder by ID."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"ids": [folder_id]}
    if opts.dry_run:
        _dry_run(opts, FOLDER_GET, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, FOLDER_GET, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    folders = data.get("folders") or []
    if not folders:
        typer.secho(f"folder {folder_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
    opts.emit(folders[0])


# ----- write commands -----


@app.command("create", epilog=epilog_for("folder create"))
def create_cmd(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Folder name."),
    workspace: int = typer.Option(..., "--workspace", help="Target workspace ID."),
    color: str | None = typer.Option(None, "--color", help="Folder color (FolderColor enum name)."),
    parent: int | None = typer.Option(
        None, "--parent", help="Parent folder ID (max 3 nesting levels)."
    ),
    icon: str | None = typer.Option(
        None, "--icon", help="Custom icon (FolderCustomIcon enum name)."
    ),
    font_weight: str | None = typer.Option(
        None, "--font-weight", help="Font weight (FolderFontWeight enum name)."
    ),
) -> None:
    """Create a new folder inside a workspace."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables: dict[str, Any] = {
        "name": name,
        "workspace": workspace,
        "color": color,
        "parent": parent,
        "icon": icon,
        "fontWeight": font_weight,
    }
    if opts.dry_run:
        _dry_run(opts, FOLDER_CREATE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, FOLDER_CREATE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("create_folder") or {})


@app.command("update", epilog=epilog_for("folder update"))
def update_cmd(
    ctx: typer.Context,
    folder_id: int = typer.Option(..., "--id", help="Folder ID."),
    name: str | None = typer.Option(None, "--name", help="New name."),
    color: str | None = typer.Option(None, "--color", help="New color (enum)."),
    product_id: int | None = typer.Option(None, "--product-id", help="Account product ID."),
    position: str | None = typer.Option(
        None,
        "--position",
        metavar="JSON",
        help='Position as JSON: `{"object_id":N,"object_type":"Folder","is_after":true}`.',
    ),
) -> None:
    """Update a folder (name / color / position)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    position_obj: Any = None
    if position is not None:
        try:
            position_obj = json.loads(position)
        except json.JSONDecodeError as e:
            typer.secho(
                f"error: --position is not valid JSON: {e}",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=2) from e
    variables: dict[str, Any] = {
        "id": folder_id,
        "name": name,
        "color": color,
        "productId": product_id,
        "position": position_obj,
    }
    if all(v is None for k, v in variables.items() if k != "id"):
        typer.secho(
            "error: pass at least one of --name, --color, --product-id, --position.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    if opts.dry_run:
        _dry_run(opts, FOLDER_UPDATE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, FOLDER_UPDATE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("update_folder") or {})


@app.command("delete", epilog=epilog_for("folder delete"))
def delete_cmd(
    ctx: typer.Context,
    folder_id: int = typer.Option(..., "--id", help="Folder ID."),
    hard: bool = typer.Option(
        False, "--hard", help="Required (folder delete archives contained boards)."
    ),
) -> None:
    """Delete a folder (only the creator can delete; contained boards are archived)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    if not hard:
        typer.secho(
            "refusing to delete without --hard (folder delete archives contained boards).",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=2)
    _confirm(opts, f"Delete folder {folder_id} (contained boards will be archived)?")
    variables = {"id": folder_id}
    if opts.dry_run:
        _dry_run(opts, FOLDER_DELETE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, FOLDER_DELETE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("delete_folder") or {})
