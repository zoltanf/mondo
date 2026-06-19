"""Field projection for --fields CSV spec. Runs after -q JMESPath.

`--fields id,name,creator.name` is a discoverable shortcut for the most
common shape: a flat record (or list of records) projected down to a few
named keys. Dotted paths walk through nested dicts; the result key is the
dotted form so a downstream JMESPath / formatter sees a flat record.
Missing keys map to None — never raise — so a heterogeneous list projects
cleanly. Projection itself is client-side, but `item list` also inspects
the spec up front and drops `column_values` from its GraphQL request when
no key reads them (see `_can_slim_column_values` in mondo.cli.item).
"""

from __future__ import annotations

from typing import Any


def _project_one(record: dict[str, Any], split_keys: list[tuple[str, list[str]]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, parts in split_keys:
        if len(parts) == 1:
            out[key] = record.get(key)
            continue
        value: Any = record
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
                break
        out[key] = value
    return out


def apply_fields(data: Any, spec: str | None) -> Any:
    """Project `data` to the keys named in `spec` ("id,name,creator.name").

    `None` or empty `spec` returns `data` unchanged.  A list payload is
    projected per-element; non-dict elements pass through. A non-dict-non-list
    payload (scalar, None) passes through unchanged.
    """
    if not spec or not spec.strip():
        return data
    keys = [k.strip() for k in spec.split(",") if k.strip()]
    if not keys:
        return data
    # Pre-split dotted keys once so a list of N rows doesn't re-split per row.
    split_keys = [(k, k.split(".")) for k in keys]
    if isinstance(data, list):
        return [_project_one(item, split_keys) if isinstance(item, dict) else item for item in data]
    if isinstance(data, dict):
        return _project_one(data, split_keys)
    return data
