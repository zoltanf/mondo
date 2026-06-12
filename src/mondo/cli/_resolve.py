"""Helpers for commands that accept an ID as either a positional or a flag.

The pattern lets us keep every existing `--id`/`--board` call working while
also supporting the shorter `mondo board get 123` form that az/gh users
expect. Each command declares both a `typer.Argument(None, ...)` and a
`typer.Option(None, "--id", ...)`, then calls `resolve_required_id` to pick
the right one with a clear error when neither or both (conflicting) are given.

`resolve_by_filters` is the sibling helper for mutating commands that want
to pick their target by client-side title match (`--name-contains` /
`--name-matches` / `--name-fuzzy`) instead of a hard-coded id. It enforces
mutex against an explicit id, applies the filter, and surfaces clear errors
on 0-match (NotFoundError) or >1-match without `--first` (UsageError).
"""

from __future__ import annotations

from typing import Any

import typer

from mondo.api.errors import NotFoundError, UsageError
from mondo.cli._filters import apply_fuzzy, compile_name_filter, name_matches


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


def resolve_by_filters(
    entries: list[dict[str, Any]],
    *,
    explicit_id: str | int | None,
    name_contains: str | None,
    name_matches_re: str | None,
    name_fuzzy: str | None,
    first: bool,
    fuzzy_threshold: int = 70,
    key: str = "name",
    id_key: str = "id",
    resource: str,
) -> dict[str, Any]:
    """Resolve a single target entry by id-or-filter against `entries`.

    Exactly one of `explicit_id` or one of the three name-filter flags must be
    set; otherwise raise `typer.BadParameter`. With `explicit_id`, search by
    `id_key` and return the matching entry (so callers see the resolved
    object, not just an id).

    With a filter, apply substring/regex/fuzzy matching against `entry[key]`:
    - 0 matches -> NotFoundError (exit 6).
    - 1 match -> return it.
    - >1 matches: return entries[0] if `first` else raise UsageError (exit 2)
      listing up to 5 candidate titles.

    `entries` are assumed to be in the natural display order returned by the
    upstream fetch (position-asc for groups, server-defined for columns), so
    `--first` always picks the first one shown to the user.
    """
    filter_active = sum(bool(x) for x in (name_contains, name_matches_re, name_fuzzy))
    if explicit_id is not None and filter_active:
        raise typer.BadParameter(
            f"pass either an {resource} id or one of "
            "--name-contains / --name-matches / --name-fuzzy, not both."
        )
    if explicit_id is None and filter_active == 0:
        raise typer.BadParameter(
            f"provide a {resource} id or one of "
            "--name-contains / --name-matches / --name-fuzzy."
        )

    if explicit_id is not None:
        for entry in entries:
            if str(entry.get(id_key)) == str(explicit_id):
                return entry
        raise NotFoundError(f"{resource} {explicit_id!r} not found.")

    if name_fuzzy is not None:
        candidates = apply_fuzzy(
            entries,
            name_fuzzy,
            threshold=fuzzy_threshold,
            include_score=False,
            key=key,
        )
    else:
        needle_lower, pattern = compile_name_filter(
            name_contains, name_matches_re, name_fuzzy=None
        )
        candidates = [
            entry for entry in entries
            if name_matches(entry, needle_lower, pattern, key=key)
        ]

    if not candidates:
        raise NotFoundError(
            f"no {resource} matched the filter (searched {len(entries)})."
        )
    if len(candidates) > 1 and not first:
        sample = ", ".join(repr(c.get(key) or "") for c in candidates[:5])
        suffix = ", ..." if len(candidates) > 5 else ""
        raise UsageError(
            f"{len(candidates)} {resource}s matched: {sample}{suffix}. "
            "Pass --first to pick the first one, or refine the filter."
        )
    return candidates[0]
