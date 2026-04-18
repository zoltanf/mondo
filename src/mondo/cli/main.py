"""Root Typer app for `mondo`.

Wires global options via a callback; command groups (auth, graphql, item, column)
are mounted as sub-apps.
"""

from __future__ import annotations

import typer

from mondo.cli.auth import app as auth_app
from mondo.cli.context import GlobalOpts
from mondo.cli.graphql import graphql_command
from mondo.logging_ import configure_logging
from mondo.version import __version__

app = typer.Typer(
    name="mondo",
    help="Power-user CLI for the monday.com GraphQL API — az/gh/gam style.",
    no_args_is_help=True,
    add_completion=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)

app.add_typer(auth_app, name="auth", help="Authenticate against monday.com.")
app.command(
    name="graphql",
    help="Send a raw GraphQL query/mutation to monday.com.",
)(graphql_command)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"mondo {__version__}")
        raise typer.Exit(0)


@app.callback()
def _root(
    ctx: typer.Context,
    profile: str | None = typer.Option(
        None,
        "--profile",
        envvar="MONDO_PROFILE",
        help="Configuration profile to use (from config.yaml).",
    ),
    api_token: str | None = typer.Option(
        None,
        "--api-token",
        help="Override the API token for this invocation. "
        "Also read from MONDAY_API_TOKEN (with lower precedence than this flag).",
    ),
    api_version: str | None = typer.Option(
        None,
        "--api-version",
        envvar="MONDAY_API_VERSION",
        help="monday.com API version header (e.g. 2026-01).",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Log INFO-level events to stderr."),
    debug: bool = typer.Option(
        False, "--debug", help="Log every GraphQL query and response to stderr."
    ),
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show the mondo version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Global options available on every command."""
    configure_logging(verbose=verbose, debug=debug)
    ctx.obj = GlobalOpts(
        profile_name=profile,
        flag_token=api_token,
        flag_api_version=api_version,
        verbose=verbose,
        debug=debug,
    )


if __name__ == "__main__":
    app()
