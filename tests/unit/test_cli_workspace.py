"""End-to-end CLI tests for the `mondo workspace ...` command group."""

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
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "workspaces": [
                        {"id": "1", "name": "Eng", "kind": "open"},
                        {"id": "2", "name": "Ops", "kind": "closed"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["workspace", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [w["id"] for w in parsed] == ["1", "2"]

    def test_kind_and_state_passed_through(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"workspaces": []}))
        result = runner.invoke(app, ["workspace", "list", "--kind", "open", "--state", "active"])
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["kind"] == "open"
        assert v["state"] == "active"

    def test_dry_run(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["--dry-run", "workspace", "list"])
        assert result.exit_code == 0, result.stdout
        assert "workspaces" in result.stdout
        assert httpx_mock.get_requests() == []


class TestGet:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"workspaces": [{"id": "7", "name": "Eng"}]}),
        )
        result = runner.invoke(app, ["workspace", "get", "--id", "7"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["name"] == "Eng"

    def test_missing_exits_6(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"workspaces": []}))
        result = runner.invoke(app, ["workspace", "get", "--id", "999"])
        assert result.exit_code == 6


class TestCreate:
    def test_defaults_kind_open(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_workspace": {"id": "9", "kind": "open"}}),
        )
        result = runner.invoke(app, ["workspace", "create", "--name", "New"])
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["kind"] == "open"
        assert v["name"] == "New"

    def test_closed_with_description_and_product(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_workspace": {"id": "9"}}),
        )
        result = runner.invoke(
            app,
            [
                "workspace",
                "create",
                "--name",
                "Priv",
                "--kind",
                "closed",
                "--description",
                "x",
                "--product-id",
                "3",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["kind"] == "closed"
        assert v["description"] == "x"
        assert v["accountProductId"] == 3


class TestUpdate:
    def test_requires_at_least_one_attribute(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["workspace", "update", "--id", "7"])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_name_only(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_workspace": {"id": "7", "name": "N2"}}),
        )
        result = runner.invoke(app, ["workspace", "update", "--id", "7", "--name", "N2"])
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"id": 7, "attributes": {"name": "N2"}}

    def test_all_three_attrs(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"update_workspace": {"id": "7"}})
        )
        result = runner.invoke(
            app,
            [
                "workspace",
                "update",
                "--id",
                "7",
                "--name",
                "N",
                "--description",
                "D",
                "--kind",
                "closed",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["attributes"] == {"name": "N", "description": "D", "kind": "closed"}


class TestDelete:
    def test_without_hard_exits_2(self) -> None:
        result = runner.invoke(app, ["--yes", "workspace", "delete", "--id", "7"])
        assert result.exit_code == 2
        assert "--hard" in result.stderr

    def test_hard_and_yes(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"delete_workspace": {"id": "7"}})
        )
        result = runner.invoke(app, ["--yes", "workspace", "delete", "--id", "7", "--hard"])
        assert result.exit_code == 0, result.stdout

    def test_hard_without_yes_prompts_and_aborts(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["workspace", "delete", "--id", "7", "--hard"],
            input="n\n",
        )
        assert result.exit_code == 1
        assert httpx_mock.get_requests() == []


class TestMembership:
    def test_add_user_defaults_subscriber(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"add_users_to_workspace": [{"id": "1", "name": "A"}]}),
        )
        result = runner.invoke(
            app,
            [
                "workspace",
                "add-user",
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
        assert v == {"id": 7, "users": [1, 2], "kind": "subscriber"}

    def test_add_user_owner(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"add_users_to_workspace": []}),
        )
        result = runner.invoke(
            app,
            [
                "workspace",
                "add-user",
                "--id",
                "7",
                "--user",
                "1",
                "--kind",
                "owner",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["kind"] == "owner"

    def test_remove_user(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_users_from_workspace": []}),
        )
        result = runner.invoke(
            app,
            ["workspace", "remove-user", "--id", "7", "--user", "5"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"id": 7, "users": [5]}

    def test_add_team(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"add_teams_to_workspace": []}),
        )
        result = runner.invoke(
            app,
            ["workspace", "add-team", "--id", "7", "--team", "11", "--team", "12"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"id": 7, "teams": [11, 12], "kind": "subscriber"}

    def test_remove_team(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_teams_from_workspace": []}),
        )
        result = runner.invoke(
            app,
            ["workspace", "remove-team", "--id", "7", "--team", "11"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"id": 7, "teams": [11]}
