"""Unit tests for mondo.util.sanitize (CSV formula guard + control stripping)."""

from __future__ import annotations

import pytest

from mondo.util.sanitize import guard_formula, strip_formula_guard, strip_terminal_controls


class TestGuardFormula:
    @pytest.mark.parametrize(
        "raw",
        # Formula leads that are NOT plain numbers stay guarded, including
        # sign-then-operator/exponent/text and pipe-command payloads.
        ["=SUM(A1:A9)", "@cmd", "\tx", "\rx", "-2+3", "-1e5", "+cmd|calc", "=-5", "+"],
    )
    def test_guards_formula_leads(self, raw: str) -> None:
        assert guard_formula(raw) == "'" + raw

    @pytest.mark.parametrize("raw", ["hello", "", "a=b", "'=already quoted"])
    def test_leaves_safe_strings(self, raw: str) -> None:
        assert guard_formula(raw) == raw

    @pytest.mark.parametrize(
        "raw",
        # Plain numbers (optional sign, then only digits/dots/commas) can't
        # execute in a spreadsheet, so they must round-trip unguarded —
        # otherwise =SUM()/pandas silently break on negatives.
        ["-5", "+491234", "-1250", "1.234,50", "-0.5", "+1"],
    )
    def test_leaves_plain_numbers(self, raw: str) -> None:
        assert guard_formula(raw) == raw

    @pytest.mark.parametrize(
        "raw",
        # Adjacent/trailing separators are not plain numbers — guarded.
        ["-1,,2", "+5.", "-1.", "+.5"],
    )
    def test_guards_malformed_numbers(self, raw: str) -> None:
        assert guard_formula(raw) == "'" + raw

    def test_guards_past_leading_bom(self) -> None:
        # At file start the BOM is eaten as the encoding signature, leaving
        # the cell to start with "=" — so BOM-prefixed leads must be guarded.
        assert guard_formula("\ufeff=SUM(A1)") == "'\ufeff=SUM(A1)"
        assert guard_formula("\ufeff-1250") == "\ufeff-1250"  # still a plain number

    def test_leaves_non_strings(self) -> None:
        assert guard_formula(None) is None
        assert guard_formula(5) == 5


class TestStripFormulaGuard:
    @pytest.mark.parametrize(
        "raw",
        ["=SUM(A1:A9)", "+491234", "-5", "@cmd", "\tx", "\rx", "hello", "", "\ufeff=x"],
    )
    def test_round_trips_guard(self, raw: str) -> None:
        assert strip_formula_guard(guard_formula(raw)) == raw

    def test_leaves_plain_apostrophe_strings(self) -> None:
        # Only the guard pattern (' + formula lead) is stripped.
        assert strip_formula_guard("'hello'") == "'hello'"
        assert strip_formula_guard("=x") == "=x"


class TestStripTerminalControls:
    def test_strips_ansi_escapes(self) -> None:
        assert strip_terminal_controls("\x1b[31mred\x1b[0m") == "[31mred[0m"

    def test_strips_c1_del_and_bell(self) -> None:
        assert strip_terminal_controls("a\x9bJ\x7f\x07b") == "aJb"

    def test_keeps_newline_and_tab(self) -> None:
        assert strip_terminal_controls("a\nb\tc") == "a\nb\tc"
