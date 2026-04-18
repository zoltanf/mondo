"""TSV formatter — same shape rules as csv but tab-delimited."""

from __future__ import annotations

import csv
import json
from typing import Any, TextIO


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def render(data: Any, stream: TextIO, tty: bool) -> None:
    writer = csv.writer(stream, delimiter="\t")
    if isinstance(data, list):
        if not data:
            return
        if all(isinstance(r, dict) for r in data):
            seen: dict[str, None] = {}
            for row in data:
                for k in row:
                    seen.setdefault(k, None)
            columns = list(seen)
            writer.writerow(columns)
            for row in data:
                writer.writerow([_stringify(row.get(col)) for col in columns])
            return
        writer.writerow(["value"])
        for item in data:
            writer.writerow([_stringify(item)])
        return

    if isinstance(data, dict):
        writer.writerow(["key", "value"])
        for k, v in data.items():
            writer.writerow([str(k), _stringify(v)])
        return

    writer.writerow(["value"])
    writer.writerow([_stringify(data)])
