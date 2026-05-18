"""Parse compact duration strings (`2s`, `500ms`, `5m`, `1h`) into seconds.

Used by the polling flags on read commands (`--poll-interval`,
`--poll-timeout`). Accepts bare numbers as seconds for convenience.
"""
from __future__ import annotations

import re

_DURATION_RE = re.compile(r"^(-?[0-9]+(?:\.[0-9]+)?)(ms|s|m|h)?$")
_SCALE: dict[str | None, float] = {
    None: 1.0,
    "ms": 1e-3,
    "s": 1.0,
    "m": 60.0,
    "h": 3600.0,
}


def parse_duration(text: str) -> float:
    """Return `text` as seconds. Raises ValueError on garbage or negatives."""
    if not text or not text.strip():
        raise ValueError("empty duration")
    match = _DURATION_RE.match(text.strip())
    if not match:
        raise ValueError(f"invalid duration {text!r}")
    raw, unit = match.groups()
    value = float(raw)
    if value < 0:
        raise ValueError(f"duration must be non-negative, got {text!r}")
    return value * _SCALE[unit]
