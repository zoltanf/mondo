"""Relation-family codecs: board_relation, dependency, world_clock.

All take integer ID lists except world_clock which takes an IANA timezone.
"""

from __future__ import annotations

import zoneinfo
from typing import Any, ClassVar

from mondo.columns.base import ColumnCodec, register


def _parse_id_list(value: str, label: str) -> list[int]:
    parts = [p.strip() for p in value.split(",") if p.strip()]
    try:
        return [int(p) for p in parts]
    except ValueError as e:
        raise ValueError(f"{label} codec requires integer item IDs (got {value!r})") from e


class BoardRelationCodec(ColumnCodec):
    type_name: ClassVar[str] = "board_relation"

    def parse(self, value: str, settings: dict[str, Any]) -> dict[str, list[int]]:
        stripped = value.strip()
        if not stripped:
            return {}
        return {"item_ids": _parse_id_list(stripped, "board_relation")}

    def render(self, value: Any, text: str | None) -> str:
        return text or ""


class DependencyCodec(ColumnCodec):
    type_name: ClassVar[str] = "dependency"

    def parse(self, value: str, settings: dict[str, Any]) -> dict[str, list[int]]:
        stripped = value.strip()
        if not stripped:
            return {}
        return {"item_ids": _parse_id_list(stripped, "dependency")}

    def render(self, value: Any, text: str | None) -> str:
        return text or ""


class WorldClockCodec(ColumnCodec):
    type_name: ClassVar[str] = "world_clock"

    def parse(self, value: str, settings: dict[str, Any]) -> dict[str, str]:
        stripped = value.strip()
        if not stripped:
            return {}
        try:
            zoneinfo.ZoneInfo(stripped)
        except zoneinfo.ZoneInfoNotFoundError as e:
            raise ValueError(
                f"invalid timezone {stripped!r}: expected IANA identifier "
                f"(e.g. 'Europe/London', 'America/New_York')"
            ) from e
        return {"timezone": stripped}

    def render(self, value: Any, text: str | None) -> str:
        if isinstance(value, dict):
            tz = value.get("timezone")
            if tz:
                return str(tz)
        return text or ""


register(BoardRelationCodec())
register(DependencyCodec())
register(WorldClockCodec())
