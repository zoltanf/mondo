"""Codecs for scalar-ish column types: text, long_text, numbers, checkbox,
rating, country.

Each codec registers itself on import.
"""

from __future__ import annotations

from typing import Any, ClassVar

from mondo.columns.base import ColumnCodec, register

# A minimal ISO-3166 alpha-2 → English-name table covering the countries
# monday users are most likely to enter. Unknown codes fall back to the
# code itself — monday validates server-side anyway.
_COUNTRY_NAMES: dict[str, str] = {
    "AT": "Austria",
    "AU": "Australia",
    "BE": "Belgium",
    "BR": "Brazil",
    "CA": "Canada",
    "CH": "Switzerland",
    "CN": "China",
    "CZ": "Czechia",
    "DE": "Germany",
    "DK": "Denmark",
    "ES": "Spain",
    "FI": "Finland",
    "FR": "France",
    "GB": "United Kingdom",
    "GR": "Greece",
    "HU": "Hungary",
    "IE": "Ireland",
    "IN": "India",
    "IT": "Italy",
    "JP": "Japan",
    "KR": "South Korea",
    "MX": "Mexico",
    "NL": "Netherlands",
    "NO": "Norway",
    "NZ": "New Zealand",
    "PL": "Poland",
    "PT": "Portugal",
    "SE": "Sweden",
    "SK": "Slovakia",
    "TR": "Turkey",
    "UA": "Ukraine",
    "US": "United States",
}

_TRUTHY: frozenset[str] = frozenset({"true", "yes", "1", "on"})


class TextCodec(ColumnCodec):
    type_name: ClassVar[str] = "text"

    def parse(self, value: str, settings: dict[str, Any]) -> str:
        return value  # monday accepts plain strings for text columns

    def render(self, value: Any, text: str | None) -> str:
        return text or ""

    def clear_payload(self) -> str:
        return ""


class LongTextCodec(ColumnCodec):
    type_name: ClassVar[str] = "long_text"

    def parse(self, value: str, settings: dict[str, Any]) -> dict[str, str]:
        return {"text": value}

    def render(self, value: Any, text: str | None) -> str:
        if text is not None:
            return text
        if isinstance(value, dict):
            return str(value.get("text") or "")
        return ""


class NumbersCodec(ColumnCodec):
    type_name: ClassVar[str] = "numbers"

    def parse(self, value: str, settings: dict[str, Any]) -> str:
        # monday wants numbers as strings; don't reformat — preserve precision
        return value

    def render(self, value: Any, text: str | None) -> str:
        return text or (str(value) if value is not None else "")

    def clear_payload(self) -> str:
        return ""


class CheckboxCodec(ColumnCodec):
    type_name: ClassVar[str] = "checkbox"

    def parse(self, value: str, settings: dict[str, Any]) -> dict[str, str] | None:
        normalized = value.strip().lower()
        if normalized in _TRUTHY:
            return {"checked": "true"}
        return None  # clear — "false" is buggy, null is the safe unchecker

    def render(self, value: Any, text: str | None) -> str:
        if isinstance(value, dict) and str(value.get("checked")).lower() == "true":
            return "✓"
        return "☐"

    def clear_payload(self) -> None:
        return None


class RatingCodec(ColumnCodec):
    type_name: ClassVar[str] = "rating"

    def parse(self, value: str, settings: dict[str, Any]) -> dict[str, int]:
        try:
            rating = int(value.strip())
        except ValueError as e:
            raise ValueError(f"rating must be an integer, got {value!r}") from e
        max_rating = int(settings.get("max_rating") or 5)
        if not 1 <= rating <= max_rating:
            raise ValueError(f"rating {rating} out of range 1..{max_rating}")
        return {"rating": rating}

    def render(self, value: Any, text: str | None) -> str:
        if not isinstance(value, dict):
            return ""
        rating = value.get("rating")
        if not isinstance(rating, int) or rating <= 0:
            return ""
        return "★" * rating


class CountryCodec(ColumnCodec):
    type_name: ClassVar[str] = "country"

    def parse(self, value: str, settings: dict[str, Any]) -> dict[str, str]:
        code = value.strip().upper()
        if len(code) != 2 or not code.isalpha():
            raise ValueError(f"country must be an ISO 3166 alpha-2 code (2 letters), got {value!r}")
        return {
            "countryCode": code,
            "countryName": _COUNTRY_NAMES.get(code, code),
        }

    def render(self, value: Any, text: str | None) -> str:
        return text or (value.get("countryName") if isinstance(value, dict) else "") or ""


register(TextCodec())
register(LongTextCodec())
register(NumbersCodec())
register(CheckboxCodec())
register(RatingCodec())
register(CountryCodec())
