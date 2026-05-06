"""Tests for the `mondo skill` command."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mondo.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")


def test_install_writes_expected_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cwd = tmp_path / "repo"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    result = runner.invoke(app, ["skill", "install"], catch_exceptions=False)
    assert result.exit_code == 0, result.output

    target = cwd / ".claude" / "skills" / "mondo" / "SKILL.md"
    assert target.exists()

    expected = resources.files("mondo.skill").joinpath("SKILL.md").read_text(encoding="utf-8")
    assert target.read_text(encoding="utf-8") == expected


def test_install_global_uses_home_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

    result = runner.invoke(app, ["skill", "install", "--global"], catch_exceptions=False)
    assert result.exit_code == 0, result.output

    target = home / ".claude" / "skills" / "mondo" / "SKILL.md"
    assert target.exists()


def test_install_refuses_overwrite_without_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "repo"
    target = cwd / ".claude" / "skills" / "mondo" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("old", encoding="utf-8")
    monkeypatch.chdir(cwd)

    result = runner.invoke(app, ["skill", "install"], input="n\n", catch_exceptions=False)
    assert result.exit_code == 1
    assert "aborted" in result.output.lower()
    assert target.read_text(encoding="utf-8") == "old"


def test_install_overwrites_with_yes_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cwd = tmp_path / "repo"
    target = cwd / ".claude" / "skills" / "mondo" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("old", encoding="utf-8")
    monkeypatch.chdir(cwd)

    result = runner.invoke(app, ["--yes", "skill", "install"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert target.read_text(encoding="utf-8") != "old"


def test_skill_resource_is_present() -> None:
    payload = resources.files("mondo.skill").joinpath("SKILL.md").read_text(encoding="utf-8")
    assert "name: mondo" in payload


def test_skill_resource_has_version_field() -> None:
    """The bundled SKILL.md must carry a `version:` field so the freshness
    check at startup has something to compare installed copies against."""
    payload = resources.files("mondo.skill").joinpath("SKILL.md").read_text(encoding="utf-8")
    from mondo.cli._skill_freshness import _parse_skill_version

    version = _parse_skill_version(payload)
    assert version is not None, "source SKILL.md is missing `version:` in frontmatter"
    assert version.count(".") >= 1, f"version {version!r} doesn't look semver-shaped"
