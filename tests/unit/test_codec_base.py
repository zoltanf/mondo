"""Tests for mondo.columns base — codec protocol, registry, defaults."""

from __future__ import annotations

import pytest

from mondo.columns.base import (
    ColumnCodec,
    UnknownColumnTypeError,
    clear_payload_for,
    get_codec,
    parse_value,
    register,
    render_value,
)


class _DummyCodec(ColumnCodec):
    type_name = "dummy"

    def parse(self, value: str, settings: dict) -> object:
        return {"dummy_parsed": value}

    def render(self, value: object | None, text: str | None) -> str:
        return f"dummy<{text}>"


def test_register_and_get() -> None:
    register(_DummyCodec())
    assert isinstance(get_codec("dummy"), _DummyCodec)


def test_get_codec_unknown_raises() -> None:
    with pytest.raises(UnknownColumnTypeError, match="no-such-type"):
        get_codec("no-such-type")


def test_parse_value_dispatches() -> None:
    register(_DummyCodec())
    assert parse_value("dummy", "hello", {}) == {"dummy_parsed": "hello"}


def test_render_value_dispatches() -> None:
    register(_DummyCodec())
    assert render_value("dummy", {"x": 1}, "display") == "dummy<display>"


def test_default_clear_payload_is_empty_dict() -> None:
    """Most JSON columns clear with `{}` per monday-api.md §11.6."""
    register(_DummyCodec())
    assert clear_payload_for("dummy") == {}


def test_clear_payload_unknown_raises() -> None:
    with pytest.raises(UnknownColumnTypeError):
        clear_payload_for("never-registered")


class _OverrideClearCodec(ColumnCodec):
    type_name = "custom_clear"

    def parse(self, value: str, settings: dict) -> object:
        return value

    def render(self, value: object | None, text: str | None) -> str:
        return text or ""

    def clear_payload(self) -> object:
        return None


def test_codec_can_override_clear_payload() -> None:
    register(_OverrideClearCodec())
    assert clear_payload_for("custom_clear") is None


def test_render_handles_none() -> None:
    register(_DummyCodec())
    assert render_value("dummy", None, None) == "dummy<None>"
