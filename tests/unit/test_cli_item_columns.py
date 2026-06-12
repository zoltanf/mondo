"""Server-side column selection on `item list` / `item get` (#19).

Two levers, both about not paying the ~3x per-page complexity of the full
`column_values` selection on big boards:

- `--columns col1,col2` → `column_values(ids: $cols)` server-side.
- auto-slim: when `--fields` provably never reads column_values, the
  GraphQL query drops the selection entirely. `-q` never auto-slims: a
  JMESPath can read fields inside predicates yet still return whole rows
  (e.g. `[?contains(name, 'x')]`), so slimming would silently lose data.
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


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


def _items_page(items: list[dict], cursor: str | None = None) -> dict:
    return {"boards": [{"items_page": {"cursor": cursor, "items": items}}]}


def _bodies(httpx_mock: HTTPXMock) -> list[dict]:
    return [json.loads(r.content) for r in httpx_mock.get_requests()]


class TestItemListColumns:
    def test_columns_narrows_server_side(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok(_items_page([{"id": "1"}]))
        )
        result = runner.invoke(
            app, ["item", "list", "--board", "42", "--columns", "status, person"]
        )
        assert result.exit_code == 0, result.output
        body = _bodies(httpx_mock)[-1]
        assert "column_values(ids: $cols)" in body["query"]
        assert body["variables"]["cols"] == ["status", "person"]

    def test_columns_threads_to_next_page(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok(_items_page([{"id": "1"}], cursor="C"))
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"next_items_page": {"cursor": None, "items": [{"id": "2"}]}}),
        )
        result = runner.invoke(
            app, ["item", "list", "--board", "42", "--columns", "status"]
        )
        assert result.exit_code == 0, result.output
        _first, second = _bodies(httpx_mock)
        assert "column_values(ids: $cols)" in second["query"]
        assert second["variables"]["cols"] == ["status"]
        assert second["variables"]["cursor"] == "C"

    def test_columns_composes_with_filter_and_max_items(
        self, httpx_mock: HTTPXMock
    ) -> None:
        # --filter triggers a column-defs preflight before the items_page call.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "id": "42",
                            "name": "B",
                            "columns": [
                                {"id": "text7", "title": "T", "type": "text"}
                            ],
                        }
                    ]
                }
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(_items_page([{"id": "1"}, {"id": "2"}])),
        )
        result = runner.invoke(
            app,
            [
                "item", "list", "--board", "42",
                "--columns", "status",
                "--filter", "text7=x",
                "--max-items", "1",
            ],
        )
        assert result.exit_code == 0, result.output
        body = _bodies(httpx_mock)[-1]
        assert body["variables"]["cols"] == ["status"]
        assert body["variables"]["qp"]["rules"][0]["column_id"] == "text7"
        assert len(json.loads(result.stdout)) == 1

    def test_columns_empty_is_usage_error(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["item", "list", "--board", "42", "--columns", " , "])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_columns_with_parent_is_usage_error(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app, ["item", "list", "--parent", "7", "--columns", "status"]
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_default_keeps_full_column_values(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok(_items_page([{"id": "1"}]))
        )
        result = runner.invoke(app, ["item", "list", "--board", "42"])
        assert result.exit_code == 0
        body = _bodies(httpx_mock)[-1]
        assert "column_values { id type text value }" in body["query"]


class TestItemListAutoSlim:
    def test_fields_id_name_drops_column_values(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(_items_page([{"id": "1", "name": "A"}])),
        )
        result = runner.invoke(
            app, ["--fields", "id,name", "item", "list", "--board", "42"]
        )
        assert result.exit_code == 0, result.output
        assert "column_values" not in _bodies(httpx_mock)[-1]["query"]
        assert json.loads(result.stdout) == [{"id": "1", "name": "A"}]

    def test_fields_dotted_group_still_slims(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok(_items_page([{"id": "1"}]))
        )
        result = runner.invoke(
            app, ["--fields", "id,name,group.title", "item", "list", "--board", "42"]
        )
        assert result.exit_code == 0
        assert "column_values" not in _bodies(httpx_mock)[-1]["query"]

    def test_fields_requesting_column_values_keeps_them(
        self, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok(_items_page([{"id": "1"}]))
        )
        result = runner.invoke(
            app, ["--fields", "id,column_values", "item", "list", "--board", "42"]
        )
        assert result.exit_code == 0
        assert "column_values" in _bodies(httpx_mock)[-1]["query"]

    @pytest.mark.parametrize(
        "expression",
        [
            # Filter-only: returns WHOLE ROW objects, so slimming would
            # silently lose column_values vs the unprojected output.
            "[?contains(name, 'x')]",
            # Projection over "safe" leaves only — still no auto-slim:
            # leaf inspection can't distinguish predicate reads from output.
            "[?group.id=='g1'].{id: id, name: name}",
            # Directly reads column_values.
            "[].column_values[?id=='status'].text",
        ],
    )
    def test_query_only_keeps_full_column_values(
        self, httpx_mock: HTTPXMock, expression: str
    ) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(_items_page([{"id": "1", "name": "Ax"}])),
        )
        result = runner.invoke(app, ["-q", expression, "item", "list", "--board", "42"])
        assert result.exit_code == 0, result.output
        assert "column_values { id type text value }" in _bodies(httpx_mock)[-1]["query"]

    def test_no_projection_keeps_full_shape(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok(_items_page([{"id": "1"}]))
        )
        result = runner.invoke(app, ["item", "list", "--board", "42"])
        assert result.exit_code == 0
        assert "column_values" in _bodies(httpx_mock)[-1]["query"]

    def test_safe_fields_with_query_keeps_them(self, httpx_mock: HTTPXMock) -> None:
        # -q runs before --fields against the raw rows; any -q disables
        # auto-slim even when --fields alone would qualify.
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok(_items_page([{"id": "1"}]))
        )
        result = runner.invoke(
            app,
            [
                "--fields", "id,name",
                "-q", "[?column_values[?text=='x']]",
                "item", "list", "--board", "42",
            ],
        )
        assert result.exit_code == 0
        assert "column_values" in _bodies(httpx_mock)[-1]["query"]

    def test_poll_until_disables_auto_slim(self, httpx_mock: HTTPXMock) -> None:
        # --poll-until evaluates against the raw fetched rows, so its
        # expression may read column_values even when --fields doesn't.
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok(_items_page([{"id": "1"}]))
        )
        result = runner.invoke(
            app,
            [
                "--fields", "id,name",
                "item", "list", "--board", "42",
                "--poll-until", "length(@) > `0`",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "column_values { id type text value }" in _bodies(httpx_mock)[-1]["query"]

    def test_dry_run_shows_cols_variable(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["--dry-run", "item", "list", "--board", "42", "--columns", "status"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert "column_values(ids: $cols)" in payload["query"]
        assert payload["variables"]["cols"] == ["status"]
        assert httpx_mock.get_requests() == []


class TestItemGetColumns:
    def test_get_columns_narrows_server_side(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "items": [
                        {
                            "id": "1",
                            "name": "T",
                            "column_values": [
                                {"id": "status", "type": "status", "text": "Done", "value": "{}"}
                            ],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["item", "get", "--id", "1", "--columns", "status"])
        assert result.exit_code == 0, result.output
        body = _bodies(httpx_mock)[-1]
        assert "column_values(ids: $cols)" in body["query"]
        assert body["variables"] == {"id": 1, "cols": ["status"]}

    def test_get_columns_conflicts_with_include_updates(
        self, httpx_mock: HTTPXMock
    ) -> None:
        result = runner.invoke(
            app, ["item", "get", "--id", "1", "--columns", "status", "--include-updates"]
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_get_columns_bypasses_cache(
        self, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MONDO_CACHE_ENABLED", "true")
        for _ in range(2):
            httpx_mock.add_response(
                url=ENDPOINT,
                method="POST",
                json=_ok({"items": [{"id": "1", "name": "T"}]}),
            )
        first = runner.invoke(app, ["item", "get", "--id", "1", "--columns", "status"])
        second = runner.invoke(app, ["item", "get", "--id", "1", "--columns", "status"])
        assert first.exit_code == 0 and second.exit_code == 0
        # Both invocations hit the API — narrowed shapes are never cached.
        assert len(httpx_mock.get_requests()) == 2
