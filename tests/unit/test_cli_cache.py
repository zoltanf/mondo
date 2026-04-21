"""Tests for `mondo cache status/refresh/clear`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from mondo.cache.store import CacheStore
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


def _prewarm_workspaces(tmp_path: Path) -> None:
    """Populate the workspaces cache so `board list` / `doc list` enrichment
    doesn't fire a workspaces fetch that's unrelated to the test's intent."""
    store = CacheStore(
        entity_type="workspaces",
        cache_dir=tmp_path / "cache" / "default",
        api_endpoint=ENDPOINT,
        ttl_seconds=3600,
    )
    store.write([{"id": "1", "name": "Main"}])


# -- status -----------------------------------------------------------------


class TestCacheStatus:
    def test_status_empty_shows_all_cold(self) -> None:
        result = runner.invoke(app, ["cache", "status", ])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert {r["type"] for r in rows} == {"boards", "workspaces", "users", "teams", "docs", "folders"}
        assert all(r["fresh"] is False for r in rows)
        assert all(r["entries"] is None for r in rows)

    def test_status_single_type(self) -> None:
        result = runner.invoke(app, ["cache", "status", "workspaces", ])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert len(rows) == 1
        assert rows[0]["type"] == "workspaces"

    def test_status_folders_type(self) -> None:
        result = runner.invoke(app, ["cache", "status", "folders", ])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert len(rows) == 1
        assert rows[0]["type"] == "folders"

    def test_status_unknown_type_is_usage_error(self) -> None:
        result = runner.invoke(app, ["cache", "status", "nonsense"])
        assert result.exit_code == 2

    def test_status_after_prime_reports_fresh(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        _prewarm_workspaces(tmp_path)
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

    def test_refresh_folders_type(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"folders": [{"id": "1", "name": "Folder A"}]}),
        )
        result = runner.invoke(app, ["cache", "refresh", "folders", ])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert len(rows) == 1
        assert rows[0]["type"] == "folders"
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

    def test_refresh_docs_via_cache_cmd(self, httpx_mock: HTTPXMock) -> None:
        # Priming fans out one docs() call per workspace; queue both stages.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"workspaces": [{"id": "42"}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "1", "object_id": "100", "name": "Spec"}]}),
        )
        result = runner.invoke(app, ["cache", "refresh", "docs"])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert rows[0]["type"] == "docs"
        assert rows[0]["count"] == 1


# -- clear ------------------------------------------------------------------


class TestCacheClear:
    def test_clear_idempotent_when_empty(self) -> None:
        result = runner.invoke(app, ["cache", "clear", ])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert all(r["removed"] is False for r in rows)

    def test_clear_folders_type(self) -> None:
        result = runner.invoke(app, ["cache", "clear", "folders", ])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert len(rows) == 1
        assert rows[0]["type"] == "folders"
        assert rows[0]["removed"] is False

    def test_clear_deletes_file(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        _prewarm_workspaces(tmp_path)
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
        _prewarm_workspaces(tmp_path)
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


# -- columns (per-board scoped cache) ---------------------------------------


COLS_RESPONSE = _ok(
    {
        "boards": [
            {
                "id": "42",
                "name": "B",
                "columns": [
                    {"id": "status", "title": "Status", "type": "status", "archived": False},
                    {"id": "date4", "title": "Due", "type": "date", "archived": False},
                ],
            }
        ]
    }
)


def _prime_columns_cache(
    httpx_mock: HTTPXMock, tmp_path: Path, board_id: int = 42
) -> Path:
    """Warm the columns cache for one board and return the resulting file path."""
    httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
    # `column list` goes through fetch_board_columns which writes the file.
    result = runner.invoke(app, ["column", "list", str(board_id)])
    assert result.exit_code == 0, result.stdout
    return tmp_path / "cache" / "default" / "columns" / f"{board_id}.json"


class TestCacheColumns:
    def test_status_all_includes_no_column_rows_when_cold(self) -> None:
        result = runner.invoke(app, ["cache", "status"])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert {r["type"] for r in rows} == {"boards", "workspaces", "users", "teams", "docs", "folders"}

    def test_status_columns_only_empty_dir(self) -> None:
        result = runner.invoke(app, ["cache", "status", "columns"])
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout) == []

    def test_column_list_writes_cache_then_second_call_is_a_hit(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        cache_file = _prime_columns_cache(httpx_mock, tmp_path)
        assert cache_file.exists()
        # Second invocation should NOT hit the API (no additional mock added).
        result = runner.invoke(app, ["column", "list", "42"])
        assert result.exit_code == 0, result.stdout

    def test_status_reports_cached_board(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        _prime_columns_cache(httpx_mock, tmp_path, board_id=42)
        result = runner.invoke(app, ["cache", "status", "columns"])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert len(rows) == 1
        assert rows[0]["type"] == "columns"
        assert rows[0]["board"] == "42"
        assert rows[0]["fresh"] is True
        assert rows[0]["entries"] == 2

    def test_clear_columns_removes_all_per_board_files(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        cache_file = _prime_columns_cache(httpx_mock, tmp_path, board_id=42)
        assert cache_file.exists()
        result = runner.invoke(app, ["cache", "clear", "columns"])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert rows[0]["type"] == "columns"
        assert rows[0]["removed"] is True
        assert not cache_file.exists()

    def test_clear_columns_with_board_filter(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        _prime_columns_cache(httpx_mock, tmp_path, board_id=42)
        result = runner.invoke(app, ["cache", "clear", "columns", "--board", "42"])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert rows[0]["board"] == "42"

    def test_refresh_columns_requires_known_board(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        _prime_columns_cache(httpx_mock, tmp_path, board_id=42)
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        result = runner.invoke(app, ["cache", "refresh", "columns", "--board", "42"])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert rows[0]["type"] == "columns"
        assert rows[0]["board"] == "42"
        assert rows[0]["count"] == 2

    def test_refresh_all_columns_uses_cached_board_ids(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        _prime_columns_cache(httpx_mock, tmp_path, board_id=42)
        # Refresh without --board should re-fetch the one board already cached.
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        result = runner.invoke(app, ["cache", "refresh", "columns"])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert [r["board"] for r in rows] == ["42"]

    def test_board_flag_rejected_for_non_columns_types(self) -> None:
        result = runner.invoke(
            app, ["cache", "clear", "boards", "--board", "42"]
        )
        assert result.exit_code == 2
        assert "only applies when clearing" in result.stderr or "only applies" in (
            result.stdout + (result.stderr or "")
        )
