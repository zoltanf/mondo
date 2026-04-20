"""Fetch-or-serve orchestration for each cached entity type.

Each `get_*` function consults its `CacheStore`, returns cached entries when
fresh, otherwise fetches the full unfiltered directory live and populates the
cache. Callers apply any filtering client-side after this returns.
"""

from __future__ import annotations

from typing import Any

from mondo.api.client import MondayClient
from mondo.api.pagination import MAX_BOARDS_PAGE_SIZE, iter_boards_page
from mondo.api.queries import (
    TEAMS_LIST,
    USERS_LIST_PAGE,
    WORKSPACES_LIST_PAGE,
    build_boards_list_query,
)
from mondo.cache.store import CachedDirectory, CacheStore


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


def _fetch_all_boards(client: MondayClient) -> list[dict[str, Any]]:
    # state="all" covers active+archived+deleted so the cache is usable for
    # every --state filter client-side.
    query, variables = build_boards_list_query(state="all")
    return list(
        iter_boards_page(
            client,
            query=query,
            variables=variables,
            collection_key="boards",
            limit=MAX_BOARDS_PAGE_SIZE,
        )
    )


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
    by_id: dict[str, dict[str, Any]] = {}
    for entry in active + disabled:
        uid = str(entry.get("id") or "")
        if uid:
            by_id[uid] = entry
    return list(by_id.values())


def _fetch_all_teams(client: MondayClient) -> list[dict[str, Any]]:
    # Teams aren't paginated server-side; single call suffices.
    result = client.execute(TEAMS_LIST, {"ids": None})
    data = result.get("data") or {}
    teams = data.get("teams") or []
    if not isinstance(teams, list):
        return []
    return teams
