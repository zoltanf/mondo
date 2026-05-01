"""Tests for the Phase 5.1 structured-error helpers (`mondo.cli._errors`)
and the `_exec._emit_error` plumbing that uses them.
"""

from __future__ import annotations

import json
from typing import Any

import click
import pytest

from mondo.api.errors import (
    AuthError,
    MondoError,
    NotFoundError,
    RateLimitError,
)
from mondo.cli import _exec
from mondo.cli._errors import (
    FLAG_ALIAS_HINTS,
    error_envelope,
    is_machine_output,
    is_machine_output_argv,
    suggest_for_no_such_option,
)
from mondo.cli.context import GlobalOpts


def _opts(output: str | None = None) -> GlobalOpts:
    return GlobalOpts(
        profile_name=None,
        flag_token=None,
        flag_api_version=None,
        verbose=False,
        debug=False,
        output=output,
    )


def _stderr_envelopes(text: str) -> list[dict[str, Any]]:
    """Pull every full-JSON-object line out of stderr capture."""
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            out.append(payload)
    return out


class TestErrorEnvelope:
    def test_mondo_error_includes_request_id_and_exit_code(self) -> None:
        exc = NotFoundError(
            "item not found",
            request_id="req-123",
            code="ResourceNotFoundException",
        )
        env = error_envelope(exc)
        assert env["error"].startswith("item not found")
        assert env["request_id"] == "req-123"
        assert env["code"] == "ResourceNotFoundException"
        assert env["exit_code"] == 6

    def test_rate_limit_error_carries_retry_in_seconds(self) -> None:
        exc = RateLimitError(
            "Rate Limit Exceeded",
            retry_in_seconds=42,
            code="RATE_LIMIT_EXCEEDED",
        )
        env = error_envelope(exc)
        assert env["retry_in_seconds"] == 42
        assert env["exit_code"] == 4

    def test_mondo_error_without_code_falls_back_to_class_name(self) -> None:
        exc = AuthError("token rejected")
        env = error_envelope(exc)
        assert env["code"] == "AuthError"

    def test_no_such_option_envelope_omits_request_id(self) -> None:
        exc = click.exceptions.NoSuchOption("--titel", possibilities=["--title"])
        env = error_envelope(exc)
        assert "request_id" not in env
        assert env["code"] == "NoSuchOption"
        assert env["exit_code"] == 2
        assert "did you mean" in env["suggestion"]

    def test_explicit_suggestion_overrides_difflib(self) -> None:
        exc = click.exceptions.NoSuchOption("--titel", possibilities=["--title"])
        env = error_envelope(exc, suggestion="custom")
        assert env["suggestion"] == "custom"

    def test_envelope_drops_null_fields(self) -> None:
        exc = MondoError("boom")  # no request_id, no retry_in_seconds, no code
        env = error_envelope(exc)
        assert "request_id" not in env
        assert "retry_in_seconds" not in env
        # `code` falls back to class name, never null.
        assert env["code"] == "MondoError"


class TestSuggestForNoSuchOption:
    def test_uses_click_possibilities_when_present(self) -> None:
        exc = click.exceptions.NoSuchOption("--titel", possibilities=["--title"])
        msg = suggest_for_no_such_option(exc)
        assert msg is not None
        assert "'--title'" in msg

    def test_falls_back_to_static_alias_table(self) -> None:
        exc = click.exceptions.NoSuchOption("--group-id", possibilities=[])
        msg = suggest_for_no_such_option(exc)
        assert msg is not None
        assert "--group" in msg
        assert "--id" in msg

    def test_returns_none_for_unknown_unhinted_option(self) -> None:
        exc = click.exceptions.NoSuchOption("--totally-unknown", possibilities=[])
        assert suggest_for_no_such_option(exc) is None

    def test_returns_none_for_non_no_such_option_usage_error(self) -> None:
        # MissingParameter is a UsageError but not NoSuchOption; no flag-typo
        # hint applies.
        exc = click.exceptions.MissingParameter(param_hint="--id")
        assert suggest_for_no_such_option(exc) is None

    def test_alias_table_shape(self) -> None:
        for typo, hints in FLAG_ALIAS_HINTS.items():
            assert typo.startswith("--")
            assert hints
            for h in hints:
                assert h.startswith("--")


