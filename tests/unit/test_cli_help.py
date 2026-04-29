"""Tests for the `mondo help` command and the machine-readable spec dump.

These lock the agent-facing contract: if the shape of `--dump-spec` changes
or a bundled topic disappears, downstream automation breaks silently without
coverage here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mondo.cli._examples import EXAMPLES, epilog_for
from mondo.cli.help import _list_topics, _read_topic
from mondo.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`help` never hits the network, but the global callback still resolves
    config — stub it out to a scratch path so tests don't touch real files."""
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")


# --- topic listing & rendering ---------------------------------------------


class TestHelpTopics:
    def test_listing_includes_seeded_topics(self) -> None:
        result = runner.invoke(app, ["help"])
        assert result.exit_code == 0, result.output
        for topic in ("codecs", "output", "exit-codes"):
            assert f"mondo help {topic}" in result.output

    def test_rendering_a_known_topic_returns_markdown(self) -> None:
        result = runner.invoke(app, ["help", "codecs"])
        assert result.exit_code == 0, result.output
        # Non-TTY (CliRunner) falls through to raw markdown — assert on a
        # couple of lines that are stable prose, not on rich formatting.
        assert "# Column-value codecs" in result.output
        assert "--column COL=VAL" in result.output

    def test_unknown_topic_exits_with_not_found_code(self) -> None:
        result = runner.invoke(app, ["help", "nope"])
        assert result.exit_code == 6
        assert "unknown help topic" in result.output
        # The error lists available topics so the user can recover.
        assert "codecs" in result.output


# --- epilog rendering -------------------------------------------------------


class TestEpilogs:
    def test_epilog_for_returns_none_for_unknown_path(self) -> None:
        assert epilog_for("does not exist") is None

    def test_epilog_for_renders_registered_examples(self) -> None:
        rendered = epilog_for("item create")
        assert rendered is not None
        assert "[bold]Examples[/bold]" in rendered
        for ex in EXAMPLES["item create"]:
            assert ex.command in rendered
            assert ex.description in rendered

    def test_every_registered_example_invokes_mondo(self) -> None:
        # Agents copy-paste these — every example must actually call the CLI.
        # We allow leading `cat … | ` or `echo … | ` pipes, so match on the
        # presence of `mondo ` anywhere in the command string rather than at
        # the start.
        for path, examples in EXAMPLES.items():
            for ex in examples:
                assert "mondo " in ex.command, (
                    f"{path}: example does not invoke `mondo`: {ex.command!r}"
                )

    def test_help_page_contains_examples_block(self) -> None:
        result = runner.invoke(app, ["item", "create", "--help"])
        assert result.exit_code == 0, result.output
        assert "Examples" in result.output
        assert "Minimal create" in result.output


# --- --dump-spec contract ---------------------------------------------------


