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

from mondo.api.errors import MondoError
from mondo.api.pagination import MAX_BOARDS_PAGE_SIZE
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
from mondo.cli._examples import epilog_for
from mondo.cli._exec import client_or_exit, execute, handle_mondo_error_or_exit
from mondo.cli._resolve import resolve_required_id
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


# ----- read commands -----


@app.command("list", epilog=epilog_for("user list"))
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
    name: str | None = typer.Option(None, "--name", help="Substring filter on name."),
    name_fuzzy: str | None = typer.Option(
        None, "--name-fuzzy", help="Client-side fuzzy filter on user name."
    ),
    fuzzy_threshold: int | None = typer.Option(
        None, "--fuzzy-threshold", help="Minimum fuzzy score (0-100)."
    ),
    fuzzy_score_flag: bool = typer.Option(
        False, "--fuzzy-score", help="Include `_fuzzy_score` field; sort by score desc."
    ),
    non_active: bool = typer.Option(
        False,
        "--include-deactivated",
        "--non-active",
        help="Include deactivated users.",
    ),
    newest_first: bool = typer.Option(
        False, "--newest-first", help="Sort by most recently created."
    ),
    limit: int = typer.Option(
        MAX_BOARDS_PAGE_SIZE,
        "--limit",
        help=f"Page size for live fetches (max {MAX_BOARDS_PAGE_SIZE}); ignored when served from cache.",
    ),
    max_items: int | None = typer.Option(
        None, "--max-items", help="Stop after this many users total."
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Skip the local directory cache; fetch live."
    ),
    refresh_cache: bool = typer.Option(
        False, "--refresh-cache", help="Force-refresh the local directory cache."
    ),
    explain_cache: bool = typer.Option(
        False,
        "--explain-cache",
        help="Print verbose cache provenance to stderr (path, ttl, fetched_at).",
    ),
) -> None:
    """List users. Served from the local directory cache when available."""
    from mondo.cli._cache_flags import reject_mutually_exclusive, resolve_cache_prefs

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    reject_mutually_exclusive(no_cache, refresh_cache)
    prefs = resolve_cache_prefs(opts, no_cache=no_cache, fuzzy_threshold=fuzzy_threshold)

    if prefs.use_cache:
        _list_users_via_cache(
            opts,
            kind=kind,
            emails=email,
            name=name,
            name_fuzzy=name_fuzzy,
            fuzzy_threshold=prefs.fuzzy_threshold,
            fuzzy_score_flag=fuzzy_score_flag,
            non_active=non_active,
            newest_first=newest_first,
            max_items=max_items,
            refresh=refresh_cache,
            explain_cache=explain_cache,
        )
        return

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

    from mondo.api.pagination import iter_boards_page

    client = client_or_exit(opts)
    try:
        with client:
            items = list(
                iter_boards_page(
                    client,
                    query=USERS_LIST_PAGE,
                    variables=variables,
                    collection_key="users",
                    limit=limit,
                    max_items=None if name_fuzzy else max_items,
                )
            )
    except MondoError as e:
        handle_mondo_error_or_exit(e)
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


def _list_users_via_cache(
    opts: GlobalOpts,
    *,
    kind: UserKind | None,
    emails: list[str] | None,
    name: str | None,
    name_fuzzy: str | None,
    fuzzy_threshold: int,
    fuzzy_score_flag: bool,
    non_active: bool,
    newest_first: bool,
    max_items: int | None,
    refresh: bool,
    explain_cache: bool = False,
) -> None:
    from mondo.cache.directory import get_users as cache_get_users
    from mondo.cli._cache_flags import emit_cache_provenance
    from mondo.cli._filters import apply_fuzzy

    if opts.dry_run:
        opts.emit(
            {
                "cache": "users",
                "refresh": refresh,
                "filters": {
                    "kind": kind.value if kind else None,
                    "emails": emails or None,
                    "name": name,
                    "name_fuzzy": name_fuzzy,
                    "fuzzy_threshold": fuzzy_threshold,
                    "non_active": non_active,
                    "newest_first": newest_first,
                    "max_items": max_items,
                },
            }
        )
        raise typer.Exit(0)

    client = client_or_exit(opts)
    try:
        store = opts.build_cache_store("users")
    except MondoError as e:
        handle_mondo_error_or_exit(e)

    try:
        with client:
            cached = cache_get_users(client, store=store, refresh=refresh)
    except MondoError as e:
        handle_mondo_error_or_exit(e)

    emit_cache_provenance(opts, cached, store=store, explain=explain_cache)

    entries = cached.entries
    if not non_active:
        entries = [u for u in entries if u.get("enabled") is not False]
    if kind is not None:
        match kind:
            case UserKind.all:
                pass
            case UserKind.non_guests:
                entries = [u for u in entries if not u.get("is_guest")]
            case UserKind.guests:
                entries = [u for u in entries if u.get("is_guest")]
            case UserKind.non_pending:
                entries = [u for u in entries if not u.get("is_pending")]
    if emails:
        allowed = set(emails)
        entries = [u for u in entries if u.get("email") in allowed]
    if name is not None:
        needle = name.lower()
        entries = [u for u in entries if needle in (u.get("name") or "").lower()]
    if newest_first:
        entries = sorted(
            entries, key=lambda u: u.get("created_at") or "", reverse=True
        )

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


