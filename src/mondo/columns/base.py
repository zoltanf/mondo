"""ColumnCodec base class and registry.

Each codec owns:
- `parse(value, settings)`: turn user shorthand → monday's JSON write shape.
- `render(value, text)`: turn monday's read payload → human-readable string.
- `clear_payload()`: what to send to clear the column (default `{}`;
  monday-api.md §11.6 lists the exceptions).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar


class UnknownColumnTypeError(KeyError):
    """Raised when a column type has no registered codec."""


class ColumnCodec(ABC):
    """Base class — subclasses set `type_name` and implement parse/render."""

    type_name: ClassVar[str]

    @abstractmethod
    def parse(self, value: str, settings: dict[str, Any]) -> Any:
        """Convert user-supplied shorthand into monday's write shape.

        `settings` is the parsed `settings_str` JSON from the column (needed
        by status/dropdown/tags/etc. to resolve labels ↔ ids).
        """

    @abstractmethod
    def render(self, value: Any, text: str | None) -> str:
        """Convert a column_values entry into a human-friendly display."""

    def clear_payload(self) -> Any:
        """Override when the column doesn't clear with `{}` (checkbox, file, ...)."""
        return {}


_REGISTRY: dict[str, ColumnCodec] = {}


def register(codec: ColumnCodec) -> None:
    """Register a codec. Safe to call multiple times with the same codec."""
    _REGISTRY[codec.type_name] = codec


def get_codec(type_name: str) -> ColumnCodec:
    try:
        return _REGISTRY[type_name]
    except KeyError as e:
        raise UnknownColumnTypeError(
            f"no codec registered for column type {type_name!r}; known types: {sorted(_REGISTRY)}"
        ) from e


class LabelAwareCodec(ColumnCodec):
    """Base for codecs whose labels can be server-created on the fly.

    ``create_labels=True`` mirrors the mutation's ``create_labels_if_missing``
    flag and tells the codec to skip its client-side reject of unknown labels
    so the server can create them.
    """

    @abstractmethod
    def parse(self, value: str, settings: dict[str, Any], *, create_labels: bool = False) -> Any:
        ...


def parse_value(
    type_name: str,
    value: str,
    settings: dict[str, Any],
    *,
    create_labels: bool = False,
) -> Any:
    codec = get_codec(type_name)
    if isinstance(codec, LabelAwareCodec):
        return codec.parse(value, settings, create_labels=create_labels)
    return codec.parse(value, settings)


def render_value(type_name: str, value: Any, text: str | None) -> str:
    return get_codec(type_name).render(value, text)


def clear_payload_for(type_name: str) -> Any:
    return get_codec(type_name).clear_payload()


def registered_types() -> list[str]:
    return sorted(_REGISTRY)
