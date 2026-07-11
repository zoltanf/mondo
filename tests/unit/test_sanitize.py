"""Unit tests for mondo.util.sanitize (CSV formula guard + control stripping)."""

from __future__ import annotations

import pytest

from mondo.util.sanitize import guard_formula, strip_formula_guard, strip_terminal_controls


class TestGuardFormula:
    @pytest.mark.parametrize(
        "raw",
        ["=SUM(A1:A9)", "+491234", "-5", "@cmd", "\tx", "\rx"],
    )
    def test_guards_formula_leads(self, raw: str) -> None:
        assert guard_formula(raw) == "'" + raw

    @pytest.mark.parametrize("raw", ["hello", "", "a=b", "'=already quoted"])
    def test_leaves_safe_strings(self, raw: str) -> None:
        assert guard_formula(raw) == raw

    def test_leaves_non_strings(self) -> None:
        assert guard_formula(None) is None
        assert guard_formula(5) == 5


class TestStripFormulaGuard:
    @pytest.mark.parametrize(
        "raw",
        ["=SUM(A1:A9)", "+491234", "-5", "@cmd", "\tx", "\rx", "hello", ""],
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
