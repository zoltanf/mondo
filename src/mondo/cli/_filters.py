"""Shared client-side name filters for list commands.

Both `mondo board list` and `mondo doc list` accept `--name-contains`,
`--name-matches`, and `--name-fuzzy` as client-side filters over cached
directory entries. The helpers here operate on the entry's `name` field and
are entity-agnostic; any list command whose entries expose a `name` scalar
can reuse them.
"""

from __future__ import annotations

import re
from typing import Any

from mondo.api.errors import UsageError
from mondo.cache.fuzzy import fuzzy_score


def compile_name_filter(
    name_contains: str | None,
    name_matches: str | None,
    name_fuzzy: str | None = None,
) -> tuple[str | None, re.Pattern[str] | None]:
    """Validate mutex on the three name-filter flags and compile the regex.

    `name_fuzzy` is applied separately (see `apply_fuzzy`); we only validate
    here that no more than one of the three name filters is active.
    """
    active = sum(bool(x) for x in (name_contains, name_matches, name_fuzzy))
    if active > 1:
        raise UsageError(
            "pass only one of --name-contains / --name-matches / --name-fuzzy."
        )
    pattern: re.Pattern[str] | None = None
    if name_matches:
        try:
            pattern = re.compile(name_matches)
        except re.error as exc:
            raise UsageError(f"invalid --name-matches regex: {exc}") from exc
    return (name_contains.lower() if name_contains else None, pattern)


def name_matches(
    entry: dict[str, Any],
    needle_lower: str | None,
    pattern: re.Pattern[str] | None,
) -> bool:
    name = entry.get("name") or ""
    if needle_lower is not None and needle_lower not in name.lower():
        return False
    return not (pattern is not None and pattern.search(name) is None)


def apply_fuzzy(
    entries: list[dict[str, Any]],
    query: str,
    *,
    threshold: int,
    include_score: bool,
) -> list[dict[str, Any]]:
    """Apply fuzzy name filter to entries, returning results in score-desc order.

    When `include_score` is True, a `_fuzzy_score` key is injected into each
    returned entry (shallow-copied so the source list isn't mutated).
    """
    scored = fuzzy_score(query, entries, threshold=threshold)
    if include_score:
        return [{**entry, "_fuzzy_score": score} for entry, score in scored]
    return [entry for entry, _ in scored]
