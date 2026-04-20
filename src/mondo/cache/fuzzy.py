"""Fuzzy name matching over cached directory entries.

Thin wrapper around `rapidfuzz.process.extract` that returns entries paired
with their match scores, sorted best-first. The import of `rapidfuzz` is
deferred to first use so non-fuzzy code paths don't pay the load cost and
the missing-dependency error is localized.
"""

from __future__ import annotations

from typing import Any

from mondo.api.errors import UsageError


def fuzzy_score(
    query: str,
    entries: list[dict[str, Any]],
    *,
    threshold: int = 70,
    name_key: str = "name",
) -> list[tuple[dict[str, Any], int]]:
    """Return `(entry, score)` pairs for entries whose `name_key` fuzzily
    matches `query`, sorted descending by score. `score` is a 0-100 integer.

    Entries with empty/missing names are dropped. An empty `query` returns all
    entries at score 100 (treated as "match everything") so callers can use
    `--name-fuzzy ""` as an escape hatch, though that's rarely useful.

    Raises `UsageError` if `rapidfuzz` is not installed.
    """
    try:
        from rapidfuzz import fuzz, process
    except ImportError as exc:
        raise UsageError(
            "fuzzy name matching requires the `rapidfuzz` package, which is not "
            "installed; reinstall mondo or `pip install rapidfuzz`"
        ) from exc

    if not entries:
        return []
    if not query:
        return [(entry, 100) for entry in entries if entry.get(name_key)]

    indexed: list[tuple[str, dict[str, Any]]] = [
        (str(entry[name_key]), entry)
        for entry in entries
        if entry.get(name_key)
    ]
    names = [name for name, _ in indexed]

    matches = process.extract(
        query,
        names,
        scorer=fuzz.WRatio,
        limit=None,
        score_cutoff=threshold,
    )

    scored: list[tuple[dict[str, Any], int]] = []
    for _name, score, idx in matches:
        _matched_name, entry = indexed[idx]
        scored.append((entry, int(score)))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored
