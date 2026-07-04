"""Architectural guard: lower layers must not import the CLI layer.

The intended dependency direction is:

    cli  ->  services / domain  ->  api / cache / output / columns

so ``mondo.cache``, ``mondo.services`` and ``mondo.api`` must never import
``mondo.cli`` (that inverts the arrow and prevents reuse/testing of the lower
layers outside the CLI).

This test currently xfails: ``cache`` and ``services`` still reach up into
``mondo.cli`` (review finding #1). Stage 1 of docs/refactor-plan.md removes
those imports; when it lands this test passes and the ``xfail`` marker below
must be deleted (``strict=True`` turns the unexpected pass into a failure to
force that).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src" / "mondo"
_LOWER_LAYERS = ("cache", "services", "api")


def _cli_imports(package: str) -> list[str]:
    """Return ``file:line`` sites where ``mondo/<package>`` imports mondo.cli."""
    violations: list[str] = []
    root = _SRC / package
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                # Resolve relative imports (level>0) to their absolute module.
                if node.level:
                    base = ".".join(("mondo", package))
                    mod = f"{base}.{mod}" if mod else base
                if mod == "mondo.cli" or mod.startswith("mondo.cli."):
                    violations.append(f"{path.relative_to(_SRC.parent.parent)}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "mondo.cli" or alias.name.startswith("mondo.cli."):
                        violations.append(
                            f"{path.relative_to(_SRC.parent.parent)}:{node.lineno}"
                        )
    return sorted(violations)


@pytest.mark.xfail(
    strict=True,
    reason="Stage 1 (docs/refactor-plan.md) removes cli imports from cache/services; "
    "delete this marker when it lands.",
)
def test_lower_layers_do_not_import_cli() -> None:
    violations: list[str] = []
    for package in _LOWER_LAYERS:
        violations.extend(_cli_imports(package))
    assert not violations, "lower-layer modules import mondo.cli:\n" + "\n".join(violations)
