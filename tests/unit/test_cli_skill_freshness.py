"""Tests for `mondo.cli._skill_freshness`.

The freshness check runs from the root callback on every CLI
invocation. It must:
  - warn (stderr) when an installed skill at the global or local path
    has a `version:` older than the bundled package resource;
  - include a copy-pasteable update command in the warning;
  - stay silent when no install exists, when an install lacks a
    `version:` field (treated as hand-customized opt-out), or when
    the installed version is current/newer;
  - in non-TTY runs, rate-limit to one warning per 24h per install
    location via a JSON marker under the cache dir, re-warning
    immediately when the bundled version changes (#75);
  - warn on every invocation in TTY or verbose runs;
  - never raise, even on a corrupt or unwritable marker.

These tests call `warn_if_skill_outdated()` directly and capture
stderr via `capsys`, avoiding the overhead of a full CLI invocation.
"""

from __future__ import annotations

import json
import time
from importlib import resources
from pathlib import Path

import pytest

from mondo.cli import _skill_freshness


def _bundled_version() -> str:
    payload = resources.files("mondo.skill").joinpath("SKILL.md").read_text(encoding="utf-8")
    version = _skill_freshness._parse_skill_version(payload)
    assert version is not None, "test setup: bundled SKILL.md should have a version"
    return version


