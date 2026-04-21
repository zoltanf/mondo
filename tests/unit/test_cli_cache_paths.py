"""CLI tests for the cache-enabled code paths on the four list commands,
plus mutation-invalidation checks."""

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


def _prewarm_workspaces(tmp_path: Path) -> None:
    """Lay down a warm workspaces cache so `board list` / `doc list` enrichment
    doesn't trigger a workspaces fetch in tests that don't care about it."""
    store = CacheStore(
        entity_type="workspaces",
        cache_dir=tmp_path / "cache" / "default",
        api_endpoint=ENDPOINT,
        ttl_seconds=3600,
    )
    store.write([{"id": "1", "name": "Main"}, {"id": "42", "name": "Engineering"}, {"id": "43", "name": "Sales"}])


@pytest.fixture(autouse=True)
def _cached_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")
    monkeypatch.setenv("MONDO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MONDO_CACHE_ENABLED", "true")
    _prewarm_workspaces(tmp_path)


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


def _board(board_id: str, name: str, **extra: object) -> dict:
    return {
        "id": board_id,
        "name": name,
        "state": "active",
        "board_kind": "public",
        "workspace_id": "1",
        "updated_at": "2026-04-20T00:00:00Z",
        **extra,
    }


# -- board list: cache-enabled path -----------------------------------------


class TestBoardListCache:
    def test_cold_cache_populates_then_warm_serves(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        # Priming call — walks to an empty page to terminate.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [_board("1", "Alpha"), _board("2", "Beta")]}),
        )

        r1 = runner.invoke(app, ["board", "list"])
        assert r1.exit_code == 0, r1.stdout
        first_requests = len(httpx_mock.get_requests())
        assert first_requests >= 1

        # Cache file exists under the MONDO_CACHE_DIR profile dir.
        cache_file = tmp_path / "cache" / "default" / "boards.json"
        assert cache_file.exists()

        # Warm call: serves entirely from cache, no new HTTP.
        r2 = runner.invoke(app, ["board", "list"])
        assert r2.exit_code == 0, r2.stdout
        assert len(httpx_mock.get_requests()) == first_requests

        parsed = json.loads(r2.stdout)
        assert [b["name"] for b in parsed] == ["Alpha", "Beta"]

    def test_no_cache_bypasses_cache(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [_board("1", "Alpha")]}),
        )
        result = runner.invoke(app, ["board", "list", "--no-cache"])
        assert result.exit_code == 0, result.stdout
        # One HTTP call that matches the original live-path query (has state arg)
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert "boards(" in body["query"]

    def test_refresh_cache_always_fetches(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        # Prime first
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"boards": [_board("1", "A")]})
        )
        runner.invoke(app, ["board", "list"])
        prime_calls = len(httpx_mock.get_requests())

        # With --refresh-cache, expect new fetches even though cache is fresh.
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"boards": [_board("2", "B")]})
        )
        result = runner.invoke(app, ["board", "list", "--refresh-cache"])
        assert result.exit_code == 0, result.stdout
        assert len(httpx_mock.get_requests()) > prime_calls
        parsed = json.loads(result.stdout)
        assert [b["name"] for b in parsed] == ["B"]

    def test_name_fuzzy_filter_on_cached(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        _board("1", "Product Launch"),
                        _board("2", "Engineering Roadmap"),
                        _board("3", "Marketing Plan"),
                    ]
                }
            ),
        )
        result = runner.invoke(
            app,
            ["board", "list", "--name-fuzzy", "prodct launc", "--fuzzy-score"],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed
        # Top result must be Product Launch, with a score included
        assert parsed[0]["name"] == "Product Launch"
        assert "_fuzzy_score" in parsed[0]

    def test_no_cache_plus_refresh_cache_rejected(self) -> None:
        result = runner.invoke(app, ["board", "list", "--no-cache", "--refresh-cache"])
        assert result.exit_code == 2

    def test_name_fuzzy_plus_name_contains_rejected(self) -> None:
        result = runner.invoke(
            app, ["board", "list", "--name-fuzzy", "foo", "--name-contains", "bar"]
        )
        assert result.exit_code == 2

    def test_with_item_counts_bypasses_cache(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [_board("1", "A", items_count=5)]}),
        )
        result = runner.invoke(app, ["board", "list", "--with-item-counts"])
        assert result.exit_code == 0, result.stdout
        assert not (tmp_path / "cache" / "default" / "boards.json").exists()

    def test_state_filter_client_side(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        _board("1", "A"),
                        _board("2", "B", state="archived"),
                        _board("3", "C", state="archived"),
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["board", "list", "--state", "archived"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [b["id"] for b in parsed] == ["2", "3"]

    def test_workspace_name_enriched_from_cache(
        self, httpx_mock: HTTPXMock
    ) -> None:
        """workspace_name resolved from pre-warmed workspaces cache
        (fixture seeds id=42 → 'Engineering')."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [_board("1", "A", workspace_id="42")]}),
        )
        result = runner.invoke(app, ["board", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed[0]["workspace_name"] == "Engineering"

    def test_main_workspace_name_synthesized_for_null_id(
        self, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [_board("1", "A", workspace_id=None)]}),
        )
        result = runner.invoke(app, ["board", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed[0]["workspace_name"] == "Main workspace"

    def test_with_url_synthesizes_board_url(
        self, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--with-url synthesizes a board URL via the monday account/me lookup."""
        from mondo.cli import _url as url_mod

        monkeypatch.setattr(url_mod, "_TENANT_SLUG_CACHE", None)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [_board("42", "Roadmap")]}),
        )
        # Tenant slug fetch for URL synthesis.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"me": {"account": {"slug": "acme"}}}),
        )
        result = runner.invoke(app, ["board", "list", "--with-url"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed[0]["url"] == "https://acme.monday.com/boards/42"

    def test_url_hidden_by_default(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [_board("42", "Roadmap")]}),
        )
        result = runner.invoke(app, ["board", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert "url" not in parsed[0]


# -- board mutation invalidation --------------------------------------------


class TestBoardMutationInvalidation:
    def test_archive_invalidates_cache(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        # Prime cache
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [_board("42", "To archive")]}),
        )
        runner.invoke(app, ["board", "list"])
        cache_file = tmp_path / "cache" / "default" / "boards.json"
        assert cache_file.exists()

        # Archive — should invalidate cache
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"archive_board": {"id": "42"}}),
        )
        result = runner.invoke(app, ["--yes", "board", "archive", "--id", "42"])
        assert result.exit_code == 0, result.stdout
        assert not cache_file.exists()


