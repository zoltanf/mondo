"""Shared client-side list filters for the cache-served `list` commands.

`board list`, `workspace list` and `doc list` all hold the full unfiltered
directory when served from the local cache and filter it client-side. The
state/kind predicates below are byte-identical across those cache paths, so
they live here as pure functions over already-resolved plain values (the
caller resolves the per-entity enum to its `.value` and applies the "active"
default). Keeping them enum-agnostic lets board (BoardKind/BoardState) and
workspace (WorkspaceKind/WorkspaceState) and doc (DocKind) reuse them without
coupling to each other's enums.
"""

from __future__ import annotations

from typing import Any


def filter_by_state(entries: list[dict[str, Any]], requested_state: str) -> list[dict[str, Any]]:
    """Keep entries matching ``requested_state`` (already resolved by caller).

    ``requested_state == "all"`` is a no-op (returns every entry). Otherwise an
    entry's missing/empty ``state`` defaults to ``"active"`` before comparison,
    matching the spec default for cache-served listings.
    """
    if requested_state == "all":
        return entries
    return [e for e in entries if (e.get("state") or "active") == requested_state]


def filter_by_kind(entries: list[dict[str, Any]], kind_value: str | None) -> list[dict[str, Any]]:
    """Keep entries whose ``kind`` equals ``kind_value``.

    ``kind_value is None`` is a no-op (no kind filter requested). A missing
    ``kind`` is treated as the empty string, so it only matches an explicit
    empty-string filter (never a real kind).
    """
    if kind_value is None:
        return entries
    return [e for e in entries if (e.get("kind") or "") == kind_value]
