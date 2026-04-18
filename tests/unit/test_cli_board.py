"""End-to-end CLI tests for the `mondo board ...` command group."""

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
    reqs = httpx_mock.get_requests()
    assert reqs, "no requests captured"
    return json.loads(reqs[-1].content)


def _bodies(httpx_mock: HTTPXMock) -> list[dict]:
    return [json.loads(r.content) for r in httpx_mock.get_requests()]


# --- list ---


class TestBoardList:
    def test_single_page(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]}),
        )
        result = runner.invoke(app, ["board", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [b["id"] for b in parsed] == ["1", "2"]

    def test_paginates_until_short_page(self, httpx_mock: HTTPXMock) -> None:
        # First page is full (limit=2) → fetcher goes for page 2.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "1"}, {"id": "2"}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "3"}]}),
        )
        result = runner.invoke(app, ["board", "list", "--limit", "2"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [b["id"] for b in parsed] == ["1", "2", "3"]
        bodies = _bodies(httpx_mock)
        assert bodies[0]["variables"]["page"] == 1
        assert bodies[1]["variables"]["page"] == 2

    def test_max_items_truncates(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "1"}, {"id": "2"}, {"id": "3"}]}),
        )
        result = runner.invoke(app, ["board", "list", "--max-items", "2"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert len(parsed) == 2

    def test_name_contains_filters_client_side(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {"id": "1", "name": "Pager Duty"},
                        {"id": "2", "name": "Marketing"},
                        {"id": "3", "name": "pager upgrade"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["board", "list", "--name-contains", "pager"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [b["id"] for b in parsed] == ["1", "3"]

    def test_name_matches_regex(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {"id": "1", "name": "team-alpha"},
                        {"id": "2", "name": "team-beta"},
                        {"id": "3", "name": "other"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["board", "list", "--name-matches", r"^team-\w+$"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [b["id"] for b in parsed] == ["1", "2"]

    def test_name_filters_mutually_exclusive(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["board", "list", "--name-contains", "x", "--name-matches", "y"],
        )
        assert result.exit_code == 2
        # No HTTP should have been made.
        assert httpx_mock.get_requests() == []

    def test_invalid_regex_usage_error(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["board", "list", "--name-matches", "["])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_passes_state_kind_workspace(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": []}))
        result = runner.invoke(
            app,
            [
                "board",
                "list",
                "--state",
                "active",
                "--kind",
                "public",
                "--workspace",
                "42",
                "--workspace",
                "43",
                "--order-by",
                "used_at",
            ],
        )
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert body["variables"]["state"] == "active"
        assert body["variables"]["kind"] == "public"
        assert body["variables"]["workspaceIds"] == [42, 43]
        assert body["variables"]["orderBy"] == "used_at"

    def test_dry_run_no_http(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["--dry-run", "board", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["query"] == "<boards page iterator>"
        assert httpx_mock.get_requests() == []


# --- get ---


class TestBoardGet:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "42", "name": "Roadmap", "state": "active"}]}),
        )
        result = runner.invoke(app, ["board", "get", "--id", "42"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["name"] == "Roadmap"
        assert _last_body(httpx_mock)["variables"] == {"id": 42}

    def test_missing_exits_6(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": []}))
        result = runner.invoke(app, ["board", "get", "--id", "999"])
        assert result.exit_code == 6


# --- create ---


class TestBoardCreate:
    def test_minimal(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "create_board": {
                        "id": "99",
                        "name": "New",
                        "board_kind": "public",
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            ["board", "create", "--name", "New"],
        )
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert body["variables"]["name"] == "New"
        assert body["variables"]["kind"] == "public"

    def test_full_options(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_board": {"id": "1"}}),
        )
        result = runner.invoke(
            app,
            [
                "board",
                "create",
                "--name",
                "X",
                "--kind",
                "private",
                "--description",
                "desc",
                "--workspace",
                "7",
                "--folder",
                "8",
                "--owner",
                "42",
                "--owner",
                "43",
                "--subscriber",
                "51",
                "--empty",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["kind"] == "private"
        assert v["description"] == "desc"
        assert v["workspace"] == 7
        assert v["folder"] == 8
        assert v["ownerIds"] == [42, 43]
        assert v["subscriberIds"] == [51]
        assert v["empty"] is True

    def test_dry_run(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["--dry-run", "board", "create", "--name", "X", "--kind", "public"],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert "create_board" in parsed["query"]
        assert parsed["variables"]["name"] == "X"
        assert httpx_mock.get_requests() == []


# --- update ---


class TestBoardUpdate:
    def test_change_name(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_board": '{"success": true}'}),
        )
        result = runner.invoke(
            app,
            [
                "board",
                "update",
                "--id",
                "42",
                "--attribute",
                "name",
                "--value",
                "Renamed",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"board": 42, "attribute": "name", "value": "Renamed"}


# --- archive ---


class TestBoardArchive:
    def test_archive_requires_yes_when_interactive(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["board", "archive", "--id", "42"], input="n\n")
        assert result.exit_code == 1
        assert "aborted" in result.stdout

    def test_archive_with_yes(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"archive_board": {"id": "42", "state": "archived"}}),
        )
        result = runner.invoke(app, ["--yes", "board", "archive", "--id", "42"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["state"] == "archived"


# --- delete ---


class TestBoardDelete:
    def test_delete_without_hard_exits_2(self) -> None:
        result = runner.invoke(app, ["--yes", "board", "delete", "--id", "42"])
        assert result.exit_code == 2
        assert "--hard" in result.stderr

    def test_delete_with_hard_yes(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_board": {"id": "42", "state": "deleted"}}),
        )
        result = runner.invoke(
            app,
            ["--yes", "board", "delete", "--id", "42", "--hard"],
        )
        assert result.exit_code == 0, result.stdout


# --- duplicate ---


class TestBoardDuplicate:
    def test_default_type(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"duplicate_board": {"board": {"id": "100", "name": "Copy"}}}),
        )
        result = runner.invoke(app, ["board", "duplicate", "--id", "42"])
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["board"] == 42
        assert v["duplicateType"] == "duplicate_board_with_structure"

    def test_with_pulses_and_options(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"duplicate_board": {"board": {"id": "101"}}}),
        )
        result = runner.invoke(
            app,
            [
                "board",
                "duplicate",
                "--id",
                "42",
                "--type",
                "duplicate_board_with_pulses_and_updates",
                "--name",
                "Cloned",
                "--workspace",
                "7",
                "--keep-subscribers",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["duplicateType"] == "duplicate_board_with_pulses_and_updates"
        assert v["name"] == "Cloned"
        assert v["workspace"] == 7
        assert v["keepSubscribers"] is True
