"""Contract test: command modules must not hand-roll the red error path.

Every command-local error should exit through the shared helpers in
``mondo.cli._exec`` (``usage_error_or_exit`` / ``handle_mondo_error_or_exit``)
so error rendering — and the machine-mode JSON envelope — stays uniform.

This guards against the regression of scattering
``typer.secho(..., fg=typer.colors.RED, err=True)`` immediately followed by
``raise typer.Exit(...)`` back into individual command modules. Intentional
YELLOW warnings (e.g. the "refusing to delete without --hard" guards) and the
canonical emitter in ``_exec.py`` are deliberately out of scope.
"""

from __future__ import annotations

import ast
from itertools import pairwise
from pathlib import Path

CLI_DIR = Path(__file__).resolve().parents[2] / "src" / "mondo" / "cli"


def _is_red_err_print(node: ast.stmt) -> bool:
    """True iff ``node`` is a ``typer.secho/echo(..., fg=...RED, err=True)``."""
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return False
    func = node.value.func
    if not (isinstance(func, ast.Attribute) and func.attr in {"secho", "echo"}):
        return False
    has_err = any(
        kw.arg == "err" and isinstance(kw.value, ast.Constant) and kw.value.value is True
        for kw in node.value.keywords
    )
    is_red = any(
        kw.arg == "fg" and ast.unparse(kw.value).split(".")[-1] == "RED"
        for kw in node.value.keywords
    )
    return has_err and is_red


def _is_typer_exit(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and isinstance(node.exc.func, ast.Attribute)
        and node.exc.func.attr == "Exit"
    )


def _scan(stmts: list[ast.stmt], path: Path, hits: list[str]) -> None:
    for first, second in pairwise(stmts):
        if _is_red_err_print(first) and _is_typer_exit(second):
            hits.append(f"{path.name}:{first.lineno}")
    for node in stmts:
        for field in ("body", "orelse", "finalbody"):
            child = getattr(node, field, None)
            if isinstance(child, list) and child and isinstance(child[0], ast.stmt):
                _scan(child, path, hits)
        for handler in getattr(node, "handlers", []) or []:
            _scan(handler.body, path, hits)


def test_no_raw_red_error_exit_pattern_outside_exec() -> None:
    hits: list[str] = []
    for path in sorted(CLI_DIR.glob("*.py")):
        if path.name == "_exec.py":  # canonical home of the red error path
            continue
        _scan(ast.parse(path.read_text()).body, path, hits)
    assert not hits, (
        "Found hand-rolled red-error + typer.Exit pairs; route these through "
        "mondo.cli._exec (usage_error_or_exit / handle_mondo_error_or_exit):\n  "
        + "\n  ".join(hits)
    )
