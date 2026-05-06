"""Unit tests for `mondo.cli._filters`."""

from __future__ import annotations

import re

import pytest

from mondo.api.errors import UsageError
from mondo.cli._filters import apply_fuzzy, compile_name_filter, name_matches


def test_apply_fuzzy_returns_score_desc_order() -> None:
    entries = [
        {"id": 1, "name": "alpha"},
        {"id": 2, "name": "beta"},
        {"id": 3, "name": "alpine"},
    ]
    out = apply_fuzzy(entries, "alp", threshold=50, include_score=False)
    names = [e["name"] for e in out]
    assert names[0] in {"alpha", "alpine"}
    assert "beta" not in names
    assert len(out) == 2


def test_apply_fuzzy_include_score_injects_field_and_does_not_mutate() -> None:
    entries = [{"id": 1, "name": "alpha"}]
    out = apply_fuzzy(entries, "alpha", threshold=50, include_score=True)
    assert out[0]["_fuzzy_score"] == 100
    assert "_fuzzy_score" not in entries[0]


def test_apply_fuzzy_filters_below_threshold() -> None:
    entries = [{"id": 1, "name": "totally-unrelated"}]
    out = apply_fuzzy(entries, "alpha", threshold=90, include_score=False)
    assert out == []


def test_compile_name_filter_mutex_raises() -> None:
    with pytest.raises(UsageError):
        compile_name_filter("foo", "bar", None)
    with pytest.raises(UsageError):
        compile_name_filter("foo", None, "baz")
    with pytest.raises(UsageError):
        compile_name_filter(None, "bar", "baz")


def test_compile_name_filter_returns_lowered_needle_and_regex() -> None:
    needle, pattern = compile_name_filter("FooBar", None, None)
    assert needle == "foobar"
    assert pattern is None

    needle, pattern = compile_name_filter(None, r"^proj-\d+$", None)
    assert needle is None
    assert isinstance(pattern, re.Pattern)


def test_compile_name_filter_invalid_regex_raises() -> None:
    with pytest.raises(UsageError):
        compile_name_filter(None, "(", None)


def test_name_matches_contains_and_pattern() -> None:
    assert name_matches({"name": "Alpha Project"}, "alpha", None) is True
    assert name_matches({"name": "Beta"}, "alpha", None) is False
    assert name_matches({"name": "proj-42"}, None, re.compile(r"^proj-\d+$")) is True
    assert name_matches({"name": "nope"}, None, re.compile(r"^proj-\d+$")) is False
    assert name_matches({}, "x", None) is False


def test_name_matches_with_alternate_key() -> None:
    # Groups and columns expose their human label as `title`, not `name`.
    # The `key=` arg lets the same predicate work over those entities.
    assert name_matches({"title": "Objective 1"}, "objective", None, key="title") is True
    assert name_matches({"title": "Other"}, "objective", None, key="title") is False


def test_apply_fuzzy_with_alternate_key() -> None:
    entries = [
        {"id": "a", "title": "Objective 1: Launch"},
        {"id": "b", "title": "Objective 2: Adoption"},
        {"id": "c", "title": "Workstreams"},
    ]
    out = apply_fuzzy(entries, "objective", threshold=50, include_score=False, key="title")
    titles = {e["title"] for e in out}
    assert "Workstreams" not in titles
    assert "Objective 1: Launch" in titles
