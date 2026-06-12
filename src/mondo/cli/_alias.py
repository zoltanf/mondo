"""Hidden `--<entity>-id` aliases for canonical entity flags (issue #9).

Agents coming from `az`/`gh` (or mirroring GraphQL field names) guess
`--item-id` / `--column-id` / `--board-id` / … and get rejected with
`No such option`, costing a failed round-trip per guess — invisible when
stderr is suppressed. 414a180 fixed this for `--board-id` on the list
commands with per-command hidden Typer params; this module generalizes
that to every command, without touching each signature.

`rewrite_id_aliases` runs in `MondoCommand.parse_args` (the class every
leaf command is re-classed to — see `_help_format.patch_help_classes`).
It rewrites an alias token to its canonical flag only when the command
actually declares the canonical option and doesn't declare the alias
itself. Because the alias never exists as a real parameter, it stays
out of `--help` and `--dump-spec` for free, and commands without the
canonical flag still produce the original `No such option '--item-id'`
error (with the `_errors.FLAG_ALIAS_HINTS` suggestion).

When both the canonical flag and the alias are passed, the canonical
wins: alias occurrences (and their values) are dropped — the same
semantics the old `coalesce_board_flag` helper had.
"""

from __future__ import annotations

import click

# Alias -> canonical long option. Extend with one line per new alias.
ID_ALIAS_MAP: dict[str, str] = {
    "--item-id": "--item",
    "--column-id": "--column",
    "--group-id": "--group",
    "--workspace-id": "--workspace",
    "--board-id": "--board",
}


def _declared_opts(cmd: click.Command) -> set[str]:
    """Every long/short option name declared on `cmd` (incl. secondary names)."""
    opts: set[str] = set()
    for param in cmd.params:
        opts.update(getattr(param, "opts", []))
        opts.update(getattr(param, "secondary_opts", []))
    return opts


def rewrite_id_aliases(cmd: click.Command, args: list[str]) -> list[str]:
    """Return `args` with applicable `--<entity>-id` tokens rewritten.

    Handles both `--item-id 5` and `--item-id=5` forms. No-op unless an
    alias token is present, the command declares the canonical option,
    and the command doesn't declare the alias as a real flag.
    """
    if not any(arg.partition("=")[0] in ID_ALIAS_MAP for arg in args):
        return args

    declared = _declared_opts(cmd)
    present = {a.partition("=")[0] for a in args}
    out: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        name, eq, value = token.partition("=")
        canonical = ID_ALIAS_MAP.get(name)
        if canonical is None or canonical not in declared or name in declared:
            out.append(token)
            i += 1
            continue
        if canonical in present:
            # Canonical wins: drop the alias and its value.
            i += 1 if eq else 2
            continue
        out.append(f"{canonical}={value}" if eq else canonical)
        i += 1
    return out
