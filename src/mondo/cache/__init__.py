"""Local on-disk cache for slowly-changing entity directories (boards,
workspaces, users, teams, docs, and per-board structures like columns/groups).
Performance optimization — never a data store.
See docs/caching.md for the full contract."""

from __future__ import annotations

from mondo.cache.config import ResolvedCacheConfig, resolve_cache_config
from mondo.cache.paths import cache_dir
from mondo.cache.store import CachedDirectory, CacheStore

__all__ = [
    "CacheStore",
    "CachedDirectory",
    "ResolvedCacheConfig",
    "cache_dir",
    "resolve_cache_config",
]
