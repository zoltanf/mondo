"""Contact-like codecs: email, phone, link.

Shorthand (common form): `value,"Display label"`. The quoted-display suffix is
optional — if omitted, monday uses the raw value.
"""

from __future__ import annotations

from typing import Any, ClassVar

from mondo.columns.base import ColumnCodec, register


def _split_value_and_display(raw: str) -> tuple[str, str | None]:
    """Split at the FIRST comma, and if the second half is quoted, strip quotes."""
    if "," not in raw:
        return raw.strip(), None
    head, _, tail = raw.partition(",")
    display = tail.strip()
    if len(display) >= 2 and display[0] == display[-1] and display[0] in {'"', "'"}:
        display = display[1:-1]
    return head.strip(), display or None


class EmailCodec(ColumnCodec):
    type_name: ClassVar[str] = "email"

    def parse(self, value: str, settings: dict[str, Any]) -> dict[str, str]:
        stripped = value.strip()
        if not stripped:
            return {}
        email, display = _split_value_and_display(stripped)
        if "@" not in email:
            raise ValueError(f"invalid email {email!r}: missing '@'")
        return {"email": email, "text": display or email}

    def render(self, value: Any, text: str | None) -> str:
        return text or ""


class PhoneCodec(ColumnCodec):
    type_name: ClassVar[str] = "phone"

    def parse(self, value: str, settings: dict[str, Any]) -> dict[str, str]:
        stripped = value.strip()
        if not stripped:
            return {}
        # Phone shorthand: `NUMBER,COUNTRY` (country required — monday validates)
        if "," not in stripped:
            raise ValueError(
                f"invalid phone {stripped!r}: expected NUMBER,COUNTRY "
                f"(ISO alpha-2, e.g. +12125551234,US)"
            )
        number, _, country = stripped.partition(",")
        country = country.strip().upper()
        if len(country) != 2 or not country.isalpha():
            raise ValueError(f"invalid country code {country!r}: need 2-letter ISO code")
        return {"phone": number.strip(), "countryShortName": country}

    def render(self, value: Any, text: str | None) -> str:
        return text or ""


class LinkCodec(ColumnCodec):
    type_name: ClassVar[str] = "link"

    def parse(self, value: str, settings: dict[str, Any]) -> dict[str, str]:
        stripped = value.strip()
        if not stripped:
            return {}
        url, display = _split_value_and_display(stripped)
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError(f"invalid link {url!r}: URL must start with http:// or https://")
        return {"url": url, "text": display or url}

    def render(self, value: Any, text: str | None) -> str:
        return text or ""


register(EmailCodec())
register(PhoneCodec())
register(LinkCodec())
