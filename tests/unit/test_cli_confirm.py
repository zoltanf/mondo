"""Unit tests for the shared confirmation helper."""

from __future__ import annotations

from dataclasses import dataclass

import click
import pytest
import typer
from typer.testing import CliRunner

from mondo.cli._confirm import confirm_or_abort


@dataclass
class _Opts:
    yes: bool = False


def _cli() -> typer.Typer:
    app = typer.Typer()

    @app.command()
    def destroy(yes: bool = typer.Option(False, "--yes", "-y")) -> None:
        confirm_or_abort(_Opts(yes=yes), "Really?")
        typer.echo("done")

    return app


runner = CliRunner()


def test_yes_short_circuits() -> None:
    """`--yes` skips the prompt entirely and the command proceeds."""
    result = runner.invoke(_cli(), ["--yes"])
    assert result.exit_code == 0
    assert "done" in result.stdout


def test_tty_decline_says_aborted() -> None:
    """Answering `n` prints `aborted.` to stdout and exits 1 (unchanged behavior)."""
    result = runner.invoke(_cli(), [], input="n\n")
    assert result.exit_code == 1
    assert "aborted." in result.stdout


def test_non_tty_abort_prints_yes_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """When stdin is exhausted on a non-TTY, print a stderr hint mentioning --yes."""

    # Simulate a non-TTY stdin that raises Abort on prompt (EOF/piped-empty case).
    def _raise_abort(*args: object, **kwargs: object) -> bool:
        raise click.Abort()

    monkeypatch.setattr("typer.confirm", _raise_abort)

    class _StdinNonTty:
        @staticmethod
        def isatty() -> bool:
            return False

    monkeypatch.setattr("sys.stdin", _StdinNonTty())

    with pytest.raises(typer.Exit) as exc:
        confirm_or_abort(_Opts(yes=False), "Really?")
    assert exc.value.exit_code == 1
    captured = capsys.readouterr()
    assert "--yes" in captured.err
    assert "non-interactive" in captured.err
