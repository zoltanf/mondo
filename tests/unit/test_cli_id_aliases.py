"""Hidden `--<entity>-id` aliases are accepted everywhere the canonical
flag exists (issue #9).

`MondoCommand.parse_args` rewrites `--item-id` / `--column-id` /
`--group-id` / `--workspace-id` / `--board-id` to their canonical flags
when the command declares the canonical option (see `mondo.cli._alias`).
The aliases never exist as real Click parameters, so they stay out of
`--help` and `--dump-spec` by construction; `--board-id` coverage for
that lives in test_cli_board_id_alias.py and applies to the shared
mechanism.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from mondo.cli._alias import ID_ALIAS_MAP
from mondo.cli.main import app

ENDPOINT = "https://api.monday.com/v2"
FILE_ENDPOINT = "https://api.monday.com/v2/file"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")
    monkeypatch.setenv("MONDO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MONDO_CACHE_ENABLED", "false")


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


def _column_context(board_id: int = 42) -> dict:
    return _ok(
        {
            "items": [
                {
                    "id": "1",
                    "name": "item",
                    "board": {
                        "id": str(board_id),
                        "columns": [
                            {
                                "id": "status",
                                "title": "S",
                                "type": "status",
                                "settings_str": json.dumps({"labels": {"1": "Done"}}),
                            }
                        ],
                    },
                    "column_values": [
                        {"id": "status", "type": "status", "text": "Done", "value": None}
                    ],
                }
            ]
        }
    )


# Each row: (argv, dry_run) — argv uses only alias forms of the flags under
# test. `dry_run=True` rows exercise mutating commands offline; the rest get
# a permissive mocked response. The assertion is parse-level: the alias must
# not be rejected with "No such option".
ALIAS_ACCEPTANCE: list[tuple[list[str], bool]] = [
    # --item-id → --item
    (["column", "get", "--item-id", "1", "--column-id", "status"], False),
    (["column", "set", "--item-id", "1", "--column-id", "status", "--value", "Done"], False),
    (["column", "set-many", "--item-id", "1", "--values", '{"status":{"label":"x"}}'], False),
    (["column", "clear", "--item-id", "1", "--column-id", "status"], False),
    (["update", "list", "--item-id", "1"], False),
    (["update", "create", "--item-id", "1", "--body", "hi"], True),
    # --column-id → --column
    (["column", "get-meta", "--board", "42", "--column-id", "status"], False),
    (["column", "labels", "--board", "42", "--column-id", "status"], False),
    (["item", "find", "--board", "42", "--column-id", "status", "--value", "Done"], False),
    # --group-id → --group
    (["item", "list", "--board", "42", "--group-id", "g1"], False),
    (["item", "create", "--board", "42", "--name", "X", "--group-id", "g1"], True),
    (["item", "move", "--id", "1", "--group-id", "g1"], True),
    (["group", "rename", "--board", "42", "--group-id", "g1", "--title", "New"], True),
    (["-y", "group", "delete", "--board", "42", "--group-id", "g1"], True),
    # --workspace-id → --workspace
    (["board", "create", "--name", "X", "--workspace-id", "7"], True),
    (["doc", "create", "--name", "X", "--workspace-id", "7"], True),
    (["folder", "create", "--name", "X", "--workspace-id", "7"], True),
    (["workspace", "get", "--workspace-id", "7"], False),
    # --board-id → --board beyond the list commands
    (["item", "create", "--board-id", "42", "--name", "X"], True),
    (["item", "rename", "--item-id", "1", "--board-id", "42", "--name", "New"], True),
    (["column", "create", "--board-id", "42", "--title", "T", "--type", "text"], True),
    (["group", "create", "--board-id", "42", "--name", "G"], True),
]


@pytest.mark.parametrize("argv,dry_run", ALIAS_ACCEPTANCE)
def test_alias_is_accepted(argv: list[str], dry_run: bool, httpx_mock: HTTPXMock) -> None:
    if not dry_run:
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_column_context(), is_optional=True, is_reusable=True
        )
    full = (["--dry-run", *argv]) if dry_run else argv
    result = runner.invoke(app, full)
    combined = (result.output or "") + (result.stderr or "")
    assert "No such option" not in combined, f"{' '.join(argv)} rejected: {combined!r}"


def test_column_get_item_id_column_id_end_to_end(httpx_mock: HTTPXMock) -> None:
    """The exact session-log repro: `column get --item-id X --column-id Y`
    behaves identically to the canonical flags."""
    httpx_mock.add_response(url=ENDPOINT, method="POST", json=_column_context())
    result = runner.invoke(app, ["column", "get", "--item-id", "1", "--column-id", "status"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == "Done"


def test_alias_and_canonical_send_identical_requests(httpx_mock: HTTPXMock) -> None:
    for _ in range(2):
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"boards": [{"columns": []}]})
        )
    r1 = runner.invoke(app, ["-o", "json", "column", "list", "--board", "42"])
    r2 = runner.invoke(app, ["-o", "json", "column", "list", "--board-id", "42"])
    assert r1.exit_code == 0 and r2.exit_code == 0
    bodies = [json.loads(r.content) for r in httpx_mock.get_requests()]
    assert bodies[0]["variables"] == bodies[1]["variables"]


def test_canonical_wins_when_both_given(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": [{"columns": []}]}))
    result = runner.invoke(app, ["column", "list", "--board", "42", "--board-id", "99"])
    assert result.exit_code == 0, result.output
    body = json.loads(httpx_mock.get_request().content)
    assert body["variables"]["board"] == 42


def test_equals_form_is_rewritten(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": [{"columns": []}]}))
    result = runner.invoke(app, ["column", "list", "--board-id=42"])
    assert result.exit_code == 0, result.output
    body = json.loads(httpx_mock.get_request().content)
    assert body["variables"]["board"] == 42


def test_alias_without_canonical_keeps_original_error(httpx_mock: HTTPXMock) -> None:
    """`subitem list` takes --parent, not --item: the alias must NOT be
    rewritten there, so the error names the flag the user actually typed
    (and the `_errors.FLAG_ALIAS_HINTS` suggestion still applies)."""
    result = runner.invoke(app, ["subitem", "list", "--item-id", "1"])
    assert result.exit_code == 2
    combined = (result.output or "") + (result.stderr or "")
    assert "--item-id" in combined
    assert httpx_mock.get_requests() == []


@pytest.mark.parametrize(
    "path",
    [
        ["column", "get"],
        ["column", "set"],
        ["item", "create"],
        ["update", "list"],
        ["board", "create"],
        ["workspace", "get"],
    ],
)
def test_aliases_hidden_from_help(path: list[str]) -> None:
    result = runner.invoke(app, [*path, "--help"])
    assert result.exit_code == 0, result.output
    for alias in ID_ALIAS_MAP:
        assert alias not in result.output, f"{' '.join(path)}: {alias} leaked into --help"


def test_dump_spec_exposes_no_aliases() -> None:
    """--dump-spec is the agent contract; no alias flag may appear anywhere."""
    result = runner.invoke(app, ["-o", "json", "help", "--dump-spec"])
    assert result.exit_code == 0
    spec = json.loads(result.output)
    offenders: list[str] = []

    def walk(node: dict) -> None:
        for param in node.get("params", []):
            for flag in param.get("flags") or []:
                if flag in ID_ALIAS_MAP:
                    offenders.append(f"{node.get('path', '<?>')}: {flag}")
        for child in node.get("commands", []):
            walk(child)

    walk(spec["root"])
    assert not offenders, f"alias flags leaked into --dump-spec: {offenders}"