@pytest.fixture(scope="module")
def spec() -> dict:
    """Invoke `mondo help --dump-spec` once and parse it for the whole module.

    CliRunner bypasses `main()`'s argv reorder, so global flags must precede
    the subcommand. The spec dump is deterministic and expensive (walks every
    registered command) — a module-scoped fixture turns N invocations into 1.
    """
    result = runner.invoke(app, ["-o", "json", "help", "--dump-spec"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


class TestDumpSpec:
    def test_top_level_shape(self, spec: dict) -> None:
        assert spec["cli"] == "mondo"
        assert set(spec) >= {"cli", "root", "exit_codes", "output_formats"}
        assert set(spec["exit_codes"]) == {"0", "1", "2", "3", "4", "5", "6", "7"}
        assert "json" in spec["output_formats"]

    def test_root_command_tree_enumerates_known_groups(self, spec: dict) -> None:
        groups = {c["name"] for c in spec["root"]["commands"]}
        for expected in ("item", "board", "column", "help", "graphql"):
            assert expected in groups

    def test_leaf_command_exposes_params_and_required_flags(self, spec: dict) -> None:
        item = next(c for c in spec["root"]["commands"] if c["name"] == "item")
        create = next(c for c in item["commands"] if c["name"] == "create")

        param_names = {p["name"] for p in create["params"]}
        assert {"board_id", "name", "columns", "raw_columns"} <= param_names

        required = {p["name"] for p in create["params"] if p["required"]}
        assert required == {"board_id", "name"}

    def test_examples_round_trip_from_registry(self, spec: dict) -> None:
        item = next(c for c in spec["root"]["commands"] if c["name"] == "item")
        create = next(c for c in item["commands"] if c["name"] == "create")
        expected = [
            {"description": ex.description, "command": ex.command} for ex in EXAMPLES["item create"]
        ]
        assert create["examples"] == expected

    def test_param_type_enum_choices_surface(self, spec: dict) -> None:
        """Enum-typed options (like `--position-relative-method`) should carry
        their `choices` list so an agent can validate without running the CLI."""
        item = next(c for c in spec["root"]["commands"] if c["name"] == "item")
        create = next(c for c in item["commands"] if c["name"] == "create")
        prm = next(p for p in create["params"] if p["name"] == "position_relative_method")
        assert prm.get("choices") == ["before_at", "after_at"]

    def test_get_commands_expose_url_examples(self, spec: dict) -> None:
        """Board/doc/item/subitem get all accept URLs — agents find the
        pattern by scanning examples in the spec."""
        targets = {
            "board": "get",
            "doc": "get",
            "item": "get",
            "subitem": "get",
        }
        for group, sub in targets.items():
            grp = next(c for c in spec["root"]["commands"] if c["name"] == group)
            cmd = next(c for c in grp["commands"] if c["name"] == sub)
            assert any("https://" in ex["command"] for ex in cmd["examples"]), (
                f"{group} {sub}: no example with a monday URL"
            )

    def test_boards_vs_docs_topic_content(self) -> None:
        """The topic is the contract agents read for workdoc handling."""
        result = runner.invoke(app, ["help", "boards-vs-docs"])
        assert result.exit_code == 0, result.output
        assert "workdoc" in result.output.lower()
        assert "mondo doc get --object-id" in result.output
        assert "--with-url" in result.output

    def test_global_params_attached_to_subcommands_only(self, spec: dict) -> None:
        """Root globals are advertised on every descendant via `global_params`,
        but not on the root itself — the root keeps them in its own `params`."""
        root = spec["root"]
        assert "global_params" not in root
        own_param_names = {p["name"] for p in root["params"]}
        # The 10 documented globals must be among root's own params.
        for name in (
            "profile",
            "api_token",
            "api_version",
            "output",
            "query",
            "verbose",
            "debug",
            "yes",
            "dry_run",
            "version",
        ):
            assert name in own_param_names, name

        skill = next(c for c in root["commands"] if c["name"] == "skill")
        assert "global_params" in skill
        skill_global_names = {p["name"] for p in skill["global_params"]}
        assert {
            "profile",
            "api_token",
            "api_version",
            "output",
            "query",
            "verbose",
            "debug",
            "yes",
            "dry_run",
            "version",
        } <= skill_global_names
        # Completion options are root-only by design — never advertised as globals.
        assert "install_completion" not in skill_global_names
        assert "show_completion" not in skill_global_names

        install = next(c for c in skill["commands"] if c["name"] == "install")
        assert "global_params" in install
        # Leaf still keeps its own --global as a regular param, not a global.
        assert {p["name"] for p in install["params"]} == {"global_"}

    def test_every_leaf_command_has_examples(self, spec: dict) -> None:
        """The binary is the docs — every runnable leaf command must ship
        copy-pasteable examples. `help` itself is exempt (it's a meta-command)."""
        missing: list[str] = []

        def walk(node: dict) -> None:
            if "commands" in node:
                for child in node["commands"]:
                    walk(child)
                return
            path = node["path"].removeprefix("mondo ")
            if path == "help":
                return
            if not node["examples"]:
                missing.append(path)

        walk(spec["root"])
        assert not missing, f"leaf commands without examples: {missing}"


# --- bundled-topic contract ------------------------------------------------


class TestBundledTopics:
    """The prose that used to live in the README is now shipped inside the
    binary. Lock the core topics so a rename or accidental deletion breaks CI
    instead of silently shipping a broken `mondo help codecs`."""

    _REQUIRED_TOPICS = frozenset(
        {
            "agent-workflow",
            "auth",
            "boards-vs-docs",
            "codecs",
            "complexity",
            "exit-codes",
            "filters",
            "graphql",
            "output",
            "profiles",
        }
    )

    def test_required_topics_are_bundled(self) -> None:
        result = runner.invoke(app, ["help"])
        assert result.exit_code == 0, result.output
        for slug in self._REQUIRED_TOPICS:
            assert f"mondo help {slug}" in result.output, f"topic missing: {slug}"

    def test_each_required_topic_renders(self) -> None:
        for slug in self._REQUIRED_TOPICS:
            result = runner.invoke(app, ["help", slug])
            assert result.exit_code == 0, f"{slug}: {result.output}"
            # Topic files always start with a top-level `#` heading.
            assert result.output.startswith("# "), (
                f"{slug} doesn't start with an H1 heading: {result.output[:80]!r}"
            )

    def test_read_topic_returns_content_directly(self) -> None:
        """Direct importlib.resources read — catches accidental deletion or
        _TOPIC_PACKAGE string changes without going through the CLI runner."""
        body = _read_topic("codecs")
        assert body is not None
        assert len(body) > 0

    def test_list_topics_returns_slugs_directly(self) -> None:
        """Direct importlib.resources listing — same guard as above."""
        topics = _list_topics()
        assert "codecs" in topics
        assert "output" in topics
