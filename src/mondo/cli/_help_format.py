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
from collections.abc import Callable
from typing import cast

import click
import typer.core

from mondo.cli._alias import rewrite_id_aliases

_GLOBAL_PANEL_TITLE = "Global Options"
_OUTPUT_PANEL_TITLE = "Output / Query"
_PANEL_ATTR = "rich_help_panel"

_OUTPUT_PARAM_NAMES: frozenset[str] = frozenset({"output", "query", "fields"})

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


def _panel_for(param: click.Parameter) -> str:
    """Choose which Rich help panel a cloned global lands in."""
    if param.name in _OUTPUT_PARAM_NAMES:
        return _OUTPUT_PANEL_TITLE
    return _GLOBAL_PANEL_TITLE


def _global_option_clones(ctx: click.Context) -> list[click.Option]:
    """Return panel-tagged copies of the root command's options for this ctx."""
    root_cmd = ctx.find_root().command
    _assert_output_params_exist(root_cmd)
    out: list[click.Option] = []
    for param in root_cmd.params:
        if not is_global_param(param):
            continue
        clone = cast(click.Option, copy.copy(param))
        setattr(clone, _PANEL_ATTR, _panel_for(param))
        out.append(clone)
    return out


def _assert_output_params_exist(root_cmd: click.Command) -> None:
    """Fail loudly if `_OUTPUT_PARAM_NAMES` drifts from the root's option names.

    Otherwise the Output / Query panel silently empties out when a flag is
    renamed in `main.py`, with no test signal until someone runs `--help`.
    """
    declared = {
        p.name
        for p in root_cmd.params
        if isinstance(p, click.Option) and p.name is not None
    }
    missing = _OUTPUT_PARAM_NAMES - declared
    if missing:
        raise AssertionError(
            f"_OUTPUT_PARAM_NAMES references param(s) not on the root command: "
            f"{sorted(missing)}. Root declares: {sorted(declared)}."
        )


def _format_help_with_globals(
    cmd: click.Command,
    ctx: click.Context,
    formatter: click.HelpFormatter,
    base_format_help: Callable[[click.Context, click.HelpFormatter], None],
) -> None:
    if ctx.parent is None:
        base_format_help(ctx, formatter)
        return
    extras = _global_option_clones(ctx)
    original = cmd.params
    cmd.params = [*original, *extras]
    try:
        base_format_help(ctx, formatter)
    finally:
        cmd.params = original


class MondoGroup(typer.core.TyperGroup):
    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        _format_help_with_globals(self, ctx, formatter, super().format_help)

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        """Append "Available subcommands: a, b, c" on No such command errors.

        Click's default fuzzy-match suggestion (`Did you mean 'duplicate'?`)
        is misleading across namespaces — e.g. `mondo item update` suggests
        a sibling under `item` when the user actually wanted `update create`.
        Listing every sibling subcommand lets the agent recover regardless
        of how close their typo was.
        """
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError as exc:
            if args:
                from difflib import get_close_matches

                siblings = sorted(self.list_commands(ctx))
                if siblings:
                    close = get_close_matches(args[0], siblings)
                    parts = [exc.message.rstrip(".")]
                    if close:
                        parts.append(
                            "Did you mean "
                            + ", ".join(repr(m) for m in close) + "?"
                        )
                    parts.append("Available subcommands: " + ", ".join(siblings) + ".")
                    exc.message = " ".join(parts)
            raise


class MondoCommand(typer.core.TyperCommand):
    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        _format_help_with_globals(self, ctx, formatter, super().format_help)

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        """Accept hidden `--<entity>-id` aliases for canonical entity flags.

        See `mondo.cli._alias` — rewrites e.g. `--item-id` to `--item`
        when this command declares the canonical option, so az/gh-style
        guesses don't cost a failed round-trip.
        """
        return super().parse_args(ctx, rewrite_id_aliases(self, args))


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
