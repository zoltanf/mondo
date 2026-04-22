"""Shared confirmation helper for destructive commands.

All `mondo <x> delete|archive|clear` subcommands gate on this. Centralized so
the abort message stays consistent, and so a non-interactive run (piped or
redirected stdin with no input) prints a hint pointing at `--yes` instead of
a silent exit 1.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import click
import typer

if TYPE_CHECKING:
    from mondo.cli.context import GlobalOpts


def confirm_or_abort(opts: GlobalOpts, prompt: str) -> None:
    """Ask for confirmation. Honors `--yes`; prints a useful hint on non-TTY abort."""
    if opts.yes:
        return
    try:
        ok = typer.confirm(prompt, default=False)
    except click.Abort:
        # stdin was closed/EOF'd before an answer was given. On a non-TTY that
        # almost always means a script forgot `--yes`; say so explicitly.
        if not sys.stdin.isatty():
            typer.secho(
                "aborted: confirmation required. "
                "Pass --yes to skip this prompt in non-interactive contexts.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(1) from None
        raise
    if not ok:
        typer.echo("aborted.")
        raise typer.Exit(1)
