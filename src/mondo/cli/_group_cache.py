"""CLI-layer helper for reading a board's group list with cache honoring.

Sits between CLI commands and `cache.directory.get_groups`. Translates the
`--no-cache` / `--refresh-cache` flags and the resolved cache config into a
single call that returns the live or cached group list. Raises `NotFoundError`
when the board isn't visible — callers render the error in their usual style.
"""

from __future__ import annotations

import contextlib
from typing import Any

from mondo.api.client import MondayClient
from mondo.api.errors import NotFoundError
from mondo.api.queries import GROUPS_LIST
from mondo.cache.directory import get_groups as _cache_get_groups
from mondo.cli.context import GlobalOpts


def invalidate_groups_cache(opts: GlobalOpts, board_id: int) -> None:
    """Drop the per-board groups cache file after a successful mutation.

    Best-effort — cache is a perf optimization, never fail a mutation because
    of it. Skipped on `--dry-run` since no state changed.
    """
    if opts.dry_run:
        return
    with contextlib.suppress(Exception):
        opts.build_cache_store("groups", scope=str(board_id)).invalidate()


def fetch_board_groups(
    opts: GlobalOpts,
    client: MondayClient,
    board_id: int,
    *,
    no_cache: bool = False,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    """Return the full group list for `board_id`.

    When cache is enabled and `no_cache` is False, reads (and writes) the
    per-board groups cache. Otherwise runs a live `GROUPS_LIST` query and
    skips the cache entirely.
    """
    cache_cfg = opts.resolve_cache_config()
    if cache_cfg.enabled and not no_cache:
        store = opts.build_cache_store("groups", scope=str(board_id))
        cached = _cache_get_groups(
            client, store=store, board_id=board_id, refresh=refresh
        )
        return list(cached.entries)

    # Live path — skip cache entirely (honors `--no-cache` and the
    # `cache.enabled=false` config knob).
    result = client.execute(GROUPS_LIST, {"board": board_id})
    data = result.get("data") or {}
    boards = data.get("boards") or []
    if not boards:
        raise NotFoundError(f"board {board_id} not found")
    groups = boards[0].get("groups") or []
    if not isinstance(groups, list):
        return []
    return groups
