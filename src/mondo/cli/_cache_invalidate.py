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
