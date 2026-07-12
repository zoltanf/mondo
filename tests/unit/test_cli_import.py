"""End-to-end CLI tests for `mondo import board ...`."""

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


COLS_RESPONSE = _ok(
    {
        "boards": [
            {
                "id": "42",
                "name": "B",
                "columns": [
                    {
                        "id": "status",
                        "title": "Status",
                        "type": "status",
                        "settings_str": "{}",
                        "archived": False,
                    },
                    {
                        "id": "date4",
                        "title": "Due",
                        "type": "date",
                        "settings_str": "{}",
                        "archived": False,
                    },
                ],
            }
        ]
    }
)


def _write_csv(path: Path, rows: list[str]) -> None:
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


class TestBasicImport:
    def test_two_rows(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        src = tmp_path / "items.csv"
        _write_csv(
            src,
            [
                "name,Status,Due",
                "Alpha,Done,2026-04-25",
                "Beta,Working on it,",
            ],
        )
        # Preflight (columns) + two create_item mutations.
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "1", "name": "Alpha"}}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "2", "name": "Beta"}}),
        )
        result = runner.invoke(app, ["import", "board", "--board", "42", "--from", str(src)])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["summary"]["created"] == 2
        assert parsed["summary"]["failed"] == 0
        # Check that the status codec picked "Done" (index 0/ label)
        second_body = json.loads(httpx_mock.get_requests()[1].content)
        values = json.loads(second_body["variables"]["values"])
        assert values["status"] == {"label": "Done"}
        assert values["date4"] == {"date": "2026-04-25"}

    def test_empty_name_fails_row(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        src = tmp_path / "i.csv"
        # Second column keeps the line non-blank so DictReader doesn't skip it.
        _write_csv(src, ["name,Status", ",Done"])
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        result = runner.invoke(app, ["import", "board", "--board", "42", "--from", str(src)])
        assert result.exit_code == 1, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["summary"]["failed"] == 1
        assert parsed["summary"]["created"] == 0

    def test_dry_run_no_mutation(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        src = tmp_path / "i.csv"
        _write_csv(src, ["name", "Alpha", "Beta"])
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        result = runner.invoke(
            app,
            ["--dry-run", "import", "board", "--board", "42", "--from", str(src)],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["summary"]["created"] == 0
        assert all(r["status"] == "dry-run" for r in parsed["results"])
        # Only the preflight query should have been sent.
        assert len(httpx_mock.get_requests()) == 1

    TAGS_COLS_RESPONSE = _ok(
        {
            "boards": [
                {
                    "id": "42",
                    "name": "B",
                    "columns": [
                        {
                            "id": "tags7",
                            "title": "Tags",
                            "type": "tags",
                            "settings_str": "{}",
                            "archived": False,
                        }
                    ],
                }
            ]
        }
    )

    def test_dry_run_tag_names_row_fails_no_mutation(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        # A tags value given as names can't be resolved in --dry-run without a
        # real create_or_get_tag mutation — the row fails instead of writing.
        src = tmp_path / "i.csv"
        _write_csv(src, ["name,Tags", 'Alpha,"urgent,blocked"'])
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=self.TAGS_COLS_RESPONSE)
        result = runner.invoke(
            app,
            ["--dry-run", "import", "board", "--board", "42", "--from", str(src)],
        )
        assert result.exit_code == 1, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["summary"]["failed"] == 1
        assert parsed["summary"]["created"] == 0
        assert parsed["results"][0]["status"] == "failed"
        assert "tag ids in --dry-run" in parsed["results"][0]["error"]
        # Only the read-only defs fetch happened; create_or_get_tag never fired.
        assert all(b"create_or_get_tag" not in r.content for r in httpx_mock.get_requests())

    def test_dry_run_tag_ids_pass_through(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        # Numeric tag ids need no resolution, so the row dry-runs cleanly with
        # only the read-only defs fetch and never touches create_or_get_tag.
        src = tmp_path / "i.csv"
        _write_csv(src, ["name,Tags", 'Alpha,"1001,1002"'])
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=self.TAGS_COLS_RESPONSE)
        result = runner.invoke(
            app,
            ["--dry-run", "import", "board", "--board", "42", "--from", str(src)],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["results"][0]["status"] == "dry-run"
        values = json.loads(parsed["results"][0]["variables"]["values"])
        assert values["tags7"] == {"tag_ids": [1001, 1002]}
        assert all(b"create_or_get_tag" not in r.content for r in httpx_mock.get_requests())


class TestFormulaGuardStrip:
    def test_export_guard_prefix_is_stripped(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        """Round-trip: guarded name, cell, and header land unguarded on monday."""
        cols = _ok(
            {
                "boards": [
                    {
                        "id": "42",
                        "name": "B",
                        "columns": [
                            {
                                "id": "t1",
                                "title": "=Evil",
                                "type": "text",
                                "settings_str": "{}",
                                "archived": False,
                            }
                        ],
                    }
                ]
            }
        )
        src = tmp_path / "i.csv"
        _write_csv(src, ["name,'=Evil", "'=EvilName,'+SUM(A1)"])
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=cols)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "1", "name": "=EvilName"}}),
        )
        result = runner.invoke(app, ["import", "board", "--board", "42", "--from", str(src)])
        assert result.exit_code == 0, result.stdout
        body = json.loads(httpx_mock.get_requests()[1].content)
        assert body["variables"]["name"] == "=EvilName"
        assert json.loads(body["variables"]["values"]) == {"t1": "+SUM(A1)"}

    def test_apostrophe_lead_title_round_trips(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        """A real title that itself starts with '-lead exports verbatim and
        must match the EXACT header first (stripping it would miss)."""
        cols = _ok(
            {
                "boards": [
                    {
                        "id": "42",
                        "name": "B",
                        "columns": [
                            {
                                "id": "t1",
                                "title": "'-Priority",
                                "type": "text",
                                "settings_str": "{}",
                                "archived": False,
                            }
                        ],
                    }
                ]
            }
        )
        src = tmp_path / "i.csv"
        # Export left the already-'-leading title verbatim; import must match it.
        _write_csv(src, ["name,'-Priority", "Alpha,high"])
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=cols)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "1", "name": "Alpha"}}),
        )
        result = runner.invoke(app, ["import", "board", "--board", "42", "--from", str(src)])
        assert result.exit_code == 0, result.stdout
        body = json.loads(httpx_mock.get_requests()[1].content)
        assert json.loads(body["variables"]["values"]) == {"t1": "high"}


