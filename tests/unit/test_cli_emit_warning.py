"""Tests for the projection-warning behavior of `GlobalOpts.emit`."""

from __future__ import annotations

import io

import pytest

from mondo.cli.context import GlobalOpts


def _opts(*, query: str | None = None) -> GlobalOpts:
    return GlobalOpts(
        profile_name=None,
        flag_token=None,
        flag_api_version=None,
        verbose=False,
        debug=False,
        output="json",
        query=query,
    )


class TestEmitProjectionWarning:
    def test_warns_for_unselected_field(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        opts = _opts(query="{f:board_folder_id}")
        opts.emit(
            {"name": "X"},
            stream=io.StringIO(),
            selected_fields=frozenset({"id", "name"}),
        )
        captured = capsys.readouterr()
        assert "warning: field 'board_folder_id'" in captured.err

    def test_no_warning_when_field_present(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        opts = _opts(query="{n:name}")
        opts.emit(
            {"name": "X"},
            stream=io.StringIO(),
            selected_fields=frozenset({"id", "name"}),
        )
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_no_warning_when_selected_fields_omitted(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Backwards-compat: callers that haven't been upgraded to pass
        # `selected_fields` get exactly today's behavior.
        opts = _opts(query="{f:board_folder_id}")
        opts.emit({"name": "X"}, stream=io.StringIO())
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_no_warning_without_query(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        opts = _opts(query=None)
        opts.emit(
            {"name": "X"},
            stream=io.StringIO(),
            selected_fields=frozenset({"id", "name"}),
        )
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_multiple_missing_fields_each_warn(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        opts = _opts(query="{a:foo, b:bar}")
        opts.emit(
            {"foo": 1, "bar": 2},
            stream=io.StringIO(),
            selected_fields=frozenset({"id"}),
        )
        captured = capsys.readouterr()
        # One warning per missing field, alphabetical.
        assert captured.err.count("warning:") == 2
        assert "warning: field 'bar'" in captured.err
        assert "warning: field 'foo'" in captured.err
        # Sorted output — bar before foo.
        assert captured.err.index("'bar'") < captured.err.index("'foo'")

    def test_aliases_do_not_false_positive(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # `ws` is the alias; only `workspace.name` resolves to fields.
        opts = _opts(query="[*].{n:name, ws:workspace.name}")
        opts.emit(
            [{"name": "X", "workspace": {"name": "WS"}}],
            stream=io.StringIO(),
            selected_fields=frozenset({"id", "name", "workspace"}),
        )
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_envar_suppresses_warning(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MONDO_NO_PROJECTION_WARNINGS", "1")
        opts = _opts(query="{f:board_folder_id}")
        opts.emit(
            {"name": "X"},
            stream=io.StringIO(),
            selected_fields=frozenset({"id", "name"}),
        )
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_stdout_unchanged_with_warning(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Warning is on stderr; stdout (the projected payload) must be byte-
        # identical to the no-warning case.
        buf_warn = io.StringIO()
        opts_warn = _opts(query="{f:board_folder_id}")
        opts_warn.emit(
            {"board_folder_id": 42},
            stream=buf_warn,
            selected_fields=frozenset({"id"}),
        )

        buf_silent = io.StringIO()
        opts_silent = _opts(query="{f:board_folder_id}")
        opts_silent.emit({"board_folder_id": 42}, stream=buf_silent)

        assert buf_warn.getvalue() == buf_silent.getvalue()
