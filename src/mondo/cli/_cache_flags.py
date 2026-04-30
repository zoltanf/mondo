"""Shared cache-flag plumbing for CLI list commands.

Several list commands accept `--no-cache`, `--refresh-cache`, and
`--fuzzy-threshold`. The mutex check, fuzzy-threshold resolution, and the
"is cache actually in play for this invocation" computation were
copy-pasted in each caller. This module centralizes them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from mondo.cache import ResolvedCacheConfig
    from mondo.cache.store import CachedDirectory, CacheStore
    from mondo.cli.context import GlobalOpts


def reject_mutually_exclusive(no_cache: bool, refresh_cache: bool) -> None:
    """Exit(2) with a uniform error when both `--no-cache` and `--refresh-cache` are set."""
    if no_cache and refresh_cache:
        typer.secho(
            "error: --no-cache and --refresh-cache are mutually exclusive.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)


@dataclass(frozen=True)
class CachePrefs:
    cfg: ResolvedCacheConfig
    use_cache: bool
    fuzzy_threshold: int


def resolve_cache_prefs(
    opts: GlobalOpts,
    *,
    no_cache: bool,
    fuzzy_threshold: int | None,
    extra_disable: bool = False,
) -> CachePrefs:
    """Resolve the cache config and fold `--no-cache` / `--fuzzy-threshold` in.

    `extra_disable` covers command-specific reasons to skip the cache even
    when the user didn't pass `--no-cache` (e.g. `board list --with-item-counts`
    which needs live data).
    """
    cfg = opts.resolve_cache_config()
    use_cache = cfg.enabled and not no_cache and not extra_disable
    threshold = fuzzy_threshold if fuzzy_threshold is not None else cfg.fuzzy_threshold
    return CachePrefs(cfg=cfg, use_cache=use_cache, fuzzy_threshold=threshold)


def _format_age(seconds: float) -> str:
    """Compact age string: `45s`, `2m`, `3h`, `2d`."""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds / 60)}m"
    if seconds < 86400:
        return f"{int(seconds / 3600)}h"
    return f"{int(seconds / 86400)}d"


def emit_cache_provenance(
    opts: GlobalOpts,
    cached: CachedDirectory,
    *,
    store: CacheStore | None = None,
    explain: bool = False,
) -> None:
    """Write one stderr line describing where the result came from.

    Fires only when `cached` was served from disk (`from_cache=True`). Suppressed
    when `MONDO_NO_CACHE_NOTICE=1` (unless `explain=True` — `--explain-cache`
    is an explicit user request and overrides the env var) or when
    `--output table` is in effect (interactive humans don't need it).

    `explain=True` adds verbose detail (path, ttl, fetched_at).
    """
    if not cached.from_cache:
        return
    if not explain:
        if os.environ.get("MONDO_NO_CACHE_NOTICE") == "1":
            return
        if opts.output == "table":
            return

    age_str = _format_age(cached.age.total_seconds())
    if explain and store is not None:
        typer.secho(
            f"cache: hit (entity={cached.entity_type}, count={len(cached.entries)}, "
            f"age={age_str}, ttl={cached.ttl_seconds}s, "
            f"fetched_at={cached.fetched_at.isoformat()}, path={store.path})",
            fg=typer.colors.BLUE,
            err=True,
        )
    else:
        typer.secho(
            f"cache: hit (entity={cached.entity_type}, age={age_str}, count={len(cached.entries)})",
            fg=typer.colors.BLUE,
            err=True,
        )
