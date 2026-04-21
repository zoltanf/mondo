"""`mondo team` command group — teams CRUD and ownership (Phase 3b).

Per monday-api.md §14:
- `teams(ids)` returns `[Team { id name picture_url users owners is_guest }]`.
  No pagination — teams are always returned in full.
- `create_team(input, options)` takes a `CreateTeamAttributesInput` object
  (`{name, subscriber_ids, parent_team_id, is_guest_team, allow_empty_team}`)
  plus a `CreateTeamOptionsInput` (`{allow_empty_team}`).
- All membership/ownership mutations return the
  `ChangeTeamsMembershipResult` partial-success shape.
"""

from __future__ import annotations

from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError
from mondo.api.queries import (
    ADD_USERS_TO_TEAM,
    ASSIGN_TEAM_OWNERS,
    REMOVE_TEAM_OWNERS,
    REMOVE_USERS_FROM_TEAM,
    TEAM_CREATE,
    TEAM_DELETE,
    TEAMS_LIST,
)
from mondo.cache.directory import get_teams as cache_get_teams
from mondo.cli._confirm import confirm_or_abort as _confirm
from mondo.cli._examples import epilog_for
from mondo.cli._filters import apply_fuzzy
from mondo.cli._resolve import resolve_required_id
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


def _invalidate_teams_cache(opts: GlobalOpts) -> None:
    if opts.dry_run:
        return
    try:
        opts.build_cache_store("teams").invalidate()
    except Exception:
        pass


# ----- read commands -----


