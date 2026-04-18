"""Tests for date, timeline, week, hour codecs."""

from __future__ import annotations

import pytest

from mondo.columns import (
    datelike,  # noqa: F401
    parse_value,
    render_value,
)


class TestDate:
    def test_date_only(self) -> None:
        assert parse_value("date", "2026-04-25", {}) == {"date": "2026-04-25"}

    def test_date_with_time_T_separator(self) -> None:
        assert parse_value("date", "2026-04-25T10:00", {}) == {
            "date": "2026-04-25",
            "time": "10:00:00",
        }

    def test_date_with_space_separator(self) -> None:
        assert parse_value("date", "2026-04-25 10:30:45", {}) == {
            "date": "2026-04-25",
            "time": "10:30:45",
        }

    def test_malformed_raises(self) -> None:
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            parse_value("date", "tomorrow", {})

    def test_empty_clears(self) -> None:
        assert parse_value("date", "", {}) == {}

    def test_render(self) -> None:
        assert render_value("date", {"date": "2026-04-25"}, "2026-04-25") == "2026-04-25"


class TestTimeline:
    def test_range(self) -> None:
        assert parse_value("timeline", "2026-04-01..2026-04-15", {}) == {
            "from": "2026-04-01",
            "to": "2026-04-15",
        }

    def test_missing_separator_raises(self) -> None:
        with pytest.raises(ValueError, match=r"\.\."):
            parse_value("timeline", "2026-04-01", {})

    def test_empty_clears(self) -> None:
        assert parse_value("timeline", "", {}) == {}


class TestWeek:
    def test_iso_week(self) -> None:
        # 2026-W16 = Mon 2026-04-13 through Sun 2026-04-19
        result = parse_value("week", "2026-W16", {})
        assert result == {"week": {"startDate": "2026-04-13", "endDate": "2026-04-19"}}

    def test_bad_format_raises(self) -> None:
        with pytest.raises(ValueError, match="YYYY-Www"):
            parse_value("week", "2026-04", {})

    def test_bad_week_number_raises(self) -> None:
        with pytest.raises(ValueError, match="1-53"):
            parse_value("week", "2026-W99", {})


class TestHour:
    def test_hour_minute(self) -> None:
        assert parse_value("hour", "14:30", {}) == {"hour": 14, "minute": 30}

    def test_hour_only(self) -> None:
        assert parse_value("hour", "9", {}) == {"hour": 9, "minute": 0}

    def test_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="0-23"):
            parse_value("hour", "25:00", {})

    def test_malformed_raises(self) -> None:
        with pytest.raises(ValueError, match="HH"):
            parse_value("hour", "half-past-three", {})

    def test_render(self) -> None:
        assert render_value("hour", {"hour": 14, "minute": 30}, None) == "14:30"

    def test_render_none(self) -> None:
        assert render_value("hour", None, None) == ""
