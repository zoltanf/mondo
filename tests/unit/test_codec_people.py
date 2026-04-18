"""Tests for people column codec."""

from __future__ import annotations

import pytest

from mondo.columns import (
    parse_value,
    people,  # noqa: F401
    render_value,
)


class TestParse:
    def test_single_id(self) -> None:
        assert parse_value("people", "42", {}) == {
            "personsAndTeams": [{"id": 42, "kind": "person"}]
        }

    def test_multiple_ids(self) -> None:
        assert parse_value("people", "42,51", {}) == {
            "personsAndTeams": [
                {"id": 42, "kind": "person"},
                {"id": 51, "kind": "person"},
            ]
        }

    def test_team_prefix(self) -> None:
        assert parse_value("people", "42,team:7", {}) == {
            "personsAndTeams": [
                {"id": 42, "kind": "person"},
                {"id": 7, "kind": "team"},
            ]
        }

    def test_person_prefix(self) -> None:
        assert parse_value("people", "person:42", {}) == {
            "personsAndTeams": [{"id": 42, "kind": "person"}]
        }

    def test_trims_whitespace(self) -> None:
        assert parse_value("people", " 42 , team: 7 ", {}) == {
            "personsAndTeams": [
                {"id": 42, "kind": "person"},
                {"id": 7, "kind": "team"},
            ]
        }

    def test_email_rejected(self) -> None:
        with pytest.raises(ValueError, match="user ID"):
            parse_value("people", "alice@example.com", {})

    def test_empty_clears(self) -> None:
        assert parse_value("people", "", {}) == {}


class TestRender:
    def test_uses_text(self) -> None:
        assert render_value("people", {}, "Alice, Bob") == "Alice, Bob"

    def test_none(self) -> None:
        assert render_value("people", None, None) == ""
