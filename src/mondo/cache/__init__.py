"""Local on-disk cache for slowly-changing entity directories (boards,
workspaces, users, teams, docs, and per-board structures like columns/groups).
Performance optimization — never a data store.
See docs/caching.md for the full contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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


def __getattr__(name: str) -> Any:
    if name in {"ResolvedCacheConfig", "resolve_cache_config"}:
        from mondo.cache import config

        return getattr(config, name)
    if name == "cache_dir":
        from mondo.cache.paths import cache_dir

        return cache_dir
    if name in {"CacheStore", "CachedDirectory"}:
        from mondo.cache import store

        return getattr(store, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
