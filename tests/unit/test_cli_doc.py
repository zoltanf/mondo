"""End-to-end CLI tests for `mondo doc ...` — workspace docs (Phase 3e)."""

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
    """Lay down a warm workspaces cache so `doc list` enrichment doesn't
    trigger a workspaces fetch in tests that don't care about it."""
    store = CacheStore(
        entity_type="workspaces",
        cache_dir=tmp_path / "cache" / "default",
        api_endpoint=ENDPOINT,
        ttl_seconds=3600,
    )
    store.write(
        [
            {"id": "1", "name": "Main"},
            {"id": "42", "name": "Engineering"},
            {"id": "43", "name": "Sales"},
        ]
    )


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")
    # Default these tests to the live (non-cache) path; cache-specific tests
    # opt back in by re-setting MONDO_CACHE_ENABLED=true.
    monkeypatch.setenv("MONDO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MONDO_CACHE_ENABLED", "false")
    _prewarm_workspaces(tmp_path)


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


def _last_body(httpx_mock: HTTPXMock) -> dict:
    return json.loads(httpx_mock.get_requests()[-1].content)


# --- list ---


class TestList:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {"id": "1", "object_id": "100", "name": "A"},
                        {"id": "2", "object_id": "200", "name": "B"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["doc", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [d["id"] for d in parsed] == ["1", "2"]

    def test_filters(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"docs": []}))
        result = runner.invoke(
            app,
            [
                "doc",
                "list",
                "--workspace",
                "42",
                "--workspace",
                "43",
                "--object-id",
                "100",
                "--order-by",
                "used_at",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["workspaceIds"] == [42, 43]
        assert v["objectIds"] == [100]
        assert v["orderBy"] == "used_at"

    def test_unfiltered_omits_workspace_ids_arg(self, httpx_mock: HTTPXMock) -> None:
        """Monday silently scopes docs() to a single workspace when
        `workspace_ids: null` is sent. Unfiltered `doc list` must omit the
        arg entirely so monday returns docs across every accessible workspace.
        """
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"docs": []}))
        result = runner.invoke(app, ["doc", "list"])
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        for forbidden in ("ids: $ids", "object_ids:", "workspace_ids:", "order_by:"):
            assert forbidden not in body["query"], (
                f"{forbidden} leaked into unfiltered query: {body['query']}"
            )
        assert body["variables"].keys() == {"limit", "page"}

    def test_name_contains_filters_client_side(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {"id": "1", "object_id": "10", "name": "Spec v1"},
                        {"id": "2", "object_id": "20", "name": "Roadmap"},
                        {"id": "3", "object_id": "30", "name": "spec doc"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["doc", "list", "--name-contains", "spec"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [d["id"] for d in parsed] == ["1", "3"]

    def test_name_matches_regex(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {"id": "1", "object_id": "10", "name": "rfc-1"},
                        {"id": "2", "object_id": "20", "name": "rfc-002"},
                        {"id": "3", "object_id": "30", "name": "spec"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["doc", "list", "--name-matches", r"^rfc-\d+$"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [d["id"] for d in parsed] == ["1", "2"]

    def test_name_filters_mutually_exclusive(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["doc", "list", "--name-contains", "x", "--name-matches", "y"],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_invalid_regex_usage_error(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["doc", "list", "--name-matches", "["])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_kind_filters_client_side(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {"id": "1", "name": "A", "doc_kind": "public"},
                        {"id": "2", "name": "B", "doc_kind": "private"},
                        {"id": "3", "name": "C", "doc_kind": "private"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["doc", "list", "--kind", "private"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [d["id"] for d in parsed] == ["2", "3"]

    def test_folder_filters_client_side(self, httpx_mock: HTTPXMock) -> None:
        """--folder keeps only docs whose doc_folder_id matches; docs at the
        workspace root (doc_folder_id null) never match."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {"id": "1", "name": "A", "doc_folder_id": "555"},
                        {"id": "2", "name": "B", "doc_folder_id": None},
                        {"id": "3", "name": "C", "doc_folder_id": "777"},
                        {"id": "4", "name": "D", "doc_folder_id": "555"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["doc", "list", "--folder", "555"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [d["id"] for d in parsed] == ["1", "4"]

    def test_folder_composes_with_name_filter(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {"id": "1", "name": "Spec v1", "doc_folder_id": "555"},
                        {"id": "2", "name": "Roadmap", "doc_folder_id": "555"},
                        {"id": "3", "name": "spec doc", "doc_folder_id": "777"},
                    ]
                }
            ),
        )
        result = runner.invoke(
            app,
            ["doc", "list", "--folder", "555", "--name-contains", "spec"],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [d["id"] for d in parsed] == ["1"]

    def test_folder_no_match_emits_empty_list(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {"id": "1", "name": "A", "doc_folder_id": "555"},
                        {"id": "2", "name": "B", "doc_folder_id": None},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["doc", "list", "--folder", "999"])
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout) == []

    def test_query_includes_doc_folder_id_and_updated_at(self, httpx_mock: HTTPXMock) -> None:
        """Both are native on Monday's `Doc` type and populate the
        `folder_id` / `updated_at` core shape fields."""
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"docs": []}))
        result = runner.invoke(app, ["doc", "list"])
        assert result.exit_code == 0, result.stdout
        query = _last_body(httpx_mock)["query"]
        assert "doc_folder_id" in query
        assert "updated_at" in query

    def test_output_uses_kind_not_doc_kind(self, httpx_mock: HTTPXMock) -> None:
        """doc_kind → kind at the output layer (tier-1 hard rename)."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "1", "name": "A", "doc_kind": "private"}]}),
        )
        result = runner.invoke(app, ["doc", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed[0]["kind"] == "private"
        assert "doc_kind" not in parsed[0]

    def test_output_uses_folder_id_not_doc_folder_id(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "1", "name": "A", "doc_folder_id": "42"}]}),
        )
        result = runner.invoke(app, ["doc", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed[0]["folder_id"] == "42"
        assert "doc_folder_id" not in parsed[0]

    def test_url_hidden_by_default(self, httpx_mock: HTTPXMock) -> None:
        """doc list no longer emits url/relative_url unless --with-url is passed.
        Symmetric with board list's opt-in url behavior."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "1",
                            "object_id": "100",
                            "name": "Spec",
                            "url": "https://acme.monday.com/docs/1",
                            "relative_url": "/docs/1",
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["doc", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert "url" not in parsed[0]
        assert "relative_url" not in parsed[0]

    def test_with_url_exposes_url_and_relative_url(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "1",
                            "object_id": "100",
                            "name": "Spec",
                            "url": "https://acme.monday.com/docs/1",
                            "relative_url": "/docs/1",
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["doc", "list", "--with-url"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed[0]["url"] == "https://acme.monday.com/docs/1"
        assert parsed[0]["relative_url"] == "/docs/1"


class TestListCache:
    """Cache-backed `doc list` — enabled by re-setting MONDO_CACHE_ENABLED=true
    on top of the class-level `_clean_env` default (which disables cache)."""

    @pytest.fixture(autouse=True)
    def _enable_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MONDO_CACHE_ENABLED", "true")

    def _queue_prime(self, httpx_mock: HTTPXMock) -> None:
        """Queue the response sequence that `_fetch_all_docs` consumes when
        priming the cache: one workspaces list, then one docs list per
        workspace. The docs payload intentionally spans two workspaces so the
        --workspace / --object-id client-side filter tests have something
        meaningful to slice."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"workspaces": [{"id": "42"}, {"id": "43"}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "1",
                            "object_id": "100",
                            "name": "Alpha",
                            "workspace_id": "42",
                            "created_at": "2024-01-01T10:00:00Z",
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
                    "docs": [
                        {
                            "id": "2",
                            "object_id": "200",
                            "name": "Beta",
                            "workspace_id": "43",
                            "created_at": "2024-02-01T10:00:00Z",
                        }
                    ]
                }
            ),
        )

    def test_cold_then_warm_cache(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        self._queue_prime(httpx_mock)
        first = runner.invoke(app, ["doc", "list"])
        assert first.exit_code == 0, first.stdout
        assert sorted(d["id"] for d in json.loads(first.stdout)) == ["1", "2"]
        cache_file = tmp_path / "cache" / "default" / "docs.json"
        assert cache_file.exists()
        prime_requests = len(httpx_mock.get_requests())

        # Second call: no new response queued — must come from cache.
        second = runner.invoke(app, ["doc", "list"])
        assert second.exit_code == 0, second.stdout
        assert sorted(d["id"] for d in json.loads(second.stdout)) == ["1", "2"]
        assert len(httpx_mock.get_requests()) == prime_requests

    def test_no_cache_bypasses(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        self._queue_prime(httpx_mock)
        runner.invoke(app, ["doc", "list"])
        cache_file = tmp_path / "cache" / "default" / "docs.json"
        assert cache_file.exists()
        prime_requests = len(httpx_mock.get_requests())

        # With --no-cache, must hit the API regardless of cache state — and
        # the direct CLI path still issues a single unfiltered docs query.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": []}),
        )
        result = runner.invoke(app, ["doc", "list", "--no-cache"])
        assert result.exit_code == 0, result.stdout
        assert len(httpx_mock.get_requests()) == prime_requests + 1

    def test_refresh_cache_forces_refetch(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        # Prime with stale content.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"workspaces": [{"id": "42"}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "1", "object_id": "100", "name": "Stale"}]}),
        )
        runner.invoke(app, ["doc", "list"])
        prime_requests = len(httpx_mock.get_requests())

        # Refresh overwrites.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"workspaces": [{"id": "42"}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "9", "object_id": "900", "name": "Fresh"}]}),
        )
        result = runner.invoke(app, ["doc", "list", "--refresh-cache"])
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout)[0]["name"] == "Fresh"
        assert len(httpx_mock.get_requests()) == prime_requests + 2

    def test_no_cache_and_refresh_cache_mutually_exclusive(self) -> None:
        result = runner.invoke(app, ["doc", "list", "--no-cache", "--refresh-cache"])
        assert result.exit_code == 2
        assert "mutually exclusive" in (result.stderr or result.stdout).lower()

    def test_workspace_filter_applies_client_side(self, httpx_mock: HTTPXMock) -> None:
        self._queue_prime(httpx_mock)
        result = runner.invoke(app, ["doc", "list", "--workspace", "42"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [d["id"] for d in parsed] == ["1"]

    def test_object_id_filter_applies_client_side(self, httpx_mock: HTTPXMock) -> None:
        self._queue_prime(httpx_mock)
        result = runner.invoke(app, ["doc", "list", "--object-id", "200"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [d["id"] for d in parsed] == ["2"]

    def test_order_by_created_at_sorts_newest_first(self, httpx_mock: HTTPXMock) -> None:
        self._queue_prime(httpx_mock)
        result = runner.invoke(app, ["doc", "list", "--order-by", "created_at"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [d["id"] for d in parsed] == ["2", "1"]

    def test_max_items_truncates(self, httpx_mock: HTTPXMock) -> None:
        self._queue_prime(httpx_mock)
        result = runner.invoke(app, ["doc", "list", "--max-items", "1"])
        assert result.exit_code == 0, result.stdout
        assert len(json.loads(result.stdout)) == 1

    def test_dry_run_emits_cache_preview(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["--dry-run", "doc", "list", "--workspace", "42"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["cache"] == "docs"
        assert parsed["filters"]["workspace_ids"] == [42]
        assert httpx_mock.get_requests() == []

    def _queue_prime_for_fuzzy(self, httpx_mock: HTTPXMock) -> None:
        """Seed the docs cache with a richer mix so fuzzy / kind / folder
        tests can distinguish matches. One workspace, four docs varying in
        name, doc_kind and doc_folder_id (docs 2 and 4 sit at the root)."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"workspaces": [{"id": "42"}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "1",
                            "object_id": "10",
                            "name": "Product Launch",
                            "workspace_id": "42",
                            "doc_kind": "public",
                            "doc_folder_id": "555",
                        },
                        {
                            "id": "2",
                            "object_id": "20",
                            "name": "Marketing Plan",
                            "workspace_id": "42",
                            "doc_kind": "private",
                            "doc_folder_id": None,
                        },
                        {
                            "id": "3",
                            "object_id": "30",
                            "name": "Product Roadmap",
                            "workspace_id": "42",
                            "doc_kind": "public",
                            "doc_folder_id": "555",
                        },
                        {
                            "id": "4",
                            "object_id": "40",
                            "name": "Unrelated Stuff",
                            "workspace_id": "42",
                            "doc_kind": "private",
                            "doc_folder_id": None,
                        },
                    ]
                }
            ),
        )

    def test_name_fuzzy_filters_with_threshold(self, httpx_mock: HTTPXMock) -> None:
        self._queue_prime_for_fuzzy(httpx_mock)
        result = runner.invoke(
            app,
            ["doc", "list", "--name-fuzzy", "prodct", "--fuzzy-threshold", "60"],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        ids = {d["id"] for d in parsed}
        # "Product Launch" and "Product Roadmap" match "prodct"; the others
        # should be filtered out by the threshold.
        assert ids == {"1", "3"}

    def test_fuzzy_score_injected_and_sorted(self, httpx_mock: HTTPXMock) -> None:
        self._queue_prime_for_fuzzy(httpx_mock)
        result = runner.invoke(
            app,
            ["doc", "list", "--name-fuzzy", "product launch", "--fuzzy-score"],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        # Every returned entry has a _fuzzy_score, and they're sorted desc.
        assert all("_fuzzy_score" in d for d in parsed)
        scores = [d["_fuzzy_score"] for d in parsed]
        assert scores == sorted(scores, reverse=True)
        # The exact match for "Product Launch" should lead.
        assert parsed[0]["id"] == "1"

    def test_kind_filters_client_side_cache(self, httpx_mock: HTTPXMock) -> None:
        self._queue_prime_for_fuzzy(httpx_mock)
        result = runner.invoke(app, ["doc", "list", "--kind", "private"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert sorted(d["id"] for d in parsed) == ["2", "4"]

    def test_folder_filters_client_side_cache(self, httpx_mock: HTTPXMock) -> None:
        """--folder served from the cache keeps only in-folder docs; docs at
        the workspace root (doc_folder_id null) are excluded."""
        self._queue_prime_for_fuzzy(httpx_mock)
        result = runner.invoke(app, ["doc", "list", "--folder", "555"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert sorted(d["id"] for d in parsed) == ["1", "3"]

    def test_name_filters_mutually_exclusive_cache(self, httpx_mock: HTTPXMock) -> None:
        # No priming required — validation happens before any cache read.
        result = runner.invoke(
            app,
            ["doc", "list", "--name-contains", "x", "--name-fuzzy", "y"],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_workspace_name_enriched_from_cache(self, httpx_mock: HTTPXMock) -> None:
        """workspace_name is resolved from the workspaces cache
        (pre-warmed by autouse fixture: id=42 → 'Engineering')."""
        self._queue_prime(httpx_mock)
        result = runner.invoke(app, ["doc", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        by_id = {d["id"]: d for d in parsed}
        assert by_id["1"]["workspace_name"] == "Engineering"
        assert by_id["2"]["workspace_name"] == "Sales"

    def test_workspace_pair_adjacent_and_created_at_last(self, httpx_mock: HTTPXMock) -> None:
        self._queue_prime(httpx_mock)
        result = runner.invoke(app, ["doc", "list"])
        assert result.exit_code == 0, result.stdout
        row = json.loads(result.stdout)[0]
        keys = list(row.keys())
        assert keys[keys.index("workspace_id") + 1] == "workspace_name"
        assert keys[-1] == "created_at"

    def test_main_workspace_name_synthesized_for_null_id(self, httpx_mock: HTTPXMock) -> None:
        """monday returns workspace_id=null for docs in the Main workspace;
        the CLI fills in the synthetic 'Main workspace' label."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"workspaces": [{"id": "42"}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {"id": "1", "object_id": "100", "name": "Homeless", "workspace_id": None}
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["doc", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed[0]["workspace_name"] == "Main workspace"


# --- get ---


class TestGet:
    def test_by_id(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "7",
                            "object_id": "77",
                            "name": "Spec",
                            "blocks": [],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["doc", "get", "--id", "7"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["id"] == "7"

    def test_by_id_normalizes_kind_and_folder_and_timestamps(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "7",
                            "object_id": "77",
                            "name": "Spec",
                            "doc_kind": "private",
                            "doc_folder_id": "9",
                            "created_at": "2024-01-01T00:00:00Z",
                            "updated_at": "2024-01-02T00:00:00Z",
                            "blocks": [],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["doc", "get", "--id", "7"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["kind"] == "private"
        assert parsed["folder_id"] == "9"
        assert "doc_kind" not in parsed
        assert "doc_folder_id" not in parsed
        assert list(parsed.keys())[-2:] == ["created_at", "updated_at"]

    def test_by_object_id(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "7",
                            "object_id": "77",
                            "blocks": [],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["doc", "get", "--object-id", "77"])
        assert result.exit_code == 0, result.stdout

    def test_requires_one_of_id_object_id(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["doc", "get"])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_both_id_and_object_id_exit_2(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["doc", "get", "--id", "1", "--object-id", "2"])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_markdown_format(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "7",
                            "blocks": [
                                {
                                    "id": "b1",
                                    "type": "normal_text",
                                    "content": {"deltaFormat": [{"insert": "Hi"}]},
                                }
                            ],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["doc", "get", "--id", "7", "--format", "markdown"])
        assert result.exit_code == 0, result.stdout
        assert "Hi" in result.stdout

    def test_missing_exits_6(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"docs": []}))
        # Object-id probe on the --id miss (the #24 guardrail) — misses too.
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"docs": []}))
        result = runner.invoke(app, ["doc", "get", "--id", "999"])
        assert result.exit_code == 6

    def test_accepts_url_for_object_id(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "7",
                            "object_id": "99",
                            "name": "X",
                            "blocks": [],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(
            app,
            [
                "doc",
                "get",
                "--object-id",
                "https://marktguru.monday.com/boards/99",
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert _last_body(httpx_mock)["variables"] == {"objs": [99], "limit": 100, "page": 1}

    def test_accepts_url_for_id(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "7",
                            "object_id": "77",
                            "name": "X",
                            "blocks": [],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(
            app,
            ["doc", "get", "--id", "https://marktguru.monday.com/boards/7"],
        )
        assert result.exit_code == 0, result.stdout
        assert _last_body(httpx_mock)["variables"] == {"ids": [7], "limit": 100, "page": 1}

    def test_not_found_falls_back_to_board_get(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"docs": []}))
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "99", "name": "Real board", "type": "board"}]}),
        )
        result = runner.invoke(app, ["doc", "get", "--object-id", "99"])
        assert result.exit_code == 6
        assert "regular board" in result.stderr
        assert "mondo board get 99" in result.stderr

    def test_not_found_generic_when_board_also_missing(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"docs": []}))
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": []}))
        result = runner.invoke(app, ["doc", "get", "--object-id", "99"])
        assert result.exit_code == 6
        assert "not found" in result.stderr
        assert "regular board" not in result.stderr

    def test_not_found_no_fallback_for_internal_id(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"docs": []}))
        # Object-id probe on the --id miss (the #24 guardrail) — misses too.
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"docs": []}))
        result = runner.invoke(app, ["doc", "get", "--id", "999"])
        assert result.exit_code == 6
        # Two HTTP calls: the fetch and the object-id probe — but no
        # BOARD_GET probe on the --id path.
        requests = httpx_mock.get_requests()
        assert len(requests) == 2
        assert "object_ids" in json.loads(requests[-1].content)["query"]
        assert "boards" not in json.loads(requests[-1].content)["query"]


# --- create ---


class TestCreate:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "create_doc": {
                        "id": "10",
                        "object_id": "100",
                        "name": "New",
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            [
                "doc",
                "create",
                "--workspace",
                "42",
                "--name",
                "New",
                "--kind",
                "private",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"workspace": 42, "name": "New", "kind": "private", "folder": None}
        parsed = json.loads(result.stdout)
        assert parsed["id"] == "10"
        assert parsed["object_id"] == "100"

    def test_folder_wired_into_variables(self, httpx_mock: HTTPXMock) -> None:
        """Issue #37: `doc create --folder` threads folder_id into the
        create_doc mutation variables (and the workspace location input)."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_doc": {"id": "10", "object_id": "100", "name": "New"}}),
        )
        result = runner.invoke(
            app,
            ["doc", "create", "--workspace", "42", "--name", "New", "--folder", "777"],
        )
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert body["variables"]["folder"] == 777
        assert "folder_id: $folder" in body["query"]

    def test_folder_omitted_defaults_null(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_doc": {"id": "10", "object_id": "100", "name": "New"}}),
        )
        result = runner.invoke(app, ["doc", "create", "--workspace", "42", "--name", "New"])
        assert result.exit_code == 0, result.stdout
        assert _last_body(httpx_mock)["variables"]["folder"] is None

    def test_with_url_flag_accepted_url_always_present(self, httpx_mock: HTTPXMock) -> None:
        """Issue #10: `doc create --with-url` is accepted for symmetry with
        `board create` / `item create`; docs always carry `url` anyway."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "create_doc": {
                        "id": "10",
                        "object_id": "100",
                        "name": "New",
                        "url": "https://acme.monday.com/docs/100",
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            ["doc", "create", "--workspace", "42", "--name", "New", "--with-url"],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["url"] == "https://acme.monday.com/docs/100"
        assert len(httpx_mock.get_requests()) == 1


# --- blocks ---


class TestBlocks:
    def test_add_block_single_on_empty_doc(self, httpx_mock: HTTPXMock) -> None:
        # Pre-fetch: empty doc → no `after` seed
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "10", "blocks": []}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_doc_block": {"id": "b1", "type": "normal_text"}}),
        )
        result = runner.invoke(
            app,
            [
                "doc",
                "add-block",
                "--doc",
                "10",
                "--type",
                "normal_text",
                "--content",
                '{"deltaFormat":[{"insert":"hi"}]}',
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["doc"] == 10
        assert v["type"] == "normal_text"
        assert json.loads(v["content"]) == {"deltaFormat": [{"insert": "hi"}]}
        assert v["after"] is None
        assert v["parent"] is None

    def test_add_block_single_seeds_from_last_block(self, httpx_mock: HTTPXMock) -> None:
        # Pre-fetch: doc has blocks → `after` seeds from last block id
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "10", "blocks": [{"id": "last-block"}]}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_doc_block": {"id": "b1", "type": "divider"}}),
        )
        result = runner.invoke(
            app,
            [
                "doc",
                "add-block",
                "--doc",
                "10",
                "--type",
                "divider",
                "--content",
                "{}",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["after"] == "last-block"

    def test_add_block_with_after_and_parent(self, httpx_mock: HTTPXMock) -> None:
        # Explicit --after skips the pre-fetch
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_doc_block": {"id": "b1"}}),
        )
        result = runner.invoke(
            app,
            [
                "doc",
                "add-block",
                "--doc",
                "10",
                "--type",
                "normal_text",
                "--content",
                '{"deltaFormat":[{"insert":"hi"}]}',
                "--after",
                "pre",
                "--parent-block",
                "parent",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["after"] == "pre"
        assert v["parent"] == "parent"
        # Only one HTTP request (no pre-fetch when --after is explicit)
        assert len(httpx_mock.get_requests()) == 1

    def test_add_block_invalid_json(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            [
                "doc",
                "add-block",
                "--doc",
                "10",
                "--type",
                "normal_text",
                "--content",
                "{not json",
            ],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_add_content_from_markdown(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        src = tmp_path / "spec.md"
        src.write_text("# Title\n\nParagraph.\n\n- one\n- two\n")
        # Pre-fetch for existing doc blocks (empty doc → first append has after=None)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "10", "blocks": []}]}),
        )
        # 4 blocks → 4 singular create_doc_block calls. Chain via after_block_id.
        for block_id in ("b1", "b2", "b3", "b4"):
            httpx_mock.add_response(
                url=ENDPOINT,
                method="POST",
                json=_ok({"create_doc_block": {"id": block_id, "type": "normal_text"}}),
            )
        result = runner.invoke(
            app,
            [
                "doc",
                "add-content",
                "--doc",
                "10",
                "--from-file",
                str(src),
            ],
        )
        assert result.exit_code == 0, result.stdout
        bodies = [json.loads(r.content) for r in httpx_mock.get_requests()]
        # 1 pre-fetch + one request per block
        assert len(bodies) == 5
        # First create call has no `after` (empty doc); subsequent chain
        assert bodies[1]["variables"]["after"] is None
        assert bodies[2]["variables"]["after"] == "b1"
        assert bodies[3]["variables"]["after"] == "b2"
        assert bodies[4]["variables"]["after"] == "b3"

    def test_add_content_seeds_from_last_block_on_nonempty_doc(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        """Append semantics: if the doc already has blocks, the first new
        block goes after the existing last one (monday's default for
        after=null is TOP insert, which breaks append)."""
        src = tmp_path / "spec.md"
        src.write_text("Paragraph\n")
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {"docs": [{"id": "10", "blocks": [{"id": "existing-last", "type": "quote"}]}]}
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_doc_block": {"id": "new-b1", "type": "normal_text"}}),
        )
        result = runner.invoke(
            app,
            ["doc", "add-content", "--doc", "10", "--from-file", str(src)],
        )
        assert result.exit_code == 0, result.stdout
        bodies = [json.loads(r.content) for r in httpx_mock.get_requests()]
        assert bodies[1]["variables"]["after"] == "existing-last"

    def test_add_content_empty_input_exit_5(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        empty = tmp_path / "e.md"
        empty.write_text("")
        result = runner.invoke(
            app,
            ["doc", "add-content", "--doc", "10", "--from-file", str(empty)],
        )
        assert result.exit_code == 5
        assert httpx_mock.get_requests() == []

    def test_create_blocks_helper_wires_parent_block_id_for_children(
        self, httpx_mock: HTTPXMock
    ) -> None:
        """`create_blocks` must recurse into `_children` and set
        `parent_block_id` on each child to the parent's API-returned id.

        Currently no public CLI path produces `_children` (monday rejects
        `create_doc_block(type: notice_box, content: ...)` for every
        content shape we tried). The recursion is kept as correct
        scaffolding so future callers — e.g. once the `notice_box`
        content schema is known, or any caller that synthesises tree
        blocks — get parent linkage for free. This test exercises the
        helper directly via a tree-shaped input.
        """
        from mondo.api.client import MondayClient
        from mondo.cli.column_doc import create_blocks

        # Parent (notice_box) → id "p1"; one child → id "c1".
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_doc_block": {"id": "p1", "type": "notice_box"}}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_doc_block": {"id": "c1", "type": "normal_text"}}),
        )
        client = MondayClient(token="t-tttttttttttt-long-enough", api_version="2026-01")
        with client:
            create_blocks(
                client,
                doc_id=10,
                blocks=[
                    {
                        "type": "notice_box",
                        "content": {},
                        "_children": [
                            {
                                "type": "normal_text",
                                "content": {"deltaFormat": [{"insert": "inside"}]},
                            },
                        ],
                    }
                ],
            )
        bodies = [json.loads(r.content) for r in httpx_mock.get_requests()]
        assert len(bodies) == 2
        parent_vars = bodies[0]["variables"]
        child_vars = bodies[1]["variables"]
        assert parent_vars["type"] == "notice_box"
        assert parent_vars["parent"] is None
        assert child_vars["type"] == "normal_text"
        # Critical: child's parent points at parent's API-returned id.
        assert child_vars["parent"] == "p1"
        # First child of a container has no `after_block_id` predecessor.
        assert child_vars["after"] is None

    def test_update_block(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_doc_block": {"id": "b1", "type": "normal_text"}}),
        )
        result = runner.invoke(
            app,
            [
                "doc",
                "update-block",
                "--id",
                "b1",
                "--content",
                '{"deltaFormat":[{"insert":"new"}]}',
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["block"] == "b1"
        # content must be a JSON-encoded STRING for monday's JSON scalar, not
        # a raw object (matches the create_doc_block pattern).
        assert isinstance(v["content"], str)
        assert json.loads(v["content"]) == {"deltaFormat": [{"insert": "new"}]}

    def test_delete_block(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_doc_block": {"id": "b1"}}),
        )
        result = runner.invoke(app, ["doc", "delete-block", "--id", "b1"])
        assert result.exit_code == 0, result.stdout

    def test_delete_block_tolerates_object_id(self, httpx_mock: HTTPXMock) -> None:
        # Agents extrapolate --object-id from add-block / doc get; block edits
        # only need the (globally unique) block id, so the flag is accepted and
        # ignored rather than rejected with "No such option".
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_doc_block": {"id": "b1"}}),
        )
        result = runner.invoke(
            app, ["doc", "delete-block", "--object-id", "5098716806", "--id", "b1"]
        )
        assert result.exit_code == 0, result.stdout
        assert _last_body(httpx_mock)["variables"] == {"block": "b1"}

    def test_update_block_tolerates_doc(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_doc_block": {"id": "b1", "type": "normal_text"}}),
        )
        result = runner.invoke(
            app,
            [
                "doc",
                "update-block",
                "--doc",
                "1777684749",
                "--id",
                "b1",
                "--content",
                '{"deltaFormat":[{"insert":"new"}]}',
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert _last_body(httpx_mock)["variables"]["block"] == "b1"


class TestDocPagination:
    def test_get_markdown_paginates_blocks(self, httpx_mock: HTTPXMock) -> None:
        first_page_blocks = [
            {
                "id": f"b{i}",
                "type": "normal_text",
                "content": {"deltaFormat": [{"insert": f"L{i}"}]},
            }
            for i in range(1, 101)
        ]
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "7", "blocks": first_page_blocks}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "7",
                            "blocks": [
                                {
                                    "id": "b101",
                                    "type": "normal_text",
                                    "content": {"deltaFormat": [{"insert": "Last line"}]},
                                }
                            ],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["doc", "get", "--id", "7", "--format", "markdown"])
        assert result.exit_code == 0, result.stdout
        assert "L1" in result.stdout
        assert "Last line" in result.stdout
        reqs = [json.loads(r.content) for r in httpx_mock.get_requests()]
        assert reqs[0]["variables"]["page"] == 1
        assert reqs[1]["variables"]["page"] == 2
        assert reqs[0]["variables"]["limit"] == 100

    def test_add_block_seeds_after_from_last_paged_block(self, httpx_mock: HTTPXMock) -> None:
        first_page_blocks = [
            {"id": f"b{i}", "type": "normal_text", "content": {}} for i in range(1, 101)
        ]
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "10", "blocks": first_page_blocks}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "10",
                            "blocks": [{"id": "b101", "type": "normal_text", "content": {}}],
                        }
                    ]
                }
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_doc_block": {"id": "new-1", "type": "normal_text"}}),
        )
        result = runner.invoke(
            app,
            [
                "doc",
                "add-block",
                "--doc",
                "10",
                "--type",
                "normal_text",
                "--content",
                '{"deltaFormat":[{"insert":"hi"}]}',
            ],
        )
        assert result.exit_code == 0, result.stdout
        create_body = json.loads(httpx_mock.get_requests()[-1].content)
        assert create_body["variables"]["after"] == "b101"


