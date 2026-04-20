"""Unit tests for the URL → ID parser used by `board/doc/item/subitem get`."""

from __future__ import annotations

import pytest
import typer

from mondo.cli._url import (
    MondayIdParam,
    board_url,
    item_url,
    parse_monday_id,
    warn_cross_type,
)


class TestParseMondayIdBoardKind:
    @pytest.mark.parametrize(
        "s,expected",
        [
            ("1234567890", 1234567890),
            ("  42  ", 42),
            ("https://marktguru.monday.com/boards/1234567890", 1234567890),
            ("https://marktguru.monday.com/boards/1234567890/", 1234567890),
            ("https://marktguru.monday.com/boards/1234567890/views/456", 1234567890),
            ("https://marktguru.monday.com/boards/1234567890?foo=bar", 1234567890),
            ("https://marktguru.monday.com/boards/1234567890#section", 1234567890),
            ("https://marktguru.monday.com/docs/77", 77),
            ("http://marktguru.monday.com/boards/1", 1),
            ("marktguru.monday.com/boards/99", 99),
            ("https://monday.com/boards/5", 5),  # no tenant subdomain
            # A /pulses/ URL still yields the BOARD id under kind="board".
            ("https://marktguru.monday.com/boards/42/pulses/987", 42),
        ],
    )
    def test_extracts(self, s: str, expected: int) -> None:
        assert parse_monday_id(s, kind="board") == expected

    @pytest.mark.parametrize(
        "s",
        [
            "",
            "not-a-number",
            "https://example.com/boards/1",
            "https://monday.com/dashboards/1",
            "boards/1",
            "12abc",
        ],
    )
    def test_rejects(self, s: str) -> None:
        with pytest.raises(typer.BadParameter):
            parse_monday_id(s, kind="board")


class TestParseMondayIdItemKind:
    @pytest.mark.parametrize(
        "s,expected",
        [
            ("987", 987),
            ("  987  ", 987),
            ("https://marktguru.monday.com/boards/42/pulses/987", 987),
            ("https://marktguru.monday.com/boards/42/pulses/987/", 987),
            ("https://marktguru.monday.com/boards/42/pulses/987?foo=bar", 987),
            ("https://marktguru.monday.com/boards/42/pulses/987#x", 987),
            ("http://marktguru.monday.com/boards/1/pulses/2", 2),
            ("marktguru.monday.com/boards/1/pulses/2", 2),
        ],
    )
    def test_extracts(self, s: str, expected: int) -> None:
        assert parse_monday_id(s, kind="item") == expected

    def test_board_url_rejected_with_hint(self) -> None:
        with pytest.raises(typer.BadParameter, match=r"mondo board get"):
            parse_monday_id("https://marktguru.monday.com/boards/42", kind="item")

    @pytest.mark.parametrize(
        "s",
        ["", "not-a-number", "https://example.com/boards/1/pulses/2"],
    )
    def test_rejects(self, s: str) -> None:
        with pytest.raises(typer.BadParameter):
            parse_monday_id(s, kind="item")


class TestMondayIdParam:
    def test_reports_integer_type_name(self) -> None:
        """Spec-compat invariant — `--dump-spec` reads `.name` verbatim."""
        assert MondayIdParam().name == "integer"
        assert MondayIdParam(kind="item").name == "integer"

    def test_converts_int_string(self) -> None:
        assert MondayIdParam().convert("42", None, None) == 42

    def test_converts_url_board_kind(self) -> None:
        url = "https://marktguru.monday.com/boards/42/views/1"
        assert MondayIdParam().convert(url, None, None) == 42

    def test_converts_url_item_kind(self) -> None:
        url = "https://marktguru.monday.com/boards/42/pulses/987"
        assert MondayIdParam(kind="item").convert(url, None, None) == 987

    def test_passes_through_int(self) -> None:
        assert MondayIdParam().convert(42, None, None) == 42


class TestWarnCrossType:
    def test_board_expected_doc_observed_warns(self, capsys: pytest.CaptureFixture[str]) -> None:
        warn_cross_type({"type": "document"}, expected="board", id_=42)
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "workdoc" in captured.err
        assert "mondo doc get --object-id 42" in captured.err

    def test_board_expected_board_observed_silent(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        warn_cross_type({"type": "board"}, expected="board", id_=42)
        assert capsys.readouterr().err == ""

    def test_missing_type_treated_as_board(self, capsys: pytest.CaptureFixture[str]) -> None:
        warn_cross_type({}, expected="board", id_=42)
        assert capsys.readouterr().err == ""

    def test_doc_expected_board_observed_warns(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        warn_cross_type({"type": "board"}, expected="doc", id_=99)
        captured = capsys.readouterr()
        assert "regular board" in captured.err
        assert "mondo board get 99" in captured.err

    def test_doc_expected_doc_observed_silent(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        warn_cross_type({"type": "document"}, expected="doc", id_=99)
        assert capsys.readouterr().err == ""


class TestUrlSynthesis:
    def test_board_url(self) -> None:
        assert board_url("marktguru", 42) == "https://marktguru.monday.com/boards/42"

    def test_item_url(self) -> None:
        assert (
            item_url("marktguru", 42, 987)
            == "https://marktguru.monday.com/boards/42/pulses/987"
        )
