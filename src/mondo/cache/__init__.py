"""Local on-disk cache for slowly-changing entity directories (boards,
workspaces, users, teams). Performance optimization — never a data store.
See docs/caching.md for the full contract."""

from __future__ import annotations

from mondo.cache.config import ResolvedCacheConfig, resolve_cache_config
from mondo.cache.paths import cache_dir
from mondo.cache.store import CachedDirectory, CacheStore

__all__ = [
    "CachedDirectory",
    "CacheStore",
    "ResolvedCacheConfig",
    "cache_dir",
    "resolve_cache_config",
]
