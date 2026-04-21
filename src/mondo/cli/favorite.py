"""`mondo favorite` — current-user favorites (Phase 3h, read-only).

monday-api.md §14 mentions mutations to add/remove favorites but their
SDL-confirmed spellings have shifted across API versions. mondo ships
the read surface first; add/remove are queued for a follow-up once we
verify against live introspection.
"""

from __future__ import annotations

import typer

from mondo.api.queries import FAVORITES_LIST
from mondo.cli._examples import epilog_for
from mondo.cli._exec import execute
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.command("list", epilog=epilog_for("favorite list"))
def list_cmd(ctx: typer.Context) -> None:
    """List the current user's favorites (boards, dashboards, workspaces, docs)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    data = execute(opts, FAVORITES_LIST, {})
    opts.emit(data.get("favorites") or [])
