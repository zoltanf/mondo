"""Tests for the dropdown column codec."""

from __future__ import annotations

import pytest

from mondo.columns import (
    dropdown,  # noqa: F401
    parse_value,
    render_value,
)

SETTINGS = {"labels": [{"id": 1, "name": "Cookie"}, {"id": 2, "name": "Cupcake"}]}


class TestParse:
    def test_single_label(self) -> None:
        assert parse_value("dropdown", "Cookie", SETTINGS) == {"labels": ["Cookie"]}

    def test_multiple_labels(self) -> None:
        assert parse_value("dropdown", "Cookie,Cupcake", SETTINGS) == {
            "labels": ["Cookie", "Cupcake"]
        }

    def test_trims_whitespace(self) -> None:
        assert parse_value("dropdown", " Cookie , Cupcake ", SETTINGS) == {
            "labels": ["Cookie", "Cupcake"]
        }

    def test_by_ids_prefix(self) -> None:
        assert parse_value("dropdown", "id:1,2", SETTINGS) == {"ids": [1, 2]}

    def test_by_ids_non_integer_raises(self) -> None:
        with pytest.raises(ValueError, match="integer"):
            parse_value("dropdown", "id:Cookie", SETTINGS)

    def test_empty_clears(self) -> None:
        assert parse_value("dropdown", "", SETTINGS) == {}

    def test_unknown_label_rejected_with_settings(self) -> None:
        with pytest.raises(ValueError, match="unknown dropdown label"):
            parse_value("dropdown", "Donut", SETTINGS)

    def test_without_settings_passes_through(self) -> None:
        assert parse_value("dropdown", "Donut", {}) == {"labels": ["Donut"]}

    def test_create_labels_skips_client_validation(self) -> None:
        """With create_labels=True, unknown labels pass through unchecked."""
        assert parse_value("dropdown", "Donut", SETTINGS, create_labels=True) == {
            "labels": ["Donut"]
        }

    def test_create_labels_mixed_known_and_unknown(self) -> None:
        assert parse_value(
            "dropdown", "Cookie,Donut", SETTINGS, create_labels=True
        ) == {"labels": ["Cookie", "Donut"]}


class TestRender:
    def test_uses_text_field(self) -> None:
        assert render_value("dropdown", {"ids": [1, 2]}, "Cookie, Cupcake") == "Cookie, Cupcake"

    def test_none(self) -> None:
        assert render_value("dropdown", None, None) == ""
