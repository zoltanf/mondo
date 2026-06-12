"""Fetch-or-serve orchestration for each cached entity type.

Each `get_*` function consults its `CacheStore`, returns cached entries when
fresh, otherwise fetches the full unfiltered directory live and populates the
cache. Callers apply any filtering client-side after this returns.
"""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from itertools import chain
from typing import Any

from mondo.api.client import MondayClient
from mondo.api.errors import NotFoundError
from mondo.api.pagination import (
    MAX_BOARDS_PAGE_SIZE,
    directory_fetch_concurrency,
    fetch_pages_concurrent,
)
from mondo.api.queries import (
    BOARD_GET,
    COLUMNS_ON_BOARD,
    DOC_GET_BY_ID_BLOCKS_PAGE,
    GROUPS_LIST,
    ITEM_GET,
    SUBITEMS_LIST,
    TAGS_LIST,
    TEAMS_LIST,
    UPDATES_FOR_ITEM,
    USERS_LIST_PAGE,
    WEBHOOKS_LIST,
    WORKSPACES_LIST_PAGE,
    build_boards_list_query,
    build_docs_list_query,
    build_folders_list_query,
)

# Block-fetch page size for `get_doc_blocks` — picked to match the existing
# CLI default in `mondo/cli/doc.py`. Doc bodies can be hundreds of blocks;
# 50/page keeps any one round-trip well under monday's complexity cap.
_DOC_BLOCKS_PAGE_SIZE = 50

# Updates-fetch page size for `get_updates_for_item` — mirrors the CLI's
# `MAX_UPDATES_PAGE_SIZE` (25). Updates change less than items but pages
# are smaller server-side.
_UPDATES_PAGE_SIZE = 25
from mondo.cache.store import CachedDirectory, CacheStore
from mondo.cli._normalize import normalize_board_entry, normalize_doc_entry, normalize_folder_entry

# Label for entries whose `workspace_id` is null (monday's "Main workspace").
MAIN_WORKSPACE_NAME = "Main workspace"


