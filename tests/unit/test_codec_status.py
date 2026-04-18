"""Tests for the status codec."""

from __future__ import annotations

import pytest

from mondo.columns import (
    parse_value,
    render_value,
    status,  # noqa: F401  (registration)
)

STATUS_SETTINGS = {
    "labels": {
        "0": "Working on it",
        "1": "Done",
        "2": "Stuck",
    },
    "labels_colors": {},
}


class TestParse:
    def test_by_label(self) -> None:
        assert parse_value("status", "Done", STATUS_SETTINGS) == {"label": "Done"}

    def test_by_index_hash_prefix(self) -> None:
        assert parse_value("status", "#1", STATUS_SETTINGS) == {"index": 1}

    def test_bare_int_without_matching_label_rejected(self) -> None:
        """Bare `1` is treated as a label; no such label exists → error lists
        the valid ones so the user can disambiguate with `#1` or the label name."""
        with pytest.raises(ValueError, match="unknown status label"):
            parse_value("status", "1", STATUS_SETTINGS)

    def test_by_index_out_of_range_rejected(self) -> None:
        with pytest.raises(ValueError, match="range"):
            parse_value("status", "#42", STATUS_SETTINGS)

    def test_unknown_label_rejected(self) -> None:
        with pytest.raises(ValueError, match="Known:"):
            parse_value("status", "NotAValidLabel", STATUS_SETTINGS)

    def test_without_settings_accepts_any_label(self) -> None:
        """If settings aren't available, trust the user's label."""
        assert parse_value("status", "New Label", {}) == {"label": "New Label"}

    def test_empty_clears(self) -> None:
        assert parse_value("status", "", STATUS_SETTINGS) == {}


class TestRender:
    def test_uses_text_field(self) -> None:
        assert render_value("status", {"index": 1}, "Done") == "Done"

    def test_none_renders_empty(self) -> None:
        assert render_value("status", None, None) == ""

    def test_text_empty_with_value(self) -> None:
        # Recent monday responses sometimes omit text; fall back to "?".
        assert render_value("status", {"index": 1}, "") == ""
