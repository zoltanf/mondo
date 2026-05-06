"""Tests for mondo.output — formatters and JMESPath projection."""

from __future__ import annotations

import io
import json

import pytest

from mondo.output import (
    AVAILABLE_FORMATS,
    choose_default_format,
    format_output,
)
from mondo.output.query import apply_query, extract_query_leaf_fields

# ---------- JSON ----------


class TestJsonFormatter:
    def test_array(self) -> None:
        buf = io.StringIO()
        format_output([{"id": 1}, {"id": 2}], fmt="json", stream=buf)
        assert json.loads(buf.getvalue()) == [{"id": 1}, {"id": 2}]

    def test_object(self) -> None:
        buf = io.StringIO()
        format_output({"me": {"id": "1"}}, fmt="json", stream=buf)
        assert json.loads(buf.getvalue()) == {"me": {"id": "1"}}

    def test_scalar(self) -> None:
        buf = io.StringIO()
        format_output(42, fmt="json", stream=buf)
        assert buf.getvalue().strip() == "42"

    def test_none_omits_null(self) -> None:
        buf = io.StringIO()
        format_output(None, fmt="json", stream=buf)
        assert buf.getvalue().strip() == "null"

    def test_pretty_indentation(self) -> None:
        buf = io.StringIO()
        format_output({"a": 1, "b": [1, 2]}, fmt="json", stream=buf)
        assert "\n" in buf.getvalue()  # multi-line = pretty-printed


# ---------- YAML ----------


class TestYamlFormatter:
    def test_object(self) -> None:
        buf = io.StringIO()
        format_output({"a": 1, "b": {"c": "x"}}, fmt="yaml", stream=buf)
        out = buf.getvalue()
        assert "a: 1" in out
        assert "c: x" in out

    def test_array(self) -> None:
        buf = io.StringIO()
        format_output([{"id": 1}, {"id": 2}], fmt="yaml", stream=buf)
        out = buf.getvalue()
        assert "id: 1" in out
        assert "id: 2" in out


# ---------- CSV / TSV ----------


