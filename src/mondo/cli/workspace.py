"""`mondo workspace` command group: CRUD for monday workspaces.

monday-api.md §14: workspace `kind` is `open | closed` (NOT `private`).
Main Workspace cannot be deleted. Uses page-based pagination like boards.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError
from mondo.api.pagination import MAX_BOARDS_PAGE_SIZE, iter_boards_page
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
from mondo.cli.context import GlobalOpts

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


def _confirm_or_abort(opts: GlobalOpts, prompt: str) -> None:
    if opts.yes:
        return
    if not typer.confirm(prompt, default=False):
        typer.echo("aborted.")
        raise typer.Exit(1)


# ----- read commands -----


@app.command("list")
def list_cmd(
    ctx: typer.Context,
    kind: WorkspaceKind | None = typer.Option(
        None, "--kind", help="Filter by workspace kind (open/closed).", case_sensitive=False
    ),
    state: WorkspaceState | None = typer.Option(
        None, "--state", help="Filter by state (default: active).", case_sensitive=False
    ),
    limit: int = typer.Option(
        MAX_BOARDS_PAGE_SIZE,
        "--limit",
        help=f"Page size (max {MAX_BOARDS_PAGE_SIZE}).",
    ),
    max_items: int | None = typer.Option(
        None, "--max-items", help="Stop after this many workspaces total."
    ),
) -> None:
    """List workspaces (page-based pagination)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
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

    client = _client_or_exit(opts)
    try:
        with client:
            items = list(
                iter_boards_page(
                    client,
                    query=WORKSPACES_LIST_PAGE,
                    variables=variables,
                    collection_key="workspaces",
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
    workspace_id: int = typer.Option(..., "--id", help="Workspace ID."),
) -> None:
    """Fetch a single workspace by ID."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, WORKSPACE_GET, {"id": workspace_id})
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    workspaces = data.get("workspaces") or []
    if not workspaces:
        typer.secho(f"workspace {workspace_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
    opts.emit(workspaces[0])


# ----- write commands -----


@app.command("create")
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
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {
        "name": name,
        "kind": kind.value,
        "description": description,
        "accountProductId": account_product_id,
    }
    if opts.dry_run:
        _dry_run(opts, WORKSPACE_CREATE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, WORKSPACE_CREATE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("create_workspace") or {})


@app.command("update")
def update_cmd(
    ctx: typer.Context,
    workspace_id: int = typer.Option(..., "--id", help="Workspace ID."),
    name: str | None = typer.Option(None, "--name", help="New name."),
    description: str | None = typer.Option(None, "--description", help="New description."),
    kind: WorkspaceKind | None = typer.Option(
        None, "--kind", help="Change open/closed.", case_sensitive=False
    ),
) -> None:
    """Update a workspace's name / description / kind."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
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
    if opts.dry_run:
        _dry_run(opts, WORKSPACE_UPDATE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, WORKSPACE_UPDATE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("update_workspace") or {})


@app.command("delete")
def delete_cmd(
    ctx: typer.Context,
    workspace_id: int = typer.Option(..., "--id", help="Workspace ID to delete."),
    hard: bool = typer.Option(False, "--hard", help="Required for permanent deletion."),
) -> None:
    """Delete a workspace (permanent; Main Workspace cannot be deleted)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    if not hard:
        typer.secho(
            "refusing to delete without --hard.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=2)
    _confirm_or_abort(opts, f"PERMANENTLY delete workspace {workspace_id}?")
    variables = {"id": workspace_id}
    if opts.dry_run:
        _dry_run(opts, WORKSPACE_DELETE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, WORKSPACE_DELETE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("delete_workspace") or {})


# ----- membership -----


@app.command("add-user")
def add_user_cmd(
    ctx: typer.Context,
    workspace_id: int = typer.Option(..., "--id", help="Workspace ID."),
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
    if opts.dry_run:
        _dry_run(opts, WORKSPACE_ADD_USERS, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, WORKSPACE_ADD_USERS, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("add_users_to_workspace") or [])


@app.command("remove-user")
def remove_user_cmd(
    ctx: typer.Context,
    workspace_id: int = typer.Option(..., "--id", help="Workspace ID."),
    user: list[int] = typer.Option(..., "--user", help="User ID to remove (repeatable)."),
) -> None:
    """Remove one or more users from a workspace."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"id": workspace_id, "users": user}
    if opts.dry_run:
        _dry_run(opts, WORKSPACE_REMOVE_USERS, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, WORKSPACE_REMOVE_USERS, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("delete_users_from_workspace") or [])


@app.command("add-team")
def add_team_cmd(
    ctx: typer.Context,
    workspace_id: int = typer.Option(..., "--id", help="Workspace ID."),
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
    if opts.dry_run:
        _dry_run(opts, WORKSPACE_ADD_TEAMS, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, WORKSPACE_ADD_TEAMS, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("add_teams_to_workspace") or [])


@app.command("remove-team")
def remove_team_cmd(
    ctx: typer.Context,
    workspace_id: int = typer.Option(..., "--id", help="Workspace ID."),
    team: list[int] = typer.Option(..., "--team", help="Team ID to remove (repeatable)."),
) -> None:
    """Remove one or more teams from a workspace."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"id": workspace_id, "teams": team}
    if opts.dry_run:
        _dry_run(opts, WORKSPACE_REMOVE_TEAMS, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, WORKSPACE_REMOVE_TEAMS, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("delete_teams_from_workspace") or [])
