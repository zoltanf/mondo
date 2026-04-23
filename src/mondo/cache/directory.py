"""Fetch-or-serve orchestration for each cached entity type.

Each `get_*` function consults its `CacheStore`, returns cached entries when
fresh, otherwise fetches the full unfiltered directory live and populates the
cache. Callers apply any filtering client-side after this returns.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from mondo.api.client import MondayClient
from mondo.api.errors import NotFoundError
from mondo.api.pagination import MAX_BOARDS_PAGE_SIZE, iter_boards_page
from mondo.api.queries import (
    COLUMNS_ON_BOARD,
    GROUPS_LIST,
    TEAMS_LIST,
    USERS_LIST_PAGE,
    WORKSPACES_LIST_PAGE,
    build_boards_list_query,
    build_docs_list_query,
    build_folders_list_query,
)
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
        for entry in iter_boards_page(
            client,
            query=query,
            variables=variables,
            collection_key="boards",
            limit=MAX_BOARDS_PAGE_SIZE,
        )
    ]


def _fetch_all_workspaces(client: MondayClient) -> list[dict[str, Any]]:
    return list(
        iter_boards_page(
            client,
            query=WORKSPACES_LIST_PAGE,
            variables={"state": "all"},
            collection_key="workspaces",
            limit=MAX_BOARDS_PAGE_SIZE,
        )
    )


def _fetch_all_users(client: MondayClient) -> list[dict[str, Any]]:
    # monday's `non_active` is either/or: true returns ONLY disabled users,
    # false returns ONLY active. To cover both, we run both queries and merge
    # (dedup by id — shouldn't collide, but be defensive).
    active = list(
        iter_boards_page(
            client,
            query=USERS_LIST_PAGE,
            variables={"nonActive": False},
            collection_key="users",
            limit=MAX_BOARDS_PAGE_SIZE,
        )
    )
    disabled = list(
        iter_boards_page(
            client,
            query=USERS_LIST_PAGE,
            variables={"nonActive": True},
            collection_key="users",
            limit=MAX_BOARDS_PAGE_SIZE,
        )
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
        for entry in iter_boards_page(
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
    # workspace and dedupe on merge (defensive; ids are globally unique).
    def _iter_all() -> Iterable[dict[str, Any]]:
        for ws in _fetch_all_workspaces(client):
            try:
                ws_id = int(ws.get("id"))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            query, variables = build_docs_list_query(workspace_ids=[ws_id])
            for entry in iter_boards_page(
                client,
                query=query,
                variables=variables,
                collection_key="docs",
                limit=MAX_BOARDS_PAGE_SIZE,
            ):
                yield normalize_doc_entry(entry)

    return _dedup_by_id(_iter_all())


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
