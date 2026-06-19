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
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from mondo.cache.paths import DEFAULT_PROFILE_NAME, cache_dir
from mondo.cache.store import EntityType
from mondo.config.schema import (
    DEFAULT_CACHE_FUZZY_THRESHOLD,
    DEFAULT_CACHE_TTL_BOARD_DETAILS,
    DEFAULT_CACHE_TTL_BOARD_ITEMS,
    DEFAULT_CACHE_TTL_BOARDS,
    DEFAULT_CACHE_TTL_COLUMNS,
    DEFAULT_CACHE_TTL_DOCS,
    DEFAULT_CACHE_TTL_DOCS_BLOCKS,
    DEFAULT_CACHE_TTL_FOLDERS,
    DEFAULT_CACHE_TTL_GROUPS,
    DEFAULT_CACHE_TTL_ITEMS,
    DEFAULT_CACHE_TTL_SUBITEMS,
    DEFAULT_CACHE_TTL_TAGS,
    DEFAULT_CACHE_TTL_TEAMS,
    DEFAULT_CACHE_TTL_UPDATES,
    DEFAULT_CACHE_TTL_USERS,
    DEFAULT_CACHE_TTL_WEBHOOKS,
    DEFAULT_CACHE_TTL_WORKSPACES,
    CacheConfig,
    Config,
)

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class ResolvedCacheConfig:
    """Flat, fully-resolved cache config for one invocation."""

    enabled: bool
    directory: Path
    ttl_boards: int
    ttl_workspaces: int
    ttl_users: int
    ttl_teams: int
    ttl_columns: int
    ttl_groups: int
    ttl_docs: int
    ttl_folders: int
    ttl_tags: int
    ttl_webhooks: int
    ttl_board_details: int
    ttl_items: int
    ttl_board_items: int
    ttl_subitems: int
    ttl_updates: int
    ttl_docs_blocks: int
    fuzzy_threshold: int

    def ttl_for(self, entity_type: EntityType) -> int:
        match entity_type:
            case "boards":
                return self.ttl_boards
            case "workspaces":
                return self.ttl_workspaces
            case "users":
                return self.ttl_users
            case "teams":
                return self.ttl_teams
            case "columns":
                return self.ttl_columns
            case "groups":
                return self.ttl_groups
            case "docs":
                return self.ttl_docs
            case "folders":
                return self.ttl_folders
            case "tags":
                return self.ttl_tags
            case "webhooks":
                return self.ttl_webhooks
            case "board_details":
                return self.ttl_board_details
            case "items":
                return self.ttl_items
            case "board_items":
                return self.ttl_board_items
            case "subitems":
                return self.ttl_subitems
            case "updates":
                return self.ttl_updates
            case "docs_blocks":
                return self.ttl_docs_blocks
            case _:
                raise ValueError(f"unknown entity_type: {entity_type!r}")


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
    ttl_boards = _resolve_ttl(
        "boards",
        default=DEFAULT_CACHE_TTL_BOARDS,
        env_key="MONDO_CACHE_TTL_BOARDS",
        global_cfg=config.cache,
        profile_cfg=profile_cache,
        env=environ,
    )
    ttl_workspaces = _resolve_ttl(
        "workspaces",
        default=DEFAULT_CACHE_TTL_WORKSPACES,
        env_key="MONDO_CACHE_TTL_WORKSPACES",
        global_cfg=config.cache,
        profile_cfg=profile_cache,
        env=environ,
    )
    ttl_users = _resolve_ttl(
        "users",
        default=DEFAULT_CACHE_TTL_USERS,
        env_key="MONDO_CACHE_TTL_USERS",
        global_cfg=config.cache,
        profile_cfg=profile_cache,
        env=environ,
    )
    ttl_teams = _resolve_ttl(
        "teams",
        default=DEFAULT_CACHE_TTL_TEAMS,
        env_key="MONDO_CACHE_TTL_TEAMS",
        global_cfg=config.cache,
        profile_cfg=profile_cache,
        env=environ,
    )
    ttl_columns = _resolve_ttl(
        "columns",
        default=DEFAULT_CACHE_TTL_COLUMNS,
        env_key="MONDO_CACHE_TTL_COLUMNS",
        global_cfg=config.cache,
        profile_cfg=profile_cache,
        env=environ,
    )
    ttl_groups = _resolve_ttl(
        "groups",
        default=DEFAULT_CACHE_TTL_GROUPS,
        env_key="MONDO_CACHE_TTL_GROUPS",
        global_cfg=config.cache,
        profile_cfg=profile_cache,
        env=environ,
    )
    ttl_docs = _resolve_ttl(
        "docs",
        default=DEFAULT_CACHE_TTL_DOCS,
        env_key="MONDO_CACHE_TTL_DOCS",
        global_cfg=config.cache,
        profile_cfg=profile_cache,
        env=environ,
    )
    ttl_folders = _resolve_ttl(
        "folders",
        default=DEFAULT_CACHE_TTL_FOLDERS,
        env_key="MONDO_CACHE_TTL_FOLDERS",
        global_cfg=config.cache,
        profile_cfg=profile_cache,
        env=environ,
    )
    ttl_tags = _resolve_ttl(
        "tags",
        default=DEFAULT_CACHE_TTL_TAGS,
        env_key="MONDO_CACHE_TTL_TAGS",
        global_cfg=config.cache,
        profile_cfg=profile_cache,
        env=environ,
    )
    ttl_webhooks = _resolve_ttl(
        "webhooks",
        default=DEFAULT_CACHE_TTL_WEBHOOKS,
        env_key="MONDO_CACHE_TTL_WEBHOOKS",
        global_cfg=config.cache,
        profile_cfg=profile_cache,
        env=environ,
    )
    ttl_board_details = _resolve_ttl(
        "board_details",
        default=DEFAULT_CACHE_TTL_BOARD_DETAILS,
        env_key="MONDO_CACHE_TTL_BOARD_DETAILS",
        global_cfg=config.cache,
        profile_cfg=profile_cache,
        env=environ,
    )
    ttl_items = _resolve_ttl(
        "items",
        default=DEFAULT_CACHE_TTL_ITEMS,
        env_key="MONDO_CACHE_TTL_ITEMS",
        global_cfg=config.cache,
        profile_cfg=profile_cache,
        env=environ,
    )
    ttl_board_items = _resolve_ttl(
        "board_items",
        default=DEFAULT_CACHE_TTL_BOARD_ITEMS,
        env_key="MONDO_CACHE_TTL_BOARD_ITEMS",
        global_cfg=config.cache,
        profile_cfg=profile_cache,
        env=environ,
    )
    ttl_subitems = _resolve_ttl(
        "subitems",
        default=DEFAULT_CACHE_TTL_SUBITEMS,
        env_key="MONDO_CACHE_TTL_SUBITEMS",
        global_cfg=config.cache,
        profile_cfg=profile_cache,
        env=environ,
    )
    ttl_updates = _resolve_ttl(
        "updates",
        default=DEFAULT_CACHE_TTL_UPDATES,
        env_key="MONDO_CACHE_TTL_UPDATES",
        global_cfg=config.cache,
        profile_cfg=profile_cache,
        env=environ,
    )
    ttl_docs_blocks = _resolve_ttl(
        "docs_blocks",
        default=DEFAULT_CACHE_TTL_DOCS_BLOCKS,
        env_key="MONDO_CACHE_TTL_DOCS_BLOCKS",
        global_cfg=config.cache,
        profile_cfg=profile_cache,
        env=environ,
    )
    fuzzy_threshold = _resolve_fuzzy_threshold(config.cache, profile_cache, environ)

    return ResolvedCacheConfig(
        enabled=enabled,
        directory=directory,
        ttl_boards=ttl_boards,
        ttl_workspaces=ttl_workspaces,
        ttl_users=ttl_users,
        ttl_teams=ttl_teams,
        ttl_columns=ttl_columns,
        ttl_groups=ttl_groups,
        ttl_docs=ttl_docs,
        ttl_folders=ttl_folders,
        ttl_tags=ttl_tags,
        ttl_webhooks=ttl_webhooks,
        ttl_board_details=ttl_board_details,
        ttl_items=ttl_items,
        ttl_board_items=ttl_board_items,
        ttl_subitems=ttl_subitems,
        ttl_updates=ttl_updates,
        ttl_docs_blocks=ttl_docs_blocks,
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
