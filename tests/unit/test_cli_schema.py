"""Tests for the `mondo schema` command and `all_resource_schemas()`."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from mondo.cli._field_sets import all_resource_schemas
from mondo.cli.main import app

runner = CliRunner()


class TestAllResourceSchemas:
    def test_covers_every_top_level_read_resource(self) -> None:
        schemas = all_resource_schemas()
        # Each of these has either a `get` or `list` operation in the CLI.
        assert set(schemas.keys()) == {
            "board",
            "column",
            "doc",
            "folder",
            "group",
            "item",
            "subitem",
            "team",
            "update",
            "user",
            "workspace",
        }

    def test_each_resource_has_at_least_one_operation(self) -> None:
        for resource, ops in all_resource_schemas().items():
            assert ops, f"resource {resource!r} has no operations"
            for op_name, fields in ops.items():
                assert op_name in {"get", "list"}, f"unexpected op {op_name!r}"
                assert isinstance(fields, list)
                assert all(isinstance(f, str) for f in fields)
                assert fields == sorted(fields), f"{resource}.{op_name} unsorted"
                assert len(fields) == len(set(fields)), f"{resource}.{op_name} dupes"

    def test_known_fields_present(self) -> None:
        schemas = all_resource_schemas()
        # Spot-check: BOARD_GET selects `board_kind` and a nested `workspace`.
        assert "board_kind" in schemas["board"]["get"]
        assert "workspace" in schemas["board"]["get"]
        # ITEM_GET has `column_values`, `creator`, etc.
        assert "column_values" in schemas["item"]["get"]
        # GROUPS_LIST has `title` and `archived`.
        assert "title" in schemas["group"]["list"]

    def test_memoized(self) -> None:
        a = all_resource_schemas()
        b = all_resource_schemas()
        assert a is b


class TestSchemaCommand:
    def test_no_arg_lists_all_resources(self) -> None:
        result = runner.invoke(app, ["schema"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "board" in data
        assert "item" in data
        assert isinstance(data["board"]["get"], list)

    def test_resource_arg_filters(self) -> None:
        result = runner.invoke(app, ["schema", "board"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        # Returns just the board entry's operations dict.
        assert "get" in data
        assert "list" in data
        assert "id" in data["get"]

    def test_unknown_resource_exits_2(self) -> None:
        result = runner.invoke(app, ["schema", "nonsense"])
        assert result.exit_code == 2
        assert "unknown resource 'nonsense'" in result.stderr

    def test_unknown_resource_lists_known(self) -> None:
        result = runner.invoke(app, ["schema", "nonsense"])
        for known in ("board", "item", "user", "workspace"):
            assert known in result.stderr

    @pytest.mark.parametrize(
        "resource", ["board", "item", "group", "update", "folder", "workspace", "user", "team", "doc", "subitem", "column"],
    )
    def test_each_resource_invocable(self, resource: str) -> None:
        result = runner.invoke(app, ["schema", resource])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, dict)
        assert data  # non-empty

    def test_jmespath_projection_works(self) -> None:
        # `-q` is a root-level global option; CliRunner doesn't apply the
        # argv-reorder so place it before the subcommand.
        result = runner.invoke(app, ["-q", "get", "schema", "item"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert "id" in data
