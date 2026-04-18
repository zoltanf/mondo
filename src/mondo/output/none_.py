"""`none` formatter — prints a scalar as a bare line, suppresses structures.

Useful with `-q '<scalar-expr>'` when a command is used as a shell variable:
    count=$(mondo item list --board X -o none -q "length(@)")
"""

from __future__ import annotations

from typing import Any, TextIO


def render(data: Any, stream: TextIO, tty: bool) -> None:
    if data is None:
        return
    if isinstance(data, (str, int, float, bool)):
        stream.write(str(data))
        stream.write("\n")
        return
    # Lists / dicts are intentionally dropped — use `json` if you want them.
