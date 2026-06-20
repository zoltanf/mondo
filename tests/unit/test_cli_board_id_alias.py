"""--board-id is accepted as a hidden alias for --board on every read
command that takes a board flag.

Friction report A1: agents reach for --board-id (the GraphQL field name is
`board.id`, and several sibling commands surface board ids as `id`) and get
rejected with `No such option`. We accept it everywhere --board is accepted
on a list/get-style command, but hide it from --help so the help layout
stays uncluttered.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from mondo.cli.main import app

ENDPOINT = "https://api.monday.com/v2"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")
    monkeypatch.setenv("MONDO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MONDO_CACHE_ENABLED", "false")


# Each tuple: (command-path tokens, extra args needed to reach the command body,
# stub response payload).  Only commands that take --board *as a flag* are in
# scope.
BOARD_FLAG_COMMANDS: list[tuple[list[str], list[str], dict]] = [
    (
        ["item", "list"],
        [],
        {"boards": [{"items_page": {"cursor": None, "items": []}}]},
    ),
    (
        ["group", "list"],
        [],
        {"boards": [{"groups": []}]},
    ),
    (
        ["column", "list"],
        [],
        {"boards": [{"columns": []}]},
    ),
    (
        ["column", "labels"],
        ["--column", "status"],
        {"boards": [{"columns": [{"id": "status", "type": "status", "settings_str": "{}"}]}]},
    ),
]


@pytest.mark.parametrize("path,extra,stub", BOARD_FLAG_COMMANDS)
def test_board_id_alias_is_accepted(
    path: list[str], extra: list[str], stub: dict, httpx_mock: HTTPXMock
) -> None:
    """--board-id should parse without 'No such option'."""
    # is_optional=True: some commands hit the local cache and never make a
    # network call. We only care that argparse accepts the flag.
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json={"data": stub, "extensions": {"request_id": "r"}},
        is_optional=True,
    )
    result = runner.invoke(app, [*path, "--board-id", "12345", *extra])
    combined = (result.output or "") + (result.stderr or "")
    assert "No such option" not in combined, f"{' '.join(path)} rejected --board-id: {combined!r}"


@pytest.mark.parametrize("path,extra,stub", BOARD_FLAG_COMMANDS)
def test_board_id_alias_hidden_in_help(path: list[str], extra: list[str], stub: dict) -> None:
    """The alias must not appear in --help output (keeps help uncluttered)."""
    result = runner.invoke(app, [*path, "--help"])
    assert result.exit_code == 0, result.output
    assert "--board-id" not in result.output, (
        f"{' '.join(path)}: --board-id appeared in --help; should be hidden"
    )


def test_dump_spec_does_not_expose_board_id_alias() -> None:
    """--dump-spec is the contract surface; hidden aliases must not leak there
    either (otherwise downstream tooling would still recommend the alias)."""
    result = runner.invoke(app, ["-o", "json", "help", "--dump-spec"])
    assert result.exit_code == 0
    spec = json.loads(result.output)
    offenders: list[str] = []

    def walk(node: dict) -> None:
        for param in node.get("params", []):
            if "--board-id" in (param.get("flags") or []):
                offenders.append(node.get("path", "<?>"))
        for child in node.get("commands", []):
            walk(child)

    walk(spec["root"])
    assert not offenders, f"--board-id leaked into --dump-spec at: {offenders}"


def test_board_id_alias_translates_to_same_query(httpx_mock: HTTPXMock) -> None:
    """--board 42 and --board-id 42 should produce identical GraphQL requests.

    This locks in the equivalence so a future refactor doesn't silently make
    the alias mean something different.
    """
    # First invocation: --board
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json={
            "data": {"boards": [{"items_page": {"cursor": None, "items": []}}]},
            "extensions": {"request_id": "r1"},
        },
    )
    r1 = runner.invoke(app, ["-o", "json", "item", "list", "--board", "42"])
    assert r1.exit_code == 0, r1.output

    # Second invocation: --board-id
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json={
            "data": {"boards": [{"items_page": {"cursor": None, "items": []}}]},
            "extensions": {"request_id": "r2"},
        },
    )
    r2 = runner.invoke(app, ["-o", "json", "item", "list", "--board-id", "42"])
    assert r2.exit_code == 0, r2.output

    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    body1 = json.loads(requests[0].content)
    body2 = json.loads(requests[1].content)
    assert body1["variables"] == body2["variables"], (
        f"--board and --board-id sent different variables: "
        f"{body1['variables']!r} vs {body2['variables']!r}"
    )
