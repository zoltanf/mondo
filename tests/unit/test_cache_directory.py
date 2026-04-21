"""Unit tests for mondo.cache.directory — fetch-or-serve orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mondo.api.errors import NotFoundError
from mondo.cache.directory import (
    enrich_workspace_names,
    get_boards,
    get_columns,
    get_docs,
    get_folders,
    get_teams,
    get_users,
    get_workspaces,
)
from mondo.cache.store import CacheStore

ENDPOINT = "https://api.monday.com/v2"


class FakeClient:
    """Minimal MondayClient stand-in used by the directory orchestrator."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def execute(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.calls.append((query, variables))
        if not self._responses:
            raise AssertionError("FakeClient: no more programmed responses")
        return self._responses.pop(0)


def _store(tmp_path: Path, entity: str) -> CacheStore:
    return CacheStore(
        entity_type=entity,
        cache_dir=tmp_path / "cache",
        api_endpoint=ENDPOINT,
        ttl_seconds=60,
    )


# -- boards ------------------------------------------------------------------


def test_get_boards_cold_cache_fetches_and_writes(tmp_path: Path) -> None:
    store = _store(tmp_path, "boards")
    client = FakeClient([
        {"data": {"boards": [{"id": "1", "name": "Alpha"}]}},
        {"data": {"boards": []}},  # stop signal
    ])

    result = get_boards(client, store=store)

    assert [e["name"] for e in result.entries] == ["Alpha"]
    assert store.path.exists()
    assert store.read() is not None  # populated cache


def test_get_boards_warm_cache_skips_api(tmp_path: Path) -> None:
    store = _store(tmp_path, "boards")
    store.write([{"id": "1", "name": "Cached"}])
    client = FakeClient([])

    result = get_boards(client, store=store)

    assert [e["name"] for e in result.entries] == ["Cached"]
    assert client.calls == []  # no API calls


def test_get_boards_refresh_overrides_cache(tmp_path: Path) -> None:
    store = _store(tmp_path, "boards")
    store.write([{"id": "1", "name": "Stale"}])
    client = FakeClient([
        {"data": {"boards": [{"id": "2", "name": "Fresh"}]}},
        {"data": {"boards": []}},
    ])

    result = get_boards(client, store=store, refresh=True)

    assert [e["name"] for e in result.entries] == ["Fresh"]
    assert client.calls, "refresh=True must call the API"


def test_get_boards_uses_state_all_for_priming(tmp_path: Path) -> None:
    store = _store(tmp_path, "boards")
    client = FakeClient([{"data": {"boards": []}}])
    get_boards(client, store=store)
    assert client.calls, "expected an API call"
    _query, variables = client.calls[0]
    assert variables is not None
    assert variables.get("state") == "all"


# -- workspaces --------------------------------------------------------------


def test_get_workspaces_cold_then_warm(tmp_path: Path) -> None:
    store = _store(tmp_path, "workspaces")
    client = FakeClient([
        {"data": {"workspaces": [{"id": "10", "name": "Engineering"}]}},
        {"data": {"workspaces": []}},
    ])

    first = get_workspaces(client, store=store)
    assert [e["name"] for e in first.entries] == ["Engineering"]

    before = len(client.calls)
    second = get_workspaces(client, store=store)
    assert second.entries == first.entries
    assert len(client.calls) == before  # still no new calls


# -- users -------------------------------------------------------------------


def test_get_users_covers_both_active_and_disabled(tmp_path: Path) -> None:
    store = _store(tmp_path, "users")
    client = FakeClient([
        {"data": {"users": [{"id": "1", "name": "Active Ann", "enabled": True}]}},
        {"data": {"users": [{"id": "2", "name": "Disabled Dan", "enabled": False}]}},
    ])

    result = get_users(client, store=store)

    # Two API calls: one with nonActive=False, one with nonActive=True
    assert len(client.calls) == 2
    seen_flags = {call[1].get("nonActive") for call in client.calls if call[1]}
    assert seen_flags == {True, False}
    # Both users merged into the cache
    assert {e["id"] for e in result.entries} == {"1", "2"}


