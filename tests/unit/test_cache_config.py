"""Unit tests for mondo.cache.config — precedence chain."""

from __future__ import annotations

from pathlib import Path

import pytest

from mondo.cache.config import resolve_cache_config
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
    CacheFuzzyConfig,
    CacheTTLConfig,
    Config,
    Profile,
)

# One row per cache EntityType. The same key names the `CacheTTLConfig` field,
# the `ResolvedCacheConfig.ttl_<key>` attribute, and (uppercased) the
# `MONDO_CACHE_TTL_<KEY>` env var. `default` is the built-in TTL constant.
CACHE_TTL_CASES: list[tuple[EntityType, int]] = [
    ("boards", DEFAULT_CACHE_TTL_BOARDS),
    ("workspaces", DEFAULT_CACHE_TTL_WORKSPACES),
    ("users", DEFAULT_CACHE_TTL_USERS),
    ("teams", DEFAULT_CACHE_TTL_TEAMS),
    ("columns", DEFAULT_CACHE_TTL_COLUMNS),
    ("groups", DEFAULT_CACHE_TTL_GROUPS),
    ("docs", DEFAULT_CACHE_TTL_DOCS),
    ("folders", DEFAULT_CACHE_TTL_FOLDERS),
    ("tags", DEFAULT_CACHE_TTL_TAGS),
    ("webhooks", DEFAULT_CACHE_TTL_WEBHOOKS),
    ("board_details", DEFAULT_CACHE_TTL_BOARD_DETAILS),
    ("items", DEFAULT_CACHE_TTL_ITEMS),
    ("board_items", DEFAULT_CACHE_TTL_BOARD_ITEMS),
    ("subitems", DEFAULT_CACHE_TTL_SUBITEMS),
    ("updates", DEFAULT_CACHE_TTL_UPDATES),
    ("docs_blocks", DEFAULT_CACHE_TTL_DOCS_BLOCKS),
]


def test_built_in_defaults_when_config_is_empty() -> None:
    resolved = resolve_cache_config(Config(), profile_name=None, env={})
    assert resolved.enabled is True
    assert resolved.ttl_boards == DEFAULT_CACHE_TTL_BOARDS
    assert resolved.ttl_workspaces == DEFAULT_CACHE_TTL_WORKSPACES
    assert resolved.ttl_users == DEFAULT_CACHE_TTL_USERS
    assert resolved.ttl_teams == DEFAULT_CACHE_TTL_WORKSPACES  # same 24h default
    assert resolved.ttl_columns == DEFAULT_CACHE_TTL_COLUMNS
    assert resolved.ttl_groups == DEFAULT_CACHE_TTL_GROUPS
    assert resolved.ttl_docs == DEFAULT_CACHE_TTL_DOCS
    assert resolved.ttl_folders == DEFAULT_CACHE_TTL_FOLDERS
    assert resolved.fuzzy_threshold == DEFAULT_CACHE_FUZZY_THRESHOLD


def test_global_cache_block_overrides_defaults() -> None:
    cfg = Config(cache=CacheConfig(enabled=False, ttl=CacheTTLConfig(boards=600)))
    resolved = resolve_cache_config(cfg, profile_name=None, env={})
    assert resolved.enabled is False
    assert resolved.ttl_boards == 600
    assert resolved.ttl_users == DEFAULT_CACHE_TTL_USERS


def test_profile_cache_overrides_global() -> None:
    cfg = Config(
        default_profile="acme",
        cache=CacheConfig(ttl=CacheTTLConfig(boards=600)),
        profiles={
            "acme": Profile(cache=CacheConfig(ttl=CacheTTLConfig(boards=120))),
        },
    )
    resolved = resolve_cache_config(cfg, profile_name="acme", env={})
    assert resolved.ttl_boards == 120


def test_env_var_overrides_config() -> None:
    cfg = Config(cache=CacheConfig(ttl=CacheTTLConfig(boards=600)))
    resolved = resolve_cache_config(
        cfg, profile_name=None, env={"MONDO_CACHE_TTL_BOARDS": "99"}
    )
    assert resolved.ttl_boards == 99


def test_env_enabled_flag_parses_truthy_and_falsy() -> None:
    cfg = Config()
    assert resolve_cache_config(cfg, profile_name=None, env={"MONDO_CACHE_ENABLED": "false"}).enabled is False
    assert resolve_cache_config(cfg, profile_name=None, env={"MONDO_CACHE_ENABLED": "0"}).enabled is False
    assert resolve_cache_config(cfg, profile_name=None, env={"MONDO_CACHE_ENABLED": "true"}).enabled is True
    assert resolve_cache_config(cfg, profile_name=None, env={"MONDO_CACHE_ENABLED": "1"}).enabled is True


def test_env_garbage_ttl_falls_back_to_config() -> None:
    cfg = Config(cache=CacheConfig(ttl=CacheTTLConfig(boards=42)))
    resolved = resolve_cache_config(
        cfg, profile_name=None, env={"MONDO_CACHE_TTL_BOARDS": "not-a-number"}
    )
    assert resolved.ttl_boards == 42