class TestDocNewOps:
    def test_create_requires_name(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["doc", "create", "--workspace", "42"])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_rename(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"update_doc_name": "Renamed"})
        )
        result = runner.invoke(app, ["doc", "rename", "--doc", "10", "--name", "Renamed"])
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert body["variables"] == {"doc": 10, "name": "Renamed"}

    def test_duplicate(self, httpx_mock: HTTPXMock) -> None:
        # monday's `duplicate_doc` returns a JSON scalar envelope whose `id`
        # is the new doc's object_id; the CLI follows up with a head-lookup
        # by object_id to resolve the internal id and emits the canonical
        # `{id, object_id, name, url}` shape (mirroring `doc create`).
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"duplicate_doc": {"success": True, "id": "900"}}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "88",
                            "object_id": "900",
                            "name": "Copy of Doc",
                            "url": "https://x.monday.com/docs/900",
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(
            app,
            [
                "doc",
                "duplicate",
                "--doc",
                "10",
                "--duplicate-type",
                "duplicate_doc_with_content_and_updates",
            ],
        )
        assert result.exit_code == 0, result.stdout
        # First body is the duplicate mutation; second is the head lookup.
        bodies = [json.loads(req.content) for req in httpx_mock.get_requests()]
        assert bodies[0]["variables"] == {
            "doc": 10,
            "dup": "duplicate_doc_with_content_and_updates",
        }
        assert bodies[1]["variables"] == {"objs": [900]}
        emitted = json.loads(result.stdout)
        assert emitted["id"] == "88"
        assert emitted["object_id"] == "900"
        assert emitted["name"] == "Copy of Doc"

    def test_duplicate_default_type(self, httpx_mock: HTTPXMock) -> None:
        # Bare `mondo doc duplicate` defaults --duplicate-type to
        # duplicate_doc_with_content (monday rejects null).
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"duplicate_doc": {"success": True, "id": "900"}}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "88", "object_id": "900", "name": "n", "url": "u"}]}),
        )
        result = runner.invoke(app, ["doc", "duplicate", "--doc", "10"])
        assert result.exit_code == 0, result.stdout
        first_body = json.loads(httpx_mock.get_requests()[0].content)
        assert first_body["variables"] == {
            "doc": 10,
            "dup": "duplicate_doc_with_content",
        }

    def test_duplicate_failure_exits_5(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"duplicate_doc": {"success": False, "error": "Unknown error"}}),
        )
        # Object-id probe on the success=False failure (the #24 guardrail).
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"docs": []}))
        result = runner.invoke(
            app,
            [
                "doc",
                "duplicate",
                "--doc",
                "10",
                "--duplicate-type",
                "duplicate_doc_with_content",
            ],
        )
        assert result.exit_code == 5
        assert "Unknown error" in result.stderr

    def test_delete(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"delete_doc": {"id": "10"}}))
        result = runner.invoke(app, ["doc", "delete", "--doc", "10"])
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert body["variables"] == {"doc": 10}

    def test_server_markdown_plain(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "export_markdown_from_doc": {
                        "success": True,
                        "error": None,
                        "markdown": "# Title",
                    }
                }
            ),
        )
        result = runner.invoke(
            app, ["doc", "get", "--doc", "10", "--format", "markdown", "--engine", "server"]
        )
        assert result.exit_code == 0, result.stdout
        assert "# Title" in result.stdout
        body = _last_body(httpx_mock)
        assert body["variables"] == {"doc": 10, "blocks": None}

    def test_server_markdown_failure_exits_5(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "export_markdown_from_doc": {
                        "success": False,
                        "error": "boom",
                        "markdown": "",
                    }
                }
            ),
        )
        # Object-id probe on the success=False failure (the #24 guardrail).
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"docs": []}))
        result = runner.invoke(
            app, ["doc", "get", "--doc", "10", "--format", "markdown", "--engine", "server"]
        )
        assert result.exit_code == 5

    def test_server_markdown_accepts_no_cache_noop(self, httpx_mock: HTTPXMock) -> None:
        """Issue #34: `--engine server` is always live, so `--no-cache` is
        accepted as a no-op rather than failing with a usage error (exit 2)."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {"export_markdown_from_doc": {"success": True, "error": None, "markdown": "# T"}}
            ),
        )
        result = runner.invoke(
            app,
            [
                "doc",
                "get",
                "--doc",
                "10",
                "--format",
                "markdown",
                "--engine",
                "server",
                "--no-cache",
            ],
        )
        assert result.exit_code == 0, result.stderr
        assert "# T" in result.stdout

    def test_server_markdown_no_cache_refresh_cache_mutually_exclusive(self) -> None:
        result = runner.invoke(
            app,
            [
                "doc",
                "get",
                "--doc",
                "10",
                "--format",
                "markdown",
                "--engine",
                "server",
                "--no-cache",
                "--refresh-cache",
            ],
        )
        assert result.exit_code == 2
        assert "mutually exclusive" in (result.stderr or result.stdout).lower()

    def test_server_engine_requires_markdown_format(self) -> None:
        result = runner.invoke(app, ["doc", "get", "--doc", "10", "--engine", "server"])
        assert result.exit_code == 2
        assert "only supports --format markdown" in (result.stderr or result.stdout)

    def test_server_engine_format_guard_precedes_out_guard(self) -> None:
        """A server-engine call that forgot --format markdown reports the
        engine/format mismatch first, not the generic --out-needs-markdown
        message (the client-path guard)."""
        result = runner.invoke(
            app, ["doc", "get", "--doc", "10", "--engine", "server", "--raw", "--out", "x.md"]
        )
        assert result.exit_code == 2
        assert "only supports --format markdown" in (result.stderr or result.stdout)

    def test_block_requires_server_engine(self) -> None:
        result = runner.invoke(
            app, ["doc", "get", "--doc", "10", "--format", "markdown", "--block", "b1"]
        )
        assert result.exit_code == 2
        assert "--block requires --engine server" in (result.stderr or result.stdout)

    def test_raw_requires_server_engine(self) -> None:
        result = runner.invoke(app, ["doc", "get", "--doc", "10", "--raw"])
        assert result.exit_code == 2
        assert "--raw requires --engine server" in (result.stderr or result.stdout)

    def test_server_markdown_blocks_subset_passed_through(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {"export_markdown_from_doc": {"success": True, "error": None, "markdown": "# T"}}
            ),
        )
        result = runner.invoke(
            app,
            [
                "doc",
                "get",
                "--doc",
                "10",
                "--format",
                "markdown",
                "--engine",
                "server",
                "--block",
                "b1",
                "--block",
                "b2",
            ],
        )
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert body["variables"] == {"doc": 10, "blocks": ["b1", "b2"]}

    def test_add_markdown(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "add_content_to_doc_from_markdown": {
                        "success": True,
                        "block_ids": ["b1"],
                        "error": None,
                    }
                }
            ),
        )
        result = runner.invoke(app, ["doc", "add-markdown", "--doc", "10", "--markdown", "# Hi"])
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert body["variables"] == {"doc": 10, "md": "# Hi", "after": None}

    def test_add_markdown_empty_input_errors_without_api_call(self, httpx_mock: HTTPXMock) -> None:
        # Whitespace-only markdown must not silently report success; it errors
        # before any client/API call (mirrors `add-content`'s no-blocks guard).
        result = runner.invoke(app, ["doc", "add-markdown", "--doc", "10", "--markdown", "   "])
        assert result.exit_code != 0
        assert httpx_mock.get_requests() == []

    def test_import_html(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"import_doc_from_html": {"success": True, "doc_id": "99", "error": None}}),
        )
        result = runner.invoke(
            app,
            [
                "doc",
                "import-html",
                "--workspace",
                "42",
                "--html",
                "<h1>Hi</h1>",
                "--title",
                "Imported",
            ],
        )
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert body["variables"] == {
            "html": "<h1>Hi</h1>",
            "workspace": 42,
            "title": "Imported",
            "folder": None,
            "kind": None,
        }

    def test_version_history(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"doc_version_history": {"doc_id": "10", "restoring_points": []}}),
        )
        result = runner.invoke(app, ["doc", "version-history", "--doc", "10"])
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert body["variables"] == {"doc": 10, "since": None, "until": None}

    def test_version_diff(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"doc_version_diff": {"doc_id": "10", "blocks": []}}),
        )
        result = runner.invoke(
            app,
            [
                "doc",
                "version-diff",
                "--doc",
                "10",
                "--date",
                "2026-01-08T10:24:02.469Z",
                "--prev-date",
                "2025-01-01T00:00:00Z",
            ],
        )
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert body["variables"] == {
            "doc": 10,
            "date": "2026-01-08T10:24:02.469Z",
            "prev": "2025-01-01T00:00:00Z",
        }


class TestDocSet:
    """Issue #35: `doc set` / `doc replace` — full in-place content overwrite."""

    def test_adds_new_content_then_deletes_old_blocks(self, httpx_mock: HTTPXMock) -> None:
        # 1) fetch existing blocks
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "10", "blocks": [{"id": "b1"}, {"id": "b2"}]}]}),
        )
        # 2) add new content (BEFORE any delete, so a failed add can't lose data)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "add_content_to_doc_from_markdown": {
                        "success": True,
                        "block_ids": ["n1"],
                        "error": None,
                    }
                }
            ),
        )
        # 3) delete b1, 4) delete b2
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"delete_doc_block": {"id": "b1"}})
        )
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"delete_doc_block": {"id": "b2"}})
        )
        result = runner.invoke(app, ["doc", "set", "--doc", "10", "--markdown", "# New"])
        assert result.exit_code == 0, result.stdout
        bodies = [json.loads(r.content) for r in httpx_mock.get_requests()]
        # fetch + add + 2 deletes = 4 requests, add ordered before deletes
        assert len(bodies) == 4
        # new content added after the last existing block, then old blocks removed
        assert bodies[1]["variables"] == {"doc": 10, "md": "# New", "after": "b2"}
        assert bodies[2]["variables"]["block"] == "b1"
        assert bodies[3]["variables"]["block"] == "b2"
        emitted = json.loads(result.stdout)
        assert emitted["success"] is True
        assert emitted["block_ids"] == ["n1"]
        assert emitted["replaced_blocks"] == 2

    def test_failed_add_does_not_delete_blocks(self, httpx_mock: HTTPXMock) -> None:
        # fetch existing blocks
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "10", "blocks": [{"id": "b1"}, {"id": "b2"}]}]}),
        )
        # add fails — original content must be left intact (no deletes issued)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "add_content_to_doc_from_markdown": {
                        "success": False,
                        "block_ids": None,
                        "error": "unsupported markdown",
                    }
                }
            ),
        )
        # the failure path probes whether --doc 10 was really an object_id
        # (shared `_fail_with_object_id_hint` behaviour); answer "no match".
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"docs": []}), is_reusable=True
        )
        result = runner.invoke(app, ["doc", "set", "--doc", "10", "--markdown", "# New"])
        assert result.exit_code != 0
        bodies = [json.loads(r.content) for r in httpx_mock.get_requests()]
        # the delete loop never runs, so the original blocks are not lost
        assert "delete_doc_block" not in json.dumps(bodies)

    def test_set_deletes_only_top_level_blocks(self, httpx_mock: HTTPXMock) -> None:
        # Deleting a container cascades its children server-side; re-deleting an
        # already-cascaded child id 400s. So a child block (parent_block_id set)
        # must NOT appear in the delete loop — only top-level ids are deleted.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "10",
                            "blocks": [
                                {"id": "t1"},
                                {"id": "c1", "parent_block_id": "t1"},
                                {"id": "b2"},
                            ],
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
                    "add_content_to_doc_from_markdown": {
                        "success": True,
                        "block_ids": ["n1"],
                        "error": None,
                    }
                }
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"delete_doc_block": {"id": "t1"}})
        )
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"delete_doc_block": {"id": "b2"}})
        )
        result = runner.invoke(app, ["doc", "set", "--doc", "10", "--markdown", "# New"])
        assert result.exit_code == 0, result.stdout
        bodies = [json.loads(r.content) for r in httpx_mock.get_requests()]
        deleted = [
            b["variables"]["block"] for b in bodies if "delete_doc_block" in b.get("query", "")
        ]
        assert deleted == ["t1", "b2"]
        assert json.loads(result.stdout)["replaced_blocks"] == 2

    def test_set_anchors_add_to_last_root_not_child(self, httpx_mock: HTTPXMock) -> None:
        # The doc ends with a container child (c1, parent t1). The add must
        # anchor to the last TOP-LEVEL block (t1), never the child — anchoring
        # `add_content_to_doc_from_markdown` to a child id 500s server-side.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "10",
                            "blocks": [
                                {"id": "b1"},
                                {"id": "t1"},
                                {"id": "c1", "parent_block_id": "t1"},
                            ],
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
                    "add_content_to_doc_from_markdown": {
                        "success": True,
                        "block_ids": ["n1"],
                        "error": None,
                    }
                }
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"delete_doc_block": {"id": "b1"}})
        )
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"delete_doc_block": {"id": "t1"}})
        )
        result = runner.invoke(app, ["doc", "set", "--doc", "10", "--markdown", "# New"])
        assert result.exit_code == 0, result.stdout
        bodies = [json.loads(r.content) for r in httpx_mock.get_requests()]
        add_body = next(
            b for b in bodies if "add_content_to_doc_from_markdown" in b.get("query", "")
        )
        assert add_body["variables"]["after"] == "t1"

    def test_empty_markdown_rejected_without_mutating(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["doc", "set", "--doc", "10", "--markdown", "   "])
        assert result.exit_code == 2
        # never touches the API — the doc keeps its content
        assert httpx_mock.get_requests() == []

    def test_empty_doc_just_adds(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"docs": [{"id": "10", "blocks": []}]})
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "add_content_to_doc_from_markdown": {
                        "success": True,
                        "block_ids": ["n1"],
                        "error": None,
                    }
                }
            ),
        )
        result = runner.invoke(app, ["doc", "set", "--doc", "10", "--markdown", "# New"])
        assert result.exit_code == 0, result.stdout
        bodies = [json.loads(r.content) for r in httpx_mock.get_requests()]
        # fetch + add only (no deletes); new content goes to the top (after=None)
        assert len(bodies) == 2
        assert bodies[1]["variables"]["after"] is None
        assert json.loads(result.stdout)["replaced_blocks"] == 0

    def test_replace_alias(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"docs": [{"id": "10", "blocks": []}]})
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "add_content_to_doc_from_markdown": {
                        "success": True,
                        "block_ids": [],
                        "error": None,
                    }
                }
            ),
        )
        result = runner.invoke(app, ["doc", "replace", "--doc", "10", "--markdown", "# X"])
        assert result.exit_code == 0, result.stdout

    def test_by_object_id_resolution(self, httpx_mock: HTTPXMock) -> None:
        # object_id → internal id via DOC_HEAD_BY_OBJECT_ID (cache disabled)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "55", "object_id": "77"}]}),
        )
        # fetch blocks for resolved id 55
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"docs": [{"id": "55", "blocks": []}]})
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "add_content_to_doc_from_markdown": {
                        "success": True,
                        "block_ids": [],
                        "error": None,
                    }
                }
            ),
        )
        result = runner.invoke(app, ["doc", "set", "--object-id", "77", "--markdown", "# X"])
        assert result.exit_code == 0, result.stdout
        bodies = [json.loads(r.content) for r in httpx_mock.get_requests()]
        # head lookup resolves object_id 77 → 55
        assert bodies[0]["variables"] == {"objs": [77]}
        # add-content targets the resolved internal id
        assert bodies[-1]["variables"]["doc"] == 55
        assert json.loads(result.stdout)["replaced_blocks"] == 0

    def test_requires_one_doc_flag(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["doc", "set", "--markdown", "# X"])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_requires_markdown_source(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["doc", "set", "--doc", "10"])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []


