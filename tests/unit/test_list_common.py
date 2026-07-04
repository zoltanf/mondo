"""Unit tests for the shared cache-path list filters."""

from __future__ import annotations

from mondo.cli._list_common import filter_by_kind, filter_by_state


def test_filter_by_state_all_returns_everything() -> None:
    entries = [{"state": "active"}, {"state": "archived"}, {"state": "deleted"}]
    assert filter_by_state(entries, "all") == entries


def test_filter_by_state_matches_requested() -> None:
    entries = [{"id": 1, "state": "active"}, {"id": 2, "state": "archived"}]
    assert filter_by_state(entries, "active") == [{"id": 1, "state": "active"}]
    assert filter_by_state(entries, "archived") == [{"id": 2, "state": "archived"}]


def test_filter_by_state_missing_state_defaults_to_active() -> None:
    entries = [{"id": 1}, {"id": 2, "state": None}, {"id": 3, "state": "archived"}]
    assert filter_by_state(entries, "active") == [{"id": 1}, {"id": 2, "state": None}]


def test_filter_by_state_missing_state_excluded_when_filtering_non_active() -> None:
    entries = [{"id": 1}, {"id": 2, "state": "archived"}]
    assert filter_by_state(entries, "archived") == [{"id": 2, "state": "archived"}]


def test_filter_by_state_empty_input() -> None:
    assert filter_by_state([], "active") == []
    assert filter_by_state([], "all") == []


def test_filter_by_kind_none_is_noop() -> None:
    entries = [{"kind": "public"}, {"kind": "private"}, {}]
    assert filter_by_kind(entries, None) == entries


def test_filter_by_kind_matches() -> None:
    entries = [{"id": 1, "kind": "public"}, {"id": 2, "kind": "private"}]
    assert filter_by_kind(entries, "public") == [{"id": 1, "kind": "public"}]
    assert filter_by_kind(entries, "private") == [{"id": 2, "kind": "private"}]


def test_filter_by_kind_missing_kind_treated_as_empty_string() -> None:
    entries = [{"id": 1}, {"id": 2, "kind": None}, {"id": 3, "kind": "public"}]
    # A missing/None kind never matches a real kind value.
    assert filter_by_kind(entries, "public") == [{"id": 3, "kind": "public"}]
    # ...but matches an explicit empty-string filter.
    assert filter_by_kind(entries, "") == [{"id": 1}, {"id": 2, "kind": None}]


def test_filter_by_kind_empty_input() -> None:
    assert filter_by_kind([], "public") == []
    assert filter_by_kind([], None) == []