class TestMapping:
    def test_explicit_mapping(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        src = tmp_path / "i.csv"
        _write_csv(
            src,
            ["name,Stage,Due Date", "Alpha,Done,2026-04-25"],
        )
        mapping = tmp_path / "map.yaml"
        mapping.write_text(
            "columns:\n  Stage: status\n  Due Date: date4\n",
            encoding="utf-8",
        )
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "1", "name": "Alpha"}}),
        )
        result = runner.invoke(
            app,
            [
                "import",
                "board",
                "--board",
                "42",
                "--from",
                str(src),
                "--mapping",
                str(mapping),
            ],
        )
        assert result.exit_code == 0, result.stdout
        body = json.loads(httpx_mock.get_requests()[1].content)
        values = json.loads(body["variables"]["values"])
        assert "status" in values and "date4" in values

    def test_mapping_honors_formula_lead_title(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        """A mapping keyed on the raw (formula-lead) title is honored even
        though export guarded the CSV header (`=Total` → `'=Total`)."""
        src = tmp_path / "i.csv"
        _write_csv(src, ["name,'=Total", "Alpha,42"])
        mapping = tmp_path / "map.yaml"
        mapping.write_text("columns:\n  '=Total': status\n", encoding="utf-8")
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "1", "name": "Alpha"}}),
        )
        result = runner.invoke(
            app,
            ["import", "board", "--board", "42", "--from", str(src), "--mapping", str(mapping)],
        )
        assert result.exit_code == 0, result.stdout
        body = json.loads(httpx_mock.get_requests()[1].content)
        assert "status" in json.loads(body["variables"]["values"])

    def test_unknown_header_ignored(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        src = tmp_path / "i.csv"
        _write_csv(src, ["name,Mystery,Status", "Alpha,foo,Done"])
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "1", "name": "Alpha"}}),
        )
        result = runner.invoke(app, ["import", "board", "--board", "42", "--from", str(src)])
        assert result.exit_code == 0, result.stdout
        body = json.loads(httpx_mock.get_requests()[1].content)
        values = json.loads(body["variables"]["values"])
        assert "Mystery" not in values
        assert "status" in values


