"""Tests for email, phone, link, location codecs."""

from __future__ import annotations

import pytest

from mondo.columns import contact, location, parse_value, render_value  # noqa: F401


class TestEmail:
    def test_plain(self) -> None:
        assert parse_value("email", "alice@example.com", {}) == {
            "email": "alice@example.com",
            "text": "alice@example.com",
        }

    def test_with_display(self) -> None:
        assert parse_value("email", 'alice@example.com,"Alice Smith"', {}) == {
            "email": "alice@example.com",
            "text": "Alice Smith",
        }

    def test_missing_at_raises(self) -> None:
        with pytest.raises(ValueError, match="email"):
            parse_value("email", "not-an-email", {})

    def test_empty_clears(self) -> None:
        assert parse_value("email", "", {}) == {}

    def test_render(self) -> None:
        assert render_value("email", {}, "alice@example.com") == "alice@example.com"


class TestPhone:
    def test_with_country(self) -> None:
        assert parse_value("phone", "+19175998722,US", {}) == {
            "phone": "+19175998722",
            "countryShortName": "US",
        }

    def test_without_country_raises(self) -> None:
        # ISO country is required
        with pytest.raises(ValueError, match=r"(?i)country"):
            parse_value("phone", "+19175998722", {})

    def test_bad_country_raises(self) -> None:
        with pytest.raises(ValueError, match="2-letter"):
            parse_value("phone", "+1234,USA", {})

    def test_empty_clears(self) -> None:
        assert parse_value("phone", "", {}) == {}


class TestLink:
    def test_plain(self) -> None:
        assert parse_value("link", "https://example.com", {}) == {
            "url": "https://example.com",
            "text": "https://example.com",
        }

    def test_with_display(self) -> None:
        assert parse_value("link", 'https://example.com,"Click me"', {}) == {
            "url": "https://example.com",
            "text": "Click me",
        }

    def test_http_no_scheme_rejected(self) -> None:
        with pytest.raises(ValueError, match="http"):
            parse_value("link", "example.com", {})

    def test_empty_clears(self) -> None:
        assert parse_value("link", "", {}) == {}


class TestLocation:
    def test_lat_lng(self) -> None:
        assert parse_value("location", "40.68,-74.04", {}) == {
            "lat": "40.68",
            "lng": "-74.04",
            "address": "",
        }

    def test_lat_lng_address(self) -> None:
        assert parse_value("location", '40.68,-74.04,"Statue of Liberty"', {}) == {
            "lat": "40.68",
            "lng": "-74.04",
            "address": "Statue of Liberty",
        }

    def test_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="latitude"):
            parse_value("location", "91,0", {})
        with pytest.raises(ValueError, match="longitude"):
            parse_value("location", "0,181", {})

    def test_non_numeric_raises(self) -> None:
        with pytest.raises(ValueError, match="number"):
            parse_value("location", "north,south", {})

    def test_empty_clears(self) -> None:
        assert parse_value("location", "", {}) == {}
