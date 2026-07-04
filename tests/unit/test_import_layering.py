"""Architectural guard: lower layers must not import the CLI layer.

The intended dependency direction is:

    cli  ->  services / domain  ->  api / cache / output / columns

so ``mondo.cache``, ``mondo.services`` and ``mondo.api`` must never import
``mondo.cli`` (that inverts the arrow and prevents reuse/testing of the lower
layers outside the CLI).

Stage 1 of docs/refactor-plan.md moved the CLI-clean helpers into
``mondo.domain`` so ``cache`` and ``services`` no longer reach up into
``mondo.cli``. This test guards that direction stays intact.
"""

from __future__ import annotations

import ast
from pathlib import Path

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


def test_lower_layers_do_not_import_cli() -> None:
    violations: list[str] = []
    for package in _LOWER_LAYERS:
        violations.extend(_cli_imports(package))
    assert not violations, "lower-layer modules import mondo.cli:\n" + "\n".join(violations)
