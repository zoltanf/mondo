"""Per-emit-site selection-set unions for projection warnings.

`emit(..., selected_fields=...)` warns when a JMESPath leaf is missing from
the set. Each call site computes its set as the union of (a) the raw GraphQL
selection set extracted from the query string, and (b) any post-normalize
keys the user can actually see in the emitted dict (e.g. `kind`, `folder_id`,
`workspace_name` produced by `normalize_board_entry`).

Centralised here so the rename rules in `cli/_normalize.py` and the queries
in `api/queries.py` only have to agree in one place.
"""

from __future__ import annotations

from functools import lru_cache

from mondo.api.queries import (
    BOARD_GET,
    FOLDER_GET,
    GROUPS_LIST,
    ITEM_GET,
    ITEM_GET_WITH_SUBITEMS,
    ITEM_GET_WITH_UPDATES,
    ITEMS_PAGE_INITIAL,
    ITEMS_PAGE_INITIAL_WITH_SUBITEMS,
    UPDATE_GET,
    UPDATES_FOR_ITEM,
    UPDATES_LIST_PAGE,
    build_boards_list_query,
    build_folders_list_query,
)
from mondo.api.selection import extract_selected_fields

# Post-`normalize_board_entry` keys not present in the GraphQL selection set.
# `board_kind` → `kind`, `board_folder_id` → `folder_id`. List enrichment
# additionally exposes `workspace_name`. `url` is added by `--with-url`; we
# allow it unconditionally to avoid warnings under that flag.
_NORMALIZED_BOARD_EXTRA = frozenset({"kind", "folder_id", "url"})
_NORMALIZED_BOARD_LIST_EXTRA = _NORMALIZED_BOARD_EXTRA | frozenset({"workspace_name"})

# `normalize_folder_entry` reshapes nested `workspace`/`parent` objects into
# scalar pairs. Include both shapes so JMESPath leaves on either resolve.
_NORMALIZED_FOLDER_EXTRA = frozenset(
    {"workspace_id", "workspace_name", "parent_id", "parent_name"}
)


@lru_cache(maxsize=1)
def board_get_fields() -> frozenset[str]:
    return extract_selected_fields(BOARD_GET) | _NORMALIZED_BOARD_EXTRA


@lru_cache(maxsize=1)
def board_list_fields() -> frozenset[str]:
    # Union the maximal builder output (with item counts) so the field set
    # matches every flag combination of `board list`.
    query, _ = build_boards_list_query(with_item_counts=True)
    return extract_selected_fields(query) | _NORMALIZED_BOARD_LIST_EXTRA


@lru_cache(maxsize=1)
def folder_get_fields() -> frozenset[str]:
    return extract_selected_fields(FOLDER_GET) | _NORMALIZED_FOLDER_EXTRA


@lru_cache(maxsize=1)
def folder_list_fields() -> frozenset[str]:
    query, _ = build_folders_list_query()
    return extract_selected_fields(query) | _NORMALIZED_FOLDER_EXTRA


@lru_cache(maxsize=1)
def group_list_fields() -> frozenset[str]:
    return extract_selected_fields(GROUPS_LIST)


@lru_cache(maxsize=1)
def item_get_fields() -> frozenset[str]:
    return (
        extract_selected_fields(ITEM_GET)
        | extract_selected_fields(ITEM_GET_WITH_UPDATES)
        | extract_selected_fields(ITEM_GET_WITH_SUBITEMS)
    )


@lru_cache(maxsize=1)
def item_list_fields() -> frozenset[str]:
    return extract_selected_fields(ITEMS_PAGE_INITIAL) | extract_selected_fields(
        ITEMS_PAGE_INITIAL_WITH_SUBITEMS
    )


@lru_cache(maxsize=1)
def update_get_fields() -> frozenset[str]:
    return extract_selected_fields(UPDATE_GET)


@lru_cache(maxsize=1)
def update_list_fields() -> frozenset[str]:
    return extract_selected_fields(UPDATES_LIST_PAGE) | extract_selected_fields(
        UPDATES_FOR_ITEM
    )
