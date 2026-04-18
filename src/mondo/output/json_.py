"""Plain JSON formatter (compact, pretty-indented, machine default)."""

from __future__ import annotations

import json
from typing import Any, TextIO


def render(data: Any, stream: TextIO, tty: bool) -> None:
    json.dump(data, stream, indent=2, ensure_ascii=False, sort_keys=False)
    stream.write("\n")
