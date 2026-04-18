"""Smoke tests for the Typer root + global options."""

from __future__ import annotations

from typer.testing import CliRunner

from mondo.cli.main import app
from mondo.version import __version__

runner = CliRunner()


class TestRootHelp:
    def test_help_exits_zero(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Power-user CLI" in result.stdout

    def test_version(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.stdout

    def test_global_options_listed(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for flag in ("--profile", "--api-token", "--api-version", "--debug", "--verbose"):
            assert flag in result.stdout


class TestBuildContext:
    def test_profile_name_from_flag(self, monkeypatch) -> None:
        from mondo.cli.context import GlobalOpts

        monkeypatch.delenv("MONDO_PROFILE", raising=False)
        monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
        opts = GlobalOpts(
            profile_name="work",
            flag_token=None,
            flag_api_version=None,
            verbose=False,
            debug=False,
        )
        assert opts.profile_name == "work"
