"""Helpers for commands that accept an ID as either a positional or a flag.

The pattern lets us keep every existing `--id`/`--board` call working while
also supporting the shorter `mondo board get 123` form that az/gh users
expect. Each command declares both a `typer.Argument(None, ...)` and a
`typer.Option(None, "--id", ...)`, then calls `resolve_required_id` to pick
the right one with a clear error when neither or both (conflicting) are given.
"""

from __future__ import annotations

import typer


def resolve_required_id[T: (int, str)](
    positional: T | None,
    flag_value: T | None,
    *,
    flag_name: str,
    resource: str,
) -> T:
    """Return the ID supplied as a positional arg or via a flag.

    Raises `typer.BadParameter` when both are given with different values, or
    when neither is given. Equal values are accepted (handy for copy-paste).
    """
    if positional is not None and flag_value is not None and positional != flag_value:
        raise typer.BadParameter(
            f"pass the {resource} ID as a positional argument or via {flag_name}, not both."
        )
    chosen = positional if positional is not None else flag_value
    if chosen is None:
        raise typer.BadParameter(
            f"missing {resource} ID (pass it as a positional argument or via {flag_name})."
        )
    return chosen
