"""apply_fields trims a payload to a comma-separated field list.

Handles list of records, single record, missing fields, dotted paths.
Runs *before* --query (JMESPath) so a typical pipeline is:
    raw payload -> apply_fields(spec) -> apply_query(jmespath) -> formatter.
"""
from __future__ import annotations

from mondo.output.fields import apply_fields


class TestRecord:
    def test_keeps_only_listed_keys(self):
        data = {"id": "1", "name": "A", "state": "active", "extra": 42}
        assert apply_fields(data, "id,name") == {"id": "1", "name": "A"}

    def test_strips_whitespace_around_keys(self):
        data = {"id": "1", "name": "A", "extra": 1}
        assert apply_fields(data, " id , name ") == {"id": "1", "name": "A"}

    def test_missing_key_yields_none(self):
        data = {"id": "1"}
        assert apply_fields(data, "id,name") == {"id": "1", "name": None}

    def test_dotted_path(self):
        data = {"id": "1", "creator": {"id": "9", "name": "X", "email": "x@y"}}
        assert apply_fields(data, "id,creator.name") == {
            "id": "1",
            "creator.name": "X",
        }

    def test_dotted_path_through_missing_returns_none(self):
        data = {"id": "1"}
        assert apply_fields(data, "id,creator.name") == {
            "id": "1",
            "creator.name": None,
        }


class TestList:
    def test_projects_each_record(self):
        data = [
            {"id": "1", "name": "A", "extra": 1},
            {"id": "2", "name": "B", "extra": 2},
        ]
        assert apply_fields(data, "id,name") == [
            {"id": "1", "name": "A"},
            {"id": "2", "name": "B"},
        ]

    def test_empty_list_passes_through(self):
        assert apply_fields([], "id,name") == []

    def test_list_of_scalars_passes_through_unchanged(self):
        data = ["a", "b", "c"]
        assert apply_fields(data, "id,name") == ["a", "b", "c"]


class TestPassthroughs:
    def test_none_spec_returns_data_unchanged(self):
        data = {"id": "1", "extra": True}
        assert apply_fields(data, None) is data

    def test_empty_spec_returns_data_unchanged(self):
        data = {"id": "1"}
        assert apply_fields(data, "") is data

    def test_whitespace_only_spec_returns_data_unchanged(self):
        data = {"id": "1"}
        assert apply_fields(data, "   ") is data

    def test_scalar_payload_passes_through(self):
        assert apply_fields(42, "id,name") == 42
        assert apply_fields("hello", "id,name") == "hello"
        assert apply_fields(None, "id,name") is None