class TestImageExportOutputGuards:
    """`--out` (markdown→file + image download) flag validation. Both guards
    must reject before any network call."""

    def test_get_out_requires_markdown_format(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["doc", "get", "--object-id", "77", "--format", "json", "--out", "x.md"],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_server_markdown_raw_and_out_mutually_exclusive(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            [
                "doc",
                "get",
                "--doc",
                "10",
                "--format",
                "markdown",
                "--engine",
                "server",
                "--raw",
                "--out",
                "x.md",
            ],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_get_no_images_skips_asset_download(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        """`--no-images` writes the file but never queries `assets(ids)` or
        fetches image bytes — the monday URL stays in the markdown."""
        httpx_mock.add_response(
            json={
                "data": {
                    "docs": [
                        {
                            "id": "7",
                            "object_id": "77",
                            "name": "D",
                            "blocks": [
                                {
                                    "id": "b1",
                                    "type": "image",
                                    "content": json.dumps(
                                        {"assetId": 99, "url": "https://x/img.png"}
                                    ),
                                }
                            ],
                        }
                    ]
                }
            }
        )
        out = tmp_path / "doc.md"
        result = runner.invoke(
            app,
            [
                "doc",
                "get",
                "--id",
                "7",
                "--format",
                "markdown",
                "--out",
                str(out),
                "--no-images",
            ],
        )
        assert result.exit_code == 0, result.stdout
        # Only the doc fetch happened — no assets(ids) call.
        assert len(httpx_mock.get_requests()) == 1
        md = out.read_text()
        assert "![](https://x/img.png)" in md
        assert json.loads(result.stdout)["images"] == []


class TestDocGetPdf:
    """`doc get --format pdf` — issue #68. WeasyPrint is never run for real:
    the renderer is monkeypatched so only mondo's surface logic is exercised."""

    def _doc_with_image(self) -> dict:
        return _ok(
            {
                "docs": [
                    {
                        "id": "7",
                        "object_id": "77",
                        "name": "D",
                        "blocks": [
                            {
                                "id": "b1",
                                "type": "image",
                                "content": json.dumps({"assetId": 99, "url": "https://x/img.png"}),
                            }
                        ],
                    }
                ]
            }
        )

    def test_pdf_requires_out(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["doc", "get", "--id", "7", "--format", "pdf"])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_pdf_success_emits_engine(
        self, httpx_mock: HTTPXMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mondo.cli import _pdf

        def fake_render(html_text: str, out: Path) -> None:
            out.write_bytes(b"%PDF-1.7\n")

        monkeypatch.setattr(_pdf, "render_pdf", fake_render)
        monkeypatch.setattr(_pdf, "find_weasyprint", lambda: "weasyprint")
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "7", "name": "D", "blocks": []}]}),
        )
        out = tmp_path / "doc.pdf"
        result = runner.invoke(
            app, ["doc", "get", "--id", "7", "--format", "pdf", "--out", str(out)]
        )
        assert result.exit_code == 0, result.stdout
        assert out.read_bytes().startswith(b"%PDF")
        payload = json.loads(result.stdout)
        assert payload["engine"] == "weasyprint"
        assert payload["out"] == str(out)

    def test_pdf_missing_weasyprint_errors(
        self, httpx_mock: HTTPXMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mondo.cli import _pdf

        monkeypatch.setattr(_pdf, "find_weasyprint", lambda: None)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "7", "name": "D", "blocks": []}]}),
        )
        out = tmp_path / "doc.pdf"
        result = runner.invoke(
            app, ["doc", "get", "--id", "7", "--format", "pdf", "--out", str(out)]
        )
        assert result.exit_code != 0
        assert "WeasyPrint" in (result.stderr or result.stdout)
        assert not out.exists()

    def test_pdf_no_images_keeps_no_remote_url(
        self, httpx_mock: HTTPXMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`--no-images` must not leave a live monday URL for WeasyPrint to
        fetch: no `assets(ids)` call, and the HTML carries an empty `src`."""
        from mondo.cli import _pdf

        captured: dict[str, str] = {}

        def fake_render(html_text: str, out: Path) -> None:
            captured["html"] = html_text
            out.write_bytes(b"%PDF-1.7\n")

        monkeypatch.setattr(_pdf, "render_pdf", fake_render)
        monkeypatch.setattr(_pdf, "find_weasyprint", lambda: "weasyprint")
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=self._doc_with_image())
        out = tmp_path / "doc.pdf"
        result = runner.invoke(
            app,
            ["doc", "get", "--id", "7", "--format", "pdf", "--out", str(out), "--no-images"],
        )
        assert result.exit_code == 0, result.stdout
        assert len(httpx_mock.get_requests()) == 1  # doc fetch only, no assets(ids)
        assert 'src=""' in captured["html"]
        assert "https://x/img.png" not in captured["html"]

    def test_pdf_unresolved_image_url_is_blanked(
        self, httpx_mock: HTTPXMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even on the default (embed) path, an image whose asset doesn't resolve
        must not leave its (doc-content, untrusted) URL in the HTML — WeasyPrint
        would dereference it (SSRF / file:// read). The renderer's `content.url`
        fallback is neutralized before conversion."""
        from mondo.cli import _pdf

        captured: dict[str, str] = {}

        def fake_render(html_text: str, out: Path) -> None:
            captured["html"] = html_text
            out.write_bytes(b"%PDF-1.7\n")

        monkeypatch.setattr(_pdf, "render_pdf", fake_render)
        monkeypatch.setattr(_pdf, "find_weasyprint", lambda: "weasyprint")
        # 1) doc fetch returns an image block; 2) assets(ids) resolves nothing,
        # so embed_doc_images returns {} and the renderer falls back to the URL.
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=self._doc_with_image())
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"assets": []}))
        out = tmp_path / "doc.pdf"
        result = runner.invoke(
            app, ["doc", "get", "--id", "7", "--format", "pdf", "--out", str(out)]
        )
        assert result.exit_code == 0, result.stdout
        assert "https://x/img.png" not in captured["html"]
        assert 'src=""' in captured["html"]

    def test_pdf_svg_data_uri_is_blanked(
        self, httpx_mock: HTTPXMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A `data:image/svg+xml` src must NOT survive: an SVG can reference
        external resources that WeasyPrint would fetch, so only raster data
        URIs are allowed through. The svg here is doc content (untrusted)."""
        from mondo.cli import _pdf

        captured: dict[str, str] = {}

        def fake_render(html_text: str, out: Path) -> None:
            captured["html"] = html_text
            out.write_bytes(b"%PDF-1.7\n")

        monkeypatch.setattr(_pdf, "render_pdf", fake_render)
        monkeypatch.setattr(_pdf, "find_weasyprint", lambda: "weasyprint")
        svg = "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4="
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "7",
                            "name": "D",
                            "blocks": [
                                {"id": "b1", "type": "image", "content": json.dumps({"url": svg})}
                            ],
                        }
                    ]
                }
            ),
        )
        out = tmp_path / "doc.pdf"
        result = runner.invoke(
            app, ["doc", "get", "--id", "7", "--format", "pdf", "--out", str(out)]
        )
        assert result.exit_code == 0, result.stdout
        assert "svg+xml" not in captured["html"]
        assert 'src=""' in captured["html"]

    def test_sanitize_pdf_image_srcs_validates_magic_bytes(self) -> None:
        import base64

        from mondo.cli.doc import _sanitize_pdf_image_srcs

        def uri(mime: str, data: bytes) -> str:
            return f"data:{mime};base64,{base64.b64encode(data).decode()}"

        png = uri("image/png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
        tiff = uri("image/tiff", b"II*\x00" + b"\x00" * 40)  # inert raster — must survive
        # SVG bytes DECLARED as png: WeasyPrint would sniff + fetch — must blank.
        svg_as_png = uri("image/png", b'<svg xmlns="http://x"><image href="http://evil/"/></svg>')
        declared_svg = uri("image/svg+xml", b"<svg/>")
        html = "".join(
            f'<img src="{s}" alt="">'
            for s in [png, tiff, svg_as_png, declared_svg, "https://x/a.png", "file:///etc/passwd"]
        )
        out = _sanitize_pdf_image_srcs(html)
        assert png in out  # real raster magic → kept
        assert tiff in out
        assert svg_as_png not in out  # the content-sniff SSRF bypass → blanked
        assert declared_svg not in out
        assert "https://x" not in out
        assert "file://" not in out
        assert out.count('src=""') == 4

    def test_pdf_missing_weasyprint_skips_image_embed(
        self, httpx_mock: HTTPXMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Preflight: with WeasyPrint absent, the command errors before the
        image-embed network work — only the doc fetch happens, no assets(ids)."""
        from mondo.cli import _pdf

        monkeypatch.setattr(_pdf, "find_weasyprint", lambda: None)
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=self._doc_with_image())
        out = tmp_path / "doc.pdf"
        result = runner.invoke(
            app, ["doc", "get", "--id", "7", "--format", "pdf", "--out", str(out)]
        )
        assert result.exit_code != 0
        assert len(httpx_mock.get_requests()) == 1  # doc fetch only; no assets(ids)
        assert not out.exists()


