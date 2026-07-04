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
import importlib.util
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "mondo"
_LOWER_LAYERS = ("cache", "services", "api")


def _targets_cli(mod: str) -> bool:
    return mod == "mondo.cli" or mod.startswith("mondo.cli.")


def _package_of(path: Path) -> str:
    """The dotted ``__package__`` a module at `path` would have at runtime."""
    parts = path.relative_to(_SRC.parent).with_suffix("").parts  # ("mondo", "services", "foo")
    # A module's package is its containing dir; a package's own __init__ maps to
    # that dir too — either way it's everything but the trailing component.
    return ".".join(parts[:-1])


def _cli_imports(package: str) -> list[str]:
    """Return ``file:line`` sites where ``mondo/<package>`` imports mondo.cli."""
    violations: list[str] = []
    root = _SRC / package
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(_SRC.parent.parent)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if node.level:
                    # Resolve the relative import the way Python would at import
                    # time, honouring node.level (`from ..cli import x` must map
                    # to mondo.cli, not mondo.<package>.cli).
                    name = "." * node.level + mod
                    try:
                        mod = importlib.util.resolve_name(name, _package_of(path))
                    except ImportError, ValueError:
                        continue
                if _targets_cli(mod):
                    violations.append(f"{rel}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if _targets_cli(alias.name):
                        violations.append(f"{rel}:{node.lineno}")
    return sorted(violations)


def test_lower_layers_do_not_import_cli() -> None:
    violations: list[str] = []
    for package in _LOWER_LAYERS:
        violations.extend(_cli_imports(package))
    assert not violations, "lower-layer modules import mondo.cli:\n" + "\n".join(violations)


def test_package_of_matches_runtime_package() -> None:
    assert _package_of(_SRC / "services" / "docs.py") == "mondo.services"
    assert _package_of(_SRC / "services" / "__init__.py") == "mondo.services"
    assert _package_of(_SRC / "cache" / "registry.py") == "mondo.cache"


def test_relative_cli_import_would_be_detected() -> None:
    """Regression guard: a level-aware relative import out of a lower layer
    (`from ..cli import x` in mondo.services.foo) must resolve to mondo.cli so
    the scanner flags it — not to mondo.services.cli (the earlier bug)."""
    resolved = importlib.util.resolve_name("..cli", _package_of(_SRC / "services" / "foo.py"))
    assert resolved == "mondo.cli"
    assert _targets_cli(resolved)
    # A genuine intra-package relative import must NOT be mistaken for a violation.
    assert not _targets_cli(
        importlib.util.resolve_name(".boards", _package_of(_SRC / "services" / "foo.py"))
    )
