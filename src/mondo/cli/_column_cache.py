"""CLI-layer helper for reading a board's column list with cache honoring.

Sits between CLI commands and `cache.directory.get_columns`. Translates the
`--no-cache` / `--refresh-cache` flags and the resolved cache config into a
single call that returns the live or cached column list. Raises `NotFoundError`
when the board isn't visible — callers render the error in their usual style.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from mondo.api.errors import NotFoundError
from mondo.api.queries import COLUMNS_ON_BOARD
from mondo.cli.context import GlobalOpts

if TYPE_CHECKING:
    from mondo.api.client import MondayClient


def invalidate_columns_cache(opts: GlobalOpts, board_id: int) -> None:
    """Drop the per-board columns cache file after a successful mutation.

    Best-effort — cache is a perf optimization, never fail a mutation because
    of it. Skipped on `--dry-run` since no state changed.
    """
    if opts.dry_run:
        return
    with contextlib.suppress(Exception):
        opts.build_cache_store("columns", scope=str(board_id)).invalidate()


def fetch_board_columns(
    opts: GlobalOpts,
    client: MondayClient,
    board_id: int,
    *,
    no_cache: bool = False,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    """Return the full column list for `board_id`.

    When cache is enabled and `no_cache` is False, reads (and writes) the
    per-board column cache. Otherwise runs a live `COLUMNS_ON_BOARD` query and
    skips the cache entirely.
    """
    cache_cfg = opts.resolve_cache_config()
    if cache_cfg.enabled and not no_cache:
        from mondo.cache.directory import get_columns as _cache_get_columns

        store = opts.build_cache_store("columns", scope=str(board_id))
        cached = _cache_get_columns(
            client, store=store, board_id=board_id, refresh=refresh
        )
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