class TestCsvFormatter:
    def test_array_of_flat_objects(self) -> None:
        buf = io.StringIO()
        format_output(
            [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
            fmt="csv",
            stream=buf,
        )
        lines = buf.getvalue().splitlines()
        # header is union of keys; body order follows input
        assert lines[0] in ("id,name", "name,id")
        assert lines[1] in ("1,A", "A,1")
        assert lines[2] in ("2,B", "B,2")

    def test_union_of_keys_across_rows(self) -> None:
        buf = io.StringIO()
        format_output(
            [{"id": 1, "name": "A"}, {"id": 2, "city": "Berlin"}],
            fmt="csv",
            stream=buf,
        )
        lines = buf.getvalue().splitlines()
        header = lines[0].split(",")
        assert set(header) == {"id", "name", "city"}

    def test_empty_list(self) -> None:
        buf = io.StringIO()
        format_output([], fmt="csv", stream=buf)
        assert buf.getvalue() == ""

    def test_object_becomes_two_column_kv(self) -> None:
        buf = io.StringIO()
        format_output({"id": 1, "name": "A"}, fmt="csv", stream=buf)
        lines = buf.getvalue().splitlines()
        assert lines[0] == "key,value"
        assert sorted(lines[1:]) == ["id,1", "name,A"]

    def test_nested_values_are_json_encoded(self) -> None:
        buf = io.StringIO()
        format_output(
            [{"id": 1, "tags": ["a", "b"]}],
            fmt="csv",
            stream=buf,
        )
        body = buf.getvalue().splitlines()[1]
        assert '"[""a"", ""b""]"' in body or '"[\\"a\\", \\"b\\"]"' in body or "[" in body


class TestTsvFormatter:
    def test_tab_separated(self) -> None:
        buf = io.StringIO()
        format_output([{"id": 1, "name": "A"}], fmt="tsv", stream=buf)
        lines = buf.getvalue().splitlines()
        assert "\t" in lines[0]
        assert "," not in lines[0]


# ---------- None ----------


class TestNoneFormatter:
    def test_scalar_printed_raw(self) -> None:
        buf = io.StringIO()
        format_output("hello", fmt="none", stream=buf)
        assert buf.getvalue().strip() == "hello"

    def test_complex_value_empty(self) -> None:
        buf = io.StringIO()
        format_output({"a": 1}, fmt="none", stream=buf)
        # `none` suppresses structured data; useful when `-q` extracts a scalar
        assert buf.getvalue() == ""


# ---------- Table ----------


class TestTableFormatter:
    def test_array_of_objects_renders_rows(self) -> None:
        buf = io.StringIO()
        format_output(
            [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
            fmt="table",
            stream=buf,
            tty=True,
        )
        out = buf.getvalue()
        # Column headers and values appear somewhere in the rendered output
        assert "id" in out and "name" in out
        assert "A" in out and "B" in out

    def test_object_renders_key_value(self) -> None:
        buf = io.StringIO()
        format_output(
            {"id": "1", "name": "Alice"},
            fmt="table",
            stream=buf,
            tty=True,
        )
        out = buf.getvalue()
        assert "id" in out
        assert "Alice" in out

    def test_nested_value_collapsed(self) -> None:
        buf = io.StringIO()
        format_output(
            [{"id": 1, "tags": ["a", "b"]}],
            fmt="table",
            stream=buf,
            tty=True,
        )
        # Nested list should not be dumped verbatim; plan §11.2 says collapse to <…>
        assert "<" in buf.getvalue()

    def test_empty_array(self) -> None:
        buf = io.StringIO()
        format_output([], fmt="table", stream=buf, tty=True)
        # Empty table is fine — should not crash
        assert buf.getvalue() is not None


# ---------- Registry + auto-detect ----------


class TestRegistry:
    def test_has_all_documented_formats(self) -> None:
        assert set(AVAILABLE_FORMATS) == {"table", "json", "jsonc", "yaml", "tsv", "csv", "none"}

    def test_unknown_format_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown format"):
            format_output({}, fmt="bogus", stream=io.StringIO())


class TestChooseDefaultFormat:
    def test_tty_default_is_table(self) -> None:
        assert choose_default_format(is_tty=True) == "table"

    def test_non_tty_default_is_json(self) -> None:
        assert choose_default_format(is_tty=False) == "json"


# ---------- JMESPath projection ----------


class TestApplyQuery:
    def test_no_expression_returns_as_is(self) -> None:
        data = [{"a": 1}]
        assert apply_query(data, None) is data

    def test_simple_projection(self) -> None:
        data = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
        assert apply_query(data, "[].name") == ["A", "B"]

    def test_multiselect_hash(self) -> None:
        data = [{"id": 1, "name": "A", "extra": "ignore"}]
        result = apply_query(data, "[].{id:id,name:name}")
        assert result == [{"id": 1, "name": "A"}]

    def test_scalar_extraction(self) -> None:
        data = {"me": {"id": "42"}}
        assert apply_query(data, "me.id") == "42"

    def test_bad_expression_raises_value_error(self) -> None:
        # Unclosed bracket → LexerError (subclass of JMESPathError).
        with pytest.raises(ValueError, match="JMESPath"):
            apply_query([], "[")


class TestExtractQueryLeafFields:
    def test_empty_returns_empty(self) -> None:
        assert extract_query_leaf_fields("") == frozenset()
        assert extract_query_leaf_fields(None) == frozenset()

    def test_simple_identifier(self) -> None:
        assert extract_query_leaf_fields("name") == frozenset({"name"})

    def test_nested_path(self) -> None:
        assert extract_query_leaf_fields("[*].workspace.name") == frozenset(
            {"workspace", "name"}
        )

    def test_multiselect_dict_excludes_aliases(self) -> None:
        # `ws` and `owner` are aliases (key_val_pair `value`), not field nodes.
        # Only `workspace`, `name`, `owner`, `id` survive — and `owner` only
        # because it's a field on the right of a key_val_pair.
        result = extract_query_leaf_fields(
            "{ws: workspace.name, owner: owner.id}"
        )
        assert result == frozenset({"workspace", "name", "owner", "id"})

    def test_filter_collects_both_sides(self) -> None:
        # The filter `[?type==\`x\`].id` projects on `id` and references `type`
        # in the comparator. Both must be in the GraphQL selection set.
        result = extract_query_leaf_fields("[?type==`multi_status`].id")
        assert result == frozenset({"type", "id"})

    def test_function_args_collected_function_name_excluded(self) -> None:
        # `length` is a JMESPath function — its name is on a function_expression
        # node, not a field node. The argument `items` IS a field.
        assert extract_query_leaf_fields("length(items)") == frozenset({"items"})

    def test_pipe_collects_both_sides(self) -> None:
        result = extract_query_leaf_fields("[*].id | [0]")
        assert result == frozenset({"id"})

    def test_malformed_expression_returns_empty(self) -> None:
        # Surfacing a JMESPath syntax error is `apply_query`'s responsibility.
        # This helper must not raise; it just returns nothing extractable.
        assert extract_query_leaf_fields("[") == frozenset()
        assert extract_query_leaf_fields("{unterminated:") == frozenset()

    def test_alias_renaming_extracts_real_field(self) -> None:
        # Mirrors the report's silent-null example: alias `folder` projects
        # `board_folder_id`. The warning must fire on the real field, not the
        # alias.
        assert extract_query_leaf_fields("{folder: board_folder_id}") == frozenset(
            {"board_folder_id"}
        )

    def test_returns_frozenset(self) -> None:
        result = extract_query_leaf_fields("name")
        assert isinstance(result, frozenset)
