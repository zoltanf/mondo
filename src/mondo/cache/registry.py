"""Single source of truth for the cache entity types.

Every cache entity (boards, columns, items, …) has exactly one row here,
pairing its `EntityType` name with its scope, built-in default TTL, and the
environment variable that overrides that TTL. The three consumers —
`cache.config` (TTL resolution), `cli.cache` (scope tuples + CLI enum), and
the drift test — all derive from `CACHE_ENTITIES` instead of re-hardcoding
the list in each place.

Layering: this module sits in the cache layer. It imports the authoritative
`EntityType` Literal from `mondo.cache.store` and the default-TTL constants
from `mondo.config.schema` (both same-layer / lower). It MUST NOT import
`mondo.cli` — the CLI derives from the registry, never the other way round.
`EntityType` stays the static, hand-written Literal; the drift test asserts
this registry matches it rather than generating it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from mondo.cache.store import EntityType
from mondo.config.schema import (
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
)

CacheScope = Literal["single_file", "board", "item", "doc"]


@dataclass(frozen=True)
class CacheEntity:
    """One cache entity type's static metadata."""

    name: EntityType
    scope: CacheScope
    default_ttl: int
    env_key: str


# All 17 entity types, in the same order as `store.EntityType`. Scope mapping:
#   single_file → former _SINGLE_FILE_TYPES
#   board       → former _BOARD_SCOPED_TYPES
#   item        → former _ITEM_SCOPED_TYPES
#   doc         → former _DOC_SCOPED_TYPES
CACHE_ENTITIES: tuple[CacheEntity, ...] = (
    CacheEntity("boards", "single_file", DEFAULT_CACHE_TTL_BOARDS, "MONDO_CACHE_TTL_BOARDS"),
    CacheEntity(
        "workspaces", "single_file", DEFAULT_CACHE_TTL_WORKSPACES, "MONDO_CACHE_TTL_WORKSPACES"
    ),
    CacheEntity("users", "single_file", DEFAULT_CACHE_TTL_USERS, "MONDO_CACHE_TTL_USERS"),
    CacheEntity("teams", "single_file", DEFAULT_CACHE_TTL_TEAMS, "MONDO_CACHE_TTL_TEAMS"),
    CacheEntity("columns", "board", DEFAULT_CACHE_TTL_COLUMNS, "MONDO_CACHE_TTL_COLUMNS"),
    CacheEntity("groups", "board", DEFAULT_CACHE_TTL_GROUPS, "MONDO_CACHE_TTL_GROUPS"),
    CacheEntity("docs", "single_file", DEFAULT_CACHE_TTL_DOCS, "MONDO_CACHE_TTL_DOCS"),
    CacheEntity("folders", "single_file", DEFAULT_CACHE_TTL_FOLDERS, "MONDO_CACHE_TTL_FOLDERS"),
    CacheEntity("tags", "single_file", DEFAULT_CACHE_TTL_TAGS, "MONDO_CACHE_TTL_TAGS"),
    CacheEntity("webhooks", "board", DEFAULT_CACHE_TTL_WEBHOOKS, "MONDO_CACHE_TTL_WEBHOOKS"),
    CacheEntity(
        "board_details", "board", DEFAULT_CACHE_TTL_BOARD_DETAILS, "MONDO_CACHE_TTL_BOARD_DETAILS"
    ),
    CacheEntity("items", "item", DEFAULT_CACHE_TTL_ITEMS, "MONDO_CACHE_TTL_ITEMS"),
    CacheEntity(
        "board_items", "item", DEFAULT_CACHE_TTL_BOARD_ITEMS, "MONDO_CACHE_TTL_BOARD_ITEMS"
    ),
    CacheEntity("subitems", "item", DEFAULT_CACHE_TTL_SUBITEMS, "MONDO_CACHE_TTL_SUBITEMS"),
    CacheEntity("updates", "item", DEFAULT_CACHE_TTL_UPDATES, "MONDO_CACHE_TTL_UPDATES"),
    CacheEntity("docs_blocks", "doc", DEFAULT_CACHE_TTL_DOCS_BLOCKS, "MONDO_CACHE_TTL_DOCS_BLOCKS"),
)

CACHE_ENTITY_BY_NAME: dict[EntityType, CacheEntity] = {e.name: e for e in CACHE_ENTITIES}


def entity_names() -> tuple[EntityType, ...]:
    """All entity type names, in registry order."""
    return tuple(e.name for e in CACHE_ENTITIES)


def names_by_scope(scope: CacheScope) -> tuple[EntityType, ...]:
    """Entity type names with the given scope, in registry order."""
    return tuple(e.name for e in CACHE_ENTITIES if e.scope == scope)
