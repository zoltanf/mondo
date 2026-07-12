"""Sanitizers for untrusted, API-controlled strings.

monday.com data (item names, column text, mirror/formula display_value)
is controlled by anyone with board access. Two output surfaces guard it:

- CSV/TSV export opened in Excel / Google Sheets / LibreOffice: cells
  starting with ``= + - @`` (or tab/CR) are evaluated as formulas (CSV
  injection). ``guard_formula`` prefixes them with a single quote — the
  spreadsheet convention for "treat as text" — and
  ``strip_formula_guard`` removes exactly that prefix on import, so the
  ``mondo export`` → ``mondo import`` round-trip is lossless.

  Plain-number exemption: a value that is only an optional ``+``/``-``
  sign followed by digit groups joined by single ``.``/``,`` separators
  (e.g. ``-1250``, ``+491234``, ``1.234,50``) can't execute anything in
  a spreadsheet, so it is left unguarded — otherwise every negative or
  plus-leading number would become text and silently break ``=SUM()``
  and numeric parsing in pandas/DB loads. Anything with an operator or
  letter after the sign (``-2+3``, ``-1e5``, ``+cmd|...``) or with
  adjacent/trailing separators (``-1,,2``, ``+5.``) is still guarded —
  only digit groups joined by single separators qualify, and digits,
  dots, and commas alone cannot form an executable formula. Leading
  U+FEFF chars are looked past when classifying: at file start the BOM
  is eaten as the encoding signature, so ``\\ufeff=x`` must be guarded
  like ``=x``.

  Corner cases (both accepted for the simplicity of the conditional
  guard): a value that itself starts with ``'=`` loses its apostrophe on
  re-import; and a hand-authored CSV whose cell is a literal ``'``
  followed by a formula lead (``'=x``) is treated as a guard and loses
  the apostrophe on import (``mondo export`` never emits such a cell —
  it only guards non-``'``-leading values — so the round-trip it
  produces is unaffected).
- Terminal display (table output): raw C0/C1 control bytes (ESC, CSI,
  OSC, ...) in a value can inject escape sequences into the user's
  terminal. ``strip_terminal_controls`` drops them, keeping newline
  and tab.
"""

from __future__ import annotations

import re
from typing import Any, overload

# Leading characters Excel & friends interpret as the start of a formula.
_FORMULA_LEADS = ("=", "+", "-", "@", "\t", "\r")

# U+FEFF (BOM / zero-width no-break space): when a cell opens the file, the
# BOM bytes are eaten as the encoding signature and the cell then starts
# with the char after it — so look past BOMs when deciding to guard.
_BOM = "\ufeff"

# Plain numbers (optional sign, digit groups joined by single ./ ,
# separators — ``-1250``, ``+49123``, ``1.234,50``) can't execute in a
# spreadsheet, so they stay unguarded — see the module docstring.
_PLAIN_NUMBER = re.compile(r"^[+-]?\d+([.,]\d+)*$")

# C0 controls (minus \t and \n), DEL, and C1 controls.
_CONTROL_CHARS: dict[int, None] = {
    c: None for c in (*range(0x00, 0x20), 0x7F, *range(0x80, 0xA0)) if c not in (0x09, 0x0A)
}


@overload
def guard_formula(value: str) -> str: ...
@overload
def guard_formula(value: Any) -> Any: ...
def guard_formula(value: Any) -> Any:
    """Prefix formula-looking strings with ``'`` (spreadsheet text guard).

    Plain numbers (``-1250``, ``+491234``) are exempt so exports stay
    numeric; see the module docstring.
    """
    if not isinstance(value, str):
        return value
    lead = value.lstrip(_BOM)
    if lead.startswith(_FORMULA_LEADS) and not _PLAIN_NUMBER.match(lead):
        return "'" + value
    return value


def strip_formula_guard(value: str) -> str:
    """Undo ``guard_formula``: drop a ``'`` that guards a formula lead."""
    if value.startswith("'") and value[1:].lstrip(_BOM).startswith(_FORMULA_LEADS):
        return value[1:]
    return value


def strip_terminal_controls(text: str) -> str:
    """Remove C0/C1 control characters (except newline and tab)."""
    return text.translate(_CONTROL_CHARS)
