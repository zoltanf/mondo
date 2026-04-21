"""`mondo folder` — folder CRUD (Phase 3h).

Per monday-api.md §14:
- Max 3 nesting levels.
- Only the creator can delete; `delete_folder` archives contained boards
  (30-day recovery) and deletes dashboards (30-day trash).
- `update_folder` can take a `position` object (`{object_id, object_type,
  is_after}`) to reorder within a workspace.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import typer

from mondo.api.errors import MondoError
from mondo.api.pagination import iter_boards_page
from mondo.api.queries import (
    FOLDER_CREATE,
    FOLDER_DELETE,
    FOLDER_GET,
    FOLDER_UPDATE,
    build_folders_list_query,
)
from mondo.cache.directory import get_folders as cache_get_folders
from mondo.cli._cache_flags import reject_mutually_exclusive, resolve_cache_prefs
from mondo.cli._cache_invalidate import invalidate_entity
from mondo.cli._confirm import confirm_or_abort as _confirm
from mondo.cli._examples import epilog_for
from mondo.cli._exec import client_or_exit, execute
from mondo.cli._json_flag import parse_json_flag
from mondo.cli._normalize import normalize_folder_entry
from mondo.cli._resolve import resolve_required_id
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


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
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Skip the local directory cache; fetch live.", rich_help_panel="Cache"
    ),
    refresh_cache: bool = typer.Option(
        False,
        "--refresh-cache",
        help="Force-refresh the local directory cache before serving.",
        rich_help_panel="Cache",
    ),
) -> None:
    """List folders (page-based). Served from the local directory cache when available."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    reject_mutually_exclusive(no_cache, refresh_cache)
    prefs = resolve_cache_prefs(opts, no_cache=no_cache, fuzzy_threshold=None)

    if prefs.use_cache:
        if opts.dry_run:
            opts.emit(
                {
                    "cache": "folders",
                    "refresh": refresh_cache,
                    "filters": {
                        "workspace_ids": workspace or None,
                        "max_items": max_items,
                    },
                }
            )
            raise typer.Exit(0)

        store = opts.build_cache_store("folders")
        client = client_or_exit(opts)
        try:
            with client:
                cached = cache_get_folders(client, store=store, refresh=refresh_cache)
        except MondoError as e:
            typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=int(e.exit_code)) from e

        items = cached.entries
        if workspace:
            wanted = {str(w) for w in workspace}
            items = [f for f in items if str(f.get("workspace_id") or "") in wanted]
        if max_items is not None:
            items = items[:max_items]
        opts.emit(items)
        return

    # Live path
    query, variables = build_folders_list_query(workspace_ids=workspace or None)
    if opts.dry_run:
        opts.emit(
            {
                "query": query,
                "variables": {**variables, "limit": limit, "max_items": max_items},
            }
        )
        raise typer.Exit(0)

    client = client_or_exit(opts)
    try:
        with client:
            items = [
                normalize_folder_entry(entry)
                for entry in iter_boards_page(
                    client,
                    query=query,
                    variables=variables,
                    collection_key="folders",
                    limit=limit,
                    max_items=max_items,
                )
            ]
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    opts.emit(items)


_TABLE_FORMATS: frozenset[str | None] = frozenset({"table", None})
FolderEntry = dict[str, Any]
FolderChildrenMap = dict[str | None, list[FolderEntry]]
FolderTreeNode = dict[str, Any]


def _render_tree_lines(
    node_list: list[FolderEntry],
    children_map: FolderChildrenMap,
    prefix: str = "  ",
) -> list[str]:
    lines: list[str] = []
    for i, folder in enumerate(node_list):
        is_last = i == len(node_list) - 1
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}[{folder['id']}] {folder['name']}")
        sub = children_map.get(str(folder["id"]), [])
        if sub:
            ext = "    " if is_last else "│   "
            lines.extend(_render_tree_lines(sub, children_map, prefix + ext))
    return lines


def _build_tree_node(folder: FolderEntry, children_map: FolderChildrenMap) -> FolderTreeNode:
    sub = children_map.get(str(folder["id"]), [])
    return {
        "id": folder["id"],
        "name": folder["name"],
        "color": folder.get("color"),
        "sub_folders": [_build_tree_node(s, children_map) for s in sub],
    }


