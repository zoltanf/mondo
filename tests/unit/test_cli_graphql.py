"""End-to-end CLI tests for `mondo graphql` using pytest-httpx."""

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
    """Isolate each test from the user's real config and env."""
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "test-token-12345-abcdef-long-enough")


def test_graphql_sends_query_and_prints_envelope(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json={"data": {"me": {"id": "1", "name": "Alice"}}, "extensions": {"request_id": "r"}},
    )
    result = runner.invoke(app, ["graphql", "query { me { id name } }"])
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["data"]["me"]["name"] == "Alice"


def test_graphql_with_variables(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json={"data": {"items": [{"id": "1"}]}, "extensions": {"request_id": "r"}},
    )
    result = runner.invoke(
        app,
        [
            "graphql",
            "query ($ids: [ID!]!) { items(ids:$ids) { id } }",
            "--vars",
            '{"ids":[1,2,3]}',
        ],
    )
    assert result.exit_code == 0, result.stdout
    req = httpx_mock.get_request()
    body = json.loads(req.content)  # type: ignore[union-attr]
    assert body["variables"] == {"ids": [1, 2, 3]}


def test_graphql_bad_variables_exits_2() -> None:
    result = runner.invoke(app, ["graphql", "query { me { id } }", "--vars", "not json"])
    assert result.exit_code == 2


def test_graphql_auth_error_exits_3(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        status_code=401,
        text="Unauthorized",
    )
    result = runner.invoke(app, ["graphql", "query { me { id } }"])
    assert result.exit_code == 3


def test_graphql_query_from_file(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    q = tmp_path / "q.graphql"
    q.write_text("query { me { id } }")
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json={"data": {"me": {"id": "1"}}},
    )
    result = runner.invoke(app, ["graphql", f"@{q}"])
    assert result.exit_code == 0, result.stdout
    body = json.loads(httpx_mock.get_request().content)  # type: ignore[union-attr]
    assert body["query"] == "query { me { id } }"


def test_graphql_hint_when_q_swallowed_query() -> None:
    """User typed `mondo graphql -q 'query { … }'`. After `reorder_argv`,
    Typer parses `-q` as the global JMESPath and dispatches `graphql` with
    no positional. Emit a targeted recovery hint instead of the generic
    "Missing argument 'QUERY'" message.
    """
    # Reordered form, matching what `main()` produces from the user's argv.
    result = runner.invoke(app, ["-q", "query { me { id } }", "graphql"])
    assert result.exit_code != 0
    combined = ((result.stdout or "") + (result.stderr or "")).lower()
    assert "graphql query" in combined and "-q" in combined
    assert "positional" in combined


def test_graphql_hint_only_when_q_looks_like_graphql() -> None:
    """A real JMESPath in -q (e.g. 'data.me.id') without a positional should
    still error, but without the GraphQL-payload hint (it'd be misleading)."""
    result = runner.invoke(app, ["-q", "data.me.id", "graphql"])
    assert result.exit_code != 0
    combined = ((result.stdout or "") + (result.stderr or "")).lower()
    assert "passed to" not in combined


def test_graphql_dry_run_refuses_mutation(httpx_mock: HTTPXMock) -> None:
    """`mondo graphql --dry-run '<mutation>'` must NOT send the request.

    Regression for issue #5: silent execution under --dry-run was deemed
    more dangerous than refusing the flag. The raw passthrough can't
    safely preview (mondo doesn't parse the query), so --dry-run is
    rejected with exit 2.
    """
    result = runner.invoke(
        app,
        ["--dry-run", "graphql", "mutation { delete_item (item_id: 1) { id } }"],
    )
    assert result.exit_code == 2, result.stdout
    combined = ((result.stdout or "") + (result.stderr or "")).lower()
    assert "--dry-run" in combined
    assert "not supported" in combined
    # And critically: no HTTP request was issued.
    assert httpx_mock.get_requests() == []


def test_graphql_dry_run_refuses_query_too(httpx_mock: HTTPXMock) -> None:
    """Refusal is unconditional — not heuristic on mutation/query.

    Sniffing the query text for `mutation` is fragile (whitespace,
    aliases, multi-document). Since `--dry-run` on raw GraphQL has no
    safe semantics, we refuse for any operation.
    """
    result = runner.invoke(
        app,
        ["--dry-run", "graphql", "query { me { id name } }"],
    )
    assert result.exit_code == 2, result.stdout
    combined = ((result.stdout or "") + (result.stderr or "")).lower()
    assert "--dry-run" in combined
    assert httpx_mock.get_requests() == []


def test_graphql_dry_run_refused_before_file_load(tmp_path: Path) -> None:
    """Dry-run check must run before `_load_query` slurps `@path`.

    If the user passes `--dry-run` plus `@nonexistent.graphql`, they
    should see the dry-run refusal — not a FileNotFoundError. Confirms
    the flag is rejected before any side-effects.
    """
    nope = tmp_path / "does-not-exist.graphql"
    result = runner.invoke(app, ["--dry-run", "graphql", f"@{nope}"])
    assert result.exit_code == 2, result.stdout
    combined = ((result.stdout or "") + (result.stderr or "")).lower()
    assert "--dry-run" in combined
    # Specifically NOT a file-system error.
    assert "no such file" not in combined
    assert "filenotfounderror" not in combined


def test_graphql_dry_run_refusal_propagates_exit_code_through_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`main()` must surface `typer.Exit(code=2)` as `sys.exit(2)`.

    The `CliRunner.invoke` path uses `standalone_mode=True`, where Click
    converts `Exit(N)` into `SystemExit(N)`. The console-script entry
    point uses `standalone_mode=False`, where Click swallows `Exit` and
    returns the code as `app()`'s return value. Without explicit
    propagation in `main()`, the user-facing CLI exits 0 even when the
    refusal fired — defeating the safety purpose of issue #5's fix.
    """
    from mondo.cli.main import main

    monkeypatch.setattr(
        "sys.argv",
        ["mondo", "--dry-run", "graphql", "mutation { delete_item(item_id: 1) { id } }"],
    )
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 2


def test_graphql_dry_run_refused_before_vars_parse() -> None:
    """Dry-run check must run before `--vars` is parsed.

    With `--dry-run` and malformed `--vars`, the user should see the
    dry-run refusal — not the vars-parse error. Confirms ordering.
    """
    result = runner.invoke(
        app,
        ["--dry-run", "graphql", "mutation { noop }", "--vars", "not json"],
    )
    assert result.exit_code == 2, result.stdout
    combined = ((result.stdout or "") + (result.stderr or "")).lower()
    assert "--dry-run" in combined
    # Specifically NOT the JSON parse error from --vars.
    assert "--variables" not in combined or "not supported" in combined
