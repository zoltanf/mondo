"""Tests for board_relation, dependency, and world_clock codecs."""

from __future__ import annotations

import pytest

from mondo.columns import (
    parse_value,
    relation,  # noqa: F401
    render_entry,
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

    def test_json_object_shape_accepted(self) -> None:
        """The GraphQL-native shape '{"item_ids":[...]}' should pass through.

        Friction report B6: agents copy the GraphQL payload shape into
        --value and the codec rejects them. Accept the shape directly.
        """
        assert parse_value("board_relation", '{"item_ids": [12345, 23456]}', {}) == {
            "item_ids": [12345, 23456]
        }

    def test_json_object_with_single_id(self) -> None:
        assert parse_value("board_relation", '{"item_ids":[1]}', {}) == {"item_ids": [1]}

    def test_json_object_with_empty_ids_clears(self) -> None:
        assert parse_value("board_relation", '{"item_ids":[]}', {}) == {"item_ids": []}

    def test_error_message_lists_accepted_shapes(self) -> None:
        with pytest.raises(ValueError) as exc:
            parse_value("board_relation", "some-name", {})
        msg = str(exc.value)
        assert "integer" in msg
        assert "item_ids" in msg  # mentions the JSON-shape escape hatch

    def test_json_object_wrong_keys_rejected(self) -> None:
        with pytest.raises(ValueError, match="item_ids"):
            parse_value("board_relation", '{"items": [1]}', {})

    def test_json_object_non_int_ids_rejected(self) -> None:
        with pytest.raises(ValueError, match="integer"):
            parse_value("board_relation", '{"item_ids": ["a", "b"]}', {})


class TestBoardRelationRenderEntry:
    """#88: board_relation returns a null `text`; linked item names come back
    in the `display_value` inline-fragment field (with `linked_item_ids`)."""

    def test_prefers_display_value(self) -> None:
        entry = {
            "id": "rel",
            "type": "board_relation",
            "text": None,
            "display_value": "Alpha, Beta",
            "linked_item_ids": ["111", "222"],
        }
        assert render_entry("board_relation", entry) == "Alpha, Beta"

    def test_falls_back_to_text(self) -> None:
        entry = {
            "id": "rel",
            "type": "board_relation",
            "text": "Alpha",
            "display_value": None,
            "linked_item_ids": ["111"],
        }
        assert render_entry("board_relation", entry) == "Alpha"

    def test_falls_back_to_linked_ids(self) -> None:
        entry = {
            "id": "rel",
            "type": "board_relation",
            "text": None,
            "display_value": None,
            "linked_item_ids": ["111", "222"],
        }
        assert render_entry("board_relation", entry) == "111, 222"

    def test_empty_when_nothing_linked(self) -> None:
        entry = {"id": "rel", "type": "board_relation", "display_value": "", "linked_item_ids": []}
        assert render_entry("board_relation", entry) == ""


class TestDependency:
    def test_multiple(self) -> None:
        assert parse_value("dependency", "111,222", {}) == {"item_ids": [111, 222]}

    def test_empty_clears(self) -> None:
        assert parse_value("dependency", "", {}) == {}

    def test_json_object_shape_accepted(self) -> None:
        assert parse_value("dependency", '{"item_ids":[7,8]}', {}) == {"item_ids": [7, 8]}


class TestDependencyRenderEntry:
    """#88: dependency returns a null `text`; linked item names come back in
    the `display_value` inline-fragment field (with `linked_item_ids`)."""

    def test_prefers_display_value(self) -> None:
        entry = {
            "id": "dep",
            "type": "dependency",
            "text": None,
            "display_value": "Task A, Task B",
            "linked_item_ids": ["111", "222"],
        }
        assert render_entry("dependency", entry) == "Task A, Task B"

    def test_falls_back_to_text_then_linked_ids(self) -> None:
        entry = {"id": "dep", "type": "dependency", "text": "Task A", "display_value": None}
        assert render_entry("dependency", entry) == "Task A"
        entry = {
            "id": "dep",
            "type": "dependency",
            "text": None,
            "display_value": None,
            "linked_item_ids": ["111", "222"],
        }
        assert render_entry("dependency", entry) == "111, 222"

    def test_empty_when_nothing_linked(self) -> None:
        entry = {"id": "dep", "type": "dependency", "display_value": "", "linked_item_ids": []}
        assert render_entry("dependency", entry) == ""


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