@app.command("get", epilog=epilog_for("user get"))
def get_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="User ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", "--user", help="User ID (flag form)."),
) -> None:
    """Fetch a single user by ID, including teams and account."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    user_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="user")
    data = execute(opts, USER_GET, {"ids": [user_id]})
    users = data.get("users") or []
    if not users:
        typer.secho(f"user {user_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
    opts.emit(users[0])


# ----- write commands -----


@app.command("deactivate", epilog=epilog_for("user deactivate"))
def deactivate_cmd(
    ctx: typer.Context,
    user: list[int] = typer.Option(..., "--user", help="User ID to deactivate (repeatable)."),
) -> None:
    """Deactivate one or more users."""
    from mondo.cli._cache_invalidate import invalidate_entity
    from mondo.cli._confirm import confirm_or_abort as _confirm

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    _confirm(opts, f"Deactivate {len(user)} user(s)?")
    variables = {"ids": user}
    data = execute(opts, USERS_DEACTIVATE, variables)
    invalidate_entity(opts, "users")
    opts.emit(data.get("deactivate_users") or {})


@app.command("activate", epilog=epilog_for("user activate"))
def activate_cmd(
    ctx: typer.Context,
    user: list[int] = typer.Option(..., "--user", help="User ID to reactivate (repeatable)."),
) -> None:
    """Reactivate one or more users."""
    from mondo.cli._cache_invalidate import invalidate_entity

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"ids": user}
    data = execute(opts, USERS_ACTIVATE, variables)
    invalidate_entity(opts, "users")
    opts.emit(data.get("activate_users") or {})


@app.command("update-role", epilog=epilog_for("user update-role"))
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
    from mondo.cli._cache_invalidate import invalidate_entity

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    query, response_key = _ROLE_TO_MUTATION[role]
    variables = {"ids": user}
    data = execute(opts, query, variables)
    invalidate_entity(opts, "users")
    opts.emit(data.get(response_key) or {})


@app.command("add-to-team", epilog=epilog_for("user add-to-team"))
def add_to_team_cmd(
    ctx: typer.Context,
    team_id: int = typer.Option(..., "--team", help="Team ID."),
    user: list[int] = typer.Option(..., "--user", help="User ID (repeatable)."),
) -> None:
    """Add one or more users to a team."""
    from mondo.cli._cache_invalidate import invalidate_entity

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"team": team_id, "users": user}
    data = execute(opts, ADD_USERS_TO_TEAM, variables)
    invalidate_entity(opts, "teams")
    opts.emit(data.get("add_users_to_team") or {})


@app.command("remove-from-team", epilog=epilog_for("user remove-from-team"))
def remove_from_team_cmd(
    ctx: typer.Context,
    team_id: int = typer.Option(..., "--team", help="Team ID."),
    user: list[int] = typer.Option(..., "--user", help="User ID (repeatable)."),
) -> None:
    """Remove one or more users from a team."""
    from mondo.cli._cache_invalidate import invalidate_entity

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"team": team_id, "users": user}
    data = execute(opts, REMOVE_USERS_FROM_TEAM, variables)
    invalidate_entity(opts, "teams")
    opts.emit(data.get("remove_users_from_team") or {})
