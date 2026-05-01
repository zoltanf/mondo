"""`mondo auth` command group — login, logout, status, whoami."""

from __future__ import annotations

import getpass
import sys

import typer

from mondo.api.auth import ENV_VAR, KEYRING_SERVICE
from mondo.api.errors import AuthError, MondoError
from mondo.api.queries import ME_QUERY
from mondo.cli._examples import epilog_for
from mondo.cli._exec import handle_mondo_error_or_exit
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.command(epilog=epilog_for("auth whoami"))
def whoami(ctx: typer.Context) -> None:
    """Print the currently authenticated user and account."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    try:
        client = opts.build_client()
    except MondoError as e:
        handle_mondo_error_or_exit(e)

    try:
        with client:
            result = client.execute(ME_QUERY)
    except MondoError as e:
        handle_mondo_error_or_exit(e)

    me = (result.get("data") or {}).get("me") or {}
    opts.emit(me)


@app.command(epilog=epilog_for("auth status"))
def status(ctx: typer.Context) -> None:
    """Show token source, profile, API version, and the authenticated identity."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)

    try:
        resolved = opts.resolve_token()
    except AuthError as e:
        typer.secho(f"not logged in: {e}", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    try:
        client = opts.build_client()
    except MondoError as e:
        typer.secho(f"\n[token present but client failed] {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    try:
        with client:
            result = client.execute(ME_QUERY)
    except MondoError as e:
        typer.secho(f"\nerror: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    me = (result.get("data") or {}).get("me") or {}
    account = me.get("account") or {}

    payload = {
        "profile": resolved.profile_name or "(default)",
        "token_source": resolved.source.describe(),
        "keyring_key": resolved.keyring_key,
        "config_file": str(resolved.config_path) if resolved.config_path else None,
        "api_version": client.api_version,
        "user_id": me.get("id"),
        "user_name": me.get("name"),
        "user_email": me.get("email"),
        "is_admin": me.get("is_admin"),
        "account_id": account.get("id"),
        "account_name": account.get("name"),
        "account_slug": account.get("slug"),
        "account_tier": account.get("tier"),
    }
    opts.emit(payload)


@app.command(epilog=epilog_for("auth login"))
def login(
    ctx: typer.Context,
    token: str | None = typer.Option(
        None,
        "--token",
        help="Provide the token non-interactively (avoid — ends up in shell history).",
    ),
) -> None:
    """Store an API token for this profile, preferring the OS keyring."""
    import keyring

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


@app.command(epilog=epilog_for("auth logout"))
def logout(ctx: typer.Context) -> None:
    """Remove the stored token for this profile from the keyring."""
    import keyring

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
