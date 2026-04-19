"""`mondo favorite` — current-user favorites (Phase 3h, read-only).

monday-api.md §14 mentions mutations to add/remove favorites but their
SDL-confirmed spellings have shifted across API versions. mondo ships
the read surface first; add/remove are queued for a follow-up once we
verify against live introspection.
"""

from __future__ import annotations

from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError
from mondo.api.queries import FAVORITES_LIST
from mondo.cli._examples import epilog_for
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


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


@app.command("list", epilog=epilog_for("favorite list"))
def list_cmd(ctx: typer.Context) -> None:
    """List the current user's favorites (boards, dashboards, workspaces, docs)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    if opts.dry_run:
        opts.emit({"query": FAVORITES_LIST, "variables": {}})
        raise typer.Exit(0)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, FAVORITES_LIST, {})
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("favorites") or [])
