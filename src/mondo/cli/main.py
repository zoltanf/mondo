"""Root Typer app for `mondo`.

Wires global options via a callback; command groups (auth, graphql, item, column)
are mounted as sub-apps.
"""

from __future__ import annotations

from enum import StrEnum

import typer

from mondo.cli.auth import app as auth_app
from mondo.cli.column import app as column_app
from mondo.cli.context import GlobalOpts
from mondo.cli.graphql import graphql_command
from mondo.cli.item import app as item_app
from mondo.logging_ import configure_logging
from mondo.version import __version__


class OutputFormat(StrEnum):
    table = "table"
    json = "json"
    jsonc = "jsonc"
    yaml = "yaml"
    tsv = "tsv"
    csv = "csv"
    none = "none"


app = typer.Typer(
    name="mondo",
    help="Power-user CLI for the monday.com GraphQL API — az/gh/gam style.",
    no_args_is_help=True,
    add_completion=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)

app.add_typer(auth_app, name="auth", help="Authenticate against monday.com.")
app.add_typer(item_app, name="item", help="Create, read, update, delete monday items.")
app.add_typer(column_app, name="column", help="Read and write monday column values.")
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
    output: OutputFormat | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output format (default: table on a TTY, json otherwise).",
        case_sensitive=False,
    ),
    query: str | None = typer.Option(
        None,
        "--query",
        "-q",
        metavar="JMESPATH",
        help="JMESPath projection applied before formatting.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Log INFO-level events to stderr."),
    debug: bool = typer.Option(
        False, "--debug", help="Log every GraphQL query and response to stderr."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip confirmation prompts on destructive actions."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="For mutating commands: print the GraphQL mutation and variables, don't send.",
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
        output=output.value if output is not None else None,
        query=query,
        yes=yes,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    app()
