"""Error visibility when stderr is suppressed (#25).

Two measures:
- benign stderr notices are gated on a human plausibly watching
  (`_notices.benign_notices_enabled`);
- fatal errors in machine mode mirror the JSON envelope to stdout when
  nothing has been written there yet, so `2>/dev/null` pipelines receive
  a parseable failure instead of empty input. Exit codes unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from mondo.cli._notices import benign_notices_enabled
from mondo.cli.main import app

ENDPOINT = "https://api.monday.com/v2"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
    monkeypatch.delenv("MONDO_VERBOSE", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")
    monkeypatch.setenv("MONDO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MONDO_CACHE_ENABLED", "false")


def _graphql_error() -> dict:
    return {
        "errors": [
            {
                "message": "Resource not found",
                "extensions": {"code": "ResourceNotFoundException", "request_id": "rq1"},
            }
        ]
    }


def _stdout_envelope(stdout: str) -> dict:
    lines = [ln for ln in stdout.strip().splitlines() if ln.strip()]
    assert lines, "expected an envelope on stdout, got nothing"
    return json.loads(lines[-1])


class TestBenignNoticesEnabled:
    def test_tty_stderr_enables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stderr.isatty", lambda: True)
        assert benign_notices_enabled() is True

    def test_non_tty_stderr_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stderr.isatty", lambda: False)
        assert benign_notices_enabled() is False

    def test_env_var_overrides_non_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stderr.isatty", lambda: False)
        monkeypatch.setenv("MONDO_VERBOSE", "1")
        assert benign_notices_enabled() is True

    def test_verbose_flag_overrides_non_tty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.stderr.isatty", lambda: False)
        assert benign_notices_enabled(verbose=True) is True


class TestMondoVerboseEnvVar:
    """`MONDO_VERBOSE=1` is wired onto the root `--verbose` option via
    `envvar`, so it enables verbose logging — not just the benign-notice
    gate in `_notices.py`."""

    def _seen_verbose(self, monkeypatch: pytest.MonkeyPatch) -> bool:
        import mondo.logging_ as logging_

        seen: dict = {}
        monkeypatch.setattr(
            logging_,
            "configure_logging",
            lambda **kw: seen.update(kw),
        )
        result = runner.invoke(app, ["help", "output"])
        assert result.exit_code == 0
        return seen["verbose"]

    def test_env_var_enables_verbose(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MONDO_VERBOSE", "1")
        assert self._seen_verbose(monkeypatch) is True

    def test_unset_env_var_keeps_verbose_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert self._seen_verbose(monkeypatch) is False


class TestMondoErrorStdoutMirror:
    def test_machine_mode_mirrors_envelope_to_stdout(
        self, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_graphql_error())
        result = runner.invoke(app, ["-o", "json", "item", "get", "--id", "1"])
        assert result.exit_code == 6
        env = _stdout_envelope(result.stdout)
        assert env["error"].startswith("Resource not found")
        assert env["exit_code"] == 6
        assert env["code"] == "ResourceNotFoundException"
        # The stderr envelope is unchanged — same payload there.
        assert "Resource not found" in result.stderr

    def test_output_none_keeps_stdout_silent(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_graphql_error())
        result = runner.invoke(app, ["-o", "none", "item", "get", "--id", "1"])
        assert result.exit_code == 6
        assert result.stdout.strip() == ""

    def test_human_mode_no_mirror(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_graphql_error())
        result = runner.invoke(app, ["-o", "table", "item", "get", "--id", "1"])
        assert result.exit_code == 6
        assert result.stdout.strip() == ""

    def test_mirror_skipped_once_stdout_written(self) -> None:
        from mondo.cli._errors import mirror_envelope_to_stdout
        from mondo.cli.context import GlobalOpts

        opts = GlobalOpts(
            profile_name=None,
            flag_token=None,
            flag_api_version=None,
            verbose=False,
            debug=False,
            output="json",
        )
        opts.stdout_emitted = True
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            mirror_envelope_to_stdout(opts, {"error": "x", "exit_code": 5})
        assert buf.getvalue() == ""


class TestUsageErrorStdoutMirror:
    def test_graphql_missing_query_usage_error_lands_on_stdout(
        self, httpx_mock: HTTPXMock
    ) -> None:
        result = runner.invoke(app, ["-o", "json", "graphql"])
        assert result.exit_code == 2
        env = _stdout_envelope(result.stdout)
        assert env["exit_code"] == 2
        assert "missing required argument" in env["error"]
        assert httpx_mock.get_requests() == []

    def test_graphql_dry_run_refusal_lands_on_stdout(
        self, httpx_mock: HTTPXMock
    ) -> None:
        result = runner.invoke(
            app, ["-o", "json", "--dry-run", "graphql", "query { me { id } }"]
        )
        assert result.exit_code == 2
        env = _stdout_envelope(result.stdout)
        assert "--dry-run is not supported" in env["error"]
        assert httpx_mock.get_requests() == []

    def test_human_mode_keeps_stdout_empty(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["-o", "table", "graphql"])
        assert result.exit_code == 2
        assert result.stdout.strip() == ""


class TestMainUsageErrorMirror:
    """Click parse failures route through `main()`'s wrapper (CliRunner uses
    standalone mode and bypasses it) — drive `main()` via argv directly."""

    def test_no_such_option_mirrors_envelope_to_stdout(
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
        out = capsys.readouterr().out
        env = _stdout_envelope(out)
        assert env["code"] == "NoSuchOption"
        assert env["exit_code"] == 2

    def test_output_none_keeps_stdout_silent(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from mondo.cli.main import main

        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        monkeypatch.setattr(
            "sys.argv",
            ["mondo", "-o", "none", "board", "get", "--definitely-not-a-flag"],
        )
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 2
        assert capsys.readouterr().out.strip() == ""
