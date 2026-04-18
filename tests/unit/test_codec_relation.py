"""Tests for board_relation, dependency, and world_clock codecs."""

from __future__ import annotations

import pytest

from mondo.columns import (
    parse_value,
    relation,  # noqa: F401
    render_value,
)


class TestBoardRelation:
    def test_single(self) -> None:
        assert parse_value("board_relation", "12345", {}) == {"item_ids": [12345]}

    def test_multiple(self) -> None:
        assert parse_value("board_relation", "12345,23456", {}) == {"item_ids": [12345, 23456]}

    def test_non_integer_raises(self) -> None:
        with pytest.raises(ValueError, match="integer"):
            parse_value("board_relation", "some-name", {})

    def test_empty_clears(self) -> None:
        assert parse_value("board_relation", "", {}) == {}


class TestDependency:
    def test_multiple(self) -> None:
        assert parse_value("dependency", "111,222", {}) == {"item_ids": [111, 222]}

    def test_empty_clears(self) -> None:
        assert parse_value("dependency", "", {}) == {}


class TestWorldClock:
    def test_iana_tz(self) -> None:
        assert parse_value("world_clock", "Europe/London", {}) == {"timezone": "Europe/London"}

    def test_empty_clears(self) -> None:
        assert parse_value("world_clock", "", {}) == {}

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="IANA"):
            parse_value("world_clock", "Middle-earth/Gondor", {})

    def test_render(self) -> None:
        assert render_value("world_clock", {"timezone": "Europe/London"}, None) == "Europe/London"
