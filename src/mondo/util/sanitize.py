"""Sanitizers for untrusted, API-controlled strings.

monday.com data (item names, column text, mirror/formula display_value)
is controlled by anyone with board access. Two output surfaces guard it:

- CSV/TSV export opened in Excel / Google Sheets / LibreOffice: cells
  starting with ``= + - @`` (or tab/CR) are evaluated as formulas (CSV
  injection). ``guard_formula`` prefixes them with a single quote — the
  spreadsheet convention for "treat as text" — and
  ``strip_formula_guard`` removes exactly that prefix on import, so the
  ``mondo export`` → ``mondo import`` round-trip is lossless. (Corner
  case: a value that itself starts with ``'=`` loses its apostrophe on
  re-import; accepted for the simplicity of the conditional guard.)
- Terminal display (table output): raw C0/C1 control bytes (ESC, CSI,
  OSC, ...) in a value can inject escape sequences into the user's
  terminal. ``strip_terminal_controls`` drops them, keeping newline
  and tab.
"""

from __future__ import annotations

from typing import Any

# Leading characters Excel & friends interpret as the start of a formula.
_FORMULA_LEADS = ("=", "+", "-", "@", "\t", "\r")

# C0 controls (minus \t and \n), DEL, and C1 controls.
_CONTROL_CHARS: dict[int, None] = {
    c: None for c in (*range(0x00, 0x20), 0x7F, *range(0x80, 0xA0)) if c not in (0x09, 0x0A)
}


def guard_formula(value: Any) -> Any:
    """Prefix formula-looking strings with ``'`` (spreadsheet text guard)."""
    if isinstance(value, str) and value.startswith(_FORMULA_LEADS):
        return "'" + value
    return value


def strip_formula_guard(value: str) -> str:
    """Undo ``guard_formula``: drop a ``'`` that guards a formula lead."""
    if value.startswith("'") and value[1:].startswith(_FORMULA_LEADS):
        return value[1:]
    return value


def strip_terminal_controls(text: str) -> str:
    """Remove C0/C1 control characters (except newline and tab)."""
    return text.translate(_CONTROL_CHARS)
