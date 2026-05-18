"""Field projection for --fields CSV spec. Runs before -q JMESPath.

Friction report C2: agents repeatedly pipe `mondo X list -o json | jq '[].{...}'`
because the JMESPath -q is hard to discover. `--fields id,name,status` is a
discoverable shortcut for the most common shape: a flat record (or list of
records) projected down to a handful of named keys.

Dotted paths (`creator.name`) are walked through nested dicts; the result
key is the dotted form so a downstream JMESPath / formatter sees a flat
record. Missing keys map to None — never raise — so a heterogeneous list
projects cleanly.
"""
from __future__ import annotations

from typing import Any


def _project_one(record: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in keys:
        if "." in key:
            value: Any = record
            for part in key.split("."):
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = None
                    break
            out[key] = value
        else:
            out[key] = record.get(key)
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
    if isinstance(data, list):
        return [
            _project_one(item, keys) if isinstance(item, dict) else item
            for item in data
        ]
    if isinstance(data, dict):
        return _project_one(data, keys)
    return data
