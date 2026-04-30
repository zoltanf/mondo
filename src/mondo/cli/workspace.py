"""`mondo workspace` command group: CRUD for monday workspaces.

monday-api.md §14: workspace `kind` is `open | closed` (NOT `private`).
Main Workspace cannot be deleted. Uses page-based pagination like boards.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

import typer

from mondo.api.errors import MondoError
from mondo.api.pagination import MAX_BOARDS_PAGE_SIZE
from mondo.api.queries import (
    WORKSPACE_ADD_TEAMS,
    WORKSPACE_ADD_USERS,
    WORKSPACE_CREATE,
    WORKSPACE_DELETE,
    WORKSPACE_GET,
    WORKSPACE_REMOVE_TEAMS,
    WORKSPACE_REMOVE_USERS,
    WORKSPACE_UPDATE,
    WORKSPACES_LIST_PAGE,
)
from mondo.cli._examples import epilog_for
from mondo.cli._exec import client_or_exit, execute, execute_read
from mondo.cli._resolve import resolve_required_id
from mondo.cli.context import GlobalOpts

if TYPE_CHECKING:
    from mondo.cli._cache_flags import CachePrefs

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


class WorkspaceKind(StrEnum):
    open = "open"
    closed = "closed"


class WorkspaceState(StrEnum):
    active = "active"
    archived = "archived"
    deleted = "deleted"
    all = "all"


class SubscriberKind(StrEnum):
    subscriber = "subscriber"
    owner = "owner"


# ----- read commands -----


@app.command("list", epilog=epilog_for("workspace list"))
def list_cmd(
    ctx: typer.Context,
    kind: WorkspaceKind | None = typer.Option(
        None, "--kind", help="Filter by workspace kind (open/closed).", case_sensitive=False
    ),
    state: WorkspaceState | None = typer.Option(
        None, "--state", help="Filter by state (default: active).", case_sensitive=False
    ),
    name_fuzzy: str | None = typer.Option(
        None, "--name-fuzzy", help="Client-side fuzzy filter on workspace name."
    ),
    fuzzy_threshold: int | None = typer.Option(
        None, "--fuzzy-threshold", help="Minimum fuzzy score (0-100)."
    ),
    fuzzy_score_flag: bool = typer.Option(
        False, "--fuzzy-score", help="Include `_fuzzy_score` field; sort by score desc."
    ),
    limit: int = typer.Option(
        MAX_BOARDS_PAGE_SIZE,
        "--limit",
        help=f"Page size for live fetches (max {MAX_BOARDS_PAGE_SIZE}); ignored when served from cache.",
    ),
    max_items: int | None = typer.Option(
        None, "--max-items", help="Stop after this many workspaces total."
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Skip the local directory cache; fetch live."
    ),
    refresh_cache: bool = typer.Option(
        False, "--refresh-cache", help="Force-refresh the local directory cache."
    ),
) -> None:
    """List workspaces. Served from the local directory cache when available."""
    from mondo.cli._cache_flags import reject_mutually_exclusive, resolve_cache_prefs

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    reject_mutually_exclusive(no_cache, refresh_cache)
    prefs = resolve_cache_prefs(opts, no_cache=no_cache, fuzzy_threshold=fuzzy_threshold)

    if prefs.use_cache:
        _list_workspaces_via_cache(
            opts,
            kind=kind,
            state=state,
            name_fuzzy=name_fuzzy,
            fuzzy_threshold=prefs.fuzzy_threshold,
            fuzzy_score_flag=fuzzy_score_flag,
            max_items=max_items,
            refresh=refresh_cache,
        )
        return

    variables: dict[str, Any] = {
        "ids": None,
        "kind": kind.value if kind else None,
        "state": state.value if state else None,
    }

    if opts.dry_run:
        opts.emit(
            {
                "query": "<workspaces page iterator>",
                "variables": {**variables, "limit": limit, "max_items": max_items},
            }
        )
        raise typer.Exit(0)

    from mondo.api.pagination import iter_boards_page

    client = client_or_exit(opts)
    try:
        with client:
            items = list(
                iter_boards_page(
                    client,
                    query=WORKSPACES_LIST_PAGE,
                    variables=variables,
                    collection_key="workspaces",
                    limit=limit,
                    max_items=None if name_fuzzy else max_items,
                )
            )
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    if name_fuzzy is not None:
        from mondo.cli._filters import apply_fuzzy

        items = apply_fuzzy(
            items,
            name_fuzzy,
            threshold=prefs.fuzzy_threshold,
            include_score=fuzzy_score_flag,
        )
        if max_items is not None:
            items = items[:max_items]
    opts.emit(items)


def _list_workspaces_via_cache(
    opts: GlobalOpts,
    *,
    kind: WorkspaceKind | None,
    state: WorkspaceState | None,
    name_fuzzy: str | None,
    fuzzy_threshold: int,
    fuzzy_score_flag: bool,
    max_items: int | None,
    refresh: bool,
) -> None:
    from mondo.cache.directory import get_workspaces as cache_get_workspaces
    from mondo.cli._filters import apply_fuzzy

    if opts.dry_run:
        opts.emit(
            {
                "cache": "workspaces",
                "refresh": refresh,
                "filters": {
                    "kind": kind.value if kind else None,
                    "state": state.value if state else None,
                    "name_fuzzy": name_fuzzy,
                    "fuzzy_threshold": fuzzy_threshold,
                    "max_items": max_items,
                },
            }
        )
        raise typer.Exit(0)

    client = client_or_exit(opts)
    try:
        store = opts.build_cache_store("workspaces")
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    try:
        with client:
            cached = cache_get_workspaces(client, store=store, refresh=refresh)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    requested_state = state.value if state else "active"
    entries = cached.entries
    if requested_state != "all":
        entries = [w for w in entries if (w.get("state") or "active") == requested_state]
    if kind is not None:
        entries = [w for w in entries if (w.get("kind") or "") == kind.value]

    if name_fuzzy is not None:
        entries = apply_fuzzy(
            entries,
            name_fuzzy,
            threshold=fuzzy_threshold,
            include_score=fuzzy_score_flag,
        )

    if max_items is not None:
        entries = entries[:max_items]
    opts.emit(entries)


@app.command("get", epilog=epilog_for("workspace get"))
def get_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(
        None, metavar="[ID]", help="Workspace ID (positional)."
    ),
    id_flag: int | None = typer.Option(None, "--id", "--workspace", help="Workspace ID (flag form)."),
) -> None:
    """Fetch a single workspace by ID."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    workspace_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="workspace")
    data = execute_read(opts, WORKSPACE_GET, {"id": workspace_id})
    workspaces = data.get("workspaces") or []
    if not workspaces:
        typer.secho(f"workspace {workspace_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
    opts.emit(workspaces[0])


# ----- write commands -----


@app.command("create", epilog=epilog_for("workspace create"))
def create_cmd(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Workspace name."),
    kind: WorkspaceKind = typer.Option(
        WorkspaceKind.open, "--kind", help="open or closed.", case_sensitive=False
    ),
    description: str | None = typer.Option(None, "--description"),
    account_product_id: int | None = typer.Option(
        None, "--product-id", help="Account product ID (if multi-product)."
    ),
) -> None:
    """Create a new workspace."""
    from mondo.cli._cache_invalidate import invalidate_entity

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {
        "name": name,
        "kind": kind.value,
        "description": description,
        "accountProductId": account_product_id,
    }
    data = execute(opts, WORKSPACE_CREATE, variables)
    invalidate_entity(opts, "workspaces")
    opts.emit(data.get("create_workspace") or {})


@app.command("update", epilog=epilog_for("workspace update"))
def update_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(
        None, metavar="[ID]", help="Workspace ID (positional)."
    ),
    id_flag: int | None = typer.Option(None, "--id", "--workspace", help="Workspace ID (flag form)."),
    name: str | None = typer.Option(None, "--name", help="New name."),
    description: str | None = typer.Option(None, "--description", help="New description."),
    kind: WorkspaceKind | None = typer.Option(
        None, "--kind", help="Change open/closed.", case_sensitive=False
    ),
) -> None:
    """Update a workspace's name / description / kind."""
    from mondo.cli._cache_invalidate import invalidate_entity

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    workspace_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="workspace")
    attributes: dict[str, Any] = {}
    if name is not None:
        attributes["name"] = name
    if description is not None:
        attributes["description"] = description
    if kind is not None:
        attributes["kind"] = kind.value
    if not attributes:
        typer.secho(
            "error: pass at least one of --name, --description, --kind.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    variables = {"id": workspace_id, "attributes": attributes}
    data = execute(opts, WORKSPACE_UPDATE, variables)
    invalidate_entity(opts, "workspaces")
    opts.emit(data.get("update_workspace") or {})


@app.command("delete", epilog=epilog_for("workspace delete"))
def delete_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(
        None, metavar="[ID]", help="Workspace ID (positional)."
    ),
    id_flag: int | None = typer.Option(None, "--id", "--workspace", help="Workspace ID (flag form)."),
    hard: bool = typer.Option(False, "--hard", help="Required for permanent deletion."),
) -> None:
    """Delete a workspace (permanent; Main Workspace cannot be deleted)."""
    from mondo.cli._cache_invalidate import invalidate_entity
    from mondo.cli._confirm import confirm_or_abort as _confirm

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    workspace_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="workspace")
    if not hard:
        typer.secho(
            "refusing to delete without --hard.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=2)
    _confirm(opts, f"PERMANENTLY delete workspace {workspace_id}?")
    variables = {"id": workspace_id}
    data = execute(opts, WORKSPACE_DELETE, variables)
    invalidate_entity(opts, "workspaces")
    opts.emit(data.get("delete_workspace") or {})


# ----- membership -----


@app.command("add-user", epilog=epilog_for("workspace add-user"))
def add_user_cmd(
    ctx: typer.Context,
    workspace_id: int = typer.Option(..., "--id", "--workspace", help="Workspace ID."),
    user: list[int] = typer.Option(..., "--user", help="User ID (repeatable)."),
    kind: SubscriberKind = typer.Option(
        SubscriberKind.subscriber,
        "--kind",
        help="Membership kind (subscriber or owner).",
        case_sensitive=False,
    ),
) -> None:
    """Add one or more users to a workspace."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"id": workspace_id, "users": user, "kind": kind.value}
    data = execute(opts, WORKSPACE_ADD_USERS, variables)
    opts.emit(data.get("add_users_to_workspace") or [])


@app.command("remove-user", epilog=epilog_for("workspace remove-user"))
def remove_user_cmd(
    ctx: typer.Context,
    workspace_id: int = typer.Option(..., "--id", "--workspace", help="Workspace ID."),
    user: list[int] = typer.Option(..., "--user", help="User ID to remove (repeatable)."),
) -> None:
    """Remove one or more users from a workspace."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"id": workspace_id, "users": user}
    data = execute(opts, WORKSPACE_REMOVE_USERS, variables)
    opts.emit(data.get("delete_users_from_workspace") or [])


@app.command("add-team", epilog=epilog_for("workspace add-team"))
def add_team_cmd(
    ctx: typer.Context,
    workspace_id: int = typer.Option(..., "--id", "--workspace", help="Workspace ID."),
    team: list[int] = typer.Option(..., "--team", help="Team ID (repeatable)."),
    kind: SubscriberKind = typer.Option(
        SubscriberKind.subscriber,
        "--kind",
        help="Membership kind (subscriber or owner).",
        case_sensitive=False,
    ),
) -> None:
    """Add one or more teams to a workspace."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"id": workspace_id, "teams": team, "kind": kind.value}
    data = execute(opts, WORKSPACE_ADD_TEAMS, variables)
    opts.emit(data.get("add_teams_to_workspace") or [])


@app.command("remove-team", epilog=epilog_for("workspace remove-team"))
def remove_team_cmd(
    ctx: typer.Context,
    workspace_id: int = typer.Option(..., "--id", "--workspace", help="Workspace ID."),
    team: list[int] = typer.Option(..., "--team", help="Team ID to remove (repeatable)."),
) -> None:
    """Remove one or more teams from a workspace."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"id": workspace_id, "teams": team}
    data = execute(opts, WORKSPACE_REMOVE_TEAMS, variables)
    opts.emit(data.get("delete_teams_from_workspace") or [])
