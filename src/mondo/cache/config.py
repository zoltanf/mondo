"""Resolve the effective cache config for a given profile + environment.

Precedence (lowest → highest):
    1. Built-in defaults (see mondo.config.schema.DEFAULT_CACHE_*)
    2. Global `cache:` block from config.yaml
    3. Profile-level `cache:` block (merges key-by-key onto global)
    4. Environment variables (MONDO_CACHE_*)
    5. CLI flags (merged at callsite, not here)
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from mondo.cache.paths import DEFAULT_PROFILE_NAME, cache_dir
from mondo.cache.registry import CACHE_ENTITIES
from mondo.cache.store import EntityType
from mondo.config.schema import (
    DEFAULT_CACHE_FUZZY_THRESHOLD,
    CacheConfig,
    Config,
)

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class ResolvedCacheConfig:
    """Fully-resolved cache config for one invocation.

    Per-entity TTLs live in `ttls` (keyed by `EntityType`), built by
    `resolve_cache_config` from the `CACHE_ENTITIES` registry. Read an
    individual TTL via `ttl_for(entity_type)`.
    """

    enabled: bool
    directory: Path
    ttls: Mapping[EntityType, int]
    fuzzy_threshold: int

    def ttl_for(self, entity_type: EntityType) -> int:
        try:
            return self.ttls[entity_type]
        except KeyError:
            raise ValueError(f"unknown entity_type: {entity_type!r}") from None


def resolve_cache_config(
    config: Config,
    *,
    profile_name: str | None,
    env: dict[str, str] | None = None,
) -> ResolvedCacheConfig:
    """Merge defaults → global cache → profile cache → env vars.

    `env` defaults to `os.environ`. Pass an explicit dict in tests for hermetic
    behavior.
    """
    environ = env if env is not None else dict(os.environ)
    effective_profile = profile_name or config.default_profile or DEFAULT_PROFILE_NAME

    # Profile-level cache override — only valid if the named profile actually
    # exists in the config. Missing profiles fall through to global-only.
    profile_cache: CacheConfig | None = None
    if profile_name and profile_name in config.profiles:
        profile_cache = config.profiles[profile_name].cache
    elif not profile_name and config.default_profile in config.profiles:
        profile_cache = config.profiles[config.default_profile].cache

    enabled = _resolve_enabled(config.cache, profile_cache, environ)
    directory = _resolve_dir(config.cache, profile_cache, environ, effective_profile)
    ttls: dict[EntityType, int] = {
        e.name: _resolve_ttl(
            e.name,
            default=e.default_ttl,
            env_key=e.env_key,
            global_cfg=config.cache,
            profile_cfg=profile_cache,
            env=environ,
        )
        for e in CACHE_ENTITIES
    }
    fuzzy_threshold = _resolve_fuzzy_threshold(config.cache, profile_cache, environ)

    return ResolvedCacheConfig(
        enabled=enabled,
        directory=directory,
        ttls=ttls,
        fuzzy_threshold=fuzzy_threshold,
    )


def _resolve_enabled(
    global_cfg: CacheConfig | None,
    profile_cfg: CacheConfig | None,
    env: dict[str, str],
) -> bool:
    value: bool = True
    if global_cfg is not None and global_cfg.enabled is not None:
        value = global_cfg.enabled
    if profile_cfg is not None and profile_cfg.enabled is not None:
        value = profile_cfg.enabled
    env_raw = env.get("MONDO_CACHE_ENABLED")
    if env_raw is not None:
        normalized = env_raw.strip().lower()
        if normalized in _TRUTHY:
            value = True
        elif normalized in _FALSY:
            value = False
    return value


def _resolve_dir(
    global_cfg: CacheConfig | None,
    profile_cfg: CacheConfig | None,
    env: dict[str, str],
    profile_name: str,
) -> Path:
    # Highest-precedence explicit override wins. Env var already covers the
    # XDG default when it's set, so we treat it as equivalent to a config-level
    # override but profile-scoped.
    env_dir = env.get("MONDO_CACHE_DIR")
    if env_dir:
        return Path(env_dir) / profile_name

    override: str | None = None
    if global_cfg is not None and global_cfg.dir:
        override = global_cfg.dir
    if profile_cfg is not None and profile_cfg.dir:
        override = profile_cfg.dir
    if override:
        return Path(override) / profile_name

    return cache_dir(profile_name)


def _resolve_ttl(
    _key: str,
    *,
    default: int,
    env_key: str,
    global_cfg: CacheConfig | None,
    profile_cfg: CacheConfig | None,
    env: dict[str, str],
) -> int:
    value = default
    if global_cfg is not None and global_cfg.ttl is not None:
        attr = getattr(global_cfg.ttl, _key)
        if attr is not None:
            value = attr
    if profile_cfg is not None and profile_cfg.ttl is not None:
        attr = getattr(profile_cfg.ttl, _key)
        if attr is not None:
            value = attr
    env_raw = env.get(env_key)
    if env_raw is not None:
        # Silently ignore garbage env values; the user's config still wins.
        with suppress(ValueError):
            value = int(env_raw)
    return max(0, value)


def _resolve_fuzzy_threshold(
    global_cfg: CacheConfig | None,
    profile_cfg: CacheConfig | None,
    env: dict[str, str],
) -> int:
    value = DEFAULT_CACHE_FUZZY_THRESHOLD
    if (
        global_cfg is not None
        and global_cfg.fuzzy is not None
        and global_cfg.fuzzy.threshold is not None
    ):
        value = global_cfg.fuzzy.threshold
    if (
        profile_cfg is not None
        and profile_cfg.fuzzy is not None
        and profile_cfg.fuzzy.threshold is not None
    ):
        value = profile_cfg.fuzzy.threshold
    env_raw = env.get("MONDO_CACHE_FUZZY_THRESHOLD")
    if env_raw is not None:
        with suppress(ValueError):
            value = int(env_raw)
    return max(0, min(100, value))
