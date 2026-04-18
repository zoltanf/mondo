"""End-to-end CLI tests for `mondo subitem ...` (Phase 3c)."""

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


class TestList:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "items": [
                        {
                            "id": "1",
                            "name": "Parent",
                            "board": {"id": "42", "name": "B"},
                            "subitems": [
                                {"id": "10", "name": "A", "board": {"id": "99"}},
                                {"id": "11", "name": "B", "board": {"id": "99"}},
                            ],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["subitem", "list", "--parent", "1"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [s["id"] for s in parsed] == ["10", "11"]

    def test_parent_not_found(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"items": []}))
        result = runner.invoke(app, ["subitem", "list", "--parent", "999"])
        assert result.exit_code == 6


class TestGet:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "items": [
                        {
                            "id": "10",
                            "name": "Sub",
                            "board": {"id": "99"},
                            "parent_item": {"id": "1"},
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["subitem", "get", "--id", "10"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["id"] == "10"

    def test_missing_exits_6(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"items": []}))
        result = runner.invoke(app, ["subitem", "get", "--id", "999"])
        assert result.exit_code == 6


class TestCreate:
    def test_minimal(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "create_subitem": {
                        "id": "20",
                        "name": "Hi",
                        "board": {"id": "99"},
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            ["subitem", "create", "--parent", "1", "--name", "Hi"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["parent"] == 1
        assert v["name"] == "Hi"
        assert v["values"] is None

    def test_raw_columns_without_board(self, httpx_mock: HTTPXMock) -> None:
        # No --subitems-board: values pass through as raw strings.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_subitem": {"id": "20"}}),
        )
        result = runner.invoke(
            app,
            [
                "subitem",
                "create",
                "--parent",
                "1",
                "--name",
                "Hi",
                "--column",
                "status9=Done",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        # Codec didn't run — string passthrough
        assert json.loads(v["values"]) == {"status9": "Done"}

    def test_codec_dispatch_with_board(self, httpx_mock: HTTPXMock) -> None:
        # Preflight fetch of the subitems-board columns first, then create.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "id": "99",
                            "name": "SubBoard",
                            "columns": [
                                {
                                    "id": "status9",
                                    "title": "Status",
                                    "type": "status",
                                    "settings_str": "{}",
                                }
                            ],
                        }
                    ]
                }
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_subitem": {"id": "20"}}),
        )
        result = runner.invoke(
            app,
            [
                "subitem",
                "create",
                "--parent",
                "1",
                "--name",
                "Hi",
                "--subitems-board",
                "99",
                "--column",
                "status9=Done",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert json.loads(v["values"]) == {"status9": {"label": "Done"}}


class TestMoveRenameArchive:
    def test_rename(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_item_name": {"id": "10", "name": "Newname"}}),
        )
        result = runner.invoke(
            app,
            [
                "subitem",
                "rename",
                "--id",
                "10",
                "--board",
                "99",
                "--name",
                "Newname",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"board": 99, "id": 10, "name": "Newname"}

    def test_move(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"move_item_to_group": {"id": "10", "group": {"id": "subitems_of_2"}}}),
        )
        result = runner.invoke(
            app,
            [
                "subitem",
                "move",
                "--id",
                "10",
                "--group",
                "subitems_of_2",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"id": 10, "group": "subitems_of_2"}

    def test_archive_confirm(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["subitem", "archive", "--id", "10"],
            input="n\n",
        )
        assert result.exit_code == 1
        assert httpx_mock.get_requests() == []

    def test_archive_yes(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"archive_item": {"id": "10", "state": "archived"}}),
        )
        result = runner.invoke(app, ["--yes", "subitem", "archive", "--id", "10"])
        assert result.exit_code == 0, result.stdout


class TestDelete:
    def test_without_hard_exits_2(self) -> None:
        result = runner.invoke(app, ["--yes", "subitem", "delete", "--id", "10"])
        assert result.exit_code == 2
        assert "--hard" in result.stderr

    def test_hard_and_yes(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_item": {"id": "10", "state": "deleted"}}),
        )
        result = runner.invoke(
            app,
            ["--yes", "subitem", "delete", "--id", "10", "--hard"],
        )
        assert result.exit_code == 0, result.stdout
