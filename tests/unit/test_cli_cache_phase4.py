"""Phase 4 cache tests: short-TTL per-entity caches for items, subitems,
updates, and doc bodies.

Verifies cache hit/miss/refresh/no-cache contracts plus best-effort
invalidation on the canonical mutation paths.
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


def _prewarm(
    tmp_path: Path,
    *,
    entity_type: str,
    entries: list[dict],
    scope: str,
    ttl: int = 3600,
) -> Path:
    store = CacheStore(
        entity_type=entity_type,
        cache_dir=tmp_path / "cache" / "default",
        api_endpoint=ENDPOINT,
        ttl_seconds=ttl,
        scope=scope,
    )
    store.write(entries)
    return store.path


# -- items / subitems -------------------------------------------------------


class TestItemGetCache:
    def test_cache_hit(self, tmp_path: Path, httpx_mock: HTTPXMock) -> None:
        _prewarm(
            tmp_path,
            entity_type="items",
            scope="123",
            entries=[{"id": "123", "name": "Cached", "column_values": []}],
        )
        result = runner.invoke(app, ["item", "get", "--id", "123"])
        assert result.exit_code == 0, result.stdout
        assert httpx_mock.get_requests() == []
        assert json.loads(result.stdout)["name"] == "Cached"

    def test_no_cache_forces_live(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        _prewarm(
            tmp_path,
            entity_type="items",
            scope="123",
            entries=[{"id": "123", "name": "Stale"}],
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"items": [{"id": "123", "name": "Live"}]}),
        )
        result = runner.invoke(app, ["item", "get", "--id", "123", "--no-cache"])
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout)["name"] == "Live"

    def test_include_updates_bypasses_cache(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        _prewarm(
            tmp_path,
            entity_type="items",
            scope="123",
            entries=[{"id": "123", "name": "Stale"}],
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {"items": [{"id": "123", "name": "Live", "updates": []}]}
            ),
        )
        result = runner.invoke(
            app, ["item", "get", "--id", "123", "--include-updates"]
        )
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout)["name"] == "Live"


class TestColumnSetInvalidatesItem:
    def test_column_set_drops_items_scope(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        path = _prewarm(
            tmp_path,
            entity_type="items",
            scope="123",
            entries=[{"id": "123", "name": "Cached"}],
        )
        # COLUMN_CONTEXT pre-fetch then CHANGE_COLUMN_VALUE.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "items": [
                        {
                            "id": "123",
                            "board": {
                                "id": "42",
                                "columns": [
                                    {
                                        "id": "text",
                                        "type": "text",
                                        "title": "Text",
                                        "settings_str": "{}",
                                    }
                                ],
                            },
                            "column_values": [{"id": "text", "value": "null"}],
                        }
                    ]
                }
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_value": {"id": "123"}}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "set",
                "--item", "123",
                "--column", "text",
                "--value", "hi",
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert not path.exists()


class TestSubitemListCache:
    def test_cache_hit(self, tmp_path: Path, httpx_mock: HTTPXMock) -> None:
        _prewarm(
            tmp_path,
            entity_type="subitems",
            scope="100",
            entries=[{"id": "200", "name": "Sub1"}, {"id": "201", "name": "Sub2"}],
        )
        result = runner.invoke(app, ["subitem", "list", "--parent", "100"])
        assert result.exit_code == 0, result.stdout
        assert httpx_mock.get_requests() == []
        parsed = json.loads(result.stdout)
        assert [s["id"] for s in parsed] == ["200", "201"]

    def test_subitem_create_drops_parent(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        path = _prewarm(
            tmp_path,
            entity_type="subitems",
            scope="100",
            entries=[{"id": "200", "name": "Sub1"}],
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_subitem": {"id": "999", "name": "New"}}),
        )
        result = runner.invoke(
            app,
            ["subitem", "create", "--parent", "100", "--name", "New"],
        )
        assert result.exit_code == 0, result.stdout
        assert not path.exists()


# -- updates ----------------------------------------------------------------


class TestUpdateListCache:
    def test_cache_hit_with_item(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        _prewarm(
            tmp_path,
            entity_type="updates",
            scope="123",
            entries=[
                {"id": "u1", "text_body": "hello"},
                {"id": "u2", "text_body": "world"},
            ],
        )
        result = runner.invoke(app, ["update", "list", "--item", "123"])
        assert result.exit_code == 0, result.stdout
        assert httpx_mock.get_requests() == []
        parsed = json.loads(result.stdout)
        assert [u["id"] for u in parsed] == ["u1", "u2"]

    def test_update_create_drops_scope(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        path = _prewarm(
            tmp_path,
            entity_type="updates",
            scope="123",
            entries=[{"id": "u1", "text_body": "old"}],
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_update": {"id": "u2"}}),
        )
        result = runner.invoke(
            app,
            ["update", "create", "--item", "123", "--body", "hi"],
        )
        assert result.exit_code == 0, result.stdout
        assert not path.exists()

    def test_update_delete_wildcard_drops_all_updates(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        a = _prewarm(
            tmp_path, entity_type="updates", scope="123", entries=[{"id": "u1"}]
        )
        b = _prewarm(
            tmp_path, entity_type="updates", scope="456", entries=[{"id": "u2"}]
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_update": {"id": "u1"}}),
        )
        result = runner.invoke(
            app, ["--yes", "update", "delete", "--id", "1"]
        )
        assert result.exit_code == 0, result.stdout
        assert not a.exists()
        assert not b.exists()


# -- doc blocks --------------------------------------------------------------


class TestDocGetCache:
    def test_cache_hit_by_id(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        _prewarm(
            tmp_path,
            entity_type="docs_blocks",
            scope="7",
            entries=[
                {
                    "id": "7",
                    "object_id": "70",
                    "name": "Cached Doc",
                    "url": "https://x.example/d/7",
                    "blocks": [{"id": "b1", "type": "normal_text"}],
                }
            ],
        )
        result = runner.invoke(app, ["doc", "get", "--id", "7"])
        assert result.exit_code == 0, result.stdout
        assert httpx_mock.get_requests() == []
        parsed = json.loads(result.stdout)
        assert parsed["name"] == "Cached Doc"
        assert len(parsed["blocks"]) == 1

    def test_doc_rename_drops_doc_blocks(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        path = _prewarm(
            tmp_path,
            entity_type="docs_blocks",
            scope="7",
            entries=[{"id": "7", "name": "Old", "blocks": []}],
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_doc_name": {"id": "7"}}),
        )
        result = runner.invoke(
            app, ["doc", "rename", "--doc", "7", "--name", "New"]
        )
        assert result.exit_code == 0, result.stdout
        assert not path.exists()


# -- cache CLI integration --------------------------------------------------


class TestCacheCliKnowsNewScopes:
    def test_status_shows_items_with_scope(self, tmp_path: Path) -> None:
        _prewarm(
            tmp_path,
            entity_type="items",
            scope="123",
            entries=[{"id": "123", "name": "X"}],
        )
        result = runner.invoke(app, ["cache", "status", "items"])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert len(rows) == 1
        assert rows[0]["type"] == "items"

    def test_clear_items_wipes_scope_files(self, tmp_path: Path) -> None:
        a = _prewarm(
            tmp_path,
            entity_type="items",
            scope="123",
            entries=[{"id": "123"}],
        )
        b = _prewarm(
            tmp_path,
            entity_type="items",
            scope="456",
            entries=[{"id": "456"}],
        )
        result = runner.invoke(app, ["cache", "clear", "items"])
        assert result.exit_code == 0, result.stdout
        assert not a.exists()
        assert not b.exists()

    def test_refresh_items_is_usage_error(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["cache", "refresh", "items"])
        assert result.exit_code == 2, result.stdout
