"""Drift guards: the cache entity registry is the single source of truth.

`CACHE_ENTITIES` must stay in lock-step with the four places the 17 entity
types used to be duplicated — the `EntityType` Literal, the `CacheType` CLI
enum, the `CacheTTLConfig` pydantic fields, the `DEFAULT_CACHE_TTL_*`
constants, and the `cli.cache` scope tuples / refresh dispatch tables.
"""

from __future__ import annotations

import typing

from mondo.cache.registry import (
    CACHE_ENTITIES,
    CACHE_ENTITY_BY_NAME,
    entity_names,
    names_by_scope,
)
from mondo.cache.store import EntityType
from mondo.cli import cache as cli_cache
from mondo.config.schema import CacheTTLConfig


def test_registry_matches_entity_type_literal() -> None:
    assert set(entity_names()) == set(typing.get_args(EntityType))


def test_registry_matches_cache_type_enum_minus_all() -> None:
    enum_members = {m.value for m in cli_cache.CacheType} - {"all"}
    assert set(entity_names()) == enum_members


def test_registry_matches_cache_ttl_config_fields() -> None:
    assert set(entity_names()) == set(CacheTTLConfig.model_fields)


def test_registry_default_ttls_match_schema_constants() -> None:
    import mondo.config.schema as schema

    for entity in CACHE_ENTITIES:
        const = getattr(schema, f"DEFAULT_CACHE_TTL_{entity.name.upper()}")
        assert entity.default_ttl == const, entity.name


def test_registry_covers_all_scope_tuples() -> None:
    union = (
        set(cli_cache._SINGLE_FILE_TYPES)
        | set(cli_cache._BOARD_SCOPED_TYPES)
        | set(cli_cache._ITEM_SCOPED_TYPES)
        | set(cli_cache._DOC_SCOPED_TYPES)
    )
    assert union == set(entity_names())


def test_scope_tuple_membership_matches_registry_scope() -> None:
    scope_to_tuple = {
        "single_file": set(cli_cache._SINGLE_FILE_TYPES),
        "board": set(cli_cache._BOARD_SCOPED_TYPES),
        "item": set(cli_cache._ITEM_SCOPED_TYPES),
        "doc": set(cli_cache._DOC_SCOPED_TYPES),
    }
    for entity in CACHE_ENTITIES:
        assert entity.name in scope_to_tuple[entity.scope], entity.name
        # And it appears in no other scope's tuple.
        for scope, members in scope_to_tuple.items():
            if scope != entity.scope:
                assert entity.name not in members, entity.name


def test_names_by_scope_agrees_with_registry() -> None:
    for scope in ("single_file", "board", "item", "doc"):
        expected = tuple(e.name for e in CACHE_ENTITIES if e.scope == scope)
        assert names_by_scope(scope) == expected  # type: ignore[arg-type]


def test_refresh_dispatch_keys_are_single_file_entities() -> None:
    single_file = set(names_by_scope("single_file"))
    assert set(cli_cache._REFRESH_DISPATCH) <= single_file


def test_scoped_refresh_dispatch_keys_are_board_entities() -> None:
    board = set(names_by_scope("board"))
    assert set(cli_cache._SCOPED_REFRESH_DISPATCH) <= board


def test_entity_by_name_covers_all() -> None:
    assert set(CACHE_ENTITY_BY_NAME) == set(entity_names())
    for name, entity in CACHE_ENTITY_BY_NAME.items():
        assert entity.name == name
