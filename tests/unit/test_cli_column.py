"""End-to-end CLI tests for the `mondo column ...` command group."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from mondo.cli.main import app

ENDPOINT = "https://api.monday.com/v2"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")
    monkeypatch.setenv("MONDO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MONDO_CACHE_ENABLED", "false")


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


def _context_response(board_id: int, cols: list[dict], values: list[dict]) -> dict:
    return _ok(
        {
            "items": [
                {
                    "id": "1",
                    "name": "item",
                    "board": {"id": str(board_id), "columns": cols},
                    "column_values": values,
                }
            ]
        }
    )


class TestColumnList:
    def test_emits_simplified_columns(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "id": "42",
                            "name": "Board",
                            "columns": [
                                {"id": "text", "title": "Text", "type": "text", "archived": False},
                                {
                                    "id": "status",
                                    "title": "Status",
                                    "type": "status",
                                    "archived": False,
                                    "settings_str": "{}",
                                },
                            ],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["column", "list", "--board", "42"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed == [
            {"id": "text", "title": "Text", "type": "text", "archived": False},
            {"id": "status", "title": "Status", "type": "status", "archived": False},
        ]


class TestColumnGet:
    def test_human_rendered(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[{"id": "status", "title": "S", "type": "status", "settings_str": "{}"}],
                values=[
                    {
                        "id": "status",
                        "type": "status",
                        "text": "Done",
                        "value": '{"index":1}',
                    }
                ],
            ),
        )
        result = runner.invoke(app, ["column", "get", "--item", "1", "--column", "status"])
        assert result.exit_code == 0
        assert result.stdout.strip() == '"Done"'

    def test_raw_emits_envelope(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[{"id": "text", "title": "T", "type": "text", "settings_str": "{}"}],
                values=[{"id": "text", "type": "text", "text": "Hello", "value": '"Hello"'}],
            ),
        )
        result = runner.invoke(app, ["column", "get", "--item", "1", "--column", "text", "--raw"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed["text"] == "Hello"
        assert parsed["type"] == "text"


class TestColumnSet:
    def test_codec_parsed_status(self, httpx_mock: HTTPXMock) -> None:
        # Context fetch
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[
                    {
                        "id": "status",
                        "title": "S",
                        "type": "status",
                        "settings_str": json.dumps({"labels": {"0": "Working on it", "1": "Done"}}),
                    }
                ],
                values=[{"id": "status", "type": "status", "text": "", "value": None}],
            ),
        )
        # Mutation
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_value": {"id": "1", "name": "item"}}),
        )
        result = runner.invoke(
            app,
            ["column", "set", "--item", "1", "--column", "status", "--value", "Done"],
        )
        assert result.exit_code == 0, result.stdout
        # Last call was the mutation — assert the codec-parsed payload
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["variables"]["value"] == json.dumps({"label": "Done"})

    def test_dry_run_does_not_mutate(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[{"id": "text", "title": "T", "type": "text", "settings_str": "{}"}],
                values=[{"id": "text", "type": "text", "text": "", "value": None}],
            ),
        )
        result = runner.invoke(
            app,
            [
                "--dry-run",
                "column",
                "set",
                "--item",
                "1",
                "--column",
                "text",
                "--value",
                "Hello",
            ],
        )
        assert result.exit_code == 0
        # Only the context fetch, not a mutation
        assert len(httpx_mock.get_requests()) == 1
        parsed = json.loads(result.stdout)
        assert "change_column_value" in parsed["query"]
        assert parsed["variables"]["value"] == '"Hello"'

    def test_raw_mode_passes_json_through(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[{"id": "status", "title": "S", "type": "status", "settings_str": "{}"}],
                values=[],
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_value": {"id": "1"}}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "set",
                "--item",
                "1",
                "--column",
                "status",
                "--value",
                '{"index":7}',
                "--raw",
            ],
        )
        assert result.exit_code == 0
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["variables"]["value"] == json.dumps({"index": 7})

    def test_tag_names_resolved_to_ids(self, httpx_mock: HTTPXMock) -> None:
        # Context fetch
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[{"id": "tags", "title": "T", "type": "tags", "settings_str": "{}"}],
                values=[{"id": "tags", "type": "tags", "text": "", "value": None}],
            ),
        )
        # create_or_get_tag x 2
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_or_get_tag": {"id": "1001", "name": "urgent"}}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_or_get_tag": {"id": "1002", "name": "blocked"}}),
        )
        # Final mutation
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_value": {"id": "1"}}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "set",
                "--item",
                "1",
                "--column",
                "tags",
                "--value",
                "urgent,blocked",
            ],
        )
        assert result.exit_code == 0, result.stdout
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["variables"]["value"] == json.dumps({"tag_ids": [1001, 1002]})


class TestColumnSetMany:
    def test_bulk(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[
                    {"id": "text", "title": "T", "type": "text", "settings_str": "{}"},
                    {"id": "status", "title": "S", "type": "status", "settings_str": "{}"},
                ],
                values=[],
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_multiple_column_values": {"id": "1", "name": "item"}}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "set-many",
                "--item",
                "1",
                "--values",
                '{"text":"Hello","status":{"label":"Done"}}',
            ],
        )
        assert result.exit_code == 0
        body = json.loads(httpx_mock.get_requests()[-1].content)
        values = json.loads(body["variables"]["values"])
        assert values == {"text": "Hello", "status": {"label": "Done"}}


class TestColumnClear:
    def test_checkbox_sends_null(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[{"id": "done", "title": "D", "type": "checkbox", "settings_str": "{}"}],
                values=[],
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_value": {"id": "1"}}),
        )
        result = runner.invoke(app, ["column", "clear", "--item", "1", "--column", "done"])
        assert result.exit_code == 0
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["variables"]["value"] == "null"

    def test_text_sends_empty_string(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[{"id": "notes", "title": "N", "type": "text", "settings_str": "{}"}],
                values=[],
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_value": {"id": "1"}}),
        )
        result = runner.invoke(app, ["column", "clear", "--item", "1", "--column", "notes"])
        assert result.exit_code == 0
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["variables"]["value"] == '""'

    def test_status_sends_empty_object(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[{"id": "status", "title": "S", "type": "status", "settings_str": "{}"}],
                values=[],
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_value": {"id": "1"}}),
        )
        result = runner.invoke(app, ["column", "clear", "--item", "1", "--column", "status"])
        assert result.exit_code == 0
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["variables"]["value"] == "{}"


# --- 2b: structural mutations ---


class TestColumnCreate:
    def test_minimal(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_column": {"id": "priority", "title": "Priority", "type": "status"}}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "create",
                "--board",
                "42",
                "--title",
                "Priority",
                "--type",
                "status",
            ],
        )
        assert result.exit_code == 0, result.stdout
        body = json.loads(httpx_mock.get_requests()[-1].content)
        v = body["variables"]
        assert v["board"] == 42
        assert v["title"] == "Priority"
        assert v["type"] == "status"
        assert v["description"] is None
        assert v["defaults"] is None
        assert v["id"] is None
        assert v["after"] is None

    def test_with_defaults_gets_json_string(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_column": {"id": "priority"}}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "create",
                "--board",
                "42",
                "--title",
                "P",
                "--type",
                "status",
                "--defaults",
                '{"labels":{"1":"High"}}',
                "--id",
                "priority",
                "--after",
                "status_1",
                "--description",
                "desc",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = json.loads(httpx_mock.get_requests()[-1].content)["variables"]
        # defaults should be a JSON-stringified string, not a dict (§11.4 double-JSON)
        assert isinstance(v["defaults"], str)
        assert json.loads(v["defaults"]) == {"labels": {"1": "High"}}
        assert v["id"] == "priority"
        assert v["after"] == "status_1"
        assert v["description"] == "desc"

    def test_invalid_defaults_json_exits_2(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            [
                "column",
                "create",
                "--board",
                "42",
                "--title",
                "P",
                "--type",
                "status",
                "--defaults",
                "{not json",
            ],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_dry_run(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            [
                "--dry-run",
                "column",
                "create",
                "--board",
                "42",
                "--title",
                "P",
                "--type",
                "status",
            ],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert "create_column" in parsed["query"]
        assert httpx_mock.get_requests() == []


class TestColumnRename:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_title": {"id": "status", "title": "Renamed"}}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "rename",
                "--board",
                "42",
                "--id",
                "status",
                "--title",
                "Renamed",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = json.loads(httpx_mock.get_requests()[-1].content)["variables"]
        assert v == {"board": 42, "col": "status", "title": "Renamed"}

    def test_name_contains_resolves_by_title(self, httpx_mock: HTTPXMock) -> None:
        # Cache is disabled in this test fixture, so the columns fetch is live.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "id": "42",
                            "columns": [
                                {"id": "status", "title": "Status", "type": "status"},
                                {"id": "owner", "title": "Owner", "type": "people"},
                            ],
                        }
                    ]
                }
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_title": {"id": "status", "title": "Workflow"}}),
        )
        result = runner.invoke(
            app,
            [
                "column", "rename",
                "--board", "42",
                "--name-contains", "status",
                "--title", "Workflow",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = json.loads(httpx_mock.get_requests()[-1].content)["variables"]
        assert v == {"board": 42, "col": "status", "title": "Workflow"}


class TestColumnChangeMetadata:
    def test_description(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_metadata": {"id": "status", "description": "x"}}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "change-metadata",
                "--board",
                "42",
                "--id",
                "status",
                "--property",
                "description",
                "--value",
                "x",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = json.loads(httpx_mock.get_requests()[-1].content)["variables"]
        assert v == {
            "board": 42,
            "col": "status",
            "property": "description",
            "value": "x",
        }

    def test_invalid_property(self, httpx_mock: HTTPXMock) -> None:
        # Only title / description are allowed; Typer validates the enum.
        result = runner.invoke(
            app,
            [
                "column",
                "change-metadata",
                "--board",
                "42",
                "--id",
                "status",
                "--property",
                "type",
                "--value",
                "x",
            ],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []


class TestColumnDelete:
    def test_requires_confirmation(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["column", "delete", "--board", "42", "--id", "status"],
            input="n\n",
        )
        assert result.exit_code == 1
        assert httpx_mock.get_requests() == []

    def test_yes_skips_prompt(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_column": {"id": "status", "archived": True}}),
        )
        result = runner.invoke(
            app,
            ["--yes", "column", "delete", "--board", "42", "--id", "status"],
        )
        assert result.exit_code == 0, result.stdout
        v = json.loads(httpx_mock.get_requests()[-1].content)["variables"]
        assert v == {"board": 42, "col": "status"}

    def test_dry_run(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["--yes", "--dry-run", "column", "delete", "--board", "42", "--id", "status"],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert "delete_column" in parsed["query"]
        assert httpx_mock.get_requests() == []
