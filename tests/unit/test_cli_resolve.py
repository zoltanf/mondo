"""Unit tests for `mondo.cli._resolve.resolve_by_filters`."""

from __future__ import annotations

import pytest
import typer

from mondo.api.errors import NotFoundError, UsageError
from mondo.cli._resolve import resolve_by_filters

GROUPS = [
    {"id": "obj1", "title": "Objective 1: Launch"},
    {"id": "obj2", "title": "Objective 2: Adoption"},
    {"id": "draft1", "title": "Draft A"},
    {"id": "draft2", "title": "Draft B"},
]


def test_explicit_id_returns_matching_entry() -> None:
    chosen = resolve_by_filters(
        GROUPS,
        explicit_id="obj2",
        name_contains=None,
        name_matches_re=None,
        name_fuzzy=None,
        first=False,
        key="title",
        resource="group",
    )
    assert chosen["id"] == "obj2"
    assert chosen["title"] == "Objective 2: Adoption"


def test_explicit_id_not_in_entries_raises_not_found() -> None:
    with pytest.raises(NotFoundError):
        resolve_by_filters(
            GROUPS,
            explicit_id="missing",
            name_contains=None,
            name_matches_re=None,
            name_fuzzy=None,
            first=False,
            key="title",
            resource="group",
        )


def test_id_and_filter_mutex_raises_bad_param() -> None:
    with pytest.raises(typer.BadParameter):
        resolve_by_filters(
            GROUPS,
            explicit_id="obj1",
            name_contains="Objective",
            name_matches_re=None,
            name_fuzzy=None,
            first=False,
            key="title",
            resource="group",
        )


def test_neither_id_nor_filter_raises_bad_param() -> None:
    with pytest.raises(typer.BadParameter):
        resolve_by_filters(
            GROUPS,
            explicit_id=None,
            name_contains=None,
            name_matches_re=None,
            name_fuzzy=None,
            first=False,
            key="title",
            resource="group",
        )


def test_name_contains_unique() -> None:
    chosen = resolve_by_filters(
        GROUPS,
        explicit_id=None,
        name_contains="Objective 2",
        name_matches_re=None,
        name_fuzzy=None,
        first=False,
        key="title",
        resource="group",
    )
    assert chosen["id"] == "obj2"


def test_name_matches_regex() -> None:
    chosen = resolve_by_filters(
        GROUPS,
        explicit_id=None,
        name_contains=None,
        name_matches_re=r"^Objective 1:",
        name_fuzzy=None,
        first=False,
        key="title",
        resource="group",
    )
    assert chosen["id"] == "obj1"


def test_zero_matches_raises_not_found() -> None:
    with pytest.raises(NotFoundError):
        resolve_by_filters(
            GROUPS,
            explicit_id=None,
            name_contains="nonexistent",
            name_matches_re=None,
            name_fuzzy=None,
            first=False,
            key="title",
            resource="group",
        )


def test_ambiguous_match_raises_usage_error() -> None:
    with pytest.raises(UsageError) as excinfo:
        resolve_by_filters(
            GROUPS,
            explicit_id=None,
            name_contains="draft",
            name_matches_re=None,
            name_fuzzy=None,
            first=False,
            key="title",
            resource="group",
        )
    msg = str(excinfo.value)
    assert "matched" in msg
    assert "--first" in msg


def test_first_picks_top_of_ambiguous() -> None:
    chosen = resolve_by_filters(
        GROUPS,
        explicit_id=None,
        name_contains="draft",
        name_matches_re=None,
        name_fuzzy=None,
        first=True,
        key="title",
        resource="group",
    )
    assert chosen["id"] == "draft1"


def test_default_key_is_name() -> None:
    items = [{"id": 1, "name": "Apple"}, {"id": 2, "name": "Banana"}]
    chosen = resolve_by_filters(
        items,
        explicit_id=None,
        name_contains="apple",
        name_matches_re=None,
        name_fuzzy=None,
        first=False,
        resource="item",
    )
    assert chosen["id"] == 1
