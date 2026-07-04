"""Helper for reading a board's column list with cache honoring.

Sits between callers and `cache.directory.get_columns`. Given an optional
per-board columns `CacheStore` (``None`` means "skip the cache"), returns the
live or cached column list. Raises `NotFoundError` when the board isn't
visible — callers render the error in their usual style.

Callers decide whether caching applies (resolving `--no-cache` /
`cache.enabled` / `--dry-run` off their own options) and pass the built store
or ``None``; this keeps the module free of any CLI-options dependency.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from mondo.api.errors import NotFoundError
from mondo.api.queries import COLUMNS_ON_BOARD

if TYPE_CHECKING:
    from mondo.api.client import MondayClient
    from mondo.cache import CacheStore


def invalidate_columns_cache(store: CacheStore | None) -> None:
    """Drop the per-board columns cache file after a successful mutation.

    Best-effort — cache is a perf optimization, never fail a mutation because
    of it. Pass ``None`` (e.g. on `--dry-run`) to make this a no-op.
    """
    if store is None:
        return
    with contextlib.suppress(Exception):
        store.invalidate()


def fetch_board_columns(
    client: MondayClient,
    board_id: int,
    *,
    store: CacheStore | None = None,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    """Return the full column list for `board_id`.

    When `store` is given, reads (and writes) the per-board column cache.
    When `store` is ``None`` (cache disabled or `--no-cache`), runs a live
    `COLUMNS_ON_BOARD` query and skips the cache entirely.
    """
    if store is not None:
        from mondo.cache.directory import get_columns as _cache_get_columns

        cached = _cache_get_columns(client, store=store, board_id=board_id, refresh=refresh)
        return list(cached.entries)

    # Live path — skip cache entirely (honors `--no-cache` and the
    # `cache.enabled=false` config knob).
    result = client.execute(COLUMNS_ON_BOARD, {"board": board_id})
    data = result.get("data") or {}
    boards = data.get("boards") or []
    if not boards:
        raise NotFoundError(f"board {board_id} not found")
    columns = boards[0].get("columns") or []
    if not isinstance(columns, list):
        return []
    return columns