class TestIdSuffixHeaders:
    """Headers like `Notes (text1)` — written by `mondo export board` when a
    column title repeats or shadows a meta field — resolve by the embedded id."""

    @staticmethod
    def _cols(columns: list[dict]) -> dict:
        for c in columns:
            c.setdefault("settings_str", "{}")
            c.setdefault("archived", False)
        return _ok({"boards": [{"id": "42", "name": "B", "columns": columns}]})

    def test_duplicate_title_headers_resolve_by_id(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        src = tmp_path / "i.csv"
        _write_csv(src, ["name,Notes (text1),Notes (text2)", "Alpha,first,second"])
        cols = self._cols(
            [
                {"id": "text1", "title": "Notes", "type": "text"},
                {"id": "text2", "title": "Notes", "type": "text"},
            ]
        )
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=cols)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "1", "name": "Alpha"}}),
        )
        result = runner.invoke(app, ["import", "board", "--board", "42", "--from", str(src)])
        assert result.exit_code == 0, result.stdout
        body = json.loads(httpx_mock.get_requests()[1].content)
        values = json.loads(body["variables"]["values"])
        assert values["text1"] == "first"
        assert values["text2"] == "second"

    def test_meta_shadow_header_resolves_by_id(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        # A column literally titled "name" exports as "name (text9)".
        src = tmp_path / "i.csv"
        _write_csv(src, ["name,name (text9)", "Alpha,shadowed"])
        cols = self._cols([{"id": "text9", "title": "name", "type": "text"}])
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=cols)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "1", "name": "Alpha"}}),
        )
        result = runner.invoke(app, ["import", "board", "--board", "42", "--from", str(src)])
        assert result.exit_code == 0, result.stdout
        body = json.loads(httpx_mock.get_requests()[1].content)
        assert body["variables"]["name"] == "Alpha"
        values = json.loads(body["variables"]["values"])
        assert values["text9"] == "shadowed"

    def test_literal_paren_title_still_matches_by_title(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        # "(mm)" is not a column id on the board, so the header must fall
        # through to the plain title match, not be dropped.
        src = tmp_path / "i.csv"
        _write_csv(src, ["name,Size (mm)", "Alpha,120"])
        cols = self._cols([{"id": "text1", "title": "Size (mm)", "type": "text"}])
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=cols)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "1", "name": "Alpha"}}),
        )
        result = runner.invoke(app, ["import", "board", "--board", "42", "--from", str(src)])
        assert result.exit_code == 0, result.stdout
        body = json.loads(httpx_mock.get_requests()[1].content)
        values = json.loads(body["variables"]["values"])
        assert values["text1"] == "120"

    def test_export_labels_round_trip_to_import_resolution(self) -> None:
        # The contract: whatever header `mondo export board` writes for a
        # column, `mondo import board` must resolve back to that column's id.
        from mondo.cli.export import _column_labels
        from mondo.cli.import_ import _build_header_to_column_id

        columns = [
            {"id": "text1", "title": "Notes", "type": "text"},
            {"id": "text2", "title": "Notes", "type": "text"},
            {"id": "text9", "title": "name", "type": "text"},
            {"id": "status", "title": "Status", "type": "status"},
        ]
        labels = _column_labels(columns)
        resolved = _build_header_to_column_id(
            headers=["name", *labels],
            mapping={},
            board_columns=columns,
            name_col="name",
            group_col="group",
        )
        assert [resolved[label] for label in labels] == [c["id"] for c in columns]


