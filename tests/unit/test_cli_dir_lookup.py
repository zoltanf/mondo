"""Tests for `<entity> get` short-circuiting through the directory cache.

Covers `workspace get`, `folder get`, and `team get` — the three GETs whose
payload shape matches the corresponding directory entry. Each test verifies:

* prewarmed cache → no network call, entry served from cache;
* `--no-cache` → forces live fetch even with a populated cache;
* `--refresh-cache` → ignores cached entries, refetches the full directory;
* cache populated but target id absent → falls through to a single-entity
  live fetch.
"""

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
    # Silence the cache: hit provenance — we assert on it explicitly when needed.
    monkeypatch.setenv("MONDO_NO_CACHE_NOTICE", "1")


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


def _prewarm(
    tmp_path: Path,
    *,
    entity_type: str,
    entries: list[dict],
    scope: str | None = None,
) -> Path:
    store = CacheStore(
        entity_type=entity_type,
        cache_dir=tmp_path / "cache" / "default",
        api_endpoint=ENDPOINT,
        ttl_seconds=3600,
        scope=scope,
    )
    store.write(entries)
    return store.path


# -- workspace get -----------------------------------------------------------


class TestWorkspaceGetCache:
    def test_cache_hit_no_network(self, tmp_path: Path, httpx_mock: HTTPXMock) -> None:
        _prewarm(
            tmp_path,
            entity_type="workspaces",
            entries=[{"id": "7", "name": "Eng", "kind": "open"}],
        )
        result = runner.invoke(app, ["workspace", "get", "--id", "7"])
        assert result.exit_code == 0, result.stdout
        assert httpx_mock.get_requests() == []
        parsed = json.loads(result.stdout)
        assert parsed["name"] == "Eng"

    def test_no_cache_forces_live(self, tmp_path: Path, httpx_mock: HTTPXMock) -> None:
        _prewarm(
            tmp_path,
            entity_type="workspaces",
            entries=[{"id": "7", "name": "Stale", "kind": "open"}],
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"workspaces": [{"id": "7", "name": "Live"}]}),
        )
        result = runner.invoke(app, ["workspace", "get", "--id", "7", "--no-cache"])
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout)["name"] == "Live"

    def test_refresh_cache_refetches_directory(self, tmp_path: Path, httpx_mock: HTTPXMock) -> None:
        _prewarm(
            tmp_path,
            entity_type="workspaces",
            entries=[{"id": "7", "name": "Old", "kind": "open"}],
        )
        # `get_workspaces` paginates via the page query. With a single-record
        # response, `iter_boards_page` returns on `len(records) < page_size`.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"workspaces": [{"id": "7", "name": "Fresh", "kind": "open"}]}),
        )
        result = runner.invoke(app, ["workspace", "get", "--id", "7", "--refresh-cache"])
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout)["name"] == "Fresh"

    def test_cache_present_id_absent_falls_through_live(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        _prewarm(
            tmp_path,
            entity_type="workspaces",
            entries=[{"id": "7", "name": "Eng", "kind": "open"}],
        )
        # Asking for id 99 — not in the cached directory; should fall through
        # to a single-entity WORKSPACE_GET.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"workspaces": [{"id": "99", "name": "JustCreated"}]}),
        )
        result = runner.invoke(app, ["workspace", "get", "--id", "99"])
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout)["name"] == "JustCreated"

    def test_no_cache_and_refresh_cache_mutex(self) -> None:
        result = runner.invoke(
            app,
            ["workspace", "get", "--id", "7", "--no-cache", "--refresh-cache"],
        )
        assert result.exit_code == 2

    def test_cache_disabled_globally_goes_live(
        self, tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MONDO_CACHE_ENABLED", "false")
        _prewarm(
            tmp_path,
            entity_type="workspaces",
            entries=[{"id": "7", "name": "Stale"}],
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"workspaces": [{"id": "7", "name": "Live"}]}),
        )
        result = runner.invoke(app, ["workspace", "get", "--id", "7"])
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout)["name"] == "Live"


# -- team get ---------------------------------------------------------------


class TestTeamGetCache:
    def test_cache_hit_no_network(self, tmp_path: Path, httpx_mock: HTTPXMock) -> None:
        _prewarm(
            tmp_path,
            entity_type="teams",
            entries=[
                {"id": "42", "name": "Squad", "is_guest": False, "users": [], "owners": []},
            ],
        )
        result = runner.invoke(app, ["team", "get", "--id", "42"])
        assert result.exit_code == 0, result.stdout
        assert httpx_mock.get_requests() == []
        assert json.loads(result.stdout)["name"] == "Squad"

    def test_dry_run_skips_cache_and_network(self, tmp_path: Path, httpx_mock: HTTPXMock) -> None:
        _prewarm(tmp_path, entity_type="teams", entries=[{"id": "42", "name": "Squad"}])
        result = runner.invoke(app, ["--dry-run", "team", "get", "--id", "42"])
        assert result.exit_code == 0, result.stdout
        assert httpx_mock.get_requests() == []
        assert "teams" in result.stdout  # query string emitted

    def test_no_cache_forces_live(self, tmp_path: Path, httpx_mock: HTTPXMock) -> None:
        _prewarm(tmp_path, entity_type="teams", entries=[{"id": "42", "name": "Stale"}])
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"teams": [{"id": "42", "name": "Live"}]}),
        )
        result = runner.invoke(app, ["team", "get", "--id", "42", "--no-cache"])
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout)["name"] == "Live"


# -- folder get -------------------------------------------------------------


class TestFolderGetCache:
    def test_cache_hit_no_network(self, tmp_path: Path, httpx_mock: HTTPXMock) -> None:
        _prewarm(
            tmp_path,
            entity_type="folders",
            entries=[
                {
                    "id": "100",
                    "name": "Projects",
                    "color": None,
                    "workspace_id": "1",
                    "workspace_name": "Main",
                    "parent_id": None,
                    "parent_name": None,
                    "owner_id": "5",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
        )
        result = runner.invoke(app, ["folder", "get", "--id", "100"])
        assert result.exit_code == 0, result.stdout
        assert httpx_mock.get_requests() == []
        assert json.loads(result.stdout)["name"] == "Projects"

    def test_dry_run_skips_cache_and_network(self, tmp_path: Path, httpx_mock: HTTPXMock) -> None:
        _prewarm(tmp_path, entity_type="folders", entries=[{"id": "100", "name": "P"}])
        result = runner.invoke(app, ["--dry-run", "folder", "get", "--id", "100"])
        assert result.exit_code == 0, result.stdout
        assert httpx_mock.get_requests() == []

    def test_cache_present_id_absent_falls_through_live(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        _prewarm(
            tmp_path,
            entity_type="folders",
            entries=[{"id": "100", "name": "Old", "workspace_id": "1"}],
        )
        # Asking for id 999 — not in the cache; live fetch should return
        # the nested-shape FOLDER_GET payload and the CLI normalizes it.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "folders": [
                        {
                            "id": "999",
                            "name": "Fresh",
                            "color": None,
                            "created_at": "2026-05-01T00:00:00Z",
                            "owner_id": "5",
                            "parent": None,
                            "workspace": {"id": "1", "name": "Main"},
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["folder", "get", "--id", "999"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["name"] == "Fresh"
        assert parsed["workspace_id"] == "1"
