"""Location codec.

Shorthand: `lat,lng[,"address"]`. monday-api.md §11.5.12 notes lat/lng are
strings (not numbers); we let the user write them numerically and stringify.
"""

from __future__ import annotations

from typing import Any, ClassVar

from mondo.columns.base import ColumnCodec, register


class LocationCodec(ColumnCodec):
    type_name: ClassVar[str] = "location"

    def parse(self, value: str, settings: dict[str, Any]) -> dict[str, str]:
        stripped = value.strip()
        if not stripped:
            return {}

        parts = stripped.split(",", 2)
        if len(parts) < 2:
            raise ValueError(
                f"invalid location {stripped!r}: expected 'lat,lng' or 'lat,lng,\"address\"'"
            )
        lat_s, lng_s = parts[0].strip(), parts[1].strip()
        try:
            lat, lng = float(lat_s), float(lng_s)
        except ValueError as e:
            raise ValueError(f"location lat/lng must be number(s); got {lat_s!r}, {lng_s!r}") from e
        if not -90 <= lat <= 90:
            raise ValueError(f"latitude {lat} out of range (-90..90)")
        if not -180 <= lng <= 180:
            raise ValueError(f"longitude {lng} out of range (-180..180)")

        address = ""
        if len(parts) == 3:
            raw = parts[2].strip()
            if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
                raw = raw[1:-1]
            address = raw

        return {"lat": lat_s, "lng": lng_s, "address": address}

    def render(self, value: Any, text: str | None) -> str:
        return text or ""


register(LocationCodec())
