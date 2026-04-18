"""Cursor-based pagination over `items_page` / `next_items_page`.

Per monday-api.md §7:
- Max page size is 500.
- Cursor lifetime is 60 minutes. An expired cursor raises `CursorExpiredError`;
  recover by re-issuing the initial page.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol

from mondo.api.errors import CursorExpiredError
from mondo.api.queries import ITEMS_PAGE_INITIAL, ITEMS_PAGE_NEXT

MAX_PAGE_SIZE = 500


class _ClientProtocol(Protocol):
    def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]: ...


def iter_items_page(
    client: _ClientProtocol,
    *,
    board_id: int | str,
    limit: int = MAX_PAGE_SIZE,
    query_params: dict[str, Any] | None = None,
    max_items: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield items from a board, following `items_page` cursors.

    Stops when `max_items` is reached (if set) or the cursor is None.
    Handles expired cursors by restarting from the initial page.
    """
    yielded = 0
    page_size = min(limit, MAX_PAGE_SIZE)
    initial_vars: dict[str, Any] = {
        "boards": [board_id],
        "limit": page_size,
        "qp": query_params,
    }
    page = _initial_page(client, initial_vars)
    cursor = page["cursor"]

    for item in page["items"]:
        if max_items is not None and yielded >= max_items:
            return
        yield item
        yielded += 1

    while cursor:
        try:
            next_page = _fetch_next(client, cursor, page_size)
        except CursorExpiredError:
            # Restart from the initial page; the caller re-sees some items.
            page = _initial_page(client, initial_vars)
            cursor = page["cursor"]
            for item in page["items"]:
                if max_items is not None and yielded >= max_items:
                    return
                yield item
                yielded += 1
            continue

        cursor = next_page["cursor"]
        for item in next_page["items"]:
            if max_items is not None and yielded >= max_items:
                return
            yield item
            yielded += 1


def _initial_page(client: _ClientProtocol, variables: dict[str, Any]) -> dict[str, Any]:
    result = client.execute(ITEMS_PAGE_INITIAL, variables)
    boards = (result.get("data") or {}).get("boards") or []
    if not boards:
        return {"cursor": None, "items": []}
    return boards[0].get("items_page") or {"cursor": None, "items": []}


def _fetch_next(client: _ClientProtocol, cursor: str, limit: int) -> dict[str, Any]:
    result = client.execute(ITEMS_PAGE_NEXT, {"cursor": cursor, "limit": limit})
    return (result.get("data") or {}).get("next_items_page") or {
        "cursor": None,
        "items": [],
    }
