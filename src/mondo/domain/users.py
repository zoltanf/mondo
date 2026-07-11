"""Normalize monday `User` records to a stable output shape.

API 2026-07 replaced the boolean role/state fields with the `kind` and
`status` scalars (the old fields are deprecated, removal targeted 2026-10).
mondo migrates its queries to the new fields but keeps emitting the legacy
booleans so existing consumers/scripts don't break, deriving them here while
also passing `kind`/`status` through untouched.

Runtime values verified live on API 2026-07:
- `kind`: "admin" | "member" | "guest" | "view_only" (+ service kinds).
- `status`: "ACTIVE" | "INACTIVE" | "PENDING".
"""

from __future__ import annotations

from typing import Any


def normalize_user(user: dict[str, Any]) -> dict[str, Any]:
    """Return `user` with legacy boolean fields derived from `kind`/`status`.

    Derivation keys off field *presence* in the source, not its value: a
    partial selection that never fetched `kind`/`status`/`photo_url` stays
    lossless (the derived keys are omitted), but a selected-but-null source
    emits the derived key as ``None`` rather than dropping it — so consumers
    see a stable shape. New fields (`kind`, `status`, `photo_url`) are
    preserved as-is.
    """
    out = dict(user)

    if "kind" in user:
        kind = user["kind"]
        out["is_admin"] = kind == "admin" if kind is not None else None
        out["is_guest"] = kind == "guest" if kind is not None else None
        out["is_view_only"] = kind == "view_only" if kind is not None else None

    if "status" in user:
        status = user["status"]
        out["enabled"] = status == "ACTIVE" if status is not None else None
        out["is_pending"] = status == "PENDING" if status is not None else None

    if "photo_url" in user:
        photo_url = user["photo_url"]
        out["photo_thumb"] = photo_url.get("thumb") if isinstance(photo_url, dict) else None

    return out
