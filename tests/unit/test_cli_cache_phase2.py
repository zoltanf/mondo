"""Phase 2 cache tests: `tag list`/`tag get` against the `tags` cache and
`webhook list` against the per-board `webhooks` cache.

Covers cache hit, `--no-cache`, `--refresh-cache`, the `--app-only` bypass
on webhooks (correctness over performance), and best-effort invalidation
on `tag create-or-get` / `webhook create` / `webhook delete`.
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
    scope: str | None = None,
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


# -- tags --------------------------------------------------------------------


class TestTagListCache:
    def test_cache_hit(self, tmp_path: Path, httpx_mock: HTTPXMock) -> None:
        _prewarm(
            tmp_path,
            entity_type="tags",
            entries=[
                {"id": "10", "name": "Bug", "color": "red"},
                {"id": "11", "name": "Feature", "color": "blue"},
            ],
        )
        result = runner.invoke(app, ["tag", "list"])
        assert result.exit_code == 0, result.stdout
        assert httpx_mock.get_requests() == []
        parsed = json.loads(result.stdout)
        assert [t["id"] for t in parsed] == ["10", "11"]

    def test_id_filter_on_cached_data(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        _prewarm(
            tmp_path,
            entity_type="tags",
            entries=[
                {"id": "10", "name": "Bug"},
                {"id": "11", "name": "Feature"},
            ],
        )
        result = runner.invoke(app, ["tag", "list", "--id", "11"])
        assert result.exit_code == 0, result.stdout
        assert httpx_mock.get_requests() == []
        parsed = json.loads(result.stdout)
        assert [t["id"] for t in parsed] == ["11"]

    def test_no_cache_forces_live(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        _prewarm(tmp_path, entity_type="tags", entries=[{"id": "10", "name": "Stale"}])
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"tags": [{"id": "10", "name": "Live"}]}),
        )
        result = runner.invoke(app, ["tag", "list", "--no-cache"])
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout)[0]["name"] == "Live"

    def test_dry_run_skips_cache_and_network(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        _prewarm(tmp_path, entity_type="tags", entries=[{"id": "10", "name": "X"}])
        result = runner.invoke(app, ["--dry-run", "tag", "list"])
        assert result.exit_code == 0, result.stdout
        assert httpx_mock.get_requests() == []


class TestTagGetCache:
    def test_cache_hit(self, tmp_path: Path, httpx_mock: HTTPXMock) -> None:
        _prewarm(
            tmp_path,
            entity_type="tags",
            entries=[{"id": "10", "name": "Bug", "color": "red"}],
        )
        result = runner.invoke(app, ["tag", "get", "--id", "10"])
        assert result.exit_code == 0, result.stdout
        assert httpx_mock.get_requests() == []
        assert json.loads(result.stdout)["name"] == "Bug"

    def test_with_board_bypasses_cache(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        _prewarm(
            tmp_path,
            entity_type="tags",
            entries=[{"id": "10", "name": "Stale"}],
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"tags": [{"id": "10", "name": "Live"}]}),
        )
        result = runner.invoke(app, ["tag", "get", "--id", "10", "--board", "42"])
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout)["name"] == "Live"


class TestTagCreateOrGetInvalidatesCache:
    def test_create_drops_tags_cache(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        cache_path = _prewarm(
            tmp_path,
            entity_type="tags",
            entries=[{"id": "10", "name": "Bug"}],
        )
        assert cache_path.exists()
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_or_get_tag": {"id": "20", "name": "NewTag"}}),
        )
        result = runner.invoke(
            app, ["tag", "create-or-get", "--name", "NewTag", "--board", "42"]
        )
        assert result.exit_code == 0, result.stdout
        assert not cache_path.exists()


# -- webhooks (per-board scope) ---------------------------------------------


class TestWebhookListCache:
    def test_cache_hit(self, tmp_path: Path, httpx_mock: HTTPXMock) -> None:
        _prewarm(
            tmp_path,
            entity_type="webhooks",
            scope="42",
            entries=[
                {"id": "1", "board_id": "42", "event": "create_item"},
                {"id": "2", "board_id": "42", "event": "change_column_value"},
            ],
        )
        result = runner.invoke(app, ["webhook", "list", "--board", "42"])
        assert result.exit_code == 0, result.stdout
        assert httpx_mock.get_requests() == []
        parsed = json.loads(result.stdout)
        assert [w["id"] for w in parsed] == ["1", "2"]

    def test_no_cache(self, tmp_path: Path, httpx_mock: HTTPXMock) -> None:
        _prewarm(
            tmp_path,
            entity_type="webhooks",
            scope="42",
            entries=[{"id": "1", "board_id": "42", "event": "create_item"}],
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "webhooks": [
                        {"id": "9", "board_id": "42", "event": "create_item"}
                    ]
                }
            ),
        )
        result = runner.invoke(
            app, ["webhook", "list", "--board", "42", "--no-cache"]
        )
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout)[0]["id"] == "9"

    def test_app_only_bypasses_cache(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        # Even with a hot cache, --app-only must hit the wire — the cached
        # unscoped set can't be filtered down to app-only correctness.
        _prewarm(
            tmp_path,
            entity_type="webhooks",
            scope="42",
            entries=[{"id": "1", "board_id": "42", "event": "create_item"}],
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "webhooks": [
                        {"id": "7", "board_id": "42", "event": "create_item"}
                    ]
                }
            ),
        )
        result = runner.invoke(
            app, ["webhook", "list", "--board", "42", "--app-only"]
        )
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout)[0]["id"] == "7"


class TestWebhookMutationInvalidations:
    def test_create_drops_scope_file(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        scope_path = _prewarm(
            tmp_path,
            entity_type="webhooks",
            scope="42",
            entries=[{"id": "1", "board_id": "42", "event": "create_item"}],
        )
        assert scope_path.exists()
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {"create_webhook": {"id": "99", "board_id": "42", "event": "create_item"}}
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
                "https://x.example/hook",
                "--event",
                "create_item",
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert not scope_path.exists()

    def test_delete_wildcard_drops_all_webhook_scopes(
        self, tmp_path: Path, httpx_mock: HTTPXMock
    ) -> None:
        scope_a = _prewarm(
            tmp_path,
            entity_type="webhooks",
            scope="42",
            entries=[{"id": "1", "board_id": "42", "event": "create_item"}],
        )
        scope_b = _prewarm(
            tmp_path,
            entity_type="webhooks",
            scope="99",
            entries=[{"id": "2", "board_id": "99", "event": "create_item"}],
        )
        assert scope_a.exists() and scope_b.exists()
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_webhook": {"id": "1", "board_id": "42"}}),
        )
        result = runner.invoke(app, ["--yes", "webhook", "delete", "--id", "1"])
        assert result.exit_code == 0, result.stdout
        assert not scope_a.exists()
        assert not scope_b.exists()


# -- cache CLI integration --------------------------------------------------


class TestCacheCliCoversNewEntities:
    def test_status_lists_new_single_file_types(self) -> None:
        result = runner.invoke(app, ["cache", "status"])
        assert result.exit_code == 0, result.stdout
        types = {r["type"] for r in json.loads(result.stdout)}
        assert "tags" in types
        # webhooks is scoped — only shows per-board rows when files exist;
        # an empty cache produces zero rows for it.

    def test_status_webhooks_with_scope(self, tmp_path: Path) -> None:
        _prewarm(
            tmp_path,
            entity_type="webhooks",
            scope="42",
            entries=[{"id": "1", "board_id": "42", "event": "create_item"}],
        )
        result = runner.invoke(app, ["cache", "status", "webhooks"])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert len(rows) == 1
        assert rows[0]["type"] == "webhooks"
        assert rows[0]["board"] == "42"

    def test_clear_tags(self, tmp_path: Path) -> None:
        cache_path = _prewarm(
            tmp_path, entity_type="tags", entries=[{"id": "10", "name": "Bug"}]
        )
        assert cache_path.exists()
        result = runner.invoke(app, ["cache", "clear", "tags"])
        assert result.exit_code == 0, result.stdout
        assert not cache_path.exists()

    def test_clear_webhooks_by_board(self, tmp_path: Path) -> None:
        scope_a = _prewarm(
            tmp_path,
            entity_type="webhooks",
            scope="42",
            entries=[{"id": "1"}],
        )
        scope_b = _prewarm(
            tmp_path,
            entity_type="webhooks",
            scope="99",
            entries=[{"id": "2"}],
        )
        result = runner.invoke(app, ["cache", "clear", "webhooks", "--board", "42"])
        assert result.exit_code == 0, result.stdout
        assert not scope_a.exists()
        assert scope_b.exists()  # unaffected
