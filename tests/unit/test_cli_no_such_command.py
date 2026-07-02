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

import click
import pytest
from typer.testing import CliRunner

from mondo.cli._errors import error_envelope, suggest_for_no_such_option
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
        assert sibling in combined, f"missing item-sibling {sibling!r}: {combined}"


def test_unknown_subcommand_under_column() -> None:
    """Same behavior for a different nested group."""
    result = runner.invoke(app, ["column", "bogus"])
    assert result.exit_code != 0
    combined = (result.output or "") + (result.stderr or "")
    for sibling in ("list", "get", "set"):
        assert sibling in combined, f"missing column-sibling {sibling!r}: {combined}"


def test_unknown_subcommand_keeps_fuzzy_hint_when_close() -> None:
    """Keep the Click-style 'Did you mean' hint when there's a close match."""
    result = runner.invoke(app, ["item", "lst"])  # missing 'i' — close to 'list'
    assert result.exit_code != 0
    combined = (result.output or "") + (result.stderr or "")
    assert "list" in combined
    # The error should still flag it as a "did you mean" hint.
    assert "Did you mean" in combined or "did you mean" in combined.lower()


def _flatten(text: str) -> str:
    """Collapse rich's Error panel (borders + line wrapping) back into one
    plain line so multi-word assertions survive the rendering."""
    return " ".join(text.replace("│", " ").split())


def test_fuzzy_hint_appears_exactly_once() -> None:
    """Typer's built-in `suggest_commands` hint used to stack on top of ours,
    printing 'Did you mean ...?' twice (#76)."""
    result = runner.invoke(app, ["item", "liist"])
    assert result.exit_code != 0
    # `result.output` already includes stderr under click's CliRunner.
    assert result.output.lower().count("did you mean") == 1


def test_removed_doc_export_markdown_gets_tombstone() -> None:
    """`doc export-markdown` (removed in 0.11) must point at the replacement
    read command, not fuzzy-match to the `add-markdown` write command (#76)."""
    result = runner.invoke(app, ["doc", "export-markdown"])
    assert result.exit_code != 0
    flat = _flatten(result.output)
    assert "removed in 0.11" in flat
    assert "mondo doc get --doc <id> --format markdown" in flat
    # The fuzzy did-you-mean is suppressed in favor of the tombstone.
    assert "did you mean" not in flat.lower()
    # The sibling listing survives.
    assert "Available subcommands:" in flat
    assert "add-markdown" in flat


def test_removed_doc_export_markdown_tombstone_covers_plural_alias() -> None:
    """`mondo docs export-markdown` (plural alias) must show the same
    tombstone — lazy loading names the group after the invoked alias, so
    the tombstone is keyed on both `mondo doc` and `mondo docs` paths."""
    result = runner.invoke(app, ["docs", "export-markdown"])
    assert result.exit_code != 0
    flat = _flatten(result.output)
    assert "removed in 0.11" in flat
    assert "mondo doc get --doc <id> --format markdown" in flat
    assert "did you mean" not in flat.lower()


def test_column_doc_export_markdown_gets_no_tombstone() -> None:
    """`mondo column doc` is a different group that happens to be named
    'doc' — `export-markdown` never existed there, so no tombstone; the
    normal siblings listing applies."""
    result = runner.invoke(app, ["column", "doc", "export-markdown"])
    assert result.exit_code != 0
    flat = _flatten(result.output)
    assert "removed in 0.11" not in flat
    assert "Available subcommands:" in flat
    for sibling in ("append", "clear", "get", "set"):
        assert sibling in flat, f"missing column-doc sibling {sibling!r}: {flat}"


def test_resolve_command_survives_missing_suggest_commands_attr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """typer<0.16 (declared floor is 0.15) has no `suggest_commands`
    attribute and no `resolve_command` override — an unknown subcommand
    must still raise UsageError, not AttributeError."""
    import typer.core

    from mondo.cli._help_format import MondoGroup

    monkeypatch.setattr(typer.core.TyperGroup, "resolve_command", click.Group.resolve_command)
    group = MondoGroup(name="doc")
    assert "suggest_commands" in vars(group)  # sanity: current typer sets it
    del group.suggest_commands  # simulate the older typer
    ctx = click.Context(group)
    with pytest.raises(click.UsageError):
        group.resolve_command(ctx, ["bogus"])
    assert not hasattr(group, "suggest_commands")  # guard didn't re-create it


def test_tombstone_feeds_envelope_suggestion() -> None:
    """The JSON error envelope's `suggestion` field carries the tombstone
    text, via the same path `main()` uses for UsageErrors."""
    with pytest.raises(click.exceptions.UsageError) as excinfo:
        app(args=["doc", "export-markdown"], standalone_mode=False)
    env = error_envelope(excinfo.value, suggestion=suggest_for_no_such_option(excinfo.value))
    assert env["suggestion"] == (
        "removed in 0.11 — use: mondo doc get --doc <id> --format markdown [--engine server]"
    )
