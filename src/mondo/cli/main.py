"""Root Typer app for `mondo`.

Wires global options via a callback; command groups (auth, graphql, item, column)
are mounted as sub-apps.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
from importlib import import_module
import sys
from enum import StrEnum
from typing import TYPE_CHECKING

import click
import typer
from typer.core import TyperGroup
from typer.main import get_command_from_info
from typer.main import get_group as get_typer_group
from typer.models import CommandInfo

from mondo.cli._examples import epilog_for
from mondo.cli.argv import reorder_argv
from mondo.version import __version__

if TYPE_CHECKING:
    from mondo.cli.context import GlobalOpts


class OutputFormat(StrEnum):
    table = "table"
    json = "json"
    jsonc = "jsonc"
    yaml = "yaml"
    tsv = "tsv"
    csv = "csv"
    none = "none"


_HELP_OPTION_NAMES = {"help_option_names": ["-h", "--help"]}


@dataclass(frozen=True)
class _LazyEntry:
    name: str
    module: str
    attr: str
    help_text: str | None = None
    epilog: str | None = None
    hidden: bool = False
    is_group: bool = True


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


def _group_entry(name: str, module: str, help_text: str) -> list[_LazyEntry]:
    out = [_LazyEntry(name=name, module=module, attr="app", help_text=help_text)]
    plural = _PLURAL_ALIASES.get(name)
    if plural is not None:
        out.append(
            _LazyEntry(
                name=plural,
                module=module,
                attr="app",
                help_text=help_text,
                hidden=True,
            )
        )
    return out


_TOP_LEVEL_ENTRIES: tuple[_LazyEntry, ...] = (
    *_group_entry("auth", "mondo.cli.auth", "Authenticate against monday.com."),
    *_group_entry(
        "cache",
        "mondo.cli.cache",
        "Inspect, refresh, and clear the local directory cache.",
    ),
    *_group_entry("board", "mondo.cli.board", "Create, read, update, delete monday boards."),
    *_group_entry("item", "mondo.cli.item", "Create, read, update, delete monday items."),
    *_group_entry("subitem", "mondo.cli.subitem", "Create, read, update, delete subitems."),
    *_group_entry(
        "update",
        "mondo.cli.update",
        "Post, edit, like, pin, and delete item updates (comments).",
    ),
    *_group_entry(
        "doc",
        "mondo.cli.doc",
        "Workspace-level docs (distinct from the `doc` column).",
    ),
    *_group_entry("webhook", "mondo.cli.webhook", "Manage monday webhook subscriptions."),
    *_group_entry(
        "file",
        "mondo.cli.file",
        "Upload files to item columns/updates; download assets.",
    ),
    *_group_entry("folder", "mondo.cli.folder", "Manage workspace folders."),
    *_group_entry(
        "tag",
        "mondo.cli.tag",
        "Read account-level tags; create-or-get for a board.",
    ),
    *_group_entry("favorite", "mondo.cli.favorite", "List the current user's favorites."),
    *_group_entry("activity", "mondo.cli.activity", "Read a board's activity logs."),
    *_group_entry("notify", "mondo.cli.notify", "Send monday notifications."),
    *_group_entry(
        "aggregate",
        "mondo.cli.aggregate",
        "Run SUM/COUNT/AVG aggregations on a board.",
    ),
    *_group_entry(
        "validation",
        "mondo.cli.validation",
        "Manage server-side validation rules.",
    ),
    _LazyEntry(
        name="me",
        module="mondo.cli.me",
        attr="me_command",
        help_text="Print the authenticated user (id, name, teams, account).",
        epilog=epilog_for("me"),
        is_group=False,
    ),
    _LazyEntry(
        name="account",
        module="mondo.cli.me",
        attr="account_command",
        help_text="Print the current monday account (tier, plan, products).",
        epilog=epilog_for("account"),
        is_group=False,
    ),
    *_group_entry("group", "mondo.cli.group", "Manage groups within a board."),
    *_group_entry("column", "mondo.cli.column", "Read and write monday column values."),
    *_group_entry(
        "workspace",
        "mondo.cli.workspace",
        "Manage workspaces and their members.",
    ),
    *_group_entry(
        "user",
        "mondo.cli.user",
        "List and manage users (roles, team membership, activation).",
    ),
    *_group_entry("team", "mondo.cli.team", "Manage teams and their owners."),
    *_group_entry(
        "export",
        "mondo.cli.export",
        "Export a board's data to CSV/JSON/XLSX/Markdown.",
    ),
    *_group_entry("import", "mondo.cli.import_", "Bulk-import items from CSV into a board."),
    *_group_entry(
        "complexity",
        "mondo.cli.complexity",
        "Inspect monday's per-minute complexity budget.",
    ),
    _LazyEntry(
        name="graphql",
        module="mondo.cli.graphql",
        attr="graphql_command",
        help_text="Send a raw GraphQL query/mutation to monday.com.",
        epilog=epilog_for("graphql"),
        is_group=False,
    ),
    _LazyEntry(
        name="help",
        module="mondo.cli.help",
        attr="help_command",
        help_text="Show a bundled help topic, or dump the full CLI spec as JSON.",
        is_group=False,
    ),
)
_LAZY_ENTRY_MAP: dict[str, _LazyEntry] = {entry.name: entry for entry in _TOP_LEVEL_ENTRIES}
_LAZY_ENTRY_ORDER: tuple[str, ...] = tuple(entry.name for entry in _TOP_LEVEL_ENTRIES)


def _load_lazy_entry(entry: _LazyEntry) -> click.Command:
    module = import_module(entry.module)
    if entry.is_group:
        click_command = get_typer_group(getattr(module, entry.attr))
        click_command.name = entry.name
        click_command.help = entry.help_text or click_command.help
        click_command.hidden = entry.hidden
        return click_command

    command_info = CommandInfo(
        name=entry.name,
        callback=getattr(module, entry.attr),
        context_settings=_HELP_OPTION_NAMES,
        help=entry.help_text,
        epilog=entry.epilog,
        hidden=entry.hidden,
    )
    return get_command_from_info(
        command_info,
        pretty_exceptions_short=True,
        rich_markup_mode="rich",
    )


class LazyMondoGroup(TyperGroup):
    def list_commands(self, ctx: click.Context) -> list[str]:
        return list(_LAZY_ENTRY_ORDER)

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        command = self.commands.get(cmd_name)
        if command is not None:
            return command
        entry = _LAZY_ENTRY_MAP.get(cmd_name)
        if entry is None:
            return None
        command = _load_lazy_entry(entry)
        self.commands[cmd_name] = command
        return command

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError as e:
            if self.suggest_commands and args:
                typo = args[0]
                matches = get_close_matches(typo, list(_LAZY_ENTRY_ORDER))
                if matches:
                    suggestions = ", ".join(f"{m!r}" for m in matches)
                    message = e.message.rstrip(".")
                    e.message = f"{message}. Did you mean {suggestions}?"
            raise


app = typer.Typer(
    cls=LazyMondoGroup,
    name="mondo",
    help="Power-user CLI for the monday.com GraphQL API — az/gh/gam style.",
    epilog=_ROOT_EPILOG,
    no_args_is_help=True,
    add_completion=True,
    rich_markup_mode="rich",
    context_settings=_HELP_OPTION_NAMES,
)


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
    from mondo.cli.context import GlobalOpts
    from mondo.logging_ import configure_logging

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