def test_get_users_dedupes_when_apis_overlap(tmp_path: Path) -> None:
    store = _store(tmp_path, "users")
    duplicate = {"id": "1", "name": "Maybe Both"}
    client = FakeClient([
        {"data": {"users": [duplicate]}},
        {"data": {"users": [duplicate]}},
    ])

    result = get_users(client, store=store)
    assert len(result.entries) == 1


# -- teams -------------------------------------------------------------------


def test_get_teams_single_call_no_pagination(tmp_path: Path) -> None:
    store = _store(tmp_path, "teams")
    client = FakeClient([
        {"data": {"teams": [{"id": "1", "name": "Platform"}]}},
    ])

    result = get_teams(client, store=store)

    assert [t["name"] for t in result.entries] == ["Platform"]
    assert len(client.calls) == 1  # exactly one API call — teams aren't paginated


def test_get_teams_warm_cache(tmp_path: Path) -> None:
    store = _store(tmp_path, "teams")
    store.write([{"id": "1", "name": "Cached Team"}])
    client = FakeClient([])

    result = get_teams(client, store=store)

    assert [t["name"] for t in result.entries] == ["Cached Team"]
    assert client.calls == []


# -- docs --------------------------------------------------------------------


def test_get_docs_cold_cache_fetches_and_writes(tmp_path: Path) -> None:
    store = _store(tmp_path, "docs")
    client = FakeClient([
        {"data": {"workspaces": [{"id": "42"}]}},
        {"data": {"docs": [{"id": "1", "object_id": "100", "name": "Spec"}]}},
    ])

    result = get_docs(client, store=store)

    assert [e["name"] for e in result.entries] == ["Spec"]
    assert store.path.exists()
    assert store.read() is not None


def test_get_docs_warm_cache_skips_api(tmp_path: Path) -> None:
    store = _store(tmp_path, "docs")
    store.write([{"id": "1", "object_id": "100", "name": "Cached"}])
    client = FakeClient([])

    result = get_docs(client, store=store)

    assert [e["name"] for e in result.entries] == ["Cached"]
    assert client.calls == []


def test_get_docs_refresh_overrides_cache(tmp_path: Path) -> None:
    store = _store(tmp_path, "docs")
    store.write([{"id": "1", "object_id": "100", "name": "Stale"}])
    client = FakeClient([
        {"data": {"workspaces": [{"id": "42"}]}},
        {"data": {"docs": [{"id": "2", "object_id": "200", "name": "Fresh"}]}},
    ])

    result = get_docs(client, store=store, refresh=True)

    assert [e["name"] for e in result.entries] == ["Fresh"]
    assert client.calls, "refresh=True must call the API"


def test_get_docs_primes_per_workspace_and_merges(tmp_path: Path) -> None:
    """Monday's unfiltered `docs(...)` silently undercounts (especially recent
    docs). Priming must enumerate workspaces and fan out one
    `docs(workspace_ids: [X])` query per workspace, merging the results."""
    store = _store(tmp_path, "docs")
    client = FakeClient([
        # workspaces list — single page (< page size stops pagination)
        {"data": {"workspaces": [{"id": "10"}, {"id": "20"}]}},
        # docs for workspace 10 — single page
        {"data": {"docs": [{"id": "1", "object_id": "100", "name": "A",
                            "workspace_id": "10"}]}},
        # docs for workspace 20 — single page
        {"data": {"docs": [{"id": "2", "object_id": "200", "name": "B",
                            "workspace_id": "20"}]}},
    ])

    result = get_docs(client, store=store)

    assert {e["id"] for e in result.entries} == {"1", "2"}
    # Every docs() query must be scoped: workspace_ids is the whole point.
    docs_calls = [(q, v) for q, v in client.calls if "docs(" in q]
    assert len(docs_calls) == 2, client.calls
    seen_ws = sorted(v["workspaceIds"] for _, v in docs_calls if v)
    assert seen_ws == [[10], [20]]