class TestAddMarkdownChunking:
    """Issues #59 / #63: auto-chunk large markdown and report blocks_added."""

    def test_blocks_added_counts_block_ids(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "add_content_to_doc_from_markdown": {
                        "success": True,
                        "block_ids": ["b1", "b2", "b3"],
                        "error": None,
                    }
                }
            ),
        )
        result = runner.invoke(app, ["doc", "add-markdown", "--doc", "10", "--markdown", "# Hi"])
        assert result.exit_code == 0, result.stdout
        emitted = json.loads(result.stdout)
        assert emitted["blocks_added"] == 3
        assert emitted["block_ids"] == ["b1", "b2", "b3"]

    def test_large_input_chunks_with_chained_after(self, httpx_mock: HTTPXMock) -> None:
        # Three big paragraphs, each its own chunk under the (small) limit.
        big = "\n\n".join("para " + str(i) + " " + "x" * 9000 for i in range(3))
        # The loop interleaves: add chunk → re-fetch last ROOT block → add next
        # chunk, anchoring afterBlockId to the re-fetched root (NOT the raw
        # block_ids[-1], which can be a nested child).
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "add_content_to_doc_from_markdown": {
                        "success": True,
                        "block_ids": ["c0"],
                        "error": None,
                    }
                }
            ),
        )
        # Re-fetch after chunk 0: its root c0 plus a pre-existing tail block.
        # The anchor must be c0 (this chunk's root), NOT the later tail.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "10", "blocks": [{"id": "c0"}, {"id": "tail"}]}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "add_content_to_doc_from_markdown": {
                        "success": True,
                        "block_ids": ["c1"],
                        "error": None,
                    }
                }
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {"docs": [{"id": "10", "blocks": [{"id": "c0"}, {"id": "c1"}, {"id": "tail"}]}]}
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "add_content_to_doc_from_markdown": {
                        "success": True,
                        "block_ids": ["c2"],
                        "error": None,
                    }
                }
            ),
        )
        result = runner.invoke(app, ["doc", "add-markdown", "--doc", "10", "--markdown", big])
        assert result.exit_code == 0, result.stdout
        bodies = [json.loads(r.content) for r in httpx_mock.get_requests()]
        # add, fetch, add, fetch, add = 5 requests.
        assert len(bodies) == 5
        adds = [b for b in bodies if "markdown:" in b["query"] or "add_content" in b["query"]]
        # First chunk uses the supplied after (None); each later chunk anchors
        # to the last root block *that chunk* produced (per the intervening
        # re-fetch), never the doc's pre-existing tail.
        assert adds[0]["variables"]["after"] is None
        assert adds[1]["variables"]["after"] == "c0"
        assert adds[2]["variables"]["after"] == "c1"
        emitted = json.loads(result.stdout)
        assert emitted["block_ids"] == ["c0", "c1", "c2"]
        assert emitted["blocks_added"] == 3

    def test_code_fence_not_split_across_chunks(self, httpx_mock: HTTPXMock) -> None:
        # A fence with internal blank lines must stay one chunk (one call).
        fence = "```\n" + "\n\n".join(f"line {i}" for i in range(5)) + "\n```"
        md = f"# Title\n\n{fence}"
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "add_content_to_doc_from_markdown": {
                        "success": True,
                        "block_ids": ["b1"],
                        "error": None,
                    }
                }
            ),
            is_reusable=True,
        )
        result = runner.invoke(app, ["doc", "add-markdown", "--doc", "10", "--markdown", md])
        assert result.exit_code == 0, result.stdout
        # Whichever chunk carries the fence keeps both ``` delimiters together.
        sent = [
            json.loads(r.content)["variables"].get("md")
            for r in httpx_mock.get_requests()
            if "md" in json.loads(r.content)["variables"]
        ]
        fence_payloads = [s for s in sent if s and "```" in s]
        assert len(fence_payloads) == 1
        assert fence_payloads[0].count("```") == 2

    def test_table_normalized_before_send(self, httpx_mock: HTTPXMock) -> None:
        # #61 wired into add-markdown: a ragged body row is normalized first.
        md = "| A | B | C |\n| --- | --- | --- |\n| 1 | 2 | 3 | 4 |\n"
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "add_content_to_doc_from_markdown": {
                        "success": True,
                        "block_ids": ["b1"],
                        "error": None,
                    }
                }
            ),
        )
        result = runner.invoke(app, ["doc", "add-markdown", "--doc", "10", "--markdown", md])
        assert result.exit_code == 0, result.stdout
        sent_md = json.loads(httpx_mock.get_requests()[-1].content)["variables"]["md"]
        # The 4th cell is merged into column C; no runaway extra column.
        assert "| 3 4 |" in sent_md


