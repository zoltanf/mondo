"""TSV formatter — same shape rules as csv but tab-delimited."""

from __future__ import annotations

import csv
import json
from typing import Any, TextIO

from mondo.util.sanitize import guard_formula


def _stringify(value: Any) -> str:
    # monday data is untrusted: guard formula-looking cells so a spreadsheet
    # opening the TSV won't execute them (see mondo.util.sanitize).
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return guard_formula(str(value))
    return guard_formula(json.dumps(value, ensure_ascii=False))


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
            writer.writerow([guard_formula(c) for c in columns])
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
            writer.writerow([guard_formula(str(k)), _stringify(v)])
        return

    writer.writerow(["value"])
    writer.writerow([_stringify(data)])
