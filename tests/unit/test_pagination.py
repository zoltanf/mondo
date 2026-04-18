"""Tests for mondo.api.pagination — cursor-based items_page iteration."""

from __future__ import annotations

from typing import Any

from mondo.api.errors import CursorExpiredError
from mondo.api.pagination import iter_items_page


class FakeClient:
    """Records every .execute() call so tests can assert on the sequence."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((query, variables or {}))
        if not self.responses:
            raise AssertionError("FakeClient ran out of pre-canned responses")
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _initial(items: list[dict], cursor: str | None) -> dict:
    return {"data": {"boards": [{"items_page": {"cursor": cursor, "items": items}}]}}


def _next(items: list[dict], cursor: str | None) -> dict:
    return {"data": {"next_items_page": {"cursor": cursor, "items": items}}}


class TestIterItemsPage:
    def test_single_page(self) -> None:
        client = FakeClient(
            [
                _initial([{"id": "1"}, {"id": "2"}], None),
            ]
        )
        result = list(iter_items_page(client, board_id=123, limit=50))
        assert [r["id"] for r in result] == ["1", "2"]
        assert len(client.calls) == 1

    def test_two_pages(self) -> None:
        client = FakeClient(
            [
                _initial([{"id": "1"}], "CURSOR_A"),
                _next([{"id": "2"}], None),
            ]
        )
        result = list(iter_items_page(client, board_id=123, limit=1))
        assert [r["id"] for r in result] == ["1", "2"]
        assert len(client.calls) == 2
        # Second call uses next_items_page with the cursor
        assert "next_items_page" in client.calls[1][0]
        assert client.calls[1][1] == {"cursor": "CURSOR_A", "limit": 1}

    def test_max_items_short_circuit(self) -> None:
        client = FakeClient(
            [
                _initial([{"id": "1"}, {"id": "2"}, {"id": "3"}], "CURSOR_A"),
            ]
        )
        result = list(iter_items_page(client, board_id=123, limit=50, max_items=2))
        assert [r["id"] for r in result] == ["1", "2"]
        # Should not have fetched the next page
        assert len(client.calls) == 1

    def test_query_params_passed_through(self) -> None:
        client = FakeClient([_initial([], None)])
        rules = {"rules": [{"column_id": "status", "compare_value": ["Done"]}]}
        list(iter_items_page(client, board_id=123, limit=25, query_params=rules))
        assert client.calls[0][1]["qp"] == rules

    def test_cursor_expired_restarts(self) -> None:
        """Per plan §8.5 / monday-api.md §7: on CursorExpiredError, re-issue the
        initial page and continue from there."""
        client = FakeClient(
            [
                _initial([{"id": "1"}], "CURSOR_EXPIRED"),
                CursorExpiredError("cursor expired", request_id="r"),
                # Restart with fresh initial page (same boardId/limit/queryParams)
                _initial([{"id": "1"}, {"id": "2"}], None),
            ]
        )
        list(iter_items_page(client, board_id=123, limit=50))
        # The same first item appears twice because the restart replays items
        # that were already yielded. The iterator must keep going without
        # raising, and the caller's dedup (if any) is a higher-level concern.
        assert len(client.calls) == 3

    def test_empty_board(self) -> None:
        client = FakeClient([_initial([], None)])
        result = list(iter_items_page(client, board_id=123, limit=50))
        assert result == []

    def test_max_items_zero_returns_nothing(self) -> None:
        client = FakeClient([_initial([{"id": "1"}], None)])
        result = list(iter_items_page(client, board_id=123, limit=50, max_items=0))
        assert result == []
        # Implementation detail: the initial page is fetched even if max_items=0,
        # since we don't know the page is empty until we try. That's fine.
