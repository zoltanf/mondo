"""Date-family codecs: date, timeline, week, hour.

All use ISO-ish formats. See monday-api.md §11.5.5 / 8 / 17 / 18.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, ClassVar

from mondo.columns.base import ColumnCodec, register

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{1,2}:\d{2}(?::\d{2})?)$")
_WEEK_RE = re.compile(r"^(\d{4})-W(\d{1,2})$")
_HOUR_RE = re.compile(r"^(\d{1,2})(?::(\d{1,2}))?$")


def _normalize_time(t: str) -> str:
    parts = t.split(":")
    if len(parts) == 2:
        parts.append("00")
    hh, mm, ss = parts
    return f"{int(hh):02d}:{int(mm):02d}:{int(ss):02d}"


class DateCodec(ColumnCodec):
    type_name: ClassVar[str] = "date"

    def parse(self, value: str, settings: dict[str, Any]) -> dict[str, str]:
        stripped = value.strip()
        if not stripped:
            return {}
        if _DATE_RE.match(stripped):
            return {"date": stripped}
        m = _DATE_TIME_RE.match(stripped)
        if m:
            date, time = m.group(1), m.group(2)
            return {"date": date, "time": _normalize_time(time)}
        raise ValueError(
            f"invalid date {stripped!r}: expected YYYY-MM-DD or YYYY-MM-DD[T ]HH:MM[:SS]"
        )

    def render(self, value: Any, text: str | None) -> str:
        return text or ""


class TimelineCodec(ColumnCodec):
    type_name: ClassVar[str] = "timeline"

    def parse(self, value: str, settings: dict[str, Any]) -> dict[str, str]:
        stripped = value.strip()
        if not stripped:
            return {}
        if ".." not in stripped:
            raise ValueError(f"invalid timeline {stripped!r}: expected YYYY-MM-DD..YYYY-MM-DD")
        start, _, end = stripped.partition("..")
        start, end = start.strip(), end.strip()
        if not (_DATE_RE.match(start) and _DATE_RE.match(end)):
            raise ValueError(f"invalid timeline endpoints {start!r} / {end!r}: use YYYY-MM-DD")
        return {"from": start, "to": end}

    def render(self, value: Any, text: str | None) -> str:
        return text or ""


class WeekCodec(ColumnCodec):
    type_name: ClassVar[str] = "week"

    def parse(self, value: str, settings: dict[str, Any]) -> dict[str, dict[str, str]]:
        stripped = value.strip()
        if not stripped:
            return {}
        m = _WEEK_RE.match(stripped)
        if not m:
            raise ValueError(f"invalid week {stripped!r}: expected YYYY-Www (e.g. 2026-W16)")
        year, week = int(m.group(1)), int(m.group(2))
        if not 1 <= week <= 53:
            raise ValueError(f"week number {week} out of range 1-53")
        try:
            start = dt.date.fromisocalendar(year, week, 1)
        except ValueError as e:
            raise ValueError(f"week {year}-W{week} is invalid for ISO calendar: {e}") from e
        end = start + dt.timedelta(days=6)
        return {"week": {"startDate": start.isoformat(), "endDate": end.isoformat()}}

    def render(self, value: Any, text: str | None) -> str:
        return text or ""


class HourCodec(ColumnCodec):
    type_name: ClassVar[str] = "hour"

    def parse(self, value: str, settings: dict[str, Any]) -> dict[str, int]:
        stripped = value.strip()
        if not stripped:
            return {}
        m = _HOUR_RE.match(stripped)
        if not m:
            raise ValueError(f"invalid hour {stripped!r}: expected HH or HH:MM")
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        if not 0 <= hour <= 23:
            raise ValueError(f"hour {hour} out of range 0-23")
        if not 0 <= minute <= 59:
            raise ValueError(f"minute {minute} out of range 0-59")
        return {"hour": hour, "minute": minute}

    def render(self, value: Any, text: str | None) -> str:
        if isinstance(value, dict):
            hour = value.get("hour")
            minute = value.get("minute", 0)
            if isinstance(hour, int):
                minute = minute if isinstance(minute, int) else 0
                return f"{hour:02d}:{minute:02d}"
        return text or ""


register(DateCodec())
register(TimelineCodec())
register(WeekCodec())
register(HourCodec())