def _dedup_by_id(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse entries to one-per-id, preserving the last occurrence. Entries
    without a usable id are skipped so callers don't have to pre-filter."""
    by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        key = str(entry.get("id") or "")
        if key:
            by_id[key] = entry
    return list(by_id.values())


def enrich_workspace_names(
    entries: list[dict[str, Any]],
    *,
    client: MondayClient,
    store: CacheStore,
) -> None:
    """Add `workspace_name` to each entry in-place.

    Names come from the workspaces cache (auto-populated when cold).
    `workspace_id=None` → `MAIN_WORKSPACE_NAME`; unknown id → None.
    """
    cached = get_workspaces(client, store=store)
    names = {str(w["id"]): w.get("name") for w in cached.entries if w.get("id") is not None}
    for entry in entries:
        wid = entry.get("workspace_id")
        if wid is None:
            entry["workspace_name"] = MAIN_WORKSPACE_NAME
        else:
            entry["workspace_name"] = names.get(str(wid))


def get_boards(
    client: MondayClient,
    *,
    store: CacheStore,
    refresh: bool = False,
) -> CachedDirectory:
    """Return the full boards directory (all states, all workspaces).

    When `refresh` is True, the cache is ignored for reads and overwritten on
    write. Otherwise a fresh cache hit short-circuits the API call.
    """
    if not refresh:
        cached = store.read()
        if cached is not None:
            return cached

    entries = list(_fetch_all_boards(client))
    return store.write(entries)


def get_workspaces(
    client: MondayClient,
    *,
    store: CacheStore,
    refresh: bool = False,
) -> CachedDirectory:
    if not refresh:
        cached = store.read()
        if cached is not None:
            return cached
    entries = list(_fetch_all_workspaces(client))
    return store.write(entries)


def get_users(
    client: MondayClient,
    *,
    store: CacheStore,
    refresh: bool = False,
) -> CachedDirectory:
    if not refresh:
        cached = store.read()
        if cached is not None:
            return cached
    entries = list(_fetch_all_users(client))
    return store.write(entries)


def get_teams(
    client: MondayClient,
    *,
    store: CacheStore,
    refresh: bool = False,
) -> CachedDirectory:
    if not refresh:
        cached = store.read()
        if cached is not None:
            return cached
    entries = _fetch_all_teams(client)
    return store.write(entries)


def get_docs(
    client: MondayClient,
    *,
    store: CacheStore,
    refresh: bool = False,
) -> CachedDirectory:
    """Return the full docs directory (all workspaces)."""
    if not refresh:
        cached = store.read()
        if cached is not None:
            return cached
    entries = _fetch_all_docs(client)
    return store.write(entries)


def get_folders(
    client: MondayClient,
    *,
    store: CacheStore,
    refresh: bool = False,
) -> CachedDirectory:
    """Return the full folders directory (all workspaces)."""
    if not refresh:
        cached = store.read()
        if cached is not None:
            return cached
    entries = list(_fetch_all_folders(client))
    return store.write(entries)


def _fetch_all_boards(client: MondayClient) -> list[dict[str, Any]]:
    # state="all" covers active+archived+deleted so the cache is usable for
    # every --state filter client-side.
    query, variables = build_boards_list_query(state="all")
    return [
        normalize_board_entry(entry)
        for entry in fetch_pages_concurrent(
            client,
            query=query,
            variables=variables,
            collection_key="boards",
            limit=MAX_BOARDS_PAGE_SIZE,
        )
    ]


def _fetch_all_workspaces(client: MondayClient) -> list[dict[str, Any]]:
    return fetch_pages_concurrent(
        client,
        query=WORKSPACES_LIST_PAGE,
        variables={"state": "all"},
        collection_key="workspaces",
        limit=MAX_BOARDS_PAGE_SIZE,
    )


def _fetch_all_users(client: MondayClient) -> list[dict[str, Any]]:
    # monday's `non_active` is either/or: true returns ONLY disabled users,
    # false returns ONLY active. To cover both, we run both queries and merge
    # (dedup by id — shouldn't collide, but be defensive).
    active = fetch_pages_concurrent(
        client,
        query=USERS_LIST_PAGE,
        variables={"nonActive": False},
        collection_key="users",
        limit=MAX_BOARDS_PAGE_SIZE,
    )
    disabled = fetch_pages_concurrent(
        client,
        query=USERS_LIST_PAGE,
        variables={"nonActive": True},
        collection_key="users",
        limit=MAX_BOARDS_PAGE_SIZE,
    )
    return _dedup_by_id(active + disabled)


def _fetch_all_teams(client: MondayClient) -> list[dict[str, Any]]:
    # Teams aren't paginated server-side; single call suffices.
    result = client.execute(TEAMS_LIST, {"ids": None})
    data = result.get("data") or {}
    teams = data.get("teams") or []
    if not isinstance(teams, list):
        return []
    return teams


def _fetch_all_folders(client: MondayClient) -> list[dict[str, Any]]:
    query, variables = build_folders_list_query()
    return [
        normalize_folder_entry(entry)
        for entry in fetch_pages_concurrent(
            client,
            query=query,
            variables=variables,
            collection_key="folders",
            limit=MAX_BOARDS_PAGE_SIZE,
        )
    ]


def _fetch_all_docs(client: MondayClient) -> list[dict[str, Any]]:
    # Monday's `docs(...)` without `workspace_ids` silently undercounts —
    # recent docs in particular go missing. Fan out one scoped query per
    # workspace (a small worker pool — most workspaces hold a handful of
    # docs, so the serial walk was dominated by per-workspace round-trips)
    # and dedupe on merge (defensive; ids are globally unique).
    ws_ids: list[int] = []
    for ws in _fetch_all_workspaces(client):
        try:
            ws_ids.append(int(ws.get("id")))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue

    def _fetch_workspace_docs(ws_id: int) -> list[dict[str, Any]]:
        query, variables = build_docs_list_query(workspace_ids=[ws_id])
        return [
            normalize_doc_entry(entry)
            for entry in fetch_pages_concurrent(
                client,
                query=query,
                variables=variables,
                collection_key="docs",
                limit=MAX_BOARDS_PAGE_SIZE,
                # The outer pool already provides the parallelism; nested
                # waves would multiply in-flight requests.
                concurrency=1,
            )
        ]

    # pool.map preserves input order, so max_workers=1 behaves exactly like
    # a serial walk — no special case needed.
    with ThreadPoolExecutor(max_workers=directory_fetch_concurrency()) as pool:
        per_workspace = list(pool.map(_fetch_workspace_docs, ws_ids))

    return _dedup_by_id(chain.from_iterable(per_workspace))


def get_columns(
    client: MondayClient,
    *,
    store: CacheStore,
    board_id: int,
    refresh: bool = False,
) -> CachedDirectory:
    """Return the full column list for `board_id`, cached per-board.

    Raises NotFoundError when the board has no columns visible (unknown id or
    no access) — same behavior callers would see from a live query.
    """
    if not refresh:
        cached = store.read()
        if cached is not None:
            return cached
    entries = _fetch_board_columns(client, board_id)
    return store.write(entries)


def _fetch_board_columns(client: MondayClient, board_id: int) -> list[dict[str, Any]]:
    result = client.execute(COLUMNS_ON_BOARD, {"board": board_id})
    data = result.get("data") or {}
    boards = data.get("boards") or []
    if not boards:
        raise NotFoundError(f"board {board_id} not found")
    columns = boards[0].get("columns") or []
    if not isinstance(columns, list):
        return []
    return columns


def get_groups(
    client: MondayClient,
    *,
    store: CacheStore,
    board_id: int,
    refresh: bool = False,
) -> CachedDirectory:
    """Return the full group list for `board_id`, cached per-board.

    Raises NotFoundError when the board isn't visible (unknown id or no
    access), matching the live query behavior.
    """
    if not refresh:
        cached = store.read()
        if cached is not None:
            return cached
    entries = _fetch_board_groups(client, board_id)
    return store.write(entries)


def _fetch_board_groups(client: MondayClient, board_id: int) -> list[dict[str, Any]]:
    result = client.execute(GROUPS_LIST, {"board": board_id})
    data = result.get("data") or {}
    boards = data.get("boards") or []
    if not boards:
        raise NotFoundError(f"board {board_id} not found")
    groups = boards[0].get("groups") or []
    if not isinstance(groups, list):
        return []
    return groups


def get_tags(
    client: MondayClient,
    *,
    store: CacheStore,
    refresh: bool = False,
) -> CachedDirectory:
    """Return account-level public tags. `TAGS_LIST` is unpaginated."""
    if not refresh:
        cached = store.read()
        if cached is not None:
            return cached
    entries = _fetch_all_tags(client)
    return store.write(entries)


def _fetch_all_tags(client: MondayClient) -> list[dict[str, Any]]:
    result = client.execute(TAGS_LIST, {"ids": None})
    data = result.get("data") or {}
    tags = data.get("tags") or []
    if not isinstance(tags, list):
        return []
    return tags


def get_webhooks(
    client: MondayClient,
    *,
    store: CacheStore,
    board_id: int,
    refresh: bool = False,
) -> CachedDirectory:
    """Return webhooks subscribed on `board_id`, cached per-board.

    Always fetches the unscoped set (no `app_only` filter) so the cache is
    reusable for both `webhook list` and `webhook list --app-only`; the
    `--app-only` filter is applied client-side on read.
    """
    if not refresh:
        cached = store.read()
        if cached is not None:
            return cached
    entries = _fetch_board_webhooks(client, board_id)
    return store.write(entries)


def _fetch_board_webhooks(
    client: MondayClient, board_id: int
) -> list[dict[str, Any]]:
    result = client.execute(WEBHOOKS_LIST, {"board": board_id, "appOnly": None})
    data = result.get("data") or {}
    webhooks = data.get("webhooks") or []
    if not isinstance(webhooks, list):
        return []
    return webhooks


def get_board_details(
    client: MondayClient,
    *,
    store: CacheStore,
    board_id: int,
    refresh: bool = False,
) -> CachedDirectory:
    """Return the cached `BOARD_GET` payload for `board_id`.

    The cached envelope's `entries` list always has exactly one item — the
    board record. `items_count` is stripped before write so this cache
    doesn't have to be invalidated on every item mutation; callers that
    project `items_count` merge it back from a live `BOARD_ITEMS_COUNT`
    one-field query.

    Raises NotFoundError when the board isn't visible.
    """
    if not refresh:
        cached = store.read()
        if cached is not None:
            return cached
    record = _fetch_board_details(client, board_id)
    return store.write([record])


def _fetch_board_details(
    client: MondayClient, board_id: int
) -> dict[str, Any]:
    result = client.execute(BOARD_GET, {"id": board_id})
    data = result.get("data") or {}
    boards = data.get("boards") or []
    if not boards:
        raise NotFoundError(f"board {board_id} not found")
    record = dict(boards[0])
    # `items_count` lives on a separate live query (BOARD_ITEMS_COUNT) so the
    # cache file is not invalidated on every item write. Strip it here to
    # keep the on-disk shape consistent regardless of what the API returned.
    record.pop("items_count", None)
    return record


def get_item(
    client: MondayClient,
    *,
    store: CacheStore,
    item_id: int,
    refresh: bool = False,
) -> CachedDirectory:
    """Return the cached `ITEM_GET` payload for `item_id`.

    The cached envelope holds exactly one entry. Subitems share this cache
    because monday's `ITEM_GET` returns the same shape for items and
    subitems. Short-TTL by default (60s) — `--refresh-cache` always
    reaches the wire.
    """
    if not refresh:
        cached = store.read()
        if cached is not None:
            return cached
    record = _fetch_item(client, item_id)
    return store.write([record])


def _fetch_item(client: MondayClient, item_id: int) -> dict[str, Any]:
    result = client.execute(ITEM_GET, {"id": item_id})
    data = result.get("data") or {}
    items = data.get("items") or []
    if not items:
        raise NotFoundError(f"item {item_id} not found")
    return dict(items[0])


def get_subitems(
    client: MondayClient,
    *,
    store: CacheStore,
    parent_item_id: int,
    refresh: bool = False,
) -> CachedDirectory:
    """Return the cached subitems list for `parent_item_id`."""
    if not refresh:
        cached = store.read()
        if cached is not None:
            return cached
    entries = _fetch_subitems(client, parent_item_id)
    return store.write(entries)


def _fetch_subitems(
    client: MondayClient, parent_item_id: int
) -> list[dict[str, Any]]:
    result = client.execute(SUBITEMS_LIST, {"parent": parent_item_id})
    data = result.get("data") or {}
    items = data.get("items") or []
    if not items:
        raise NotFoundError(f"parent item {parent_item_id} not found")
    subitems = items[0].get("subitems") or []
    if not isinstance(subitems, list):
        return []
    return subitems


def get_updates_for_item(
    client: MondayClient,
    *,
    store: CacheStore,
    item_id: int,
    refresh: bool = False,
) -> CachedDirectory:
    """Return the cached updates list for `item_id`."""
    if not refresh:
        cached = store.read()
        if cached is not None:
            return cached
    entries = _fetch_updates_for_item(client, item_id)
    return store.write(entries)


def _fetch_updates_for_item(
    client: MondayClient, item_id: int
) -> list[dict[str, Any]]:
    page = 1
    collected: list[dict[str, Any]] = []
    while True:
        result = client.execute(
            UPDATES_FOR_ITEM,
            {"id": item_id, "limit": _UPDATES_PAGE_SIZE, "page": page},
        )
        data = result.get("data") or {}
        items = data.get("items") or []
        if not items:
            if page == 1:
                raise NotFoundError(f"item {item_id} not found")
            break
        updates = items[0].get("updates") or []
        if not updates:
            break
        collected.extend(updates)
        if len(updates) < _UPDATES_PAGE_SIZE:
            break
        page += 1
    return collected


def get_doc_blocks(
    client: MondayClient,
    *,
    store: CacheStore,
    doc_id: int,
    refresh: bool = False,
) -> CachedDirectory:
    """Return the cached doc payload (with merged block tree) for `doc_id`.

    The cached envelope holds exactly one entry — the doc dict including a
    `blocks: [...]` list spanning every paginated page. Cache key is always
    the internal `doc_id`; callers using `--object-id` must resolve to a
    `doc_id` first (e.g. via the `docs.json` directory cache).
    """
    if not refresh:
        cached = store.read()
        if cached is not None:
            return cached
    record = _fetch_doc_with_blocks_by_id(client, doc_id)
    if record is None:
        raise NotFoundError(f"doc {doc_id} not found")
    return store.write([record])


def _fetch_doc_with_blocks_by_id(
    client: MondayClient, doc_id: int
) -> dict[str, Any] | None:
    page = 1
    merged: dict[str, Any] | None = None
    all_blocks: list[dict[str, Any]] = []
    while True:
        result = client.execute(
            DOC_GET_BY_ID_BLOCKS_PAGE,
            {"ids": [doc_id], "limit": _DOC_BLOCKS_PAGE_SIZE, "page": page},
        )
        data = result.get("data") or {}
        docs = data.get("docs") or []
        if not docs:
            return None
        doc = docs[0]
        page_blocks = doc.get("blocks") or []
        if merged is None:
            merged = {k: v for k, v in doc.items() if k != "blocks"}
        if isinstance(page_blocks, list):
            all_blocks.extend(page_blocks)
        if len(page_blocks) < _DOC_BLOCKS_PAGE_SIZE:
            break
        page += 1
    assert merged is not None
    merged["blocks"] = all_blocks
    return merged
