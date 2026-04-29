"""Help-rendering hooks that surface root global options on every subcommand.

Click/Typer's help renderer only lists options declared directly on the command
being rendered, so the root callback's globals (`--profile`, `--debug`, etc.)
disappear from `mondo skill --help`, `mondo board list --help`, and so on —
even though argv-reorder makes them functionally available everywhere.

`MondoGroup` and `MondoCommand` plug into Typer's rich help pipeline by
temporarily appending tagged clones of the root globals (`rich_help_panel
= "Global Options"`) to `self.params` for the duration of `format_help`.
Typer groups options into panels by that attribute, so the globals render in
their own panel below the command's own options.

`patch_help_classes` walks an already-instantiated Click command tree and
re-classes nodes to our subclasses; it's used by the lazy loader in
`mondo.cli.main` so we don't have to touch every sub-app file.
"""

from __future__ import annotations

import copy

import click
import typer.core

_GLOBAL_PANEL_TITLE = "Global Options"
_PANEL_ATTR = "rich_help_panel"

# Root-app params that aren't true globals: `--help` is context-sensitive and
# `--install-completion`/`--show-completion` only work at the root by nature.
# Mirror the carve-outs in `mondo.cli.argv`.
_ROOT_PARAM_SKIP: frozenset[str] = frozenset(
    {"help", "install_completion", "show_completion"}
)


def is_global_param(param: click.Parameter) -> bool:
    """True if `param` (from the root command) is a true global option."""
    if not isinstance(param, click.Option):
        return False
    return param.name not in _ROOT_PARAM_SKIP


def _global_option_clones(ctx: click.Context) -> list[click.Option]:
    """Return panel-tagged copies of the root command's options for this ctx."""
    root_cmd = ctx.find_root().command
    out: list[click.Option] = []
    for param in root_cmd.params:
        if not is_global_param(param):
            continue
        clone = copy.copy(param)
        setattr(clone, _PANEL_ATTR, _GLOBAL_PANEL_TITLE)
        out.append(clone)
    return out


def _format_help_with_globals(
    cmd: click.Command,
    ctx: click.Context,
    formatter: click.HelpFormatter,
    base_format_help,
) -> None:
    if ctx.parent is None:
        base_format_help(ctx, formatter)
        return
    extras = _global_option_clones(ctx)
    original = cmd.params
    cmd.params = list(original) + extras
    try:
        base_format_help(ctx, formatter)
    finally:
        cmd.params = original


class MondoGroup(typer.core.TyperGroup):
    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        _format_help_with_globals(self, ctx, formatter, super().format_help)


class MondoCommand(typer.core.TyperCommand):
    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        _format_help_with_globals(self, ctx, formatter, super().format_help)


def patch_help_classes(cmd: click.Command) -> None:
    """Reclass `cmd` (and any descendants) to use our help-injecting subclasses.

    Class reassignment is safe because `MondoGroup`/`MondoCommand` are pure
    behavioral subclasses — no extra `__init__` state, no slot changes.
    """
    if isinstance(cmd, click.Group):
        if isinstance(cmd, typer.core.TyperGroup) and not isinstance(cmd, MondoGroup):
            cmd.__class__ = MondoGroup
        for child in cmd.commands.values():
            patch_help_classes(child)
    else:
        if isinstance(cmd, typer.core.TyperCommand) and not isinstance(cmd, MondoCommand):
            cmd.__class__ = MondoCommand
