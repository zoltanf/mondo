"""When a user types `mondo item bogus` (no such subcommand), the error
should list **all** available subcommands of `item` plus a fuzzy
suggestion.

Friction report A3: `mondo item update` (typo for `mondo update create`)
hits Click's default fuzzy-only suggestion which says "Did you mean
'duplicate'?" — actively misleading because the user wants 'update create'
from a different namespace.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from mondo.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")


def test_unknown_top_level_command_lists_siblings() -> None:
    """`mondo bogus` lists all top-level commands in the error body."""
    result = runner.invoke(app, ["bogus"])
    assert result.exit_code != 0
    combined = (result.output or "") + (result.stderr or "")
    # A handful of well-known top-level commands must appear in the error.
    for sibling in ("item", "board", "column", "group"):
        assert sibling in combined, f"missing top-level sibling {sibling!r}: {combined}"


def test_unknown_subcommand_lists_siblings_under_item() -> None:
    """`mondo item bogus` lists item's subcommands (the friction report's
    canonical case)."""
    result = runner.invoke(app, ["item", "bogus"])
    assert result.exit_code != 0
    combined = (result.output or "") + (result.stderr or "")
    # All of these are real `item` subcommands.
    for sibling in ("create", "delete", "list", "get", "duplicate", "find"):
        assert sibling in combined, (
            f"missing item-sibling {sibling!r}: {combined}"
        )


def test_unknown_subcommand_under_column() -> None:
    """Same behavior for a different nested group."""
    result = runner.invoke(app, ["column", "bogus"])
    assert result.exit_code != 0
    combined = (result.output or "") + (result.stderr or "")
    for sibling in ("list", "get", "set"):
        assert sibling in combined, (
            f"missing column-sibling {sibling!r}: {combined}"
        )


def test_unknown_subcommand_keeps_fuzzy_hint_when_close() -> None:
    """Keep the Click-style 'Did you mean' hint when there's a close match."""
    result = runner.invoke(app, ["item", "lst"])  # missing 'i' — close to 'list'
    assert result.exit_code != 0
    combined = (result.output or "") + (result.stderr or "")
    assert "list" in combined
    # The error should still flag it as a "did you mean" hint.
    assert "Did you mean" in combined or "did you mean" in combined.lower()
