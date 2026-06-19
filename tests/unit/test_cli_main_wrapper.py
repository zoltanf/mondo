"""Exercise the console-script wrapper `main()` directly.

`main()` in `mondo.cli.main` does work that the Typer `app` (driven via
Click's `CliRunner` in standalone mode) never reaches: it reorders argv so
root-level global flags are accepted after the subcommand, and it wraps the
Typer call to turn Click `UsageError` parse failures into exit-code 2 plus
(in machine-output mode) a JSON error envelope mirrored to stdout.

These tests drive `main()` in-process by monkeypatching `sys.argv` and
asserting on the `SystemExit` code and capsys-captured stdout. Every command
used here fails fast at parse time or is the eager `--version` path, so no
test touches the network or auth.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from mondo.cli.main import main
from mondo.version import __version__


def _last_json_line(stdout: str) -> dict[str, Any]:
    lines = [ln for ln in stdout.strip().splitlines() if ln.strip()]
    assert lines, "expected a JSON envelope on stdout, got nothing"
    return json.loads(lines[-1])


class TestGlobalFlagReordering:
    """A global flag placed after the subcommand behaves like one before it.

    `--version` is eager and exits before any subcommand runs, so it is a
    hermetic probe for `reorder_argv`: if the flag is recognized after the
    subcommand token, it can only be because the wrapper moved it to the
    front before handing argv to Typer.
    """

    def test_version_before_subcommand(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.argv", ["mondo", "--version"])
        main()
        assert capsys.readouterr().out.strip() == f"mondo {__version__}"

    def test_version_after_subcommand_matches(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Flag positioned after the subcommand token. Without reordering Click
        # would reject `--version` here; with it, output matches the
        # before-subcommand placement above.
        monkeypatch.setattr("sys.argv", ["mondo", "board", "--version"])
        main()
        assert capsys.readouterr().out.strip() == f"mondo {__version__}"


class TestUnknownOptionUsageError:
    def test_unknown_option_exits_2(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        monkeypatch.setattr(
            "sys.argv",
            ["mondo", "board", "get", "--definitely-not-a-flag"],
        )
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 2


class TestMachineModeMirror:
    """In machine-output mode a parse error mirrors the JSON envelope to
    stdout, so pipelines that suppress stderr (`2>/dev/null`) still get
    machine-readable failure detail."""

    def test_usage_error_envelope_on_stdout(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Non-TTY stdout would already select machine output, but `-o json`
        # makes the intent explicit and independent of the test runner's tty.
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        monkeypatch.setattr(
            "sys.argv",
            ["mondo", "-o", "json", "board", "get", "--definitely-not-a-flag"],
        )
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 2
        env = _last_json_line(capsys.readouterr().out)
        assert env["code"] == "NoSuchOption"
        assert env["exit_code"] == 2

    def test_human_output_keeps_stdout_silent(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # `-o none` classifies as human output, so the mirror must not fire.
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        monkeypatch.setattr(
            "sys.argv",
            ["mondo", "-o", "none", "board", "get", "--definitely-not-a-flag"],
        )
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 2
        assert capsys.readouterr().out.strip() == ""
