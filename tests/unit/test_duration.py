"""parse_duration accepts compact strings (s/ms/m/h) and returns seconds."""

from __future__ import annotations

import pytest

from mondo.util.duration import parse_duration


class TestUnits:
    def test_seconds(self):
        assert parse_duration("2s") == 2.0

    def test_milliseconds(self):
        assert parse_duration("500ms") == 0.5

    def test_minutes(self):
        assert parse_duration("5m") == 300.0

    def test_hours(self):
        assert parse_duration("1h") == 3600.0

    def test_decimal_seconds(self):
        assert parse_duration("1.5s") == 1.5

    def test_bare_number_treated_as_seconds(self):
        assert parse_duration("3") == 3.0

    def test_zero_seconds(self):
        assert parse_duration("0s") == 0.0
        assert parse_duration("0") == 0.0


class TestErrors:
    def test_rejects_garbage(self):
        with pytest.raises(ValueError, match="duration"):
            parse_duration("forever")

    def test_rejects_negative(self):
        with pytest.raises(ValueError, match="non-negative"):
            parse_duration("-1s")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            parse_duration("")

    def test_rejects_unknown_unit(self):
        with pytest.raises(ValueError):
            parse_duration("5d")
