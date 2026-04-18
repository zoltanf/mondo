"""`mondo user` command group — user CRUD and role management (Phase 3a).

Per monday-api.md §14:
- `users(ids, kind, emails, name, non_active, newest_first, limit, page)` is
  the primary query. `users(emails:)` is case-sensitive.
- Role changes use **four** mutations (admins/members/guests/viewers) —
  there's no single role-enum argument. `mondo user update-role` hides this.
- `deactivate_users` / `activate_users` / `add_users_to_team` /
  `remove_users_from_team` all accept lists and return partial-success
  payloads with per-user errors.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError
from mondo.api.pagination import MAX_BOARDS_PAGE_SIZE, iter_boards_page
from mondo.api.queries import (
    ADD_USERS_TO_TEAM,
    REMOVE_USERS_FROM_TEAM,
    USER_GET,
    USERS_ACTIVATE,
    USERS_DEACTIVATE,
    USERS_LIST_PAGE,
    USERS_UPDATE_AS_ADMINS,
    USERS_UPDATE_AS_GUESTS,
    USERS_UPDATE_AS_MEMBERS,
    USERS_UPDATE_AS_VIEWERS,
)
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


class UserKind(StrEnum):
    all = "all"
    non_guests = "non_guests"
    guests = "guests"
    non_pending = "non_pending"


class UserRole(StrEnum):
    admin = "admin"
    member = "member"
    guest = "guest"
    viewer = "viewer"


_ROLE_TO_MUTATION = {
    UserRole.admin: (USERS_UPDATE_AS_ADMINS, "update_multiple_users_as_admins"),
    UserRole.member: (USERS_UPDATE_AS_MEMBERS, "update_multiple_users_as_members"),
    UserRole.guest: (USERS_UPDATE_AS_GUESTS, "update_multiple_users_as_guests"),
    UserRole.viewer: (USERS_UPDATE_AS_VIEWERS, "update_multiple_users_as_viewers"),
}


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


# ----- read commands -----


@app.command("list")
def list_cmd(
    ctx: typer.Context,
    kind: UserKind | None = typer.Option(
        None,
        "--kind",
        help="Filter by kind (all/non_guests/guests/non_pending).",
        case_sensitive=False,
    ),
    email: list[str] | None = typer.Option(
        None,
        "--email",
        help="Filter by email (case-sensitive exact match, repeatable).",
    ),
    name: str | None = typer.Option(None, "--name", help="Server-side substring filter on name."),
    non_active: bool = typer.Option(False, "--non-active", help="Include deactivated users."),
    newest_first: bool = typer.Option(
        False, "--newest-first", help="Sort by most recently created."
    ),
    limit: int = typer.Option(
        MAX_BOARDS_PAGE_SIZE,
        "--limit",
        help=f"Page size (max {MAX_BOARDS_PAGE_SIZE}).",
    ),
    max_items: int | None = typer.Option(
        None, "--max-items", help="Stop after this many users total."
    ),
) -> None:
    """List users (page-based pagination)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables: dict[str, Any] = {
        "ids": None,
        "kind": kind.value if kind else None,
        "emails": email or None,
        "name": name,
        "nonActive": True if non_active else None,
        "newestFirst": True if newest_first else None,
    }

    if opts.dry_run:
        opts.emit(
            {
                "query": "<users page iterator>",
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
                    query=USERS_LIST_PAGE,
                    variables=variables,
                    collection_key="users",
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
    user_id: int = typer.Option(..., "--id", help="User ID."),
) -> None:
    """Fetch a single user by ID, including teams and account."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    if opts.dry_run:
        _dry_run(opts, USER_GET, {"ids": [user_id]})
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, USER_GET, {"ids": [user_id]})
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    users = data.get("users") or []
    if not users:
        typer.secho(f"user {user_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
    opts.emit(users[0])


# ----- write commands -----


@app.command("deactivate")
def deactivate_cmd(
    ctx: typer.Context,
    user: list[int] = typer.Option(..., "--user", help="User ID to deactivate (repeatable)."),
) -> None:
    """Deactivate one or more users."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    _confirm(opts, f"Deactivate {len(user)} user(s)?")
    variables = {"ids": user}
    if opts.dry_run:
        _dry_run(opts, USERS_DEACTIVATE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, USERS_DEACTIVATE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("deactivate_users") or {})


@app.command("activate")
def activate_cmd(
    ctx: typer.Context,
    user: list[int] = typer.Option(..., "--user", help="User ID to reactivate (repeatable)."),
) -> None:
    """Reactivate one or more users."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"ids": user}
    if opts.dry_run:
        _dry_run(opts, USERS_ACTIVATE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, USERS_ACTIVATE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("activate_users") or {})


@app.command("update-role")
def update_role_cmd(
    ctx: typer.Context,
    user: list[int] = typer.Option(..., "--user", help="User ID (repeatable)."),
    role: UserRole = typer.Option(
        ...,
        "--role",
        help="Target role (admin/member/guest/viewer).",
        case_sensitive=False,
    ),
) -> None:
    """Change the role of one or more users.

    monday ships four separate mutations; mondo dispatches to the right one.
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    query, response_key = _ROLE_TO_MUTATION[role]
    variables = {"ids": user}
    if opts.dry_run:
        _dry_run(opts, query, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, query, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get(response_key) or {})


@app.command("add-to-team")
def add_to_team_cmd(
    ctx: typer.Context,
    team_id: int = typer.Option(..., "--team", help="Team ID."),
    user: list[int] = typer.Option(..., "--user", help="User ID (repeatable)."),
) -> None:
    """Add one or more users to a team."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"team": team_id, "users": user}
    if opts.dry_run:
        _dry_run(opts, ADD_USERS_TO_TEAM, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, ADD_USERS_TO_TEAM, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("add_users_to_team") or {})


@app.command("remove-from-team")
def remove_from_team_cmd(
    ctx: typer.Context,
    team_id: int = typer.Option(..., "--team", help="Team ID."),
    user: list[int] = typer.Option(..., "--user", help="User ID (repeatable)."),
) -> None:
    """Remove one or more users from a team."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"team": team_id, "users": user}
    if opts.dry_run:
        _dry_run(opts, REMOVE_USERS_FROM_TEAM, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, REMOVE_USERS_FROM_TEAM, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("remove_users_from_team") or {})
