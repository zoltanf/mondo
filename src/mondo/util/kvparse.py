"""Parse repeating `--column K=V` CLI flags into monday's column_values JSON dict.

Phase 1d accepts raw JSON values (or bare strings falling through as-is).
Phase 1e will layer a smart codec per column type on top (plan §9).
"""

from __future__ import annotations

import json
from typing import Any


def parse_column_kv(pair: str) -> tuple[str, Any]:
    """Split `col_id=value` into (col_id, parsed_value).

    `value` is parsed as JSON if possible; otherwise returned as a bare string.
    This covers the 1d MVP: simple text/number columns can be written as bare
    strings, and structured columns accept raw JSON objects/arrays.
    """
    if "=" not in pair:
        raise ValueError(
            f"expected KEY=VALUE, got {pair!r}. "
            'Example: --column status=\'{"label":"Done"}\' or --column text="Hello"'
        )
    key, _, raw = pair.partition("=")
    key = key.strip()
    if not key:
        raise ValueError(f"empty column id in {pair!r}")
    try:
        return key, json.loads(raw)
    except json.JSONDecodeError:
        return key, raw


def parse_columns(pairs: list[str]) -> dict[str, Any]:
    """Apply `parse_column_kv` over a list. Later keys override earlier ones."""
    out: dict[str, Any] = {}
    for p in pairs:
        k, v = parse_column_kv(p)
        out[k] = v
    return out
