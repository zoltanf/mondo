"""Detect outdated `mondo` skill installs and warn the user.

Runs from the root callback on every CLI invocation. Compares the
`version:` field in the bundled package resource (`mondo.skill/SKILL.md`)
against any installed copies under `~/.claude/skills/mondo/SKILL.md` and
`./.claude/skills/mondo/SKILL.md`. Emits one stderr line per outdated
location, including a copy-pasteable update command.

Hand-customized installs (no `version:` field) are silently ignored.
Every IO/parse error is swallowed — this must never break the CLI.
"""

from __future__ import annotations

import re
import sys
from importlib import resources
from pathlib import Path

_VERSION_RE = re.compile(r'^version:\s*["\']?([^"\'\n]+?)["\']?\s*$', re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def _parse_skill_version(text: str) -> str | None:
    """Extract `version:` from the leading YAML frontmatter, if any."""
    fm = _FRONTMATTER_RE.match(text)
    if not fm:
        return None
    match = _VERSION_RE.search(fm.group(1))
    return match.group(1).strip() if match else None


def _is_older(installed: str, bundled: str) -> bool:
    """Return True if `installed` is strictly older than `bundled`."""
    try:
        from packaging.version import Version

        return Version(installed) < Version(bundled)
    except Exception:
        try:
            inst = tuple(int(p) for p in installed.split("."))
            bund = tuple(int(p) for p in bundled.split("."))
            return inst < bund
        except Exception:
            return False


def _bundled_version() -> str | None:
    try:
        text = resources.files("mondo.skill").joinpath("SKILL.md").read_text(encoding="utf-8")
    except Exception:
        return None
    return _parse_skill_version(text)


def _installed_version(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    return _parse_skill_version(text)


def _candidate_locations() -> list[tuple[Path, str, str]]:
    """Return [(skill_md_path, display_path, fix_command), ...].

    `display_path` uses `~` for the global location for friendlier output.
    """
    return [
        (
            Path.home() / ".claude" / "skills" / "mondo" / "SKILL.md",
            "~/.claude/skills/mondo",
            "mondo skill install --global --yes",
        ),
        (
            Path.cwd() / ".claude" / "skills" / "mondo" / "SKILL.md",
            "./.claude/skills/mondo",
            "mondo skill install --yes",
        ),
    ]


def warn_if_skill_outdated() -> None:
    """Emit one stderr line per outdated install location, if any.

    Silent when no install exists, when an install lacks a `version:`
    field (treated as an opt-out via hand-customization), when the
    bundled skill itself has no version, or on any IO/parse error.
    """
    try:
        bundled = _bundled_version()
        if bundled is None:
            return
        for path, display, fix_cmd in _candidate_locations():
            if not path.is_file():
                continue
            installed = _installed_version(path)
            if installed is None:
                continue
            if _is_older(installed, bundled):
                print(
                    f"warning: mondo skill at {display} is v{installed} "
                    f"(current: v{bundled}). Update: {fix_cmd}",
                    file=sys.stderr,
                )
    except Exception:
        return
