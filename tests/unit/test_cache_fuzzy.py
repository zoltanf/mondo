"""Unit tests for mondo.cache.fuzzy."""

from __future__ import annotations

import pytest

from mondo.api.errors import UsageError
from mondo.cache.fuzzy import fuzzy_score


def test_empty_entries_returns_empty() -> None:
    assert fuzzy_score("anything", []) == []


def test_empty_query_returns_all_entries_with_score_100() -> None:
    entries = [{"name": "alpha"}, {"name": "beta"}]
    result = fuzzy_score("", entries)
    assert len(result) == 2
    assert all(score == 100 for _, score in result)


def test_null_name_entries_are_not_silently_dropped() -> None:
    # Entries with name=None or missing name must not be dropped — they should
    # score low but still appear in results when threshold=0.  This guards the
    # "59 teams returned, 58 after sort" regression where a single null-named
    # team was silently excluded by the previous `if entry.get(name_key)` guard.
    null_entry = {"id": 99}
    entries = [{"name": "alpha"}, null_entry]
    result = fuzzy_score("alpha", entries, threshold=0)
    returned_ids = [e.get("id") for e, _ in result]
    assert 99 in returned_ids, "null-name entry was silently dropped"


def test_empty_query_includes_null_name_entries() -> None:
    null_entry = {"id": 99}
    entries = [{"name": "alpha"}, null_entry]
    result = fuzzy_score("", entries)
    assert len(result) == 2
    assert all(score == 100 for _, score in result)


def test_exact_match_scores_100() -> None:
    entries = [{"name": "Product Launch"}, {"name": "Other"}]
    result = fuzzy_score("Product Launch", entries)
    assert result
    top, score = result[0]
    assert top["name"] == "Product Launch"
    assert score == 100


def test_typo_tolerance() -> None:
    entries = [
        {"id": 1, "name": "Product Launch"},
        {"id": 2, "name": "Marketing Campaign"},
        {"id": 3, "name": "Engineering Roadmap"},
    ]
    # "prodct launc" (2 dropped letters) should still match the first entry
    result = fuzzy_score("prodct launc", entries, threshold=60)
    assert result
    assert result[0][0]["id"] == 1


def test_threshold_filters_out_poor_matches() -> None:
    entries = [{"name": "zzzzzz"}, {"name": "product launch"}]
    result = fuzzy_score("product launch", entries, threshold=90)
    names = [entry["name"] for entry, _ in result]
    assert "product launch" in names
    assert "zzzzzz" not in names


def test_results_sorted_descending_by_score() -> None:
    entries = [
        {"name": "alpha beta"},
        {"name": "alpha"},
        {"name": "alpha beta gamma"},
    ]
    result = fuzzy_score("alpha", entries, threshold=0)
    scores = [score for _, score in result]
    assert scores == sorted(scores, reverse=True)


def test_custom_name_key() -> None:
    entries = [{"title": "Foo"}, {"title": "Bar"}]
    result = fuzzy_score("Foo", entries, name_key="title", threshold=0)
    assert result[0][0]["title"] == "Foo"


def test_missing_rapidfuzz_raises_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    original_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "rapidfuzz":
            raise ImportError("simulated missing rapidfuzz")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    with pytest.raises(UsageError, match="rapidfuzz"):
        fuzzy_score("query", [{"name": "anything"}])