def test_get_docs_dedupes_across_workspaces(tmp_path: Path) -> None:
    """If the same doc id appears under two workspaces (shouldn't happen in
    practice but monday has surprised us before), dedupe by id."""
    store = _store(tmp_path, "docs")
    duplicate = {"id": "7", "object_id": "77", "name": "Shared"}
    client = FakeClient([
        {"data": {"workspaces": [{"id": "10"}, {"id": "20"}]}},
        {"data": {"docs": [duplicate]}},
        {"data": {"docs": [duplicate]}},
    ])

    result = get_docs(client, store=store)

    assert len(result.entries) == 1


# -- folders -----------------------------------------------------------------


def test_get_folders_cold_cache_fetches_and_writes(tmp_path: Path) -> None:
    store = _store(tmp_path, "folders")
    client = FakeClient([
        {"data": {"folders": [
            {"id": "1", "name": "Design", "color": "blue",
             "created_at": "2024-01-01", "owner_id": "99",
             "workspace": {"id": "10", "name": "Engineering"},
             "parent": None},
        ]}},
        {"data": {"folders": []}},  # stop signal
    ])

    result = get_folders(client, store=store)

    assert [e["name"] for e in result.entries] == ["Design"]
    assert store.path.exists()
    assert store.read() is not None


def test_get_folders_warm_cache_skips_api(tmp_path: Path) -> None:
    store = _store(tmp_path, "folders")
    store.write([{"id": "1", "name": "Cached", "workspace_id": "10",
                  "workspace_name": "Engineering", "parent_id": None, "parent_name": None}])
    client = FakeClient([])

    result = get_folders(client, store=store)

    assert [e["name"] for e in result.entries] == ["Cached"]
    assert client.calls == []


def test_get_folders_refresh_overrides_cache(tmp_path: Path) -> None:
    store = _store(tmp_path, "folders")
    store.write([{"id": "1", "name": "Stale", "workspace_id": "10",
                  "workspace_name": "Engineering", "parent_id": None, "parent_name": None}])
    client = FakeClient([
        {"data": {"folders": [
            {"id": "2", "name": "Fresh", "color": None,
             "created_at": "2024-06-01", "owner_id": "99",
             "workspace": {"id": "10", "name": "Engineering"},
             "parent": None},
        ]}},
        {"data": {"folders": []}},
    ])

    result = get_folders(client, store=store, refresh=True)

    assert [e["name"] for e in result.entries] == ["Fresh"]
    assert client.calls, "refresh=True must call the API"


def test_get_folders_entries_are_normalized(tmp_path: Path) -> None:
    """Fetched entries must be normalized: nested workspace/parent → scalar keys."""
    store = _store(tmp_path, "folders")
    client = FakeClient([
        {"data": {"folders": [
            {"id": "5", "name": "Sub", "color": "red",
             "created_at": "2024-03-01", "owner_id": "7",
             "workspace": {"id": "10", "name": "Engineering"},
             "parent": {"id": "3", "name": "Root"}},
        ]}},
        {"data": {"folders": []}},
    ])

    result = get_folders(client, store=store)

    entry = result.entries[0]
    assert entry["workspace_id"] == "10"
    assert entry["workspace_name"] == "Engineering"
    assert entry["parent_id"] == "3"
    assert entry["parent_name"] == "Root"
    assert "workspace" not in entry
    assert "parent" not in entry


# -- columns (per-board scoped cache) ----------------------------------------


def _scoped_store(tmp_path: Path, board_id: str) -> CacheStore:
    return CacheStore(
        entity_type="columns",
        cache_dir=tmp_path / "cache",
        api_endpoint=ENDPOINT,
        ttl_seconds=60,
        scope=board_id,
    )


