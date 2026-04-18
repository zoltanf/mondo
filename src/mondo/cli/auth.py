"""`mondo auth` command group — login, logout, status, whoami."""

from __future__ import annotations

import getpass
import json
import sys
from typing import Any

import keyring
import typer
from rich.console import Console
from rich.table import Table

from mondo.api.auth import ENV_VAR
from mondo.api.errors import AuthError, MondoError
from mondo.cli.context import GlobalOpts

KEYRING_SERVICE = "mondo"

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


_ME_QUERY = """
query {
  me {
    id
    name
    email
    is_admin
    account { id name slug tier }
  }
}
""".strip()


def _format_me(data: dict[str, Any]) -> str:
    """Fallback text format for `me` data."""
    me = data.get("me") or {}
    acct = me.get("account") or {}
    lines = [
        f"id:      {me.get('id')}",
        f"name:    {me.get('name')}",
        f"email:   {me.get('email')}",
        f"admin:   {me.get('is_admin')}",
        f"account: {acct.get('name')} ({acct.get('slug')}, tier={acct.get('tier')})",
    ]
    return "\n".join(lines)


@app.command()
def whoami(ctx: typer.Context) -> None:
    """Print the currently authenticated user and account."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    try:
        client = opts.build_client()
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    try:
        with client:
            result = client.execute(_ME_QUERY)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    data = result.get("data") or {}
    if sys.stdout.isatty():
        typer.echo(_format_me(data))
    else:
        typer.echo(json.dumps(data, indent=2))


@app.command()
def status(ctx: typer.Context) -> None:
    """Show token source, profile, API version, and the authenticated identity."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    console = Console()

    try:
        resolved = opts.resolve_token()
    except AuthError as e:
        typer.secho(f"not logged in: {e}", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="cyan")
    table.add_column()
    table.add_row("profile", resolved.profile_name or "(default)")
    table.add_row("token source", resolved.source.describe())
    if resolved.keyring_key:
        table.add_row("keyring key", resolved.keyring_key)
    if resolved.config_path:
        table.add_row("config file", str(resolved.config_path))
    console.print(table)

    try:
        client = opts.build_client()
    except MondoError as e:
        typer.secho(f"\n[token present but client failed] {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    try:
        with client:
            result = client.execute(_ME_QUERY)
    except MondoError as e:
        typer.secho(f"\nerror: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    data = result.get("data") or {}
    console.print()
    console.print(_format_me(data))


@app.command()
def login(
    ctx: typer.Context,
    token: str | None = typer.Option(
        None,
        "--token",
        help="Provide the token non-interactively (avoid — ends up in shell history).",
    ),
) -> None:
    """Store an API token for this profile, preferring the OS keyring."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    username = opts.profile_name or "default"

    if token is None:
        if not sys.stdin.isatty():
            typer.secho(
                "error: login requires a TTY (or pass --token non-interactively).",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=2)
        typer.echo(
            f"Paste your monday.com personal API token for profile {username!r}.\n"
            "Profile → Developers → API Token → Show."
        )
        token = getpass.getpass("token: ").strip()
        if not token:
            typer.secho("error: empty token", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)

    try:
        keyring.set_password(KEYRING_SERVICE, username, token)
    except keyring.errors.KeyringError as e:
        typer.secho(
            f"error: keyring unavailable ({e}). Set {ENV_VAR} in your environment instead.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1) from e

    typer.secho(
        f"stored token in keyring ({KEYRING_SERVICE}:{username}). "
        f"Reference it from config.yaml as api_token_keyring: '{KEYRING_SERVICE}:{username}'.",
        fg=typer.colors.GREEN,
    )


@app.command()
def logout(ctx: typer.Context) -> None:
    """Remove the stored token for this profile from the keyring."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    username = opts.profile_name or "default"

    try:
        existing = keyring.get_password(KEYRING_SERVICE, username)
    except keyring.errors.KeyringError as e:
        typer.secho(f"error: keyring unavailable ({e})", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    if existing is None:
        typer.echo(f"no token stored for {KEYRING_SERVICE}:{username}")
        return

    try:
        keyring.delete_password(KEYRING_SERVICE, username)
    except keyring.errors.KeyringError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    typer.secho(
        f"removed token from keyring ({KEYRING_SERVICE}:{username}).",
        fg=typer.colors.GREEN,
    )
