"""Tests for `fetch_pages_concurrent` — the worker-pool walk for page-based
collections (#20).

The fake client serves pages by the requested `page` variable (thread-safe),
so the assertions hold regardless of which worker finishes first. The
contract under test: output identical to the serial iterator — pages
concatenated in page order, truncated at the first short page, then at
`max_items`.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from mondo.api.pagination import directory_fetch_concurrency, fetch_pages_concurrent

QUERY = "query ($limit: Int!, $page: Int!) { boards { id } }"


class PagedFakeClient:
    """Serves `pages[page_number]` (default: empty). Thread-safe call log."""

    def __init__(self, pages: dict[int, list[dict[str, Any]]]) -> None:
        self.pages = pages
        self._lock = threading.Lock()
        self.requested_pages: list[int] = []

    def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        page = (variables or {})["page"]
        with self._lock:
            self.requested_pages.append(page)
        return {"data": {"boards": self.pages.get(page, [])}}


def _rows(start: int, count: int) -> list[dict[str, Any]]:
    return [{"id": str(i)} for i in range(start, start + count)]


class TestFetchPagesConcurrent:
    def test_single_short_page_costs_one_request(self) -> None:
        client = PagedFakeClient({1: _rows(1, 3)})
        out = fetch_pages_concurrent(client, query=QUERY, variables={}, limit=5, concurrency=4)
        assert [r["id"] for r in out] == ["1", "2", "3"]
        assert client.requested_pages == [1]

    def test_multi_page_preserves_order(self) -> None:
        pages = {
            1: _rows(1, 5),
            2: _rows(6, 5),
            3: _rows(11, 5),
            4: _rows(16, 5),
            5: _rows(21, 5),
            6: _rows(26, 2),  # short → final
        }
        client = PagedFakeClient(pages)
        out = fetch_pages_concurrent(client, query=QUERY, variables={}, limit=5, concurrency=4)
        assert [r["id"] for r in out] == [str(i) for i in range(1, 28)]
        # Page 1 first (serial), then waves starting at 2.
        assert client.requested_pages[0] == 1
        assert set(client.requested_pages) >= {1, 2, 3, 4, 5, 6}

    def test_short_page_mid_wave_discards_later_pages(self) -> None:
        # Page 2 is short; pages 3-5 (same wave) return rows that must NOT
        # leak into the result — serial semantics stop at the first short page.
        pages = {
            1: _rows(1, 5),
            2: _rows(6, 2),
            3: _rows(100, 5),
            4: _rows(200, 5),
        }
        client = PagedFakeClient(pages)
        out = fetch_pages_concurrent(client, query=QUERY, variables={}, limit=5, concurrency=4)
        assert [r["id"] for r in out] == [str(i) for i in range(1, 8)]

    def test_exact_multiple_then_empty_page(self) -> None:
        pages = {1: _rows(1, 5), 2: _rows(6, 5)}
        client = PagedFakeClient(pages)
        out = fetch_pages_concurrent(client, query=QUERY, variables={}, limit=5, concurrency=4)
        assert len(out) == 10

    def test_max_items_truncates(self) -> None:
        pages = {1: _rows(1, 5), 2: _rows(6, 5), 3: _rows(11, 5)}
        client = PagedFakeClient(pages)
        out = fetch_pages_concurrent(
            client, query=QUERY, variables={}, limit=5, max_items=7, concurrency=4
        )
        assert [r["id"] for r in out] == [str(i) for i in range(1, 8)]

    def test_max_items_caps_wave_size(self) -> None:
        # max_items=250, page_size=100, workers=4: page 1 (serial) leaves
        # 150 rows → ceil(150/100) = 2 pages. The wave must request pages
        # 2-3 only — pages 4-5 would be billed complexity, then discarded.
        pages = {p: _rows((p - 1) * 100 + 1, 100) for p in range(1, 7)}
        client = PagedFakeClient(pages)
        out = fetch_pages_concurrent(
            client, query=QUERY, variables={}, limit=100, max_items=250, concurrency=4
        )
        assert len(out) == 250
        assert sorted(client.requested_pages) == [1, 2, 3]

    def test_max_items_within_first_page_stays_serial(self) -> None:
        client = PagedFakeClient({1: _rows(1, 5)})
        out = fetch_pages_concurrent(
            client, query=QUERY, variables={}, limit=5, max_items=2, concurrency=4
        )
        assert len(out) == 2
        assert client.requested_pages == [1]

    def test_concurrency_one_falls_back_to_serial(self) -> None:
        pages = {1: _rows(1, 5), 2: _rows(6, 3)}
        client = PagedFakeClient(pages)
        out = fetch_pages_concurrent(client, query=QUERY, variables={}, limit=5, concurrency=1)
        assert len(out) == 8
        assert client.requested_pages == [1, 2]

    def test_env_var_sets_default_concurrency(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MONDO_DIR_FETCH_CONCURRENCY", "1")
        pages = {1: _rows(1, 5), 2: _rows(6, 3)}
        client = PagedFakeClient(pages)
        out = fetch_pages_concurrent(client, query=QUERY, variables={}, limit=5)
        assert len(out) == 8
        assert client.requested_pages == [1, 2]

    def test_env_var_invalid_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MONDO_DIR_FETCH_CONCURRENCY", "not-a-number")
        assert directory_fetch_concurrency() == 4

    def test_env_var_clamped_to_16(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MONDO_DIR_FETCH_CONCURRENCY", "500")
        assert directory_fetch_concurrency() == 16

    def test_env_var_above_one_is_honored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MONDO_DIR_FETCH_CONCURRENCY", "2")
        assert directory_fetch_concurrency() == 2
        # Behavioral check: the walk ends at page 3 (short), the last page of
        # a 2-wide wave — pages 4-5 are never requested (a wave of 4 would
        # have submitted them).
        pages = {
            1: _rows(1, 5),
            2: _rows(6, 5),
            3: _rows(11, 2),
            4: _rows(100, 5),
            5: _rows(200, 5),
        }
        client = PagedFakeClient(pages)
        out = fetch_pages_concurrent(client, query=QUERY, variables={}, limit=5)
        assert [r["id"] for r in out] == [str(i) for i in range(1, 13)]
        assert sorted(client.requested_pages) == [1, 2, 3]

    def test_variables_passed_through_with_page_and_limit(self) -> None:
        captured: list[dict[str, Any]] = []
        lock = threading.Lock()

        class CapturingClient:
            def execute(
                self, query: str, variables: dict[str, Any] | None = None
            ) -> dict[str, Any]:
                with lock:
                    captured.append(variables or {})
                return {"data": {"boards": []}}

        fetch_pages_concurrent(
            CapturingClient(),
            query=QUERY,
            variables={"state": "all"},
            limit=7,
            concurrency=4,
        )
        assert captured == [{"state": "all", "limit": 7, "page": 1}]

    def test_worker_exception_propagates(self) -> None:
        class ExplodingClient:
            def execute(
                self, query: str, variables: dict[str, Any] | None = None
            ) -> dict[str, Any]:
                page = (variables or {})["page"]
                if page >= 2:
                    raise RuntimeError("boom")
                return {"data": {"boards": _rows(1, 5)}}

        with pytest.raises(RuntimeError, match="boom"):
            fetch_pages_concurrent(
                ExplodingClient(), query=QUERY, variables={}, limit=5, concurrency=4
            )