class TestIsMachineOutput:
    @pytest.mark.parametrize("value", ["json", "JSON", "jsonc", "yaml"])
    def test_explicit_machine_format_is_machine(self, value: str) -> None:
        assert is_machine_output(_opts(value)) is True

    @pytest.mark.parametrize("value", ["table", "csv", "tsv", "none"])
    def test_explicit_human_format_is_not_machine(self, value: str) -> None:
        assert is_machine_output(_opts(value)) is False

    def test_unset_format_falls_back_to_tty_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        assert is_machine_output(_opts(None)) is False
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        assert is_machine_output(_opts(None)) is True

    def test_none_opts_uses_tty_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        assert is_machine_output(None) is True
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        assert is_machine_output(None) is False


class TestIsMachineOutputArgv:
    def test_short_flag(self) -> None:
        assert is_machine_output_argv(["-o", "json", "board", "get", "1"]) is True

    def test_long_flag_with_space(self) -> None:
        assert is_machine_output_argv(["--output", "yaml", "item", "get"]) is True

    def test_long_flag_with_equals(self) -> None:
        assert is_machine_output_argv(["--output=jsonc", "item", "get"]) is True

    def test_human_flag_returns_false(self) -> None:
        assert is_machine_output_argv(["-o", "table", "board", "list"]) is False

    def test_unset_falls_back_to_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        assert is_machine_output_argv(["board", "list"]) is True
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        assert is_machine_output_argv(["board", "list"]) is False


class TestExecEmitError:
    """`_exec._emit_error` is the shared sink for every MondoError raised
    from a command body. Confirm it always writes the human line and
    emits the JSON envelope only in machine modes."""

    def test_machine_mode_emits_envelope_alongside_human_line(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        opts = _opts("json")
        ctx = click.Context(click.Command("dummy"), obj=opts)
        with ctx:
            _exec._emit_error(
                NotFoundError(
                    "item gone",
                    request_id="req-9",
                    code="ResourceNotFoundException",
                )
            )
        err = capsys.readouterr().err
        # First non-empty line is the red `error: ...`
        first = next(ln for ln in err.splitlines() if ln.strip())
        assert "error: item gone" in first
        envs = _stderr_envelopes(err)
        assert len(envs) == 1, err
        env = envs[0]
        assert env["code"] == "ResourceNotFoundException"
        assert env["request_id"] == "req-9"
        assert env["exit_code"] == 6

    def test_human_mode_skips_envelope(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        opts = _opts("table")
        ctx = click.Context(click.Command("dummy"), obj=opts)
        with ctx:
            _exec._emit_error(NotFoundError("item gone"))
        err = capsys.readouterr().err
        assert _stderr_envelopes(err) == []
        first = next(ln for ln in err.splitlines() if ln.strip())
        assert "error: item gone" in first

    def test_no_active_context_falls_back_to_tty(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # No `click.Context` active — simulates an error raised before
        # the root callback runs. Off-TTY → machine envelope still fires.
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        _exec._emit_error(NotFoundError("preflight failure"))
        err = capsys.readouterr().err
        assert len(_stderr_envelopes(err)) == 1


class TestMainNoSuchOptionWrapping:
    """The console-script `main()` entry point wraps `app(args=...)` so
    Click `UsageError` failures emit the JSON envelope on stderr in
    machine output modes. The Typer `CliRunner` uses standalone_mode=True
    and bypasses our wrapper, so we drive `main()` directly via
    monkeypatched argv.
    """

    def test_no_such_option_in_json_mode_emits_envelope(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from mondo.cli.main import main

        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        monkeypatch.setattr(
            "sys.argv",
            ["mondo", "-o", "json", "board", "get", "--definitely-not-a-flag"],
        )
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 2
        err = capsys.readouterr().err
        envs = _stderr_envelopes(err)
        assert len(envs) == 1, err
        env = envs[0]
        assert env["code"] == "NoSuchOption"
        assert env["exit_code"] == 2

    def test_no_such_option_in_human_mode_skips_envelope(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from mondo.cli.main import main

        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        monkeypatch.setattr(
            "sys.argv",
            ["mondo", "-o", "table", "board", "get", "--definitely-not-a-flag"],
        )
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 2
        err = capsys.readouterr().err
        assert _stderr_envelopes(err) == []
