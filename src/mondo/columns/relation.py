"""Relation-family codecs: board_relation, dependency, world_clock.

All take integer ID lists except world_clock which takes an IANA timezone.
"""

from __future__ import annotations

import json
import zoneinfo
from typing import Any, ClassVar

from mondo.columns.base import ColumnCodec, register


def _parse_id_list(value: str, label: str) -> list[int]:
    """Accept three shapes:

    - ``"12345"`` — a single integer item ID.
    - ``"12345,67890"`` — CSV of integer IDs.
    - ``'{"item_ids":[12345,67890]}'`` — the GraphQL-native shape that
      agents copy from monday's API responses.

    Returns the int list. Caller decides clear-vs-set semantics.
    """
    stripped = value.strip()
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
        except ValueError as e:
            raise ValueError(
                f"{label} codec: value looks like JSON but didn't parse — {e}. "
                f"Accepted shapes: integer ID, CSV of integer IDs "
                f"(e.g. '12345,67890'), or the GraphQL-native object "
                f'\'{{"item_ids":[12345,67890]}}\'.'
            ) from e
        if not isinstance(obj, dict) or "item_ids" not in obj:
            keys = list(obj) if isinstance(obj, dict) else type(obj).__name__
            raise ValueError(
                f'{label} codec: JSON object must have shape '
                f'\'{{"item_ids":[...]}}\' (got keys={keys}).'
            )
        ids = obj["item_ids"]
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            raise ValueError(
                f"{label} codec: item_ids must be a list of integers, got {ids!r}."
            )
        return list(ids)

    parts = [p.strip() for p in stripped.split(",") if p.strip()]
    try:
        return [int(p) for p in parts]
    except ValueError as e:
        raise ValueError(
            f"{label} codec requires integer item IDs (got {value!r}). "
            f"Accepted shapes: '12345', CSV like '12345,67890', or the "
            f'GraphQL-native object \'{{"item_ids":[12345,67890]}}\'.'
        ) from e


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
