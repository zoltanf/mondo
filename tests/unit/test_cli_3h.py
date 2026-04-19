"""End-to-end CLI tests for Phase 3h: activity / folder / favorite / tag."""

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
    return json.loads(httpx_mock.get_requests()[-1].content)


# --- activity ---


class TestActivity:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "id": "42",
                            "activity_logs": [
                                {
                                    "id": "a1",
                                    "event": "change_column_value",
                                    "user_id": "1",
                                },
                                {
                                    "id": "a2",
                                    "event": "create_item",
                                    "user_id": "1",
                                },
                            ],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["activity", "board", "--board", "42"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [log["id"] for log in parsed] == ["a1", "a2"]

    def test_filters(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "42", "activity_logs": []}]}),
        )
        result = runner.invoke(
            app,
            [
                "activity",
                "board",
                "--board",
                "42",
                "--since",
                "2026-04-01T00:00:00Z",
                "--until",
                "2026-04-18T23:59:59Z",
                "--user",
                "1",
                "--user",
                "2",
                "--item",
                "100",
                "--group",
                "topics",
                "--column",
                "status",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["fromDate"] == "2026-04-01T00:00:00Z"
        assert v["toDate"] == "2026-04-18T23:59:59Z"
        assert v["userIds"] == [1, 2]
        assert v["itemIds"] == [100]
        assert v["groupIds"] == ["topics"]
        assert v["columnIds"] == ["status"]

    def test_board_not_found(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": []}))
        result = runner.invoke(app, ["activity", "board", "--board", "999"])
        assert result.exit_code == 6


# --- folder ---


class TestFolderList:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "folders": [
                        {"id": "1", "name": "Eng"},
                        {"id": "2", "name": "Ops"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["folder", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [f["id"] for f in parsed] == ["1", "2"]

    def test_workspace_filter(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"folders": []}))
        result = runner.invoke(
            app,
            ["folder", "list", "--workspace", "42", "--workspace", "43"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["workspaceIds"] == [42, 43]


class TestFolderGet:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"folders": [{"id": "7", "name": "Eng"}]}),
        )
        result = runner.invoke(app, ["folder", "get", "--id", "7"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["name"] == "Eng"

    def test_missing_exits_6(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"folders": []}))
        result = runner.invoke(app, ["folder", "get", "--id", "999"])
        assert result.exit_code == 6


class TestFolderCreate:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_folder": {"id": "7", "name": "New"}}),
        )
        result = runner.invoke(
            app,
            [
                "folder",
                "create",
                "--name",
                "New",
                "--workspace",
                "42",
                "--color",
                "DONE_GREEN",
                "--parent",
                "3",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["name"] == "New"
        assert v["workspace"] == 42
        assert v["color"] == "DONE_GREEN"
        assert v["parent"] == 3


class TestFolderUpdate:
    def test_requires_at_least_one_attr(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["folder", "update", "--id", "7"])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_name_only(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_folder": {"id": "7", "name": "Renamed"}}),
        )
        result = runner.invoke(app, ["folder", "update", "--id", "7", "--name", "Renamed"])
        assert result.exit_code == 0, result.stdout

    def test_position_json(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_folder": {"id": "7"}}),
        )
        result = runner.invoke(
            app,
            [
                "folder",
                "update",
                "--id",
                "7",
                "--position",
                '{"object_id":8,"object_type":"Folder","is_after":true}',
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["position"] == {
            "object_id": 8,
            "object_type": "Folder",
            "is_after": True,
        }

    def test_position_invalid_json(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["folder", "update", "--id", "7", "--position", "{not json"],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []


class TestFolderDelete:
    def test_without_hard_exits_2(self) -> None:
        result = runner.invoke(app, ["--yes", "folder", "delete", "--id", "7"])
        assert result.exit_code == 2

    def test_hard_yes(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_folder": {"id": "7", "name": "Eng"}}),
        )
        result = runner.invoke(app, ["--yes", "folder", "delete", "--id", "7", "--hard"])
        assert result.exit_code == 0, result.stdout


# --- favorite ---


class TestFavoriteList:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "favorites": [
                        {"id": "1", "type": "BOARD", "entity_id": "42"},
                        {"id": "2", "type": "DOC", "entity_id": "99"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["favorite", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [f["id"] for f in parsed] == ["1", "2"]

    def test_dry_run(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["--dry-run", "favorite", "list"])
        assert result.exit_code == 0, result.stdout
        assert httpx_mock.get_requests() == []


# --- tag ---


class TestTag:
    def test_list(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "tags": [
                        {"id": "1", "name": "urgent", "color": "red"},
                        {"id": "2", "name": "blocked", "color": "yellow"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["tag", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [t["name"] for t in parsed] == ["urgent", "blocked"]

    def test_list_filter(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"tags": []}))
        result = runner.invoke(app, ["tag", "list", "--id", "1", "--id", "2"])
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"ids": [1, 2]}

    def test_get(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"tags": [{"id": "1", "name": "urgent"}]}),
        )
        result = runner.invoke(app, ["tag", "get", "--id", "1"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["id"] == "1"

    def test_get_missing_exit_6(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"tags": []}))
        result = runner.invoke(app, ["tag", "get", "--id", "999"])
        assert result.exit_code == 6

    def test_create_or_get(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_or_get_tag": {"id": "3", "name": "new"}}),
        )
        result = runner.invoke(
            app,
            ["tag", "create-or-get", "--name", "new", "--board", "42"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"name": "new", "board": 42}