def test_fuzzy_threshold_clamped_to_0_100() -> None:
    cfg = Config()
    resolved = resolve_cache_config(
        cfg, profile_name=None, env={"MONDO_CACHE_FUZZY_THRESHOLD": "500"}
    )
    assert resolved.fuzzy_threshold == 100

    resolved = resolve_cache_config(
        cfg, profile_name=None, env={"MONDO_CACHE_FUZZY_THRESHOLD": "-20"}
    )
    assert resolved.fuzzy_threshold == 0


def test_explicit_dir_override_via_env(tmp_path: Path) -> None:
    cfg = Config()
    resolved = resolve_cache_config(
        cfg, profile_name="alpha", env={"MONDO_CACHE_DIR": str(tmp_path)}
    )
    assert resolved.directory == tmp_path / "alpha"


def test_explicit_dir_override_via_global_config(tmp_path: Path) -> None:
    cfg = Config(cache=CacheConfig(dir=str(tmp_path)))
    resolved = resolve_cache_config(cfg, profile_name="beta", env={})
    assert resolved.directory == tmp_path / "beta"


def test_unknown_profile_name_falls_through_to_global_only() -> None:
    cfg = Config(
        cache=CacheConfig(ttl=CacheTTLConfig(boards=111)),
        profiles={"other": Profile(cache=CacheConfig(ttl=CacheTTLConfig(boards=222)))},
    )
    resolved = resolve_cache_config(cfg, profile_name="nonexistent", env={})
    assert resolved.ttl_boards == 111


def test_default_profile_cache_picked_up_when_name_omitted() -> None:
    cfg = Config(
        default_profile="acme",
        profiles={
            "acme": Profile(cache=CacheConfig(fuzzy=CacheFuzzyConfig(threshold=42))),
        },
    )
    resolved = resolve_cache_config(cfg, profile_name=None, env={})
    assert resolved.fuzzy_threshold == 42


@pytest.mark.parametrize(("entity", "default"), CACHE_TTL_CASES)
def test_ttl_default(entity: EntityType, default: int) -> None:
    """Every EntityType resolves to its built-in default TTL on an empty config."""
    resolved = resolve_cache_config(Config(), profile_name=None, env={})
    assert resolved.ttl_for(entity) == default


@pytest.mark.parametrize(("entity", "default"), CACHE_TTL_CASES)
def test_ttl_for_matches_attribute(entity: EntityType, default: int) -> None:
    """`ttl_for(entity)` mirrors the flat `ttl_<entity>` attribute."""
    resolved = resolve_cache_config(Config(), profile_name=None, env={})
    assert resolved.ttl_for(entity) == getattr(resolved, f"ttl_{entity}")


def test_ttl_for_rejects_unknown_entity() -> None:
    resolved = resolve_cache_config(Config(), profile_name=None, env={})
    with pytest.raises(ValueError):
        resolved.ttl_for("nonsense")  # type: ignore[arg-type]


@pytest.mark.parametrize(("entity", "default"), CACHE_TTL_CASES)
def test_ttl_env_override(entity: EntityType, default: int) -> None:
    """`MONDO_CACHE_TTL_<ENTITY>` overrides the default for each EntityType."""
    env_key = f"MONDO_CACHE_TTL_{entity.upper()}"
    resolved = resolve_cache_config(Config(), profile_name=None, env={env_key: "77"})
    assert resolved.ttl_for(entity) == 77


@pytest.mark.parametrize(("entity", "default"), CACHE_TTL_CASES)
def test_ttl_profile_overrides_global(entity: EntityType, default: int) -> None:
    """A profile-level TTL beats the global `cache:` block for each EntityType."""
    cfg = Config(
        default_profile="acme",
        cache=CacheConfig(ttl=CacheTTLConfig(**{entity: 600})),
        profiles={
            "acme": Profile(cache=CacheConfig(ttl=CacheTTLConfig(**{entity: 120}))),
        },
    )
    resolved = resolve_cache_config(cfg, profile_name="acme", env={})
    assert resolved.ttl_for(entity) == 120


@pytest.mark.parametrize(("entity", "default"), CACHE_TTL_CASES)
def test_ttl_env_overrides_profile(entity: EntityType, default: int) -> None:
    """Env var wins over both global and profile TTLs for each EntityType."""
    env_key = f"MONDO_CACHE_TTL_{entity.upper()}"
    cfg = Config(
        default_profile="acme",
        cache=CacheConfig(ttl=CacheTTLConfig(**{entity: 600})),
        profiles={
            "acme": Profile(cache=CacheConfig(ttl=CacheTTLConfig(**{entity: 120}))),
        },
    )
    resolved = resolve_cache_config(cfg, profile_name="acme", env={env_key: "55"})
    assert resolved.ttl_for(entity) == 55
