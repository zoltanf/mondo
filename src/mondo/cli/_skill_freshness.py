"""Detect outdated `mondo` skill installs and warn the user.

Runs from the root callback on every CLI invocation. Compares the
`version:` field in the bundled package resource (`mondo.skill/SKILL.md`)
against any installed copies under `~/.claude/skills/mondo/SKILL.md` and
`./.claude/skills/mondo/SKILL.md`. Emits one stderr line per outdated
location, including a copy-pasteable update command.

The warning is exempt from the benign-notices gate (#25): agent (non-TTY)
runs are exactly the audience consuming the skill, so they must see it
too. To avoid spamming pipelines, non-TTY runs are instead rate-limited to
one warning per 24h per install location, tracked in a JSON marker under
the mondo cache dir (`skill_freshness_warned.json`). A new bundled version
re-warns immediately, ignoring the window. TTY or `--verbose` /
`MONDO_VERBOSE=1` runs warn on every invocation.

Hand-customized installs (no `version:` field) are silently ignored.
Every IO/parse error is swallowed (including marker read/write) — this
must never break the CLI. Marker updates are unlocked read-modify-write:
two concurrent runs may each warn once, which is accepted as best-effort.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import tempfile
import time
from importlib import resources
from pathlib import Path

_VERSION_RE = re.compile(r'^version:\s*["\']?([^"\'\n]+?)["\']?\s*$', re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_WARN_INTERVAL_SECONDS = 24 * 60 * 60


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
    except OSError, ValueError:
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


def _marker_path() -> Path:
    from mondo.cache.paths import cache_dir

    return cache_dir() / "skill_freshness_warned.json"


def _read_marker() -> dict[str, object]:
    try:
        data = json.loads(_marker_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_marker(marker: dict[str, object]) -> None:
    """Atomically replace the marker file (temp file + os.replace).

    A plain write could leave torn JSON if the process dies mid-write,
    costing a parse failure on every subsequent run.
    """
    tmp: str | None = None
    try:
        path = _marker_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(marker))
        os.replace(tmp, path)
    except Exception:
        if tmp is not None:
            with contextlib.suppress(OSError):
                os.remove(tmp)


def _rate_limit_allows(entry: object, bundled: str) -> bool:
    """True when the non-TTY rate limit allows warning for this location."""
    if not isinstance(entry, dict):
        return True
    if entry.get("bundled_version") != bundled:
        return True  # new release: re-warn once, ignoring the window
    warned_at = entry.get("warned_at")
    if not isinstance(warned_at, (int, float)):
        return True
    # Default-allow: suppress only inside a sane elapsed window. A future
    # warned_at (clock skew) or NaN makes the comparison False → warn and
    # rewrite the marker with a fresh timestamp.
    return not (0 <= time.time() - warned_at < _WARN_INTERVAL_SECONDS)


def warn_if_skill_outdated(*, verbose: bool = False) -> None:
    """Emit one stderr line per outdated install location, if any.

    Silent when no install exists, when an install lacks a `version:`
    field (treated as an opt-out via hand-customization), when the
    bundled skill itself has no version, or on any IO/parse error.
    TTY or verbose runs warn on every invocation; non-TTY runs are
    rate-limited to once per 24h per location via the cache marker.
    """
    try:
        bundled = _bundled_version()
        if bundled is None:
            return
        from mondo.cli._notices import benign_notices_enabled

        rate_limited = not benign_notices_enabled(verbose=verbose)
        marker = _read_marker() if rate_limited else {}
        marker_dirty = False
        for path, display, fix_cmd in _candidate_locations():
            if not path.is_file():
                continue
            installed = _installed_version(path)
            if installed is None:
                continue
            if not _is_older(installed, bundled):
                continue
            if rate_limited:
                if not _rate_limit_allows(marker.get(str(path)), bundled):
                    continue
                marker[str(path)] = {"bundled_version": bundled, "warned_at": time.time()}
                marker_dirty = True
            print(
                f"warning: mondo skill at {display} is v{installed} "
                f"(current: v{bundled}). Update: {fix_cmd}",
                file=sys.stderr,
            )
        if marker_dirty:
            _write_marker(marker)
    except Exception:
        return
