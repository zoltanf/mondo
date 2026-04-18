"""Tests for the simple column codecs: text, long_text, numbers, checkbox,
rating, country."""

from __future__ import annotations

import pytest

# Importing the module triggers registration.
from mondo.columns import (
    clear_payload_for,
    parse_value,
    render_value,
    simple,  # noqa: F401
)


class TestText:
    def test_parse_passthrough(self) -> None:
        assert parse_value("text", "Hello", {}) == "Hello"

    def test_parse_empty_clears(self) -> None:
        # Simple strings clear with "" (monday-api.md §11.6)
        assert parse_value("text", "", {}) == ""

    def test_render_uses_text(self) -> None:
        assert render_value("text", {}, "Hello world") == "Hello world"

    def test_render_none(self) -> None:
        assert render_value("text", None, None) == ""

    def test_clear_payload_is_empty_string(self) -> None:
        assert clear_payload_for("text") == ""


class TestLongText:
    def test_parse_wraps_in_text_key(self) -> None:
        assert parse_value("long_text", "line 1\nline 2", {}) == {"text": "line 1\nline 2"}

    def test_render_from_text(self) -> None:
        assert render_value("long_text", {"text": "body"}, "body") == "body"


class TestNumbers:
    def test_parse_passthrough_string(self) -> None:
        assert parse_value("numbers", "42.5", {}) == "42.5"

    def test_parse_bare_integer(self) -> None:
        assert parse_value("numbers", "9", {}) == "9"

    def test_render(self) -> None:
        assert render_value("numbers", "42.5", "42.5") == "42.5"

    def test_clear_payload_is_empty_string(self) -> None:
        assert clear_payload_for("numbers") == ""


class TestCheckbox:
    @pytest.mark.parametrize("val", ["true", "yes", "1", "on"])
    def test_parse_truthy(self, val: str) -> None:
        # Monday quirk: must be string "true", not boolean
        assert parse_value("checkbox", val, {}) == {"checked": "true"}

    @pytest.mark.parametrize("val", ["false", "no", "0", "off", ""])
    def test_parse_falsy_clears(self, val: str) -> None:
        # "false" is buggy on monday; send null to clear instead
        assert parse_value("checkbox", val, {}) is None

    def test_parse_clear(self) -> None:
        assert parse_value("checkbox", "clear", {}) is None

    def test_render_checked(self) -> None:
        assert render_value("checkbox", {"checked": "true"}, "v") == "✓"

    def test_render_unchecked(self) -> None:
        assert render_value("checkbox", None, None) == "☐"
        assert render_value("checkbox", {}, "") == "☐"

    def test_clear_payload(self) -> None:
        assert clear_payload_for("checkbox") is None


class TestRating:
    def test_parse_integer(self) -> None:
        assert parse_value("rating", "4", {}) == {"rating": 4}

    def test_parse_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="integer"):
            parse_value("rating", "four", {})

    def test_parse_out_of_range_raises(self) -> None:
        settings = {"max_rating": 5}
        with pytest.raises(ValueError, match=r"1\.\.5"):
            parse_value("rating", "10", settings)

    def test_render(self) -> None:
        assert render_value("rating", {"rating": 3}, "3") == "★★★"

    def test_render_none(self) -> None:
        assert render_value("rating", None, None) == ""


class TestCountry:
    def test_parse_two_letter_code(self) -> None:
        result = parse_value("country", "US", {})
        assert result == {"countryCode": "US", "countryName": "United States"}

    def test_parse_lowercase(self) -> None:
        result = parse_value("country", "de", {})
        assert result == {"countryCode": "DE", "countryName": "Germany"}

    def test_parse_unknown_code_keeps_code(self) -> None:
        """Unknown code → use the code as the name fallback."""
        result = parse_value("country", "ZZ", {})
        assert result["countryCode"] == "ZZ"
        assert result["countryName"] == "ZZ"

    def test_parse_bad_length_raises(self) -> None:
        with pytest.raises(ValueError, match="ISO"):
            parse_value("country", "USA", {})

    def test_render(self) -> None:
        assert render_value("country", {"countryCode": "US"}, "United States") == "United States"