def test_get_columns_cold_fetches_and_writes(tmp_path: Path) -> None:
    store = _scoped_store(tmp_path, "1")
    columns_payload = [
        {"id": "status", "title": "Status", "type": "status"},
        {"id": "text", "title": "Text", "type": "text"},
    ]
    client = FakeClient([
        {"data": {"boards": [{"id": "1", "columns": columns_payload}]}}
    ])

    result = get_columns(client, store=store, board_id=1)

    assert [c["id"] for c in result.entries] == ["status", "text"]
    assert store.path.exists()
    assert len(client.calls) == 1


def test_get_columns_warm_cache_skips_api(tmp_path: Path) -> None:
    store = _scoped_store(tmp_path, "1")
    store.write([{"id": "cached", "title": "Cached", "type": "text"}])
    client = FakeClient([])

    result = get_columns(client, store=store, board_id=1)

    assert [c["id"] for c in result.entries] == ["cached"]
    assert client.calls == []


def test_get_columns_refresh_ignores_cache(tmp_path: Path) -> None:
    store = _scoped_store(tmp_path, "1")
    store.write([{"id": "stale", "title": "Stale", "type": "text"}])
    client = FakeClient([
        {"data": {"boards": [{"id": "1", "columns": [{"id": "fresh"}]}]}}
    ])

    result = get_columns(client, store=store, board_id=1, refresh=True)

    assert [c["id"] for c in result.entries] == ["fresh"]
    assert len(client.calls) == 1


def test_get_columns_missing_board_raises_not_found(tmp_path: Path) -> None:
    store = _scoped_store(tmp_path, "999")
    client = FakeClient([{"data": {"boards": []}}])
    with pytest.raises(NotFoundError):
        get_columns(client, store=store, board_id=999)
    assert not store.path.exists()


# -- enrich_workspace_names --------------------------------------------------


def test_enrich_workspace_names_uses_warm_cache(tmp_path: Path) -> None:
    store = _store(tmp_path, "workspaces")
    store.write([
        {"id": "10", "name": "Engineering"},
        {"id": "20", "name": "Sales"},
    ])
    client = FakeClient([])
    entries = [
        {"id": "A", "workspace_id": "10"},
        {"id": "B", "workspace_id": "20"},
    ]

    enrich_workspace_names(entries, client=client, store=store)

    assert entries[0]["workspace_name"] == "Engineering"
    assert entries[1]["workspace_name"] == "Sales"
    assert client.calls == []  # warm cache — no API calls


def test_enrich_workspace_names_populates_cold_cache(tmp_path: Path) -> None:
    store = _store(tmp_path, "workspaces")
    client = FakeClient([
        {"data": {"workspaces": [{"id": "10", "name": "Engineering"}]}},
    ])
    entries = [{"id": "A", "workspace_id": "10"}]

    enrich_workspace_names(entries, client=client, store=store)

    assert entries[0]["workspace_name"] == "Engineering"
    assert store.path.exists(), "cold cache must be populated"
    assert len(client.calls) == 1


def test_enrich_workspace_names_synthesizes_main_workspace(tmp_path: Path) -> None:
    store = _store(tmp_path, "workspaces")
    store.write([{"id": "10", "name": "Engineering"}])
    client = FakeClient([])
    entries = [
        {"id": "A", "workspace_id": None},
        {"id": "B", "workspace_id": "10"},
    ]

    enrich_workspace_names(entries, client=client, store=store)

    assert entries[0]["workspace_name"] == "Main workspace"
    assert entries[1]["workspace_name"] == "Engineering"


def test_enrich_workspace_names_unknown_id_is_none(tmp_path: Path) -> None:
    store = _store(tmp_path, "workspaces")
    store.write([{"id": "10", "name": "Engineering"}])
    client = FakeClient([])
    entries = [{"id": "A", "workspace_id": "99"}]

    enrich_workspace_names(entries, client=client, store=store)

    assert entries[0]["workspace_name"] is None
