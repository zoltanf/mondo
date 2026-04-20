"""End-to-end CLI tests for `mondo team ...` (Phase 3b)."""

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


def _last_body(httpx_mock: HTTPXMock) -> dict:
    return json.loads(httpx_mock.get_requests()[-1].content)


class TestList:
    def test_all(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "teams": [
                        {"id": "1", "name": "Eng"},
                        {"id": "2", "name": "Ops"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["team", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [t["id"] for t in parsed] == ["1", "2"]
        v = _last_body(httpx_mock)["variables"]
        assert v == {"ids": None}

    def test_filter_by_ids(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"teams": [{"id": "1", "name": "Eng"}]}),
        )
        result = runner.invoke(app, ["team", "list", "--id", "1", "--id", "2"])
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"ids": [1, 2]}


class TestGet:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "teams": [
                        {
                            "id": "7",
                            "name": "Eng",
                            "users": [{"id": "1", "name": "A"}],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["team", "get", "--id", "7"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["name"] == "Eng"

    def test_missing_exits_6(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"teams": []}))
        result = runner.invoke(app, ["team", "get", "--id", "999"])
        assert result.exit_code == 6


class TestCreate:
    def test_minimal(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_team": {"id": "10", "name": "New"}}),
        )
        result = runner.invoke(app, ["team", "create", "--name", "New"])
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["input"] == {"name": "New"}
        assert v["options"] is None

    def test_full_options(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_team": {"id": "10"}}),
        )
        result = runner.invoke(
            app,
            [
                "team",
                "create",
                "--name",
                "G",
                "--subscriber",
                "1",
                "--subscriber",
                "2",
                "--parent-team",
                "3",
                "--guest-team",
                "--allow-empty",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["input"] == {
            "name": "G",
            "subscriber_ids": [1, 2],
            "parent_team_id": 3,
            "is_guest_team": True,
        }
        assert v["options"] == {"allow_empty_team": True}


class TestDelete:
    def test_without_hard_exits_2(self) -> None:
        result = runner.invoke(app, ["--yes", "team", "delete", "--id", "7"])
        assert result.exit_code == 2
        assert "--hard" in result.stderr

    def test_hard_with_yes(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_team": {"id": "7", "name": "Gone"}}),
        )
        result = runner.invoke(app, ["--yes", "team", "delete", "--id", "7", "--hard"])
        assert result.exit_code == 0, result.stdout


class TestMembership:
    def test_add_users(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "add_users_to_team": {
                        "successful_users": [{"id": "1"}, {"id": "2"}],
                        "failed_users": [],
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            [
                "team",
                "add-users",
                "--id",
                "7",
                "--user",
                "1",
                "--user",
                "2",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"team": 7, "users": [1, 2]}

    def test_remove_users(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "remove_users_from_team": {
                        "successful_users": [{"id": "1"}],
                        "failed_users": [],
                    }
                }
            ),
        )
        result = runner.invoke(app, ["team", "remove-users", "--id", "7", "--user", "1"])
        assert result.exit_code == 0, result.stdout


class TestOwners:
    def test_assign_owners(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "assign_team_owners": {
                        "successful_users": [{"id": "1"}],
                        "failed_users": [],
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            ["team", "assign-owners", "--id", "7", "--user", "1"],
        )
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert "assign_team_owners" in body["query"]

    def test_remove_owners(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "remove_team_owners": {
                        "successful_users": [{"id": "1"}],
                        "failed_users": [],
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            ["team", "remove-owners", "--id", "7", "--user", "1"],
        )
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert "remove_team_owners" in body["query"]
