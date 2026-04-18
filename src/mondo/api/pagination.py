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
    query_initial: str = ITEMS_PAGE_INITIAL,
    query_next: str = ITEMS_PAGE_NEXT,
) -> Iterator[dict[str, Any]]:
    """Yield items from a board, following `items_page` cursors.

    Stops when `max_items` is reached (if set) or the cursor is None.
    Handles expired cursors by restarting from the initial page.

    `query_initial` / `query_next` let callers swap in field selections
    (e.g. `ITEMS_PAGE_INITIAL_WITH_SUBITEMS` for export).
    """
    yielded = 0
    page_size = min(limit, MAX_PAGE_SIZE)
    initial_vars: dict[str, Any] = {
        "boards": [board_id],
        "limit": page_size,
        "qp": query_params,
    }
    page = _initial_page(client, query_initial, initial_vars)
    cursor = page["cursor"]

    for item in page["items"]:
        if max_items is not None and yielded >= max_items:
            return
        yield item
        yielded += 1

    while cursor:
        try:
            next_page = _fetch_next(client, query_next, cursor, page_size)
        except CursorExpiredError:
            # Restart from the initial page; the caller re-sees some items.
            page = _initial_page(client, query_initial, initial_vars)
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


def _initial_page(client: _ClientProtocol, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    result = client.execute(query, variables)
    boards = (result.get("data") or {}).get("boards") or []
    if not boards:
        return {"cursor": None, "items": []}
    return boards[0].get("items_page") or {"cursor": None, "items": []}


def _fetch_next(client: _ClientProtocol, query: str, cursor: str, limit: int) -> dict[str, Any]:
    result = client.execute(query, {"cursor": cursor, "limit": limit})
    return (result.get("data") or {}).get("next_items_page") or {
        "cursor": None,
        "items": [],
    }


MAX_BOARDS_PAGE_SIZE = 100


def iter_boards_page(
    client: _ClientProtocol,
    *,
    query: str,
    variables: dict[str, Any],
    collection_key: str = "boards",
    limit: int = MAX_BOARDS_PAGE_SIZE,
    max_items: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Iterate a page-based monday collection (boards/workspaces/users/etc.).

    Unlike `iter_items_page`, these endpoints use `limit` + `page` (1-indexed);
    stop when a page returns fewer than `limit` items.

    `query` must accept `$limit: Int!` and `$page: Int!` variables and return
    a top-level list under `data[collection_key]`.
    """
    page = 1
    page_size = max(1, limit)
    yielded = 0
    while True:
        result = client.execute(query, {**variables, "limit": page_size, "page": page})
        records = (result.get("data") or {}).get(collection_key) or []
        if not records:
            return
        for rec in records:
            if max_items is not None and yielded >= max_items:
                return
            yield rec
            yielded += 1
        if len(records) < page_size:
            return
        page += 1
