"""Tests for `mondo cache status/refresh/clear`."""

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
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")
    monkeypatch.setenv("MONDO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MONDO_CACHE_ENABLED", "true")


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


# -- status -----------------------------------------------------------------


class TestCacheStatus:
    def test_status_empty_shows_all_cold(self) -> None:
        result = runner.invoke(app, ["cache", "status", ])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert {r["type"] for r in rows} == {"boards", "workspaces", "users", "teams"}
        assert all(r["fresh"] is False for r in rows)
        assert all(r["entries"] is None for r in rows)

    def test_status_single_type(self) -> None:
        result = runner.invoke(app, ["cache", "status", "workspaces", ])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert len(rows) == 1
        assert rows[0]["type"] == "workspaces"

    def test_status_unknown_type_is_usage_error(self) -> None:
        result = runner.invoke(app, ["cache", "status", "nonsense"])
        assert result.exit_code == 2

    def test_status_after_prime_reports_fresh(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "1", "name": "A", "state": "active"}]}),
        )
        runner.invoke(app, ["board", "list"])

        result = runner.invoke(app, ["cache", "status", "boards", ])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert rows[0]["fresh"] is True
        assert rows[0]["entries"] == 1
        assert rows[0]["fetched_at"] is not None


# -- refresh ----------------------------------------------------------------


class TestCacheRefresh:
    def test_refresh_single_type(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"teams": [{"id": "1", "name": "Platform"}]}),
        )
        result = runner.invoke(app, ["cache", "refresh", "teams", ])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert len(rows) == 1
        assert rows[0]["type"] == "teams"
        assert rows[0]["count"] == 1

    def test_refresh_dry_run_emits_plan(self) -> None:
        result = runner.invoke(
            app, ["--dry-run", "cache", "refresh", "boards", ]
        )
        assert result.exit_code == 0, result.stdout
        plan = json.loads(result.stdout)
        assert plan == [{"type": "boards", "action": "refresh"}]

    def test_refresh_unknown_type_rejected(self) -> None:
        result = runner.invoke(app, ["cache", "refresh", "wat"])
        assert result.exit_code == 2


# -- clear ------------------------------------------------------------------


class TestCacheClear:
    def test_clear_idempotent_when_empty(self) -> None:
        result = runner.invoke(app, ["cache", "clear", ])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert all(r["removed"] is False for r in rows)

    def test_clear_deletes_file(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "1", "name": "A", "state": "active"}]}),
        )
        runner.invoke(app, ["board", "list"])
        cache_file = tmp_path / "cache" / "default" / "boards.json"
        assert cache_file.exists()

        result = runner.invoke(app, ["cache", "clear", "boards", ])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert rows[0]["removed"] is True
        assert not cache_file.exists()

    def test_clear_dry_run_preserves_files(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "1", "name": "A", "state": "active"}]}),
        )
        runner.invoke(app, ["board", "list"])
        cache_file = tmp_path / "cache" / "default" / "boards.json"
        assert cache_file.exists()

        result = runner.invoke(app, ["--dry-run", "cache", "clear", "boards"])
        assert result.exit_code == 0, result.stdout
        # File must still exist
        assert cache_file.exists()