class TestIdempotency:
    def test_skips_existing(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        src = tmp_path / "i.csv"
        _write_csv(src, ["name", "Alpha", "Beta"])
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        # Pre-fetch of existing names (single page)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "items_page": {
                                "cursor": None,
                                "items": [
                                    {"id": "99", "name": "Alpha"},
                                ],
                            }
                        }
                    ]
                }
            ),
        )
        # Only Beta should be created
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "100", "name": "Beta"}}),
        )
        result = runner.invoke(
            app,
            [
                "import",
                "board",
                "--board",
                "42",
                "--from",
                str(src),
                "--idempotency-name",
            ],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["summary"] == {"created": 1, "skipped": 1, "failed": 0, "total": 2}
        skipped_row = next(r for r in parsed["results"] if r["status"] == "skipped")
        assert skipped_row["name"] == "Alpha"


class TestGroup:
    def test_default_group_applied(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        src = tmp_path / "i.csv"
        _write_csv(src, ["name", "Alpha"])
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "1", "name": "Alpha"}}),
        )
        result = runner.invoke(
            app,
            [
                "import",
                "board",
                "--board",
                "42",
                "--from",
                str(src),
                "--group",
                "topics",
            ],
        )
        assert result.exit_code == 0, result.stdout
        body = json.loads(httpx_mock.get_requests()[1].content)
        assert body["variables"]["group"] == "topics"

    def test_per_row_group_overrides_default(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        src = tmp_path / "i.csv"
        _write_csv(src, ["name,group", "Alpha,grp_a", "Beta,"])
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "1", "name": "Alpha"}}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "2", "name": "Beta"}}),
        )
        result = runner.invoke(
            app,
            [
                "import",
                "board",
                "--board",
                "42",
                "--from",
                str(src),
                "--group",
                "grp_default",
            ],
        )
        assert result.exit_code == 0, result.stdout
        b1 = json.loads(httpx_mock.get_requests()[1].content)
        b2 = json.loads(httpx_mock.get_requests()[2].content)
        assert b1["variables"]["group"] == "grp_a"
        assert b2["variables"]["group"] == "grp_default"

    def test_group_cell_guard_is_stripped(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        # Export guards the group cell like any other; import must strip it
        # back off so a formula-lead group id/title round-trips.
        src = tmp_path / "i.csv"
        _write_csv(src, ["name,group", "Alpha,'=grp"])
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "1", "name": "Alpha"}}),
        )
        result = runner.invoke(app, ["import", "board", "--board", "42", "--from", str(src)])
        assert result.exit_code == 0, result.stdout
        body = json.loads(httpx_mock.get_requests()[1].content)
        assert body["variables"]["group"] == "=grp"


class TestCsvErrors:
    def test_missing_name_column_exits_2(self, tmp_path: Path) -> None:
        # The name-header check happens before the board preflight, so no
        # HTTP mock is needed.
        src = tmp_path / "bad.csv"
        _write_csv(src, ["title,Status", "Alpha,Done"])
        result = runner.invoke(app, ["import", "board", "--board", "42", "--from", str(src)])
        assert result.exit_code == 2
        assert "--name-column" in result.stderr

    def test_file_not_found(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "import",
                "board",
                "--board",
                "42",
                "--from",
                str(tmp_path / "nope.csv"),
            ],
        )
        assert result.exit_code == 2
