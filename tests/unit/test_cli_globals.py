"""Smoke tests for the Typer root + global options."""

from __future__ import annotations

from typer.testing import CliRunner

from mondo.cli.main import app
from mondo.version import __version__

runner = CliRunner()


_GLOBAL_FLAGS = (
    "--profile",
    "--api-token",
    "--api-version",
    "--output",
    "--query",
    "--verbose",
    "--debug",
    "--yes",
    "--dry-run",
    "--version",
)


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

    def test_root_help_does_not_duplicate_globals_panel(self) -> None:
        """Root keeps a single 'Options' section; no separate Global Options
        panel (those would be redundant with what's already shown)."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Global Options" not in result.stdout


class TestSubcommandHelp:
    """Globals declared on the root callback are also surfaced on every
    subcommand's help via a 'Global Options' panel — `mondo skill --help`
    must tell users about `--profile`, `-o`, `--debug`, etc."""

    def test_subgroup_help_lists_globals(self) -> None:
        result = runner.invoke(app, ["skill", "--help"])
        assert result.exit_code == 0, result.output
        assert "Global Options" in result.output
        for flag in _GLOBAL_FLAGS:
            assert flag in result.output, f"{flag} missing from `mondo skill --help`"

    def test_subgroup_help_does_not_list_root_only_completion_flags(self) -> None:
        """`--install-completion`/`--show-completion` are root-only by nature
        and explicitly excluded from argv-reorder; they must not appear under
        Global Options on subcommands."""
        result = runner.invoke(app, ["skill", "--help"])
        assert result.exit_code == 0, result.output
        assert "--install-completion" not in result.output
        assert "--show-completion" not in result.output

    def test_leaf_help_lists_globals_alongside_local_options(self) -> None:
        result = runner.invoke(app, ["skill", "install", "--help"])
        assert result.exit_code == 0, result.output
        # Leaf-local --global stays in the regular Options panel.
        assert "--global" in result.output
        # And globals are also visible.
        assert "Global Options" in result.output
        for flag in _GLOBAL_FLAGS:
            assert flag in result.output, f"{flag} missing from `mondo skill install --help`"

    def test_leaf_help_in_other_group(self) -> None:
        """Spot-check a different group so we know the patch isn't skill-specific."""
        result = runner.invoke(app, ["board", "list", "--help"])
        assert result.exit_code == 0, result.output
        assert "Global Options" in result.output
        for flag in _GLOBAL_FLAGS:
            assert flag in result.output


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
