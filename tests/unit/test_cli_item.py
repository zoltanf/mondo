"""End-to-end CLI tests for the `mondo item ...` command group."""

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


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


def _last_body(httpx_mock: HTTPXMock) -> dict:
    return json.loads(httpx_mock.get_request().content)  # type: ignore[union-attr]


# --- get ---


class TestItemGet:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"items": [{"id": "1", "name": "Test", "state": "active"}]}),
        )
        result = runner.invoke(app, ["item", "get", "--id", "1"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["name"] == "Test"
        body = _last_body(httpx_mock)
        assert body["variables"] == {"id": 1}

    def test_missing_exits_6(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"items": []}))
        result = runner.invoke(app, ["item", "get", "--id", "999"])
        assert result.exit_code == 6

    def test_include_updates_uses_updates_query(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"items": [{"id": "1", "name": "T", "updates": []}]}),
        )
        result = runner.invoke(app, ["item", "get", "--id", "1", "--include-updates"])
        assert result.exit_code == 0
        assert "updates" in _last_body(httpx_mock)["query"]

    def test_include_subitems_uses_subitems_query(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"items": [{"id": "1", "name": "T", "subitems": []}]}),
        )
        result = runner.invoke(app, ["item", "get", "--id", "1", "--include-subitems"])
        assert result.exit_code == 0
        assert "subitems" in _last_body(httpx_mock)["query"]


# --- list ---


class TestItemList:
    def test_single_page(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "items_page": {
                                "cursor": None,
                                "items": [
                                    {"id": "1", "name": "A"},
                                    {"id": "2", "name": "B"},
                                ],
                            }
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["item", "list", "--board", "42"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert [r["id"] for r in parsed] == ["1", "2"]

    def test_paginates(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"items_page": {"cursor": "C", "items": [{"id": "1"}]}}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"next_items_page": {"cursor": None, "items": [{"id": "2"}]}}),
        )
        result = runner.invoke(app, ["item", "list", "--board", "42"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert [r["id"] for r in parsed] == ["1", "2"]
        assert len(httpx_mock.get_requests()) == 2

    def test_max_items(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "items_page": {
                                "cursor": "C",
                                "items": [{"id": "1"}, {"id": "2"}, {"id": "3"}],
                            }
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["item", "list", "--board", "42", "--max-items", "2"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert [r["id"] for r in parsed] == ["1", "2"]
        assert len(httpx_mock.get_requests()) == 1

    def test_filter_builds_rule(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"items_page": {"cursor": None, "items": []}}]}),
        )
        result = runner.invoke(app, ["item", "list", "--board", "42", "--filter", "status=Done"])
        assert result.exit_code == 0
        qp = _last_body(httpx_mock)["variables"]["qp"]
        assert qp["rules"] == [
            {"column_id": "status", "compare_value": ["Done"], "operator": "any_of"}
        ]

    def test_bad_filter_exits_2(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["item", "list", "--board", "42", "--filter", "nobareequals"])
        assert result.exit_code == 2
        assert len(httpx_mock.get_requests()) == 0


# --- create ---


class TestItemCreate:
    def test_minimal(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "99", "name": "New"}}),
        )
        result = runner.invoke(app, ["item", "create", "--board", "42", "--name", "New"])
        assert result.exit_code == 0
        body = _last_body(httpx_mock)
        assert body["variables"]["board"] == 42
        assert body["variables"]["name"] == "New"
        assert body["variables"]["values"] is None

    def test_with_columns_json_encoded(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "99", "name": "New"}}),
        )
        result = runner.invoke(
            app,
            [
                "item",
                "create",
                "--board",
                "42",
                "--name",
                "New",
                "--column",
                "text=Hello",
                "--column",
                'status={"label":"Done"}',
            ],
        )
        assert result.exit_code == 0, result.stdout
        values = json.loads(_last_body(httpx_mock)["variables"]["values"])
        assert values == {"text": "Hello", "status": {"label": "Done"}}

    def test_dry_run_does_not_call_api(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            [
                "--dry-run",
                "item",
                "create",
                "--board",
                "42",
                "--name",
                "Hi",
            ],
        )
        assert result.exit_code == 0
        assert len(httpx_mock.get_requests()) == 0
        # Output contains the mutation and variables
        parsed = json.loads(result.stdout)
        assert "create_item" in parsed["query"]
        assert parsed["variables"]["name"] == "Hi"

    def test_position_relative_method(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "99", "name": "New"}}),
        )
        result = runner.invoke(
            app,
            [
                "item",
                "create",
                "--board",
                "42",
                "--name",
                "New",
                "--position-relative-method",
                "after_at",
                "--relative-to",
                "77",
            ],
        )
        assert result.exit_code == 0
        vars_ = _last_body(httpx_mock)["variables"]
        assert vars_["prm"] == "after_at"
        assert vars_["relto"] == 77


# --- rename / duplicate ---


class TestItemRename:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_item_name": {"id": "1", "name": "New name"}}),
        )
        result = runner.invoke(
            app, ["item", "rename", "--id", "1", "--board", "42", "--name", "New name"]
        )
        assert result.exit_code == 0
        body = _last_body(httpx_mock)
        assert body["variables"] == {"board": 42, "id": 1, "name": "New name"}


class TestItemDuplicate:
    def test_with_updates(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"duplicate_item": {"id": "2", "name": "A copy"}}),
        )
        result = runner.invoke(
            app,
            ["item", "duplicate", "--id", "1", "--board", "42", "--with-updates"],
        )
        assert result.exit_code == 0
        assert _last_body(httpx_mock)["variables"]["with_updates"] is True


# --- archive / delete / move ---


class TestItemArchive:
    def test_requires_confirmation(self, httpx_mock: HTTPXMock) -> None:
        # Pipe stdin: no input → confirmation prompt auto-rejects → exit 1
        result = runner.invoke(app, ["item", "archive", "--id", "1"], input="n\n")
        assert result.exit_code == 1
        assert len(httpx_mock.get_requests()) == 0

    def test_yes_skips_prompt(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"archive_item": {"id": "1", "name": "gone"}}),
        )
        result = runner.invoke(app, ["-y", "item", "archive", "--id", "1"])
        assert result.exit_code == 0

    def test_confirmed_interactive(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"archive_item": {"id": "1", "name": "gone"}}),
        )
        result = runner.invoke(app, ["item", "archive", "--id", "1"], input="y\n")
        assert result.exit_code == 0


class TestItemDelete:
    def test_rejects_without_hard(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["-y", "item", "delete", "--id", "1"])
        assert result.exit_code == 2
        assert len(httpx_mock.get_requests()) == 0

    def test_hard_plus_yes(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_item": {"id": "1", "name": "gone"}}),
        )
        result = runner.invoke(app, ["-y", "item", "delete", "--id", "1", "--hard"])
        assert result.exit_code == 0


class TestItemMove:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"move_item_to_group": {"id": "1", "group": {"id": "g2"}}}),
        )
        result = runner.invoke(app, ["item", "move", "--id", "1", "--group", "topics_two"])
        assert result.exit_code == 0
        body = _last_body(httpx_mock)
        assert body["variables"] == {"id": 1, "group": "topics_two"}
