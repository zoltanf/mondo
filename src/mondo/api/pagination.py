"""Cursor-based pagination over `items_page` / `next_items_page`.

Per monday-api.md §7:
- Max page size is 500.
- Cursor lifetime is 60 minutes. An expired cursor raises `CursorExpiredError`;
  recover by re-issuing the initial page.

Also home to `fetch_pages_concurrent` — the worker-pool walk for page-based
collections (boards/users/docs/folders/workspaces/updates), whose pages are
independently addressable, unlike `items_page` cursors.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
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
    extra_vars: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield items from a board, following `items_page` cursors.

    Stops when `max_items` is reached (if set) or the cursor is None.
    Handles expired cursors by restarting from the initial page.

    `query_initial` / `query_next` let callers swap in field selections
    (e.g. `ITEMS_PAGE_INITIAL_WITH_SUBITEMS` for export). `extra_vars`
    binds additional variables both queries declare (e.g. `$cols` from
    `build_items_page_queries(column_values="ids")`).
    """
    yielded = 0
    page_size = min(limit, MAX_PAGE_SIZE)
    initial_vars: dict[str, Any] = {
        "boards": [board_id],
        "limit": page_size,
        "qp": query_params,
        **(extra_vars or {}),
    }
    # Track ids already emitted so a cursor-expiry restart (which replays the
    # initial page) can't yield the same item twice.
    seen: set[Any] = set()

    page = _initial_page(client, query_initial, initial_vars)
    cursor = page["cursor"]

    for item in page["items"]:
        if max_items is not None and yielded >= max_items:
            return
        item_id = item.get("id")
        if item_id in seen:
            continue
        seen.add(item_id)
        yield item
        yielded += 1

    while cursor:
        try:
            next_page = _fetch_next(client, query_next, cursor, page_size, extra_vars)
        except CursorExpiredError:
            # Restart from the initial page; the `seen` set below skips any
            # item already yielded, so the restart can't produce duplicates.
            next_page = _initial_page(client, query_initial, initial_vars)

        cursor = next_page["cursor"]
        for item in next_page["items"]:
            if max_items is not None and yielded >= max_items:
                return
            item_id = item.get("id")
            if item_id in seen:
                continue
            seen.add(item_id)
            yield item
            yielded += 1


def _initial_page(client: _ClientProtocol, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    result = client.execute(query, variables)
    boards = (result.get("data") or {}).get("boards") or []
    if not boards:
        return {"cursor": None, "items": []}
    return boards[0].get("items_page") or {"cursor": None, "items": []}


def _fetch_next(
    client: _ClientProtocol,
    query: str,
    cursor: str,
    limit: int,
    extra_vars: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = client.execute(query, {"cursor": cursor, "limit": limit, **(extra_vars or {})})
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


DIRECTORY_FETCH_CONCURRENCY_ENV = "MONDO_DIR_FETCH_CONCURRENCY"
DEFAULT_DIRECTORY_FETCH_CONCURRENCY = 4


def directory_fetch_concurrency() -> int:
    raw = os.environ.get(DIRECTORY_FETCH_CONCURRENCY_ENV)
    if raw:
        try:
            # Clamp to 16 — anything higher just spawns idle threads and
            # multiplies in-flight requests against the complexity budget.
            return max(1, min(int(raw), 16))
        except ValueError:
            pass
    return DEFAULT_DIRECTORY_FETCH_CONCURRENCY


def fetch_pages_concurrent(
    client: _ClientProtocol,
    *,
    query: str,
    variables: dict[str, Any],
    collection_key: str = "boards",
    limit: int = MAX_BOARDS_PAGE_SIZE,
    max_items: int | None = None,
    concurrency: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch every page of a page-based collection with a small worker pool.

    Page 1 is always fetched serially — the overwhelmingly common
    single-page case costs exactly one request, byte-for-byte identical
    to the serial iterator. When page 1 comes back full, pages 2..N are
    fetched in waves of `concurrency` (default 4, override with
    `MONDO_DIR_FETCH_CONCURRENCY`; 1 falls back to the serial iterator).

    The first short page ends the walk; anything a later page in the same
    wave returned is discarded, so the output matches the serial iterator
    exactly (pages concatenated in page order, truncated at the first
    short page, then at `max_items`).

    Thread-safety: `httpx.Client` is documented thread-safe; the complexity
    meter takes an internal lock in `record()`. A wave of 4 100-row pages
    stays far below the complexity budget.
    """
    page_size = max(1, limit)
    workers = concurrency if concurrency is not None else directory_fetch_concurrency()
    if workers <= 1:
        return list(
            iter_boards_page(
                client,
                query=query,
                variables=variables,
                collection_key=collection_key,
                limit=page_size,
                max_items=max_items,
            )
        )

    def _truncated(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return records[:max_items] if max_items is not None else records

    def _fetch(page: int) -> list[dict[str, Any]]:
        result = client.execute(query, {**variables, "limit": page_size, "page": page})
        records = (result.get("data") or {}).get(collection_key) or []
        return records if isinstance(records, list) else []

    out = _fetch(1)
    if len(out) < page_size or (max_items is not None and len(out) >= max_items):
        return _truncated(out)

    next_page = 2
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while True:
            wave_size = workers
            if max_items is not None:
                # Don't request pages beyond what max_items can consume —
                # overshoot requests are billed complexity, then discarded.
                pages_left = -(-(max_items - len(out)) // page_size)
                wave_size = min(workers, pages_left)
            wave = range(next_page, next_page + wave_size)
            for records in pool.map(_fetch, wave):
                out.extend(records)
                if len(records) < page_size:
                    return _truncated(out)
                if max_items is not None and len(out) >= max_items:
                    return _truncated(out)
            next_page += wave_size
