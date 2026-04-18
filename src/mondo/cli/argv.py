"""Pre-parse argv to move root-level global flags in front of subcommands.

Typer inherits Click's strict left-to-right option parsing: a flag defined on
the root group is only recognized before the first subcommand token. Users
coming from `az`/`gh`/`gam` expect flags to work *anywhere* on the line
(`mondo item list --board 42 -o table`), so we normalize the ordering.
"""

from __future__ import annotations

# Flags owned by the root callback in mondo.cli.main.
# We deliberately do NOT include `--help` / `-h` (context-sensitive) or
# `--install-completion` / `--show-completion` (root-only by nature).
_GLOBAL_FLAGS_WITH_VALUE: frozenset[str] = frozenset(
    {
        "--profile",
        "--api-token",
        "--api-version",
        "--output",
        "-o",
        "--query",
        "-q",
    }
)

_GLOBAL_BOOLEAN_FLAGS: frozenset[str] = frozenset(
    {
        "--verbose",
        "-v",
        "--debug",
        "--yes",
        "-y",
        "--dry-run",
        "--version",
        "-V",
    }
)


def reorder_argv(argv: list[str]) -> list[str]:
    """Return `argv` with recognized global flags moved to the front.

    - `--foo=bar` equals-form is treated as a single token.
    - Boolean flags move alone.
    - Value-taking flags move with their value (next token).
    - Unknown flags + positional args pass through in original order.
    """
    moved: list[str] = []
    kept: list[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]

        # equals-form: `--output=yaml`, `--profile=work`, etc.
        if "=" in token and token.startswith("-"):
            name = token.split("=", 1)[0]
            if name in _GLOBAL_FLAGS_WITH_VALUE:
                moved.append(token)
                i += 1
                continue

        if token in _GLOBAL_FLAGS_WITH_VALUE:
            if i + 1 < len(argv):
                moved.extend([token, argv[i + 1]])
                i += 2
            else:
                # Malformed; leave as-is for Click to complain about.
                moved.append(token)
                i += 1
            continue

        if token in _GLOBAL_BOOLEAN_FLAGS:
            moved.append(token)
            i += 1
            continue

        kept.append(token)
        i += 1

    return moved + kept
