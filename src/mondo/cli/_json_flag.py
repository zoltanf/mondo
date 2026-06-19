"""Shared JSON-flag parser for CLI commands.

Many commands accept a `--<flag>` whose value is a JSON literal (e.g.
`--config`, `--filter`, `--content`, `--values`, `--position`,
`--variables`). On bad JSON they all emit the same shape
`error: --<flag> is not valid JSON: <exc>` and exit with code 2.
"""

from __future__ import annotations

import json
from typing import Any


def parse_json_flag(value: str, *, flag_name: str) -> Any:
    """Return `json.loads(value)`, or exit(2) with a consistent error message."""
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        from mondo.cli._exec import usage_error_or_exit

        usage_error_or_exit(f"{flag_name} is not valid JSON: {exc}")
