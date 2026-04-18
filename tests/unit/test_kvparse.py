"""Tests for mondo.util.kvparse — --column K=V parsing."""

from __future__ import annotations

import pytest

from mondo.util.kvparse import parse_column_kv, parse_columns


class TestParseColumnKv:
    def test_bare_string(self) -> None:
        assert parse_column_kv("text=Hello") == ("text", "Hello")

    def test_json_object(self) -> None:
        assert parse_column_kv('status={"label":"Done"}') == ("status", {"label": "Done"})

    def test_json_number(self) -> None:
        assert parse_column_kv("price=42.5") == ("price", 42.5)

    def test_json_bool(self) -> None:
        assert parse_column_kv("done=true") == ("done", True)

    def test_empty_value(self) -> None:
        assert parse_column_kv("text=") == ("text", "")

    def test_value_contains_equals(self) -> None:
        # Only the FIRST `=` splits key from value; rest is part of the value.
        k, v = parse_column_kv("link=https://x.com/?a=1")
        assert k == "link"
        assert v == "https://x.com/?a=1"

    def test_missing_equals_raises(self) -> None:
        with pytest.raises(ValueError, match="KEY=VALUE"):
            parse_column_kv("no-equals-here")

    def test_empty_key_raises(self) -> None:
        with pytest.raises(ValueError, match="empty column id"):
            parse_column_kv("=value")


class TestParseColumns:
    def test_multiple(self) -> None:
        result = parse_columns(["text=Hello", 'status={"index":1}'])
        assert result == {"text": "Hello", "status": {"index": 1}}

    def test_later_overrides_earlier(self) -> None:
        result = parse_columns(["text=first", "text=second"])
        assert result == {"text": "second"}

    def test_empty_list(self) -> None:
        assert parse_columns([]) == {}
