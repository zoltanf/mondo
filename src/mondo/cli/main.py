"""Root Typer app for `mondo`.

Phase 1a: entry point with `--version` and `--help` only.
Command groups (auth, item, column, graphql) are wired in later sub-phases.
"""

from __future__ import annotations

import typer

from mondo.version import __version__

app = typer.Typer(
    name="mondo",
    help="Power-user CLI for the monday.com GraphQL API — az/gh/gam style.",
    no_args_is_help=True,
    add_completion=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"mondo {__version__}")
        raise typer.Exit(0)


@app.callback()
def _root(
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


if __name__ == "__main__":
    app()
