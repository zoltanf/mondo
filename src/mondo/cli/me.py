"""`mondo me` and `mondo account` — convenience read commands (Phase 3i).

Both are thin wrappers: `me` returns the authenticated user (plus teams
and account); `account` traverses `me { account { ... } }` because monday
doesn't expose a root `accounts` query (§14).
"""

from __future__ import annotations

import typer

from mondo.api.queries import ACCOUNT_ONLY, ME_FULL
from mondo.cli._exec import execute
from mondo.cli.context import GlobalOpts


def me_command(ctx: typer.Context) -> None:
    """Print the authenticated user (id, name, teams, account)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    data = execute(opts, ME_FULL, {})
    opts.emit(data.get("me") or {})


def account_command(ctx: typer.Context) -> None:
    """Print the current account (tier, plan, products, active_members_count)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    data = execute(opts, ACCOUNT_ONLY, {})
    me = data.get("me") or {}
    opts.emit(me.get("account") or {})
