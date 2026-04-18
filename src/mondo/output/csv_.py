"""CSV formatter — handles array-of-objects, object, and scalar inputs."""

from __future__ import annotations

import csv
import json
from typing import Any, TextIO


def _stringify(value: Any) -> str:
    """Encode a non-scalar value as JSON; leave scalars alone."""
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def _write_rows(stream: TextIO, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    # Column header = union of top-level keys across all rows, preserving first-seen order.
    seen: dict[str, None] = {}
    for row in rows:
        for k in row:
            seen.setdefault(k, None)
    columns = list(seen)
    writer = csv.writer(stream)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_stringify(row.get(col)) for col in columns])


def render(data: Any, stream: TextIO, tty: bool) -> None:
    if isinstance(data, list):
        # Homogeneous dict rows or empty list
        if all(isinstance(r, dict) for r in data):
            _write_rows(stream, data)
            return
        # Scalars / mixed → single-column "value"
        writer = csv.writer(stream)
        writer.writerow(["value"])
        for item in data:
            writer.writerow([_stringify(item)])
        return

    if isinstance(data, dict):
        writer = csv.writer(stream)
        writer.writerow(["key", "value"])
        for k, v in data.items():
            writer.writerow([str(k), _stringify(v)])
        return

    # Scalar
    writer = csv.writer(stream)
    writer.writerow(["value"])
    writer.writerow([_stringify(data)])