@app.command("tree", epilog=epilog_for("folder tree"))
def tree_cmd(
    ctx: typer.Context,
    workspace: list[int] | None = typer.Option(
        None, "--workspace", help="Restrict to workspace IDs (repeatable).", rich_help_panel="Filters"
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Skip the local directory cache; fetch live.", rich_help_panel="Cache"
    ),
    refresh_cache: bool = typer.Option(
        False,
        "--refresh-cache",
        help="Force-refresh the local directory cache before serving.",
        rich_help_panel="Cache",
    ),
) -> None:
    """Show folders as a hierarchy tree, grouped by workspace."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    reject_mutually_exclusive(no_cache, refresh_cache)
    prefs = resolve_cache_prefs(opts, no_cache=no_cache, fuzzy_threshold=None)

    if prefs.use_cache:
        if opts.dry_run:
            opts.emit({
                "cache": "folders",
                "refresh": refresh_cache,
                "filters": {"workspace_ids": workspace or None},
            })
            raise typer.Exit(0)

        store = opts.build_cache_store("folders")
        client = client_or_exit(opts)
        try:
            with client:
                cached = cache_get_folders(client, store=store, refresh=refresh_cache)
        except MondoError as e:
            typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=int(e.exit_code)) from e
        folders = cached.entries
    else:
        # Live path
        query, variables = build_folders_list_query(workspace_ids=workspace or None)
        if opts.dry_run:
            opts.emit({
                "query": query,
                "variables": {**variables, "limit": 100},
            })
            raise typer.Exit(0)

        client = client_or_exit(opts)
        try:
            with client:
                folders = [
                    normalize_folder_entry(entry)
                    for entry in iter_boards_page(
                        client,
                        query=query,
                        variables=variables,
                        collection_key="folders",
                        limit=100,
                        max_items=None,
                    )
                ]
        except MondoError as e:
            typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=int(e.exit_code)) from e

    # Client-side workspace filter applied unconditionally: the live path passes
    # workspaceIds to GraphQL (server-side), the cache path does not. Applying
    # it here as well is a belt-and-suspenders guard that also makes the live
    # path consistent with the cache path when the server returns extra data.
    if workspace:
        wanted = {str(w) for w in workspace}
        folders = [f for f in folders if str(f.get("workspace_id") or "") in wanted]

    # Build children_map: parent_id (str) → list of child folders
    # Root folders have parent_id == None.
    # Orphan folders (parent references a non-existent folder) are treated as root.
    all_ids = {str(f["id"]) for f in folders}
    children_map: FolderChildrenMap = defaultdict(list)
    for f in folders:
        pid = f.get("parent_id")
        if pid is not None and str(pid) in all_ids:
            key: str | None = str(pid)
        else:
            key = None
        children_map[key].append(f)

    # Group root folders (children_map[None]) by workspace
    root_folders = children_map.get(None, [])
    by_workspace: dict[Any, list[FolderEntry]] = defaultdict(list)
    for f in root_folders:
        by_workspace[f.get("workspace_id")].append(f)

    # Collect all workspace ids/names present in folder list for ordering.
    # Computed once and shared by both output paths.
    ws_meta: dict[Any, str] = {}
    for f in folders:
        wid = f.get("workspace_id")
        wname = f.get("workspace_name") or ""
        ws_meta.setdefault(wid, wname)

    if opts.output not in _TABLE_FORMATS:
        # Structured JSON output
        if not folders:
            opts.emit([])
            return

        structured = [
            {
                "workspace_id": wid,
                "workspace_name": ws_meta[wid],
                "folders": [_build_tree_node(f, children_map) for f in by_workspace.get(wid, [])],
            }
            for wid in sorted(ws_meta, key=lambda k: ws_meta[k])
            if by_workspace.get(wid)
        ]
        opts.emit(structured)
        return

    # Table / TTY output: emit ASCII tree string
    if not folders:
        opts.emit("")
        return

    all_lines: list[str] = []
    for wid in sorted(ws_meta, key=lambda k: ws_meta[k]):
        ws_roots = by_workspace.get(wid, [])
        if not ws_roots:
            continue
        wname = ws_meta[wid]
        all_lines.append(f"{wname}  (workspace_id: {wid})")
        all_lines.extend(_render_tree_lines(ws_roots, children_map))

    opts.emit("\n".join(all_lines))


@app.command("get", epilog=epilog_for("folder get"))
def get_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Folder ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", help="Folder ID (flag form)."),
) -> None:
    """Fetch a single folder by ID."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    folder_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="folder")
    variables = {"ids": [folder_id]}
    data = execute(opts, FOLDER_GET, variables)
    folders = data.get("folders") or []
    if not folders:
        typer.secho(f"folder {folder_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
    opts.emit(normalize_folder_entry(folders[0]))


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
    data = execute(opts, FOLDER_CREATE, variables)
    invalidate_entity(opts, "folders")
    opts.emit(data.get("create_folder") or {})


@app.command("update", epilog=epilog_for("folder update"))
def update_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Folder ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", help="Folder ID (flag form)."),
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
    folder_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="folder")
    position_obj: Any = None
    if position is not None:
        position_obj = parse_json_flag(position, flag_name="--position")
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
    data = execute(opts, FOLDER_UPDATE, variables)
    invalidate_entity(opts, "folders")
    opts.emit(data.get("update_folder") or {})


@app.command("delete", epilog=epilog_for("folder delete"))
def delete_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Folder ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", help="Folder ID (flag form)."),
    hard: bool = typer.Option(
        False, "--hard", help="Required (folder delete archives contained boards)."
    ),
) -> None:
    """Delete a folder (only the creator can delete; contained boards are archived)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    folder_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="folder")
    if not hard:
        typer.secho(
            "refusing to delete without --hard (folder delete archives contained boards).",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=2)
    _confirm(opts, f"Delete folder {folder_id} (contained boards will be archived)?")
    variables = {"id": folder_id}
    data = execute(opts, FOLDER_DELETE, variables)
    invalidate_entity(opts, "folders")
    opts.emit(data.get("delete_folder") or {})
