"""`mondo help` — bundled topics + machine-readable command spec.

Two jobs:

1. Deliver prose that used to live only in the README. Topic files are shipped
   as package resources under `mondo.help`, so a standalone binary still has
   them.

2. Emit a full JSON spec of the command tree (commands, flags, types, required-
   ness, docstrings, epilog examples, exit codes). An agent can ingest this
   once and plan many invocations without parsing terminal help text.
"""

from __future__ import annotations

from importlib import resources
from typing import Any

import click
import typer
from rich.console import Console
from rich.markdown import Markdown

from mondo.cli._examples import EXAMPLES

_TOPIC_PACKAGE = "mondo.help"


def _list_topics() -> list[str]:
    """Return the topic slugs available in the bundled `mondo.help` package."""
    out: list[str] = []
    for entry in resources.files(_TOPIC_PACKAGE).iterdir():
        if entry.is_file() and entry.name.endswith(".md"):
            out.append(entry.name.removesuffix(".md"))
    return sorted(out)


def _read_topic(slug: str) -> str | None:
    """Return the raw markdown for a bundled topic, or None if not found."""
    resource = resources.files(_TOPIC_PACKAGE).joinpath(f"{slug}.md")
    if not resource.is_file():
        return None
    return resource.read_text(encoding="utf-8")


def _print_topic_list() -> None:
    """Print the available topics as a table on stdout."""
    topics = _list_topics()
    if not topics:
        typer.echo("(no help topics bundled)", err=True)
        raise typer.Exit(1)
    typer.echo("Available help topics:")
    typer.echo("")
    for slug in topics:
        typer.echo(f"  mondo help {slug}")
    typer.echo("")
    typer.echo("Run `mondo help --dump-spec -o json` for the full machine-readable spec.")


def _param_to_dict(param: click.Parameter) -> dict[str, Any]:
    """Serialize one Click parameter (option or argument) as JSON-ready data."""
    entry: dict[str, Any] = {
        "name": param.name,
        "param_type": "argument" if isinstance(param, click.Argument) else "option",
        "required": bool(getattr(param, "required", False)),
        "multiple": bool(getattr(param, "multiple", False)),
        "is_flag": bool(getattr(param, "is_flag", False)),
        "default": None if callable(param.default) else param.default,
    }
    if isinstance(param, click.Option):
        entry["flags"] = list(param.opts) + list(param.secondary_opts)
        entry["help"] = param.help
        entry["envvar"] = param.envvar
        entry["metavar"] = param.metavar
    type_name = getattr(param.type, "name", None) or type(param.type).__name__
    entry["type"] = type_name
    if isinstance(param.type, click.Choice):
        entry["choices"] = list(param.type.choices)
    return entry


def _walk(cmd: click.Command, path: list[str]) -> dict[str, Any]:
    """Recursively serialize a Click command tree."""
    full_path = " ".join(path)
    # Examples are keyed on the path relative to the root (no "mondo" prefix)
    # so the registry stays app-name-agnostic.
    example_key = " ".join(path[1:]) if len(path) > 1 else ""
    node: dict[str, Any] = {
        "name": cmd.name,
        "path": full_path,
        "help": cmd.help or "",
        "short_help": cmd.short_help or "",
        "epilog": cmd.epilog or "",
        "hidden": bool(getattr(cmd, "hidden", False)),
        "deprecated": bool(getattr(cmd, "deprecated", False)),
        "params": [_param_to_dict(p) for p in cmd.params if p.name != "help"],
        "examples": [
            {"description": ex.description, "command": ex.command}
            for ex in EXAMPLES.get(example_key, [])
        ],
    }
    if isinstance(cmd, click.Group):
        ctx = click.Context(cmd)
        children: list[dict[str, Any]] = []
        for child_name in cmd.list_commands(ctx):
            child = cmd.get_command(ctx, child_name)
            if child is None or bool(getattr(child, "hidden", False)):
                continue
            children.append(_walk(child, [*path, child_name]))
        node["commands"] = children
    return node


def _dump_spec(root: typer.Typer) -> dict[str, Any]:
    """Produce the full JSON spec rooted at the given Typer app."""
    click_app = typer.main.get_command(root)
    tree = _walk(click_app, [click_app.name or "mondo"])
    return {
        "cli": "mondo",
        "root": tree,
        "exit_codes": {
            "0": "success",
            "1": "generic error",
            "2": "usage error",
            "3": "auth error",
            "4": "rate / complexity exhausted after retries",
            "5": "validation error",
            "6": "not found",
            "7": "network / transport error",
        },
        "output_formats": ["table", "json", "jsonc", "yaml", "tsv", "csv", "none"],
    }


def help_command(
    topic: str | None = typer.Argument(
        None,
        metavar="[TOPIC]",
        help="Topic slug to display. Omit to list all topics.",
    ),
    dump_spec: bool = typer.Option(
        False,
        "--dump-spec",
        help="Emit the full command tree as JSON (honors `-o json|jsonc|yaml`).",
    ),
) -> None:
    """Show a bundled help topic, or the full machine-readable CLI spec.

    Topics are markdown documents shipped with the binary (no internet or
    source checkout needed). Run `mondo help` with no args to see what's
    available.
    """
    # Local import avoids a module-level circular import with main.py
    from mondo.cli.context import GlobalOpts
    from mondo.cli.main import app as root_app

    ctx = click.get_current_context()
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)

    if dump_spec:
        opts.emit(_dump_spec(root_app))
        return

    if topic is None:
        _print_topic_list()
        return

    body = _read_topic(topic)
    if body is None:
        available = ", ".join(_list_topics()) or "(none)"
        typer.secho(
            f"unknown help topic: {topic!r}. Available: {available}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=6)

    import sys

    if sys.stdout.isatty():
        Console().print(Markdown(body))
    else:
        typer.echo(body)
