"""#88: every `column_values` selection must request the polymorphic
`display_value` (mirror, formula) and `display_value`/`linked_item_ids`
(board_relation, dependency) inline fragments, so typed reads no longer need
raw GraphQL escapes."""

from __future__ import annotations

import pytest

from mondo.api.queries import (
    CHANGE_COLUMN_VALUE,
    CHANGE_MULTIPLE_COLUMN_VALUES,
    COLUMN_CONTEXT,
    ITEM_GET,
    ITEM_GET_WITH_COLUMNS,
    ITEM_GET_WITH_SUBITEMS,
    ITEM_GET_WITH_UPDATES,
    ITEMS_PAGE_INITIAL,
    ITEMS_PAGE_INITIAL_WITH_SUBITEMS,
    ITEMS_PAGE_NEXT,
    ITEMS_PAGE_NEXT_WITH_SUBITEMS,
    SUBITEM_CREATE,
    SUBITEM_GET,
    SUBITEMS_LIST,
    build_items_page_queries,
)

MIRROR_FRAGMENT = "... on MirrorValue { display_value }"
RELATION_FRAGMENT = "... on BoardRelationValue { display_value linked_item_ids }"
FORMULA_FRAGMENT = "... on FormulaValue { display_value }"
DEPENDENCY_FRAGMENT = "... on DependencyValue { display_value linked_item_ids }"
ALL_FRAGMENTS = (MIRROR_FRAGMENT, RELATION_FRAGMENT, FORMULA_FRAGMENT, DEPENDENCY_FRAGMENT)

QUERIES_WITH_COLUMN_VALUES = [
    ITEM_GET,
    ITEM_GET_WITH_UPDATES,
    ITEM_GET_WITH_SUBITEMS,
    ITEM_GET_WITH_COLUMNS,
    ITEMS_PAGE_INITIAL,
    ITEMS_PAGE_NEXT,
    ITEMS_PAGE_INITIAL_WITH_SUBITEMS,
    ITEMS_PAGE_NEXT_WITH_SUBITEMS,
    COLUMN_CONTEXT,
    CHANGE_COLUMN_VALUE,
    CHANGE_MULTIPLE_COLUMN_VALUES,
    SUBITEMS_LIST,
    SUBITEM_GET,
    SUBITEM_CREATE,
]


@pytest.mark.parametrize("query", QUERIES_WITH_COLUMN_VALUES)
def test_query_contains_display_value_fragments(query: str) -> None:
    for fragment in ALL_FRAGMENTS:
        assert fragment in query


@pytest.mark.parametrize("mode", ["full", "ids"])
def test_items_page_builder_includes_fragments(mode: str) -> None:
    initial, next_q = build_items_page_queries(column_values=mode)
    for q in (initial, next_q):
        for fragment in ALL_FRAGMENTS:
            assert fragment in q


def test_items_page_builder_none_mode_has_no_fragments() -> None:
    # `--fields id,name` drops column_values entirely — no fragments expected.
    initial, next_q = build_items_page_queries(column_values="none")
    for q in (initial, next_q):
        assert "column_values" not in q
        for fragment in ALL_FRAGMENTS:
            assert fragment not in q
