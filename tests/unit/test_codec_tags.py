"""Tests for the tags column codec.

The codec itself is pure — it only handles integer IDs. Name → ID resolution
is a separate CLI-level step (via `create_or_get_tag`).
"""

from __future__ import annotations

import pytest

from mondo.columns import (
    parse_value,
    render_value,
    tags,  # noqa: F401
)


class TestParse:
    def test_single_id(self) -> None:
        assert parse_value("tags", "42", {}) == {"tag_ids": [42]}

    def test_multiple_ids(self) -> None:
        assert parse_value("tags", "42,51,73", {}) == {"tag_ids": [42, 51, 73]}

    def test_trims_whitespace(self) -> None:
        assert parse_value("tags", " 42 , 51 ", {}) == {"tag_ids": [42, 51]}

    def test_names_rejected_with_helpful_message(self) -> None:
        """Non-integer values get a message pointing to the resolution helper."""
        with pytest.raises(ValueError, match="create_or_get_tag"):
            parse_value("tags", "urgent,blocked", {})

    def test_empty_clears(self) -> None:
        assert parse_value("tags", "", {}) == {}


class TestRender:
    def test_uses_text(self) -> None:
        assert render_value("tags", {"tag_ids": [1, 2]}, "urgent, blocked") == "urgent, blocked"

    def test_none(self) -> None:
        assert render_value("tags", None, None) == ""
