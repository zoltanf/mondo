"""Root Typer app for `mondo`.

Wires global options via a callback; command groups (auth, graphql, item, column)
are mounted as sub-apps.
"""

from __future__ import annotations

import sys
from enum import StrEnum

import typer

from mondo.cli._examples import epilog_for
from mondo.cli.activity import app as activity_app
from mondo.cli.aggregate import app as aggregate_app
from mondo.cli.argv import reorder_argv
from mondo.cli.auth import app as auth_app
from mondo.cli.board import app as board_app
from mondo.cli.cache import app as cache_app
from mondo.cli.column import app as column_app
from mondo.cli.complexity import app as complexity_app
from mondo.cli.context import GlobalOpts
from mondo.cli.doc import app as doc_app
from mondo.cli.export import app as export_app
from mondo.cli.favorite import app as favorite_app
from mondo.cli.file import app as file_app
from mondo.cli.folder import app as folder_app
from mondo.cli.graphql import graphql_command
from mondo.cli.group import app as group_app
from mondo.cli.help import help_command
from mondo.cli.import_ import app as import_app
from mondo.cli.item import app as item_app
from mondo.cli.me import account_command, me_command
from mondo.cli.notify import app as notify_app
from mondo.cli.subitem import app as subitem_app
from mondo.cli.tag import app as tag_app
from mondo.cli.team import app as team_app
from mondo.cli.update import app as update_app
from mondo.cli.user import app as user_app
from mondo.cli.validation import app as validation_app
from mondo.cli.webhook import app as webhook_app
from mondo.cli.workspace import app as workspace_app
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


_ROOT_EPILOG = "\n\n".join(
    [
        "[bold]Getting started[/bold]",
        "[dim]# Authenticate (stores token in the OS keyring)[/dim]",
        "  $ mondo auth login",
        "[dim]# Confirm the token works[/dim]",
        "  $ mondo auth status",
        "\u200b",
        "[bold]Built-in help[/bold]",
        "[dim]# List every agent-facing topic shipped inside the binary[/dim]",
        "  $ mondo help",
        "[dim]# Read a topic (e.g. column-value codecs, exit codes, rate limits)[/dim]",
        "  $ mondo help codecs",
        "[dim]# Emit the full command tree as JSON — the contract for agents[/dim]",
        "  $ mondo help --dump-spec -o json",
        "\u200b",
        "[bold]More[/bold]",
        "[dim]# Per-command examples live in each subcommand's --help[/dim]",
        "  $ mondo item create --help",
        "[dim]# Read the AI/agent onboarding guide[/dim]",
        "  $ mondo help agent-workflow",
    ]
)

app = typer.Typer(
    name="mondo",
    help="Power-user CLI for the monday.com GraphQL API — az/gh/gam style.",
    epilog=_ROOT_EPILOG,
    no_args_is_help=True,
    add_completion=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)

_PLURAL_ALIASES: dict[str, str] = {
    "board": "boards",
    "item": "items",
    "subitem": "subitems",
    "update": "updates",
    "doc": "docs",
    "webhook": "webhooks",
    "file": "files",
    "folder": "folders",
    "tag": "tags",
    "favorite": "favorites",
    "activity": "activities",
    "validation": "validations",
    "group": "groups",
    "column": "columns",
    "workspace": "workspaces",
    "user": "users",
    "team": "teams",
}


def _add_group(subapp: typer.Typer, *, name: str, help_text: str) -> None:
    """Register a top-level group and an optional hidden plural alias."""
    app.add_typer(subapp, name=name, help=help_text)
    plural = _PLURAL_ALIASES.get(name)
    if plural is not None:
        app.add_typer(subapp, name=plural, help=help_text, hidden=True)


_add_group(auth_app, name="auth", help_text="Authenticate against monday.com.")
_add_group(
    cache_app,
    name="cache",
    help_text="Inspect, refresh, and clear the local directory cache.",
)
_add_group(board_app, name="board", help_text="Create, read, update, delete monday boards.")
_add_group(item_app, name="item", help_text="Create, read, update, delete monday items.")
_add_group(subitem_app, name="subitem", help_text="Create, read, update, delete subitems.")
_add_group(
    update_app,
    name="update",
    help_text="Post, edit, like, pin, and delete item updates (comments).",
)
_add_group(
    doc_app,
    name="doc",
    help_text="Workspace-level docs (distinct from the `doc` column).",
)
_add_group(webhook_app, name="webhook", help_text="Manage monday webhook subscriptions.")
_add_group(
    file_app,
    name="file",
    help_text="Upload files to item columns/updates; download assets.",
)
_add_group(folder_app, name="folder", help_text="Manage workspace folders.")
_add_group(tag_app, name="tag", help_text="Read account-level tags; create-or-get for a board.")
_add_group(favorite_app, name="favorite", help_text="List the current user's favorites.")
_add_group(activity_app, name="activity", help_text="Read a board's activity logs.")
_add_group(notify_app, name="notify", help_text="Send monday notifications.")
_add_group(
    aggregate_app,
    name="aggregate",
    help_text="Run SUM/COUNT/AVG aggregations on a board.",
)
_add_group(validation_app, name="validation", help_text="Manage server-side validation rules.")
app.command(
    name="me",
    help="Print the authenticated user (id, name, teams, account).",
    epilog=epilog_for("me"),
)(me_command)
app.command(
    name="account",
    help="Print the current monday account (tier, plan, products).",
    epilog=epilog_for("account"),
)(account_command)
_add_group(group_app, name="group", help_text="Manage groups within a board.")
_add_group(column_app, name="column", help_text="Read and write monday column values.")
_add_group(
    workspace_app, name="workspace", help_text="Manage workspaces and their members."
)
_add_group(
    user_app,
    name="user",
    help_text="List and manage users (roles, team membership, activation).",
)
_add_group(team_app, name="team", help_text="Manage teams and their owners.")
_add_group(
    export_app,
    name="export",
    help_text="Export a board's data to CSV/JSON/XLSX/Markdown.",
)
_add_group(import_app, name="import", help_text="Bulk-import items from CSV into a board.")
_add_group(
    complexity_app,
    name="complexity",
    help_text="Inspect monday's per-minute complexity budget.",
)
app.command(
    name="graphql",
    help="Send a raw GraphQL query/mutation to monday.com.",
    epilog=epilog_for("graphql"),
)(graphql_command)
app.command(
    name="help",
    help="Show a bundled help topic, or dump the full CLI spec as JSON.",
)(help_command)


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


def main() -> None:
    """Console-script entry point.

    Reorders argv so root-level global flags work anywhere on the command line
    (az/gh/gam UX), then hands off to Typer.
    """
    args = reorder_argv(sys.argv[1:])
    app(args=args)


if __name__ == "__main__":
    main()
