"""End-to-end CLI tests for `mondo update ...` (Phase 3d)."""

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
    def test_account_wide(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "updates": [
                        {"id": "1", "body": "<p>hi</p>", "item_id": "10"},
                        {"id": "2", "body": "<p>hello</p>", "item_id": "11"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["update", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [u["id"] for u in parsed] == ["1", "2"]

    def test_for_item_paginates(self, httpx_mock: HTTPXMock) -> None:
        # Full page → next page with a short list → terminator.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "items": [
                        {
                            "id": "10",
                            "updates": [{"id": str(i)} for i in range(1, 101)],
                        }
                    ]
                }
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "items": [
                        {"id": "10", "updates": [{"id": "101"}, {"id": "102"}]},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["update", "list", "--item", "10"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert len(parsed) == 102

    def test_item_missing_exits_6(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"items": []}))
        result = runner.invoke(app, ["update", "list", "--item", "999"])
        assert result.exit_code == 6


# --- get ---


class TestGet:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"updates": [{"id": "1", "body": "<p>hi</p>"}]}),
        )
        result = runner.invoke(app, ["update", "get", "--id", "1"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["id"] == "1"

    def test_missing_exits_6(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"updates": []}))
        result = runner.invoke(app, ["update", "get", "--id", "999"])
        assert result.exit_code == 6


# --- create / reply / edit ---


class TestCreate:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_update": {"id": "1", "body": "<p>hi</p>"}}),
        )
        result = runner.invoke(
            app,
            ["update", "create", "--item", "10", "--body", "<p>hi</p>"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"item": 10, "parent": None, "body": "<p>hi</p>"}

    def test_body_required(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["update", "create", "--item", "10"])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_markdown_is_default(self, httpx_mock: HTTPXMock) -> None:
        # Without --html, --body is treated as CommonMark and converted.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_update": {"id": "1"}}),
        )
        result = runner.invoke(
            app,
            ["update", "create", "--item", "10", "--body", "**bold**"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["body"] == "<p><strong>bold</strong></p>\n"

    def test_html_flag_skips_markdown_conversion(self, httpx_mock: HTTPXMock) -> None:
        # `--html` sends the body verbatim, including monday-specific tags.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_update": {"id": "1"}}),
        )
        result = runner.invoke(
            app,
            [
                "update",
                "create",
                "--item",
                "10",
                "--body",
                "**not bold** <mention user=42>x</mention>",
                "--html",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["body"] == "**not bold** <mention user=42>x</mention>"

    def test_markdown_and_html_are_mutually_exclusive(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            [
                "update",
                "create",
                "--item",
                "10",
                "--body",
                "x",
                "--markdown",
                "--html",
            ],
        )
        assert result.exit_code == 2
        assert "mutually exclusive" in result.stderr

    def test_from_file(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        body_path = tmp_path / "body.html"
        body_path.write_text("<p>from file</p>")
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_update": {"id": "1"}}),
        )
        result = runner.invoke(
            app,
            [
                "update",
                "create",
                "--item",
                "10",
                "--from-file",
                str(body_path),
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["body"] == "<p>from file</p>"


class TestReply:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_update": {"id": "99"}}),
        )
        result = runner.invoke(
            app,
            ["update", "reply", "--parent", "1", "--body", "<p>re</p>"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"item": None, "parent": 1, "body": "<p>re</p>"}


class TestEdit:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"edit_update": {"id": "1", "body": "<p>new</p>"}}),
        )
        result = runner.invoke(
            app,
            ["update", "edit", "--id", "1", "--body", "<p>new</p>"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"id": 1, "body": "<p>new</p>"}


# --- delete / like / clear / pin ---


class TestDelete:
    def test_requires_confirmation(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["update", "delete", "--id", "1"], input="n\n")
        assert result.exit_code == 1
        assert httpx_mock.get_requests() == []

    def test_yes(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_update": {"id": "1"}}),
        )
        result = runner.invoke(app, ["--yes", "update", "delete", "--id", "1"])
        assert result.exit_code == 0, result.stdout


class TestLikes:
    def test_like(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"like_update": {"id": "1"}}),
        )
        result = runner.invoke(app, ["update", "like", "--id", "1"])
        assert result.exit_code == 0, result.stdout

    def test_unlike(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"unlike_update": {"id": "1"}}),
        )
        result = runner.invoke(app, ["update", "unlike", "--id", "1"])
        assert result.exit_code == 0, result.stdout


class TestClear:
    def test_requires_confirmation(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["update", "clear", "--item", "10"], input="n\n")
        assert result.exit_code == 1
        assert httpx_mock.get_requests() == []

    def test_yes(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"clear_item_updates": {"id": "10", "name": "x"}}),
        )
        result = runner.invoke(app, ["--yes", "update", "clear", "--item", "10"])
        assert result.exit_code == 0, result.stdout


class TestPin:
    def test_pin(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"pin_to_top": {"id": "1", "item_id": "10"}}),
        )
        result = runner.invoke(
            app,
            ["update", "pin", "--id", "1", "--item", "10"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"item": 10, "update": 1}

    def test_unpin(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"unpin_from_top": {"id": "1"}}),
        )
        result = runner.invoke(
            app,
            ["update", "unpin", "--id", "1", "--item", "10"],
        )
        assert result.exit_code == 0, result.stdout
