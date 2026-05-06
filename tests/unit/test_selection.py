"""Tests for `mondo.api.selection.extract_selected_fields`."""

from __future__ import annotations

import pytest

from mondo.api.queries import (
    AGGREGATE_BOARD,
    BOARD_GET,
    FOLDER_GET,
    GROUPS_LIST,
    ITEM_GET,
    UPDATES_FOR_ITEM,
    build_boards_list_query,
    build_folders_list_query,
)
from mondo.api.selection import extract_selected_fields


class TestExtractSelectedFields:
    def test_simple_query(self) -> None:
        q = """
        query ($id: ID!) {
          boards(ids: [$id]) {
            id
            name
            state
          }
        }
        """
        assert extract_selected_fields(q) == frozenset({"boards", "id", "name", "state"})

    def test_excludes_arguments_and_variables(self) -> None:
        q = "query ($id: ID!) { items(ids: [$id], limit: 10) { id name } }"
        # `ID`, `id` (variable), `items` arg list — only `items`, `id`, `name`
        # should remain. `id` is the leaf field name AND a variable name; the
        # variable inside `(...)` is filtered, the leaf field survives.
        assert extract_selected_fields(q) == frozenset({"items", "id", "name"})

    def test_nested_selection_unioned(self) -> None:
        q = "{ boards { id workspace { id name kind } } }"
        assert extract_selected_fields(q) == frozenset(
            {"boards", "id", "workspace", "name", "kind"}
        )

    def test_inline_fragments_skip_type_names(self) -> None:
        # The `__typename` meta-field IS a real selectable field — keep it.
        # The type-condition `TypeA` / `TypeB` are NOT selectable — drop.
        q = """
        {
          value {
            __typename
            ... on TypeA { result }
            ... on TypeB { another }
          }
        }
        """
        assert extract_selected_fields(q) == frozenset(
            {"value", "__typename", "result", "another"}
        )

    def test_aggregate_board_query(self) -> None:
        # AGGREGATE_BOARD has nested inline fragments — verify TypeName tokens
        # don't leak in.
        fields = extract_selected_fields(AGGREGATE_BOARD)
        assert "AggregateBasicAggregationResult" not in fields
        assert "AggregateGroupByResult" not in fields
        assert "result" in fields
        assert "value_string" in fields
        assert "__typename" in fields

    def test_line_comments_stripped(self) -> None:
        q = """
        # outer comment
        { boards { id  # inline comment
          name } }
        """
        assert extract_selected_fields(q) == frozenset({"boards", "id", "name"})

    def test_field_with_args_still_counted(self) -> None:
        # `column_values(ids: $cols)` — the `column_values` field name is
        # before the parens and must be retained.
        q = "{ items { id column_values(ids: [\"a\"]) { id type text } } }"
        assert extract_selected_fields(q) == frozenset(
            {"items", "id", "column_values", "type", "text"}
        )

    def test_memoized(self) -> None:
        # Lru cache means repeated calls return the same frozenset object.
        a = extract_selected_fields(BOARD_GET)
        b = extract_selected_fields(BOARD_GET)
        assert a is b

    @pytest.mark.parametrize(
        "query, expected_present, expected_absent",
        [
            (BOARD_GET, {"id", "name", "board_kind", "board_folder_id", "workspace"}, {"created_at", "url"}),
            (ITEM_GET, {"items", "id", "name", "url", "column_values", "creator"}, {"updates", "subitems"}),
            (GROUPS_LIST, {"groups", "id", "title", "color", "archived", "deleted"}, {"created_at"}),
            (FOLDER_GET, {"folders", "id", "name", "color", "parent", "workspace"}, {"description"}),
            (UPDATES_FOR_ITEM, {"items", "updates", "body", "text_body", "creator", "replies", "likes"}, {"description"}),
        ],
    )
    def test_real_query_constants(
        self,
        query: str,
        expected_present: set[str],
        expected_absent: set[str],
    ) -> None:
        fields = extract_selected_fields(query)
        assert expected_present <= fields, f"missing expected fields: {expected_present - fields}"
        assert expected_absent.isdisjoint(fields), (
            f"unexpected fields present: {expected_absent & fields}"
        )

    def test_builder_outputs(self) -> None:
        # Builders return tuples (query, variables) — the query string is what
        # we tokenize.
        q, _ = build_boards_list_query(with_item_counts=True)
        fields = extract_selected_fields(q)
        assert {"boards", "id", "name", "workspace_id", "workspace", "items_count"} <= fields

        q, _ = build_folders_list_query()
        fields = extract_selected_fields(q)
        assert {"folders", "id", "name", "color", "parent", "workspace"} <= fields

    def test_builder_omits_optional_fields(self) -> None:
        # without items_count, the field should not appear in the selection set.
        q, _ = build_boards_list_query()
        assert "items_count" not in extract_selected_fields(q)

    def test_returns_frozenset(self) -> None:
        result = extract_selected_fields(BOARD_GET)
        assert isinstance(result, frozenset)
