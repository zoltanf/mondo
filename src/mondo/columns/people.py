"""People column codec.

Shorthand:
    `42`              → single person id
    `42,51`           → multiple person ids
    `team:7`          → team id
    `42,team:7`       → mixed
Emails are NOT accepted (monday requires ids — use `users(emails:...)` first).
"""

from __future__ import annotations

from typing import Any, ClassVar

from mondo.columns.base import ColumnCodec, register


class PeopleCodec(ColumnCodec):
    type_name: ClassVar[str] = "people"

    def parse(self, value: str, settings: dict[str, Any]) -> dict[str, Any]:
        stripped = value.strip()
        if not stripped:
            return {}
        parts = [p.strip() for p in stripped.split(",") if p.strip()]
        entries: list[dict[str, Any]] = []
        for raw in parts:
            entries.append(_parse_one(raw))
        return {"personsAndTeams": entries}

    def render(self, value: Any, text: str | None) -> str:
        return text or ""


def _parse_one(token: str) -> dict[str, Any]:
    if "@" in token:
        raise ValueError(
            f"people column requires user IDs, not emails (got {token!r}). "
            f'Look up IDs with `users(emails:["{token}"]) {{ id }}` first.'
        )
    kind = "person"
    body = token
    for prefix, resolved in (("team:", "team"), ("person:", "person")):
        if token.lower().startswith(prefix):
            kind = resolved
            body = token[len(prefix) :].strip()
            break
    try:
        return {"id": int(body), "kind": kind}
    except ValueError as e:
        raise ValueError(
            f"invalid people token {token!r}: expected integer id"
            " (optionally prefixed with team: or person:)"
        ) from e


register(PeopleCodec())