@app.command("list", epilog=epilog_for("team list"))
def list_cmd(
    ctx: typer.Context,
    team_id: list[int] | None = typer.Option(
        None, "--id", help="Filter to specific team IDs (repeatable)."
    ),
    name_fuzzy: str | None = typer.Option(
        None, "--name-fuzzy", help="Client-side fuzzy filter on team name."
    ),
    fuzzy_threshold: int | None = typer.Option(
        None, "--fuzzy-threshold", help="Minimum fuzzy score (0-100)."
    ),
    fuzzy_score_flag: bool = typer.Option(
        False, "--fuzzy-score", help="Include `_fuzzy_score` field; sort by score desc."
    ),
    max_items: int | None = typer.Option(
        None, "--max-items", help="Stop after this many teams."
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Skip the local directory cache; fetch live."
    ),
    refresh_cache: bool = typer.Option(
        False, "--refresh-cache", help="Force-refresh the local directory cache."
    ),
) -> None:
    """List teams (optionally filtered to specific IDs or by fuzzy name)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)

    if no_cache and refresh_cache:
        typer.secho(
            "error: --no-cache and --refresh-cache are mutually exclusive.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    cache_cfg = opts.resolve_cache_config()
    use_cache = cache_cfg.enabled and not no_cache
    effective_fuzzy_threshold = (
        fuzzy_threshold if fuzzy_threshold is not None else cache_cfg.fuzzy_threshold
    )

    if use_cache and not team_id:
        # `--id` pins to specific IDs → the live query is more targeted than
        # filtering a full cached directory, so skip cache in that case.
        _list_teams_via_cache(
            opts,
            name_fuzzy=name_fuzzy,
            fuzzy_threshold=effective_fuzzy_threshold,
            fuzzy_score_flag=fuzzy_score_flag,
            max_items=max_items,
            refresh=refresh_cache,
        )
        return

    variables = {"ids": team_id or None}
    if opts.dry_run:
        _dry_run(opts, TEAMS_LIST, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, TEAMS_LIST, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    teams = data.get("teams") or []
    if name_fuzzy is not None:
        teams = apply_fuzzy(
            teams,
            name_fuzzy,
            threshold=effective_fuzzy_threshold,
            include_score=fuzzy_score_flag,
        )
    if max_items is not None:
        teams = teams[:max_items]
    opts.emit(teams)


def _list_teams_via_cache(
    opts: GlobalOpts,
    *,
    name_fuzzy: str | None,
    fuzzy_threshold: int,
    fuzzy_score_flag: bool,
    max_items: int | None,
    refresh: bool,
) -> None:
    if opts.dry_run:
        opts.emit(
            {
                "cache": "teams",
                "refresh": refresh,
                "filters": {
                    "name_fuzzy": name_fuzzy,
                    "fuzzy_threshold": fuzzy_threshold,
                    "max_items": max_items,
                },
            }
        )
        raise typer.Exit(0)

    client = _client_or_exit(opts)
    try:
        store = opts.build_cache_store("teams")
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    try:
        with client:
            cached = cache_get_teams(client, store=store, refresh=refresh)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    entries = cached.entries
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


@app.command("get", epilog=epilog_for("team get"))
def get_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Team ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", help="Team ID (flag form)."),
) -> None:
    """Fetch a single team by ID."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    team_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="team")
    variables = {"ids": [team_id]}
    if opts.dry_run:
        _dry_run(opts, TEAMS_LIST, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, TEAMS_LIST, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    teams = data.get("teams") or []
    if not teams:
        typer.secho(f"team {team_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
    opts.emit(teams[0])


# ----- write commands -----


@app.command("create", epilog=epilog_for("team create"))
def create_cmd(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Team name."),
    subscriber: list[int] | None = typer.Option(
        None, "--subscriber", help="Initial team member user ID (repeatable)."
    ),
    parent_team: int | None = typer.Option(
        None, "--parent-team", help="Parent team ID (nested teams)."
    ),
    is_guest: bool = typer.Option(False, "--guest-team", help="Create as a guest team."),
    allow_empty: bool = typer.Option(
        False, "--allow-empty", help="Permit creating a team with no members."
    ),
) -> None:
    """Create a new team."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    attrs: dict[str, Any] = {"name": name}
    if subscriber:
        attrs["subscriber_ids"] = subscriber
    if parent_team is not None:
        attrs["parent_team_id"] = parent_team
    if is_guest:
        attrs["is_guest_team"] = True
    options: dict[str, Any] | None = {"allow_empty_team": True} if allow_empty else None
    variables = {"input": attrs, "options": options}
    if opts.dry_run:
        _dry_run(opts, TEAM_CREATE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, TEAM_CREATE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    _invalidate_teams_cache(opts)
    opts.emit(data.get("create_team") or {})


@app.command("delete", epilog=epilog_for("team delete"))
def delete_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Team ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", help="Team ID (flag form)."),
    hard: bool = typer.Option(False, "--hard", help="Required for permanent deletion."),
) -> None:
    """Delete a team (permanent)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    team_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="team")
    if not hard:
        typer.secho(
            "refusing to delete without --hard.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=2)
    _confirm(opts, f"PERMANENTLY delete team {team_id}?")
    variables = {"id": team_id}
    if opts.dry_run:
        _dry_run(opts, TEAM_DELETE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, TEAM_DELETE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    _invalidate_teams_cache(opts)
    opts.emit(data.get("delete_team") or {})


@app.command("add-users", epilog=epilog_for("team add-users"))
def add_users_cmd(
    ctx: typer.Context,
    team_id: int = typer.Option(..., "--id", help="Team ID."),
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
    _invalidate_teams_cache(opts)
    opts.emit(data.get("add_users_to_team") or {})


@app.command("remove-users", epilog=epilog_for("team remove-users"))
def remove_users_cmd(
    ctx: typer.Context,
    team_id: int = typer.Option(..., "--id", help="Team ID."),
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
    _invalidate_teams_cache(opts)
    opts.emit(data.get("remove_users_from_team") or {})


@app.command("assign-owners", epilog=epilog_for("team assign-owners"))
def assign_owners_cmd(
    ctx: typer.Context,
    team_id: int = typer.Option(..., "--id", help="Team ID."),
    user: list[int] = typer.Option(..., "--user", help="User ID to promote to owner (repeatable)."),
) -> None:
    """Promote one or more users to team owner."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"team": team_id, "users": user}
    if opts.dry_run:
        _dry_run(opts, ASSIGN_TEAM_OWNERS, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, ASSIGN_TEAM_OWNERS, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    _invalidate_teams_cache(opts)
    opts.emit(data.get("assign_team_owners") or {})


@app.command("remove-owners", epilog=epilog_for("team remove-owners"))
def remove_owners_cmd(
    ctx: typer.Context,
    team_id: int = typer.Option(..., "--id", help="Team ID."),
    user: list[int] = typer.Option(
        ..., "--user", help="User ID to demote from owner (repeatable)."
    ),
) -> None:
    """Demote one or more users from team owner."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"team": team_id, "users": user}
    if opts.dry_run:
        _dry_run(opts, REMOVE_TEAM_OWNERS, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, REMOVE_TEAM_OWNERS, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    _invalidate_teams_cache(opts)
    opts.emit(data.get("remove_team_owners") or {})