# -- workspace cache path ---------------------------------------------------


class TestWorkspaceListCache:
    def test_warm_cache_serves_without_new_http(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        # The autouse fixture pre-warms workspaces for board/doc enrichment;
        # this test wants to exercise the cold-then-warm path explicitly, so
        # drop that file before priming.
        (tmp_path / "cache" / "default" / "workspaces.json").unlink(missing_ok=True)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"workspaces": [{"id": "1", "name": "Eng"}]}),
        )
        runner.invoke(app, ["workspace", "list"])
        baseline = len(httpx_mock.get_requests())

        r = runner.invoke(app, ["workspace", "list"])
        assert r.exit_code == 0, r.stdout
        assert len(httpx_mock.get_requests()) == baseline


# -- user cache path --------------------------------------------------------


class TestUserListCache:
    def test_cache_prime_and_warm(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        # Priming issues two queries (nonActive=false + nonActive=true).
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {"users": [{"id": "1", "name": "Zoe", "email": "z@x", "enabled": True}]}
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"users": []}),
        )
        r1 = runner.invoke(app, ["user", "list"])
        assert r1.exit_code == 0, r1.stdout
        baseline = len(httpx_mock.get_requests())

        r2 = runner.invoke(app, ["user", "list"])
        assert r2.exit_code == 0, r2.stdout
        assert len(httpx_mock.get_requests()) == baseline


# -- team cache path --------------------------------------------------------


class TestTeamListCache:
    def test_cache_prime_is_single_call(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"teams": [{"id": "1", "name": "Platform"}]}),
        )
        r = runner.invoke(app, ["team", "list"])
        assert r.exit_code == 0, r.stdout
        assert len(httpx_mock.get_requests()) == 1

    def test_id_filter_bypasses_cache(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"teams": [{"id": "5", "name": "T5"}]}),
        )
        r = runner.invoke(app, ["team", "list", "--id", "5"])
        assert r.exit_code == 0, r.stdout
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["variables"]["ids"] == [5]
