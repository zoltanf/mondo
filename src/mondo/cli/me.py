"""`mondo me` and `mondo account` — convenience read commands (Phase 3i).

Both are thin wrappers: `me` returns the authenticated user (plus teams
and account); `account` traverses `me { account { ... } }` because monday
doesn't expose a root `accounts` query (§14).
"""

from __future__ import annotations

from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError
from mondo.api.queries import ACCOUNT_ONLY, ME_FULL
from mondo.cli.context import GlobalOpts


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


def me_command(ctx: typer.Context) -> None:
    """Print the authenticated user (id, name, teams, account)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    if opts.dry_run:
        opts.emit({"query": ME_FULL, "variables": {}})
        raise typer.Exit(0)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, ME_FULL, {})
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("me") or {})


def account_command(ctx: typer.Context) -> None:
    """Print the current account (tier, plan, products, active_members_count)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    if opts.dry_run:
        opts.emit({"query": ACCOUNT_ONLY, "variables": {}})
        raise typer.Exit(0)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, ACCOUNT_ONLY, {})
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    me = data.get("me") or {}
    opts.emit(me.get("account") or {})
