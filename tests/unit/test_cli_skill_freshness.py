"""Tests for `mondo.cli._skill_freshness`.

The freshness check runs from the root callback on every CLI
invocation. It must:
  - warn (stderr) when an installed skill at the global or local path
    has a `version:` older than the bundled package resource;
  - include a copy-pasteable update command in the warning;
  - stay silent when no install exists, when an install lacks a
    `version:` field (treated as hand-customized opt-out), or when
    the installed version is current/newer;
  - never raise.

These tests call `warn_if_skill_outdated()` directly and capture
stderr via `capsys`, avoiding the overhead of a full CLI invocation.
"""

from __future__ import annotations

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

    Returns (home, cwd) so tests can write fake installed SKILL.mds.
    """
    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(cwd)
    return home, cwd


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

    err_lines = [line for line in capsys.readouterr().err.splitlines() if line.startswith("warning:")]
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


def test_parse_skill_version_handles_quoted_and_unquoted() -> None:
    parse = _skill_freshness._parse_skill_version
    assert parse('---\nname: x\nversion: "1.2.3"\n---\n') == "1.2.3"
    assert parse("---\nname: x\nversion: 1.2.3\n---\n") == "1.2.3"
    assert parse("---\nname: x\nversion: '1.2.3'\n---\n") == "1.2.3"
    assert parse("---\nname: x\n---\n") is None
    assert parse("no frontmatter\n") is None