class TestDocSetChunking:
    """Issue #59: `doc set` chunks too, and never deletes on a failed add."""

    def test_failed_add_chunk_rolls_back_partial_and_keeps_old(self, httpx_mock: HTTPXMock) -> None:
        big = "\n\n".join("para " + str(i) + " " + "x" * 9000 for i in range(3))
        # 1) fetch existing blocks
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "10", "blocks": [{"id": "old1"}, {"id": "old2"}]}]}),
        )
        # 2) first add chunk succeeds, appending n0
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "add_content_to_doc_from_markdown": {
                        "success": True,
                        "block_ids": ["n0"],
                        "error": None,
                    }
                }
            ),
        )
        # 2b) re-fetch the last root block to anchor the next chunk
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "10", "blocks": [{"id": "n0"}]}]}),
        )
        # 3) second add chunk FAILS
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "add_content_to_doc_from_markdown": {
                        "success": False,
                        "block_ids": None,
                        "error": "INTERNAL_SERVER_ERROR",
                    }
                }
            ),
        )
        # 4) rollback re-fetch: doc now holds the old blocks + the appended n0
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {"docs": [{"id": "10", "blocks": [{"id": "old1"}, {"id": "old2"}, {"id": "n0"}]}]}
            ),
        )
        # 5) rollback deletes the partial block
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"delete_doc_block": {"id": "n0"}})
        )
        # any further calls (object-id probe) answer "no match"
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"docs": []}), is_reusable=True
        )
        result = runner.invoke(app, ["doc", "set", "--doc", "10", "--markdown", big])
        assert result.exit_code != 0
        deleted = [
            json.loads(r.content)["variables"].get("block")
            for r in httpx_mock.get_requests()
            if "delete_doc_block" in json.loads(r.content).get("query", "")
        ]
        # Only the partially-added block is rolled back; the old content stays.
        assert deleted == ["n0"]

    def test_rollback_spares_concurrent_block(self, httpx_mock: HTTPXMock) -> None:
        # A block another user added between the initial fetch and the rollback
        # is NOT in the add's reported ids, so rollback must not delete it.
        big = "\n\n".join("para " + str(i) + " " + "x" * 9000 for i in range(3))
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "10", "blocks": [{"id": "old1"}]}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "add_content_to_doc_from_markdown": {
                        "success": True,
                        "block_ids": ["n0"],
                        "error": None,
                    }
                }
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "10", "blocks": [{"id": "n0"}]}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "add_content_to_doc_from_markdown": {
                        "success": False,
                        "block_ids": None,
                        "error": "INTERNAL_SERVER_ERROR",
                    }
                }
            ),
        )
        # rollback re-fetch: old1, the added n0, AND a concurrent block "conc1"
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {"docs": [{"id": "10", "blocks": [{"id": "old1"}, {"id": "n0"}, {"id": "conc1"}]}]}
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"delete_doc_block": {"id": "n0"}})
        )
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"docs": []}), is_reusable=True
        )
        result = runner.invoke(app, ["doc", "set", "--doc", "10", "--markdown", big])
        assert result.exit_code != 0
        deleted = [
            json.loads(r.content)["variables"].get("block")
            for r in httpx_mock.get_requests()
            if "delete_doc_block" in json.loads(r.content).get("query", "")
        ]
        # n0 (added by the failed run) is rolled back; conc1 (concurrent) is spared.
        assert deleted == ["n0"]

    def test_raised_error_mid_chunk_still_rolls_back(self, httpx_mock: HTTPXMock) -> None:
        # When a later chunk *raises* (server/network error) rather than
        # returning success:false, the already-added blocks must still roll back.
        big = "\n\n".join("para " + str(i) + " " + "x" * 9000 for i in range(3))
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "10", "blocks": [{"id": "old1"}]}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "add_content_to_doc_from_markdown": {
                        "success": True,
                        "block_ids": ["n0"],
                        "error": None,
                    }
                }
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "10", "blocks": [{"id": "n0"}]}]}),
        )
        # chunk 2 raises (GraphQL error envelope → MondoError), not success:false
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json={
                "errors": [{"message": "boom", "extensions": {"code": "BANG", "request_id": "r"}}]
            },
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "10", "blocks": [{"id": "old1"}, {"id": "n0"}]}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"delete_doc_block": {"id": "n0"}})
        )
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"docs": []}), is_reusable=True
        )
        result = runner.invoke(app, ["doc", "set", "--doc", "10", "--markdown", big])
        assert result.exit_code != 0
        deleted = [
            json.loads(r.content)["variables"].get("block")
            for r in httpx_mock.get_requests()
            if "delete_doc_block" in json.loads(r.content).get("query", "")
        ]
        assert deleted == ["n0"]


