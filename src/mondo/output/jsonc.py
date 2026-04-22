"""Rich-highlighted JSON for humans (`jsonc` = json-color)."""

from __future__ import annotations

import json
from typing import Any, TextIO


def render(data: Any, stream: TextIO, tty: bool) -> None:
    payload = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False)
    if not tty:
        stream.write(payload)
        stream.write("\n")
        return
    from rich.console import Console
    from rich.syntax import Syntax

    console = Console(file=stream, force_terminal=True, highlight=False)
    console.print(Syntax(payload, "json", theme="ansi_dark", background_color="default"))
