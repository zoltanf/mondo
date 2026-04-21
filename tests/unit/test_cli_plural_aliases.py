"""Top-level plural command aliases (`boards`, `docs`, …)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mondo.cli.main import _PLURAL_ALIASES, app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")
    monkeypatch.setenv("MONDO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MONDO_CACHE_ENABLED", "false")


def test_boards_alias_executes_board_list_dry_run() -> None:
    result = runner.invoke(app, ["--dry-run", "boards", "list"])
    assert result.exit_code == 0, result.stdout
    parsed = json.loads(result.stdout)
    assert "boards(" in parsed["query"]


def test_docs_alias_executes_doc_list_dry_run() -> None:
    result = runner.invoke(app, ["--dry-run", "docs", "list"])
    assert result.exit_code == 0, result.stdout
    parsed = json.loads(result.stdout)
    assert "docs(" in parsed["query"]


def test_plural_aliases_are_hidden_from_dump_spec() -> None:
    result = runner.invoke(app, ["-o", "json", "help", "--dump-spec"])
    assert result.exit_code == 0, result.stdout
    spec = json.loads(result.stdout)
    groups = {c["name"] for c in spec["root"]["commands"]}
    for alias in _PLURAL_ALIASES.values():
        assert alias not in groups