class TestDocClear:
    """Issue #60: `doc clear` empties a doc but keeps the document."""

    def test_clears_all_blocks(self, httpx_mock: HTTPXMock) -> None:
        # 1) fetch existing blocks
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "10", "blocks": [{"id": "b1"}, {"id": "b2"}]}]}),
        )
        # 2) delete b1, 3) delete b2
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"delete_doc_block": {"id": "b1"}})
        )
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"delete_doc_block": {"id": "b2"}})
        )
        result = runner.invoke(app, ["doc", "clear", "--doc", "10"])
        assert result.exit_code == 0, result.stdout
        bodies = [json.loads(r.content) for r in httpx_mock.get_requests()]
        assert len(bodies) == 3
        assert bodies[1]["variables"]["block"] == "b1"
        assert bodies[2]["variables"]["block"] == "b2"
        emitted = json.loads(result.stdout)
        assert emitted == {"id": 10, "cleared_blocks": 2}

    def test_empty_doc_is_noop(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"docs": [{"id": "10", "blocks": []}]})
        )
        result = runner.invoke(app, ["doc", "clear", "--doc", "10"])
        assert result.exit_code == 0, result.stdout
        # Only the fetch happened — no deletes.
        assert len(httpx_mock.get_requests()) == 1
        assert json.loads(result.stdout) == {"id": 10, "cleared_blocks": 0}

    def test_requires_one_doc_flag(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["doc", "clear"])
        assert result.exit_code == 2

    def test_dry_run_prints_plan(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["--dry-run", "doc", "clear", "--doc", "10"])
        assert result.exit_code == 0, result.stdout
        assert httpx_mock.get_requests() == []
        plan = json.loads(result.stdout)
        assert plan["variables"] == {"doc": 10}
        assert "delete_doc_block" in plan["query"].lower() or "DELETE" in plan["query"]


