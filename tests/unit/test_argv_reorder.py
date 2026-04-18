"""Tests for mondo.cli.argv — moves root-level flags in front of subcommands.

az/gh/gam all accept global flags anywhere on the command line. Typer's
Click-based parser only honors them at the root level, so we pre-process
`sys.argv` to normalize the order.
"""

from __future__ import annotations

import pytest

from mondo.cli.argv import reorder_argv


class TestReorderArgv:
    def test_empty(self) -> None:
        assert reorder_argv([]) == []

    def test_no_globals_unchanged(self) -> None:
        assert reorder_argv(["item", "get", "--id", "42"]) == ["item", "get", "--id", "42"]

    def test_output_moves_to_front(self) -> None:
        assert reorder_argv(["item", "list", "--board", "42", "-o", "table"]) == [
            "-o",
            "table",
            "item",
            "list",
            "--board",
            "42",
        ]

    def test_query_moves_to_front(self) -> None:
        assert reorder_argv(["item", "list", "--board", "42", "-q", "[].name"]) == [
            "-q",
            "[].name",
            "item",
            "list",
            "--board",
            "42",
        ]

    def test_multiple_globals_preserve_order(self) -> None:
        assert reorder_argv(
            [
                "item",
                "list",
                "--board",
                "42",
                "-o",
                "json",
                "-q",
                "[].name",
                "--debug",
            ]
        ) == [
            "-o",
            "json",
            "-q",
            "[].name",
            "--debug",
            "item",
            "list",
            "--board",
            "42",
        ]

    def test_leading_globals_stay_leading(self) -> None:
        # Users who already put globals first shouldn't see reshuffling
        argv = ["-o", "json", "item", "list", "--board", "42"]
        assert reorder_argv(argv) == argv

    def test_equals_form(self) -> None:
        assert reorder_argv(["item", "list", "--board=42", "--output=yaml"]) == [
            "--output=yaml",
            "item",
            "list",
            "--board=42",
        ]

    def test_boolean_globals(self) -> None:
        assert reorder_argv(["item", "archive", "--id", "1", "--yes", "--debug"]) == [
            "--yes",
            "--debug",
            "item",
            "archive",
            "--id",
            "1",
        ]

    def test_verbose_short_form(self) -> None:
        assert reorder_argv(["auth", "status", "-v"]) == ["-v", "auth", "status"]

    def test_version_flag_ignored(self) -> None:
        """--help and --version are not reordered — they should take effect
        at whatever level the user typed them."""
        assert reorder_argv(["item", "--help"]) == ["item", "--help"]
        assert reorder_argv(["item", "get", "--help"]) == ["item", "get", "--help"]

    def test_global_flag_before_its_value_not_separated(self) -> None:
        # If the user writes `--profile work`, the "work" must stay attached
        # to `--profile` after reordering.
        assert reorder_argv(["item", "list", "--board", "42", "--profile", "work"]) == [
            "--profile",
            "work",
            "item",
            "list",
            "--board",
            "42",
        ]

    def test_global_flag_with_subsequent_subcommand_args(self) -> None:
        # Global inserted between subcommand and its args must still reorder.
        assert reorder_argv(["item", "--profile", "work", "get", "--id", "42"]) == [
            "--profile",
            "work",
            "item",
            "get",
            "--id",
            "42",
        ]

    def test_similar_prefix_not_global_left_alone(self) -> None:
        # `--board` is NOT a global — stays where it is.
        argv = ["item", "list", "--board", "42"]
        assert reorder_argv(argv) == argv

    def test_api_token_with_value(self) -> None:
        assert reorder_argv(["auth", "status", "--api-token", "abc123"]) == [
            "--api-token",
            "abc123",
            "auth",
            "status",
        ]


class TestDoesNotMisfire:
    """Regression: reorder must never swallow a subcommand arg by accident."""

    @pytest.mark.parametrize(
        "argv",
        [
            ["graphql", "query { me { id } }"],
            ["item", "create", "--board", "42", "--name", "Hi"],
            ["column", "set", "--item", "1", "--column", "status", "--value", "Done"],
        ],
    )
    def test_preserves_argv(self, argv: list[str]) -> None:
        assert reorder_argv(argv) == argv
