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
    store.write([
        {"id": "1", "name": "Main"},
        {"id": "42", "name": "Engineering"},
        {"id": "43", "name": "Sales"},
    ])


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
        result = runner.invoke(
            app, ["doc", "list", "--name-matches", r"^rfc-\d+$"]
        )
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

    def test_query_includes_doc_folder_id_and_updated_at(
        self, httpx_mock: HTTPXMock
    ) -> None:
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
            json=_ok(
                {"docs": [{"id": "1", "name": "A", "doc_kind": "private"}]}
            ),
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
            json=_ok(
                {"docs": [{"id": "1", "name": "A", "doc_folder_id": "42"}]}
            ),
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

    def test_with_url_exposes_url_and_relative_url(
        self, httpx_mock: HTTPXMock
    ) -> None:
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
            json=_ok({"docs": [{
                "id": "1",
                "object_id": "100",
                "name": "Alpha",
                "workspace_id": "42",
                "created_at": "2024-01-01T10:00:00Z",
            }]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{
                "id": "2",
                "object_id": "200",
                "name": "Beta",
                "workspace_id": "43",
                "created_at": "2024-02-01T10:00:00Z",
            }]}),
        )

    def test_cold_then_warm_cache(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
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

    def test_refresh_cache_forces_refetch(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
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
        result = runner.invoke(
            app, ["doc", "list", "--no-cache", "--refresh-cache"]
        )
        assert result.exit_code == 2
        assert "mutually exclusive" in (result.stderr or result.stdout).lower()

    def test_workspace_filter_applies_client_side(
        self, httpx_mock: HTTPXMock
    ) -> None:
        self._queue_prime(httpx_mock)
        result = runner.invoke(
            app, ["doc", "list", "--workspace", "42"]
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [d["id"] for d in parsed] == ["1"]

    def test_object_id_filter_applies_client_side(
        self, httpx_mock: HTTPXMock
    ) -> None:
        self._queue_prime(httpx_mock)
        result = runner.invoke(
            app, ["doc", "list", "--object-id", "200"]
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [d["id"] for d in parsed] == ["2"]

    def test_order_by_created_at_sorts_newest_first(
        self, httpx_mock: HTTPXMock
    ) -> None:
        self._queue_prime(httpx_mock)
        result = runner.invoke(
            app, ["doc", "list", "--order-by", "created_at"]
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [d["id"] for d in parsed] == ["2", "1"]

    def test_max_items_truncates(self, httpx_mock: HTTPXMock) -> None:
        self._queue_prime(httpx_mock)
        result = runner.invoke(app, ["doc", "list", "--max-items", "1"])
        assert result.exit_code == 0, result.stdout
        assert len(json.loads(result.stdout)) == 1

    def test_dry_run_emits_cache_preview(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app, ["--dry-run", "doc", "list", "--workspace", "42"]
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["cache"] == "docs"
        assert parsed["filters"]["workspace_ids"] == [42]
        assert httpx_mock.get_requests() == []

    def _queue_prime_for_fuzzy(self, httpx_mock: HTTPXMock) -> None:
        """Seed the docs cache with a richer mix so fuzzy / kind tests can
        distinguish matches. One workspace, four docs varying in name and
        doc_kind."""
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
                        },
                        {
                            "id": "2",
                            "object_id": "20",
                            "name": "Marketing Plan",
                            "workspace_id": "42",
                            "doc_kind": "private",
                        },
                        {
                            "id": "3",
                            "object_id": "30",
                            "name": "Product Roadmap",
                            "workspace_id": "42",
                            "doc_kind": "public",
                        },
                        {
                            "id": "4",
                            "object_id": "40",
                            "name": "Unrelated Stuff",
                            "workspace_id": "42",
                            "doc_kind": "private",
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

    def test_name_filters_mutually_exclusive_cache(
        self, httpx_mock: HTTPXMock
    ) -> None:
        # No priming required — validation happens before any cache read.
        result = runner.invoke(
            app,
            ["doc", "list", "--name-contains", "x", "--name-fuzzy", "y"],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_workspace_name_enriched_from_cache(
        self, httpx_mock: HTTPXMock
    ) -> None:
        """workspace_name is resolved from the workspaces cache
        (pre-warmed by autouse fixture: id=42 → 'Engineering')."""
        self._queue_prime(httpx_mock)
        result = runner.invoke(app, ["doc", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        by_id = {d["id"]: d for d in parsed}
        assert by_id["1"]["workspace_name"] == "Engineering"
        assert by_id["2"]["workspace_name"] == "Sales"

    def test_workspace_pair_adjacent_and_created_at_last(
        self, httpx_mock: HTTPXMock
    ) -> None:
        self._queue_prime(httpx_mock)
        result = runner.invoke(app, ["doc", "list"])
        assert result.exit_code == 0, result.stdout
        row = json.loads(result.stdout)[0]
        keys = list(row.keys())
        assert keys[keys.index("workspace_id") + 1] == "workspace_name"
        assert keys[-1] == "created_at"

    def test_main_workspace_name_synthesized_for_null_id(
        self, httpx_mock: HTTPXMock
    ) -> None:
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
            json=_ok({"docs": [{"id": "1", "object_id": "100", "name": "Homeless",
                                "workspace_id": None}]}),
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
        assert _last_body(httpx_mock)["variables"] == {"objs": [99]}

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
        assert _last_body(httpx_mock)["variables"] == {"ids": [7]}

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

    def test_not_found_generic_when_board_also_missing(
        self, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"docs": []}))
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": []}))
        result = runner.invoke(app, ["doc", "get", "--object-id", "99"])
        assert result.exit_code == 6
        assert "not found" in result.stderr
        assert "regular board" not in result.stderr

    def test_not_found_no_fallback_for_internal_id(
        self, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"docs": []}))
        result = runner.invoke(app, ["doc", "get", "--id", "999"])
        assert result.exit_code == 6
        # Only one HTTP call — no BOARD_GET probe on --id path.
        assert len(httpx_mock.get_requests()) == 1


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
        assert v == {"workspace": 42, "name": "New", "kind": "private"}
        parsed = json.loads(result.stdout)
        assert parsed["id"] == "10"
        assert parsed["object_id"] == "100"


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
