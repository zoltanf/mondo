"""Unit tests for the extracted CLI render pipeline + client factory.

`render_output` (mondo.cli._render) is the body of what used to live inside
`GlobalOpts.emit`; these tests exercise it directly with a StringIO stream so
the `wrote-to-real-stdout` contract, projection, and warning behaviour are
pinned independently of GlobalOpts.
"""

from __future__ import annotations

import io
import json

import pytest
import typer

from mondo.cli._render import render_output


class TestRenderOutput:
    def test_json_output_to_stream(self) -> None:
        buf = io.StringIO()
        wrote = render_output({"name": "X"}, output="json", query=None, fields=None, stream=buf)
        assert json.loads(buf.getvalue()) == {"name": "X"}
        # A provided stream is never "real stdout".
        assert wrote is False

    def test_returns_true_only_for_real_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        # stream=None → writes to sys.stdout, fmt != none → wrote True.
        wrote = render_output({"name": "X"}, output="json", query=None, fields=None, stream=None)
        assert wrote is True
        assert json.loads(capsys.readouterr().out) == {"name": "X"}

    def test_none_format_does_not_count_as_wrote(self, capsys: pytest.CaptureFixture[str]) -> None:
        wrote = render_output({"name": "X"}, output="none", query=None, fields=None, stream=None)
        assert wrote is False
        assert capsys.readouterr().out == ""

    def test_query_projection(self) -> None:
        buf = io.StringIO()
        render_output(
            {"name": "X", "id": 1},
            output="json",
            query="{n:name}",
            fields=None,
            stream=buf,
        )
        assert json.loads(buf.getvalue()) == {"n": "X"}

    def test_bad_query_raises_usage_exit(self) -> None:
        # usage_error_or_exit routes the bad --query through the canonical
        # error path, which raises typer.Exit(2).
        buf = io.StringIO()
        with pytest.raises(typer.Exit) as exc_info:
            render_output(
                {"name": "X"},
                output="json",
                query="{unterminated",
                fields=None,
                stream=buf,
            )
        assert exc_info.value.exit_code == 2

    def test_projection_warning_emitted(self, capsys: pytest.CaptureFixture[str]) -> None:
        buf = io.StringIO()
        render_output(
            {"name": "X"},
            output="json",
            query="{f:board_folder_id}",
            fields=None,
            stream=buf,
            selected_fields=frozenset({"id", "name"}),
        )
        assert "warning: field 'board_folder_id'" in capsys.readouterr().err

    def test_projection_warning_suppressed_by_envvar(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MONDO_NO_PROJECTION_WARNINGS", "1")
        buf = io.StringIO()
        render_output(
            {"name": "X"},
            output="json",
            query="{f:board_folder_id}",
            fields=None,
            stream=buf,
            selected_fields=frozenset({"id", "name"}),
        )
        assert capsys.readouterr().err == ""

    def test_no_warning_without_selected_fields(self, capsys: pytest.CaptureFixture[str]) -> None:
        buf = io.StringIO()
        render_output(
            {"name": "X"},
            output="json",
            query="{f:board_folder_id}",
            fields=None,
            stream=buf,
        )
        assert capsys.readouterr().err == ""


class TestClientFactory:
    def _config(self, api_version: str = "2026-01", profile_version: str | None = None):
        from mondo.config.schema import Config, Profile

        return Config(
            default_profile="default",
            api_version=api_version,
            profiles={"default": Profile(api_version=profile_version)},
        )

    def test_flag_version_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from mondo.cli import _client_factory

        monkeypatch.setenv("MONDAY_API_TOKEN", "tok")
        client = _client_factory.build_client_from_config(
            self._config(profile_version="2025-01"),
            profile_name=None,
            flag_token=None,
            flag_api_version="2099-12",
        )
        assert client.api_version == "2099-12"

    def test_profile_version_over_global(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from mondo.cli import _client_factory

        monkeypatch.setenv("MONDAY_API_TOKEN", "tok")
        client = _client_factory.build_client_from_config(
            self._config(api_version="2026-01", profile_version="2025-07"),
            profile_name=None,
            flag_token=None,
            flag_api_version=None,
        )
        assert client.api_version == "2025-07"

    def test_global_version_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from mondo.cli import _client_factory

        monkeypatch.setenv("MONDAY_API_TOKEN", "tok")
        client = _client_factory.build_client_from_config(
            self._config(api_version="2026-01"),
            profile_name=None,
            flag_token=None,
            flag_api_version=None,
        )
        assert client.api_version == "2026-01"

    def test_flag_token_resolves(self) -> None:
        from mondo.api.auth import TokenSource
        from mondo.cli import _client_factory

        resolved = _client_factory.resolve_token_from_config(
            self._config(), profile_name=None, flag_token="flagtok"
        )
        assert resolved.token == "flagtok"
        assert resolved.source == TokenSource.FLAG
