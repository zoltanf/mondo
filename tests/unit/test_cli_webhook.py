"""End-to-end CLI tests for `mondo webhook ...` (Phase 3f)."""

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
                    "webhooks": [
                        {
                            "id": "1",
                            "board_id": "42",
                            "event": "create_item",
                        },
                        {
                            "id": "2",
                            "board_id": "42",
                            "event": "change_column_value",
                        },
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["webhook", "list", "--board", "42"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [w["id"] for w in parsed] == ["1", "2"]
        v = _last_body(httpx_mock)["variables"]
        assert v == {"board": 42, "appOnly": None}

    def test_app_only(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"webhooks": []}))
        result = runner.invoke(app, ["webhook", "list", "--board", "42", "--app-only"])
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["appOnly"] is True


class TestCreate:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "create_webhook": {
                        "id": "123",
                        "board_id": "42",
                        "event": "create_item",
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            [
                "webhook",
                "create",
                "--board",
                "42",
                "--url",
                "https://example.com/hook",
                "--event",
                "create_item",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {
            "board": 42,
            "url": "https://example.com/hook",
            "event": "create_item",
            "config": None,
        }

    def test_with_config(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_webhook": {"id": "123"}}),
        )
        result = runner.invoke(
            app,
            [
                "webhook",
                "create",
                "--board",
                "42",
                "--url",
                "https://example.com/hook",
                "--event",
                "change_specific_column_value",
                "--config",
                '{"columnId":"status"}',
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["config"] == {"columnId": "status"}

    def test_invalid_config_exit_2(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            [
                "webhook",
                "create",
                "--board",
                "42",
                "--url",
                "https://x.example",
                "--event",
                "create_item",
                "--config",
                "{not json",
            ],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []


class TestDelete:
    def test_requires_confirmation(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["webhook", "delete", "--id", "1"], input="n\n")
        assert result.exit_code == 1
        assert httpx_mock.get_requests() == []

    def test_yes(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_webhook": {"id": "1", "board_id": "42"}}),
        )
        result = runner.invoke(app, ["--yes", "webhook", "delete", "--id", "1"])
        assert result.exit_code == 0, result.stdout
