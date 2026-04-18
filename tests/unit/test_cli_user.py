"""End-to-end CLI tests for `mondo user ...` (Phase 3a)."""

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


# --- list ---


class TestList:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "users": [
                        {"id": "1", "name": "Alice", "email": "a@x.com"},
                        {"id": "2", "name": "Bob", "email": "b@x.com"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["user", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [u["name"] for u in parsed] == ["Alice", "Bob"]

    def test_filters_passed_through(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"users": []}))
        result = runner.invoke(
            app,
            [
                "user",
                "list",
                "--kind",
                "non_guests",
                "--email",
                "a@x.com",
                "--email",
                "b@x.com",
                "--name",
                "Ali",
                "--non-active",
                "--newest-first",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["kind"] == "non_guests"
        assert v["emails"] == ["a@x.com", "b@x.com"]
        assert v["name"] == "Ali"
        assert v["nonActive"] is True
        assert v["newestFirst"] is True

    def test_dry_run(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["--dry-run", "user", "list"])
        assert result.exit_code == 0, result.stdout
        assert "users" in result.stdout
        assert httpx_mock.get_requests() == []


# --- get ---


class TestGet:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"users": [{"id": "42", "name": "Alice", "email": "a@x.com"}]}),
        )
        result = runner.invoke(app, ["user", "get", "--id", "42"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["name"] == "Alice"
        v = _last_body(httpx_mock)["variables"]
        assert v == {"ids": [42]}

    def test_missing_exits_6(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"users": []}))
        result = runner.invoke(app, ["user", "get", "--id", "999"])
        assert result.exit_code == 6


# --- deactivate / activate ---


class TestDeactivate:
    def test_requires_confirmation(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["user", "deactivate", "--user", "1"], input="n\n")
        assert result.exit_code == 1
        assert httpx_mock.get_requests() == []

    def test_yes_multiple_users(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "deactivate_users": {
                        "deactivated_users": [{"id": "1", "enabled": False}],
                        "errors": [],
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            ["--yes", "user", "deactivate", "--user", "1", "--user", "2"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"ids": [1, 2]}


class TestActivate:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "activate_users": {
                        "activated_users": [{"id": "1", "enabled": True}],
                        "errors": [],
                    }
                }
            ),
        )
        result = runner.invoke(app, ["user", "activate", "--user", "1"])
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"ids": [1]}


# --- update-role ---


class TestUpdateRole:
    def test_admin_routes_to_admins_mutation(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "update_multiple_users_as_admins": {
                        "updated_users": [{"id": "1", "is_admin": True}],
                        "errors": [],
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            ["user", "update-role", "--user", "1", "--role", "admin"],
        )
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert "update_multiple_users_as_admins" in body["query"]

    def test_member(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "update_multiple_users_as_members": {
                        "updated_users": [],
                        "errors": [],
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            ["user", "update-role", "--user", "1", "--role", "member"],
        )
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert "update_multiple_users_as_members" in body["query"]

    def test_guest(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "update_multiple_users_as_guests": {
                        "updated_users": [],
                        "errors": [],
                    }
                }
            ),
        )
        result = runner.invoke(app, ["user", "update-role", "--user", "1", "--role", "guest"])
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert "update_multiple_users_as_guests" in body["query"]

    def test_viewer(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "update_multiple_users_as_viewers": {
                        "updated_users": [],
                        "errors": [],
                    }
                }
            ),
        )
        result = runner.invoke(app, ["user", "update-role", "--user", "1", "--role", "viewer"])
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert "update_multiple_users_as_viewers" in body["query"]

    def test_invalid_role_exit_2(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["user", "update-role", "--user", "1", "--role", "owner"],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []


# --- team membership ---


class TestTeamMembership:
    def test_add_to_team(self, httpx_mock: HTTPXMock) -> None:
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
                "user",
                "add-to-team",
                "--team",
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

    def test_remove_from_team(self, httpx_mock: HTTPXMock) -> None:
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
        result = runner.invoke(
            app,
            ["user", "remove-from-team", "--team", "7", "--user", "1"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"team": 7, "users": [1]}
