"""Unit tests for mondo.cache.directory — fetch-or-serve orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mondo.cache.directory import (
    get_boards,
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