class TestExportMarkdownCoalesce:
    """Issue #62: fragmented bold runs are rejoined in server-markdown output."""

    def test_fragmented_bold_collapsed(self, httpx_mock: HTTPXMock) -> None:
        fragmented = "**Caching is ****not**** a win**"
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "export_markdown_from_doc": {
                        "success": True,
                        "error": None,
                        "markdown": fragmented,
                    }
                }
            ),
        )
        result = runner.invoke(
            app, ["doc", "get", "--doc", "10", "--format", "markdown", "--engine", "server"]
        )
        assert result.exit_code == 0, result.stdout
        assert "**Caching is not a win**" in result.stdout
        assert "****" not in result.stdout

    def test_coalesce_applied_to_out_path(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        fragmented = "**a ****b**"
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "export_markdown_from_doc": {
                        "success": True,
                        "error": None,
                        "markdown": fragmented,
                    }
                }
            ),
        )
        out = tmp_path / "exported.md"
        result = runner.invoke(
            app,
            [
                "doc",
                "get",
                "--doc",
                "10",
                "--format",
                "markdown",
                "--engine",
                "server",
                "--out",
                str(out),
                "--no-images",
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert out.read_text() == "**a b**"


class TestDocCreateUnauthorizedSuggestion:
    """Issue #64: actionable suggestion on USER_UNAUTHORIZED doc create."""

    def test_unauthorized_carries_license_suggestion(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json={
                "errors": [
                    {
                        "message": "User is not permitted to create public doc in this workspace",
                        "extensions": {"code": "USER_UNAUTHORIZED", "request_id": "r"},
                    }
                ]
            },
        )
        result = runner.invoke(
            app,
            ["-o", "json", "doc", "create", "--workspace", "42", "--name", "Spec"],
        )
        assert result.exit_code == 3
        # The structured envelope (stderr) carries the suggestion field.
        env_line = [
            line
            for line in result.stderr.splitlines()
            if line.strip().startswith("{") and "suggestion" in line
        ]
        assert env_line, result.stderr
        env = json.loads(env_line[-1])
        assert env["code"] == "USER_UNAUTHORIZED"
        assert "doc-creation license/policy" in env["suggestion"]

    def test_other_errors_unchanged(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json={
                "errors": [
                    {
                        "message": "Workspace not found",
                        "extensions": {"code": "ResourceNotFoundException", "request_id": "r"},
                    }
                ]
            },
        )
        result = runner.invoke(
            app,
            ["-o", "json", "doc", "create", "--workspace", "42", "--name", "Spec"],
        )
        assert result.exit_code == 6
        assert "doc-creation license" not in (result.stderr + result.stdout)