def _write_skill(path: Path, version: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if version is None:
        path.write_text(
            "---\nname: mondo\ndescription: …\n---\n\n# mondo\n",
            encoding="utf-8",
        )
    else:
        path.write_text(
            f'---\nname: mondo\ndescription: …\nversion: "{version}"\n---\n\n# mondo\n',
            encoding="utf-8",
        )


@pytest.fixture
def isolated_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Point Path.home() and Path.cwd() at fresh tmp dirs.

    Also isolates the rate-limit marker (fresh `MONDO_CACHE_DIR`) and
    pins the non-TTY, non-verbose path so rate-limit behavior is
    deterministic regardless of the surrounding environment.

    Returns (home, cwd) so tests can write fake installed SKILL.mds.
    """
    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("MONDO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("MONDO_VERBOSE", raising=False)
    monkeypatch.setattr("sys.stderr.isatty", lambda: False)
    return home, cwd


def _warning_lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return [line for line in capsys.readouterr().err.splitlines() if line.startswith("warning:")]


def test_warns_when_global_install_is_outdated(
    isolated_paths: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    home, _ = isolated_paths
    _write_skill(home / ".claude" / "skills" / "mondo" / "SKILL.md", "0.0.1")

    _skill_freshness.warn_if_skill_outdated()

    err = capsys.readouterr().err
    assert "warning: mondo skill at ~/.claude/skills/mondo" in err
    assert "v0.0.1" in err
    assert f"v{_bundled_version()}" in err
    assert "mondo skill install --global --yes" in err


def test_warns_when_local_install_is_outdated(
    isolated_paths: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, cwd = isolated_paths
    _write_skill(cwd / ".claude" / "skills" / "mondo" / "SKILL.md", "0.0.1")

    _skill_freshness.warn_if_skill_outdated()

    err = capsys.readouterr().err
    assert "warning: mondo skill at ./.claude/skills/mondo" in err
    assert "v0.0.1" in err
    assert "mondo skill install --yes" in err
    assert "--global" not in err


def test_warns_for_both_locations_independently(
    isolated_paths: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    home, cwd = isolated_paths
    _write_skill(home / ".claude" / "skills" / "mondo" / "SKILL.md", "0.0.1")
    _write_skill(cwd / ".claude" / "skills" / "mondo" / "SKILL.md", "0.0.1")

    _skill_freshness.warn_if_skill_outdated()

    err_lines = [
        line for line in capsys.readouterr().err.splitlines() if line.startswith("warning:")
    ]
    assert len(err_lines) == 2
    assert any("~/.claude/skills/mondo" in line for line in err_lines)
    assert any("./.claude/skills/mondo" in line for line in err_lines)


def test_silent_when_current(
    isolated_paths: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    home, cwd = isolated_paths
    current = _bundled_version()
    _write_skill(home / ".claude" / "skills" / "mondo" / "SKILL.md", current)
    _write_skill(cwd / ".claude" / "skills" / "mondo" / "SKILL.md", current)

    _skill_freshness.warn_if_skill_outdated()

    assert capsys.readouterr().err == ""


def test_silent_when_no_install_present(
    isolated_paths: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _skill_freshness.warn_if_skill_outdated()
    assert capsys.readouterr().err == ""


def test_silent_when_version_field_missing(
    isolated_paths: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    home, _ = isolated_paths
    _write_skill(home / ".claude" / "skills" / "mondo" / "SKILL.md", None)

    _skill_freshness.warn_if_skill_outdated()

    assert capsys.readouterr().err == ""


def test_silent_when_installed_is_newer(
    isolated_paths: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    home, _ = isolated_paths
    _write_skill(home / ".claude" / "skills" / "mondo" / "SKILL.md", "9.9.9")

    _skill_freshness.warn_if_skill_outdated()

    assert capsys.readouterr().err == ""


def test_does_not_raise_on_malformed_yaml(
    isolated_paths: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    home, _ = isolated_paths
    target = home / ".claude" / "skills" / "mondo" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("no frontmatter here at all, just a body\n", encoding="utf-8")

    _skill_freshness.warn_if_skill_outdated()

    assert capsys.readouterr().err == ""


def test_nontty_warns_once_then_suppresses_within_window(
    isolated_paths: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    home, _ = isolated_paths
    _write_skill(home / ".claude" / "skills" / "mondo" / "SKILL.md", "0.0.1")

    _skill_freshness.warn_if_skill_outdated()
    assert len(_warning_lines(capsys)) == 1

    _skill_freshness.warn_if_skill_outdated()
    assert _warning_lines(capsys) == []


def test_nontty_rate_limits_locations_independently(
    isolated_paths: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    home, cwd = isolated_paths
    _write_skill(home / ".claude" / "skills" / "mondo" / "SKILL.md", "0.0.1")

    _skill_freshness.warn_if_skill_outdated()
    assert len(_warning_lines(capsys)) == 1

    # A second outdated location warns even though the first is in-window.
    _write_skill(cwd / ".claude" / "skills" / "mondo" / "SKILL.md", "0.0.1")
    _skill_freshness.warn_if_skill_outdated()
    lines = _warning_lines(capsys)
    assert len(lines) == 1
    assert "./.claude/skills/mondo" in lines[0]


def test_nontty_warns_again_after_window_expires(
    isolated_paths: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    home, _ = isolated_paths
    _write_skill(home / ".claude" / "skills" / "mondo" / "SKILL.md", "0.0.1")

    _skill_freshness.warn_if_skill_outdated()
    assert len(_warning_lines(capsys)) == 1

    # Rewind the recorded timestamp past the 24h window.
    marker_path = _skill_freshness._marker_path()
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    for entry in marker.values():
        entry["warned_at"] -= _skill_freshness._WARN_INTERVAL_SECONDS + 1
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    _skill_freshness.warn_if_skill_outdated()
    assert len(_warning_lines(capsys)) == 1


def test_nontty_new_bundled_version_rewarns_immediately(
    isolated_paths: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, _ = isolated_paths
    _write_skill(home / ".claude" / "skills" / "mondo" / "SKILL.md", "0.0.1")

    _skill_freshness.warn_if_skill_outdated()
    assert len(_warning_lines(capsys)) == 1

    # A new release changes the bundled version: re-warn despite the window.
    monkeypatch.setattr(_skill_freshness, "_bundled_version", lambda: "999.0.0")
    _skill_freshness.warn_if_skill_outdated()
    lines = _warning_lines(capsys)
    assert len(lines) == 1
    assert "v999.0.0" in lines[0]

    # ...but only once for that version.
    _skill_freshness.warn_if_skill_outdated()
    assert _warning_lines(capsys) == []


def test_nontty_future_warned_at_warns_and_rewrites_marker(
    isolated_paths: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    home, _ = isolated_paths
    _write_skill(home / ".claude" / "skills" / "mondo" / "SKILL.md", "0.0.1")

    _skill_freshness.warn_if_skill_outdated()
    assert len(_warning_lines(capsys)) == 1

    # Clock skew: a marker written under a fast clock, then NTP-corrected
    # back, must not suppress forever — default-allow outside the window.
    marker_path = _skill_freshness._marker_path()
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    for entry in marker.values():
        entry["warned_at"] += 365 * 24 * 60 * 60
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    before = time.time()
    _skill_freshness.warn_if_skill_outdated()
    assert len(_warning_lines(capsys)) == 1

    # The marker is rewritten with a sane (current) timestamp.
    rewritten = json.loads(marker_path.read_text(encoding="utf-8"))
    for entry in rewritten.values():
        assert before <= entry["warned_at"] <= time.time()


def test_nontty_nan_warned_at_warns_without_raising(
    isolated_paths: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    home, _ = isolated_paths
    _write_skill(home / ".claude" / "skills" / "mondo" / "SKILL.md", "0.0.1")

    _skill_freshness.warn_if_skill_outdated()
    assert len(_warning_lines(capsys)) == 1

    # json.loads accepts NaN; every comparison against it is False, so a
    # naive elapsed check would suppress forever.
    marker_path = _skill_freshness._marker_path()
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    for entry in marker.values():
        entry["warned_at"] = float("nan")
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    _skill_freshness.warn_if_skill_outdated()
    assert len(_warning_lines(capsys)) == 1


def test_nontty_string_warned_at_warns_without_raising(
    isolated_paths: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    home, _ = isolated_paths
    _write_skill(home / ".claude" / "skills" / "mondo" / "SKILL.md", "0.0.1")

    _skill_freshness.warn_if_skill_outdated()
    assert len(_warning_lines(capsys)) == 1

    marker_path = _skill_freshness._marker_path()
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    for entry in marker.values():
        entry["warned_at"] = "yesterday"
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    _skill_freshness.warn_if_skill_outdated()
    assert len(_warning_lines(capsys)) == 1


def test_nontty_corrupt_marker_warns_and_does_not_raise(
    isolated_paths: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    home, _ = isolated_paths
    _write_skill(home / ".claude" / "skills" / "mondo" / "SKILL.md", "0.0.1")
    marker_path = _skill_freshness._marker_path()
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text("{not json", encoding="utf-8")

    _skill_freshness.warn_if_skill_outdated()

    assert len(_warning_lines(capsys)) == 1


def test_nontty_unwritable_marker_warns_and_does_not_raise(
    isolated_paths: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    home, _ = isolated_paths
    _write_skill(home / ".claude" / "skills" / "mondo" / "SKILL.md", "0.0.1")
    # A directory at the marker path makes both read and write fail.
    _skill_freshness._marker_path().mkdir(parents=True, exist_ok=True)

    _skill_freshness.warn_if_skill_outdated()
    assert len(_warning_lines(capsys)) == 1

    # No marker could be recorded, so the next run warns again.
    _skill_freshness.warn_if_skill_outdated()
    assert len(_warning_lines(capsys)) == 1


def test_verbose_warns_on_every_invocation(
    isolated_paths: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    home, _ = isolated_paths
    _write_skill(home / ".claude" / "skills" / "mondo" / "SKILL.md", "0.0.1")

    _skill_freshness.warn_if_skill_outdated(verbose=True)
    assert len(_warning_lines(capsys)) == 1
    _skill_freshness.warn_if_skill_outdated(verbose=True)
    assert len(_warning_lines(capsys)) == 1


def test_tty_warns_on_every_invocation(
    isolated_paths: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, _ = isolated_paths
    _write_skill(home / ".claude" / "skills" / "mondo" / "SKILL.md", "0.0.1")
    monkeypatch.setattr("sys.stderr.isatty", lambda: True)

    _skill_freshness.warn_if_skill_outdated()
    assert len(_warning_lines(capsys)) == 1
    _skill_freshness.warn_if_skill_outdated()
    assert len(_warning_lines(capsys)) == 1


def test_parse_skill_version_handles_quoted_and_unquoted() -> None:
    parse = _skill_freshness._parse_skill_version
    assert parse('---\nname: x\nversion: "1.2.3"\n---\n') == "1.2.3"
    assert parse("---\nname: x\nversion: 1.2.3\n---\n") == "1.2.3"
    assert parse("---\nname: x\nversion: '1.2.3'\n---\n") == "1.2.3"
    assert parse("---\nname: x\n---\n") is None
    assert parse("no frontmatter\n") is None
