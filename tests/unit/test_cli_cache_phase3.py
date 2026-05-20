"""Phase 3 cache tests: `board get` against the per-board `board_details`
cache, with live `items_count` merge and bypass on `--with-views` /
`--poll-until`.

Covers hit/miss, `--no-cache`, `--refresh-cache`, the items_count merge
contract, and invalidation on board/column/group/tag mutations.
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
    monkeypatch.setenv("MONDO_NO_CACHE_NOTICE", "1")


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


def _board_details_payload(
    board_id: str = "42",
    *,
    name: str = "Board",
    extra: dict | None = None,
) -> dict:
    """A minimal BOARD_GET-shaped record minus items_count."""
    base: dict = {
        "id": board_id,
        "name": name,
        "description": None,
        "state": "active",
        "board_kind": "public",
        "type": "board",
        "board_folder_id": None,
        "workspace_id": "1",
        "workspace": {"id": "1", "name": "Main"},
        "hierarchy_type": None,
        "updated_at": "2026-05-01T00:00:00Z",
        "permissions": "everyone",
        "owners": [],
        "subscribers": [],
        "top_group": None,
        "groups": [],
        "columns": [],
        "tags": [],
    }
    if extra:
        base.update(extra)
    return base


def _prewarm_board_details(
    tmp_path: Path, board_id: str, payload: dict, *, ttl: int = 900
) -> Path:
    store = CacheStore(
        entity_type="board_details",
        cache_dir=tmp_path / "cache" / "default",
        api_endpoint=ENDPOINT,
        ttl_seconds=ttl,
        scope=board_id,
    )
    store.write([payload])
    return store.path


# -- read paths --------------------------------------------------------------


class TestBoardGetCache:
    def test_cache_hit_merges_items_count(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        _prewarm_board_details(tmp_path, "42", _board_details_payload(name="Cached"))
        # Only the items_count merge query should hit the wire.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "42", "items_count": 17}]}),
        )
        result = runner.invoke(app, ["board", "get", "--id", "42"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["name"] == "Cached"
        assert parsed["items_count"] == 17

    def test_no_cache_forces_live(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        _prewarm_board_details(tmp_path, "42", _board_details_payload(name="Stale"))
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "42", "name": "Live", "items_count": 5}]}),
        )
        result = runner.invoke(app, ["board", "get", "--id", "42", "--no-cache"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["name"] == "Live"

    def test_refresh_cache_refetches_board_get(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        _prewarm_board_details(tmp_path, "42", _board_details_payload(name="Old"))
        # First call is the BOARD_GET refresh; second is the items_count merge.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [_board_details_payload(name="Fresh")]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "42", "items_count": 9}]}),
        )
        result = runner.invoke(
            app, ["board", "get", "--id", "42", "--refresh-cache"]
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["name"] == "Fresh"
        assert parsed["items_count"] == 9

    def test_cache_hit_skips_items_count_when_projection_excludes_it(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        # No `items_count` mock — if the merge ran, pytest-httpx would
        # detect a missing response. Cache hit + `-q` excluding the field
        # must not touch the wire. (`-q` is a root option in this CLI, so
        # it goes before the subcommand.)
        _prewarm_board_details(tmp_path, "42", _board_details_payload(name="Cached"))
        result = runner.invoke(
            app,
            ["-q", "name", "board", "get", "--id", "42"],
        )
        assert result.exit_code == 0, result.stdout
        assert httpx_mock.get_requests() == []

    def test_with_views_bypasses_cache(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        # Even with a hot cache, --with-views must always go live (different
        # selection set).
        _prewarm_board_details(tmp_path, "42", _board_details_payload(name="Stale"))
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            **_board_details_payload(name="Live"),
                            "items_count": 3,
                            "views": [{"id": "v1", "name": "Default", "type": "kanban"}],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(
            app, ["board", "get", "--id", "42", "--with-views"]
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["name"] == "Live"
        assert parsed.get("views") and parsed["views"][0]["id"] == "v1"

    def test_cold_cache_misses_then_serves_subsequent(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        # Cold path: one BOARD_GET + one items_count call.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {**_board_details_payload(name="Live"), "items_count": 4}
                    ]
                }
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "42", "items_count": 4}]}),
        )
        result = runner.invoke(app, ["board", "get", "--id", "42"])
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout)["items_count"] == 4

    def test_dry_run_skips_cache_and_network(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        _prewarm_board_details(tmp_path, "42", _board_details_payload())
        result = runner.invoke(app, ["--dry-run", "board", "get", "--id", "42"])
        assert result.exit_code == 0, result.stdout
        assert httpx_mock.get_requests() == []


# -- invalidation -----------------------------------------------------------


class TestBoardDetailsInvalidation:
    def test_board_update_drops_details(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        details_path = _prewarm_board_details(
            tmp_path, "42", _board_details_payload(name="Cached")
        )
        assert details_path.exists()
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_board": "{\"success\":true}"}),
        )
        result = runner.invoke(
            app,
            ["board", "update", "--id", "42", "--attribute", "name", "--value", "New"],
        )
        assert result.exit_code == 0, result.stdout
        assert not details_path.exists()

    def test_board_archive_drops_details(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        details_path = _prewarm_board_details(
            tmp_path, "42", _board_details_payload()
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"archive_board": {"id": "42"}}),
        )
        result = runner.invoke(
            app, ["--yes", "board", "archive", "--id", "42"]
        )
        assert result.exit_code == 0, result.stdout
        assert not details_path.exists()

    def test_column_create_drops_board_details(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        details_path = _prewarm_board_details(
            tmp_path, "42", _board_details_payload()
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_column": {"id": "new_col", "title": "New"}}),
        )
        result = runner.invoke(
            app,
            ["column", "create", "--board", "42", "--title", "New", "--type", "text"],
        )
        assert result.exit_code == 0, result.stdout
        assert not details_path.exists()

    def test_column_rename_drops_board_details(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        details_path = _prewarm_board_details(
            tmp_path, "42", _board_details_payload()
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_title": {"id": "c"}}),
        )
        result = runner.invoke(
            app,
            [
                "column", "rename",
                "--board", "42",
                "--id", "c",
                "--title", "Renamed",
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert not details_path.exists()

    def test_group_create_drops_board_details(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        details_path = _prewarm_board_details(
            tmp_path, "42", _board_details_payload()
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_group": {"id": "g1", "title": "G1"}}),
        )
        result = runner.invoke(
            app,
            ["group", "create", "--board", "42", "--name", "G1"],
        )
        assert result.exit_code == 0, result.stdout
        assert not details_path.exists()

    def test_tag_create_or_get_drops_board_details(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        details_path = _prewarm_board_details(
            tmp_path, "42", _board_details_payload()
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_or_get_tag": {"id": "t1", "name": "Bug"}}),
        )
        result = runner.invoke(
            app,
            ["tag", "create-or-get", "--name", "Bug", "--board", "42"],
        )
        assert result.exit_code == 0, result.stdout
        assert not details_path.exists()


# -- cache CLI integration --------------------------------------------------


class TestCacheCliKnowsBoardDetails:
    def test_status_board_details_with_scope(self, tmp_path: Path) -> None:
        _prewarm_board_details(tmp_path, "42", _board_details_payload())
        result = runner.invoke(app, ["cache", "status", "board_details"])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert len(rows) == 1
        assert rows[0]["type"] == "board_details"
        assert rows[0]["board"] == "42"

    def test_clear_board_details_by_board(self, tmp_path: Path) -> None:
        path_a = _prewarm_board_details(tmp_path, "42", _board_details_payload())
        path_b = _prewarm_board_details(tmp_path, "99", _board_details_payload(board_id="99"))
        result = runner.invoke(
            app, ["cache", "clear", "board_details", "--board", "42"]
        )
        assert result.exit_code == 0, result.stdout
        assert not path_a.exists()
        assert path_b.exists()
