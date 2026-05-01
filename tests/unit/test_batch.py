"""Unit tests for `mondo.cli._batch` (multi-mutation aliasing helpers)."""

from __future__ import annotations

import pytest

from mondo.api.queries import ITEM_CREATE
from mondo.cli._batch import (
    build_aliased_mutation,
    chunk_inputs,
    parse_aliased_response,
)

# ----- build_aliased_mutation -----


def test_build_single_alias_preserves_structure() -> None:
    query, var_names = build_aliased_mutation(ITEM_CREATE, 1)
    assert "m_0:" in query
    assert "create_item(" in query
    # Original variable names appear suffixed in the operation header.
    assert "$board_0: ID!" in query
    assert "$name_0: String!" in query
    assert "$values_0: JSON" in query
    # Original (un-suffixed) declarations should NOT appear.
    assert "$board: ID!" not in query
    assert "$name: String!" not in query
    # var_names is the ordered list of original names.
    assert var_names[0] == "board"
    assert "name" in var_names
    assert "values" in var_names


def test_build_multiple_aliases() -> None:
    query, var_names = build_aliased_mutation(ITEM_CREATE, 3)
    assert "m_0: create_item(" in query
    assert "m_1: create_item(" in query
    assert "m_2: create_item(" in query
    # Each row gets its own variable scope.
    for i in range(3):
        assert f"$board_{i}: ID!" in query
        assert f"$name_{i}: String!" in query
        # Body references should use the suffixed names.
        assert f"item_name: $name_{i}" in query
        assert f"board_id: $board_{i}" in query
    # The variable schema returned matches the template, not a per-row copy.
    assert len(var_names) == 7
    assert var_names == ["board", "name", "group", "values", "create_labels", "prm", "relto"]


def test_build_count_zero_raises() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        build_aliased_mutation(ITEM_CREATE, 0)


def test_build_invalid_template_raises() -> None:
    with pytest.raises(ValueError, match=r"single .* document"):
        build_aliased_mutation("query { foo }", 1)


def test_build_no_variables_raises() -> None:
    with pytest.raises(ValueError, match=r"no .variables"):
        build_aliased_mutation("mutation () { create_item { id } }", 1)


# ----- parse_aliased_response -----


def test_parse_all_success() -> None:
    chunk = [
        {"name": "A"},
        {"name": "B"},
        {"name": "C"},
    ]
    response = {
        "data": {
            "m_0": {"id": "1", "name": "A"},
            "m_1": {"id": "2", "name": "B"},
            "m_2": {"id": "3", "name": "C"},
        }
    }
    out = parse_aliased_response(response, chunk)
    assert all(r["ok"] for r in out)
    assert [r["id"] for r in out] == ["1", "2", "3"]
    assert [r["row_index"] for r in out] == [0, 1, 2]
    assert [r["name"] for r in out] == ["A", "B", "C"]


def test_parse_partial_failure_via_path() -> None:
    chunk = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
    response = {
        "data": {
            "m_0": {"id": "1", "name": "A"},
            "m_1": None,
            "m_2": {"id": "3", "name": "C"},
        },
        "errors": [
            {
                "message": "Group not found",
                "path": ["m_1"],
            }
        ],
    }
    out = parse_aliased_response(response, chunk)
    assert out[0]["ok"] is True
    assert out[0]["id"] == "1"
    assert out[1]["ok"] is False
    assert out[1]["error"] == "Group not found"
    assert out[2]["ok"] is True


def test_parse_base_index_offsets_row_index() -> None:
    chunk = [{"name": "B"}]
    response = {"data": {"m_0": {"id": "11", "name": "B"}}}
    out = parse_aliased_response(response, chunk, base_index=10)
    assert out[0]["row_index"] == 10
    assert out[0]["id"] == "11"


def test_parse_top_level_error_marks_missing_rows() -> None:
    # No `path` on the error -> falls back to a global error message
    # for any alias that produced no data.
    chunk = [{"name": "A"}, {"name": "B"}]
    response = {
        "data": None,
        "errors": [{"message": "Maintenance mode"}],
    }
    out = parse_aliased_response(response, chunk)
    assert all(r["ok"] is False for r in out)
    assert all(r["error"] == "Maintenance mode" for r in out)


def test_parse_no_data_no_error_is_defensive() -> None:
    chunk = [{"name": "X"}]
    out = parse_aliased_response({}, chunk)
    assert out[0]["ok"] is False
    assert out[0]["error"] == "no result"


# ----- chunk_inputs -----


def test_chunk_basic() -> None:
    assert chunk_inputs([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_chunk_exact_division() -> None:
    assert chunk_inputs([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]


def test_chunk_size_larger_than_input() -> None:
    assert chunk_inputs([1, 2, 3], 10) == [[1, 2, 3]]


def test_chunk_zero_size_raises() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        chunk_inputs([1, 2], 0)


def test_chunk_empty() -> None:
    assert chunk_inputs([], 5) == []
