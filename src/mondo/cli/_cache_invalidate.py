"""Best-effort cache invalidation helpers.

After a successful mutation, the on-disk directory cache for the affected
entity is stale. Drop the file so the next read refetches. Never fail the
command because of it — cache is a perf optimization, not the source of
truth.
"""

from __future__ import annotations

from loguru import logger

from mondo.cache.store import EntityType
from mondo.cli.context import GlobalOpts


def invalidate_entity(
    opts: GlobalOpts, entity: EntityType, *, scope: str | None = None
) -> None:
    """Drop the cache file for `entity` (and optional `scope`). Best-effort.

    Skipped on `--dry-run`. `OSError` (file-op failures) logs at debug and
    keeps going; other exceptions propagate so real bugs surface.
    """
    if opts.dry_run:
        return
    try:
        opts.build_cache_store(entity, scope=scope).invalidate()
    except OSError as exc:
        logger.debug(
            "cache invalidation failed for {}{}: {}",
            entity,
            f"[{scope}]" if scope is not None else "",
            exc,
        )


def invalidate_board_caches(opts: GlobalOpts, board_id: int) -> None:
    """Drop both the global `boards` directory cache and the per-board
    `board_details/<board_id>` cache.

    Used by every `board <mutation>` that changes the cached shape (rename,
    move, archive, delete, duplicate, set-permission). For column/group/tag
    mutations against a board, callers invalidate `board_details` directly
    alongside the existing `columns`/`groups` invalidations.
    """
    invalidate_entity(opts, "boards")
    invalidate_entity(opts, "board_details", scope=str(board_id))


def invalidate_all_scopes(opts: GlobalOpts, entity: EntityType) -> None:
    """Drop every `<entity>/*.json` cache file under the resolved cache dir.

    Used when a mutation only carries a child id (e.g. `webhook delete`
    knows the webhook id, not its board id; `update edit` knows the update
    id, not its item id). Best-effort — any I/O failure is silently
    swallowed since the cache is a perf optimization. Skipped on `--dry-run`.
    """
    import contextlib

    if opts.dry_run:
        return
    try:
        resolved = opts.resolve_cache_config()
    except Exception:
        return
    scoped_dir = resolved.directory / entity
    for p in scoped_dir.glob("*.json"):
        with contextlib.suppress(OSError):
            p.unlink()
