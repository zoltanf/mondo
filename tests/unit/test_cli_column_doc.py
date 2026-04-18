"""End-to-end CLI tests for `mondo column doc ...`."""

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
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


def _context_for_doc_column(raw_value: str | None) -> dict:
    """Response shape for `COLUMN_CONTEXT` when the target is a doc column."""
    return _ok(
        {
            "items": [
                {
                    "id": "1",
                    "name": "Spec item",
                    "board": {
                        "id": "42",
                        "columns": [
                            {"id": "spec", "title": "Spec", "type": "doc", "settings_str": "{}"},
                        ],
                    },
                    "column_values": [
                        {
                            "id": "spec",
                            "type": "doc",
                            "text": "",
                            "value": raw_value,
                        }
                    ]
                    if raw_value is not None
                    else [],
                }
            ]
        }
    )


_DOC_COLUMN_VALUE = json.dumps(
    {
        "files": [
            {
                "linkToFile": "https://x/docs/5000",
                "fileType": "MONDAY_DOC",
                "docId": 700,
                "objectId": 5000,
            }
        ]
    }
)


# --- get ---


class TestDocGet:
    def test_markdown_default(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_context_for_doc_column(_DOC_COLUMN_VALUE)
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "700",
                            "object_id": 5000,
                            "name": "Spec",
                            "blocks": [
                                {
                                    "type": "heading",
                                    "content": {"deltaFormat": [{"insert": "Spec"}]},
                                },
                                {
                                    "type": "normal_text",
                                    "content": {"deltaFormat": [{"insert": "Hello"}]},
                                },
                            ],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["column", "doc", "get", "--item", "1", "--column", "spec"])
        assert result.exit_code == 0, result.stdout
        out = result.stdout
        assert "# Spec" in out
        assert "Hello" in out

    def test_raw_blocks(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_context_for_doc_column(_DOC_COLUMN_VALUE)
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "700",
                            "object_id": 5000,
                            "blocks": [
                                {
                                    "type": "heading",
                                    "content": {"deltaFormat": [{"insert": "Spec"}]},
                                }
                            ],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "doc",
                "get",
                "--item",
                "1",
                "--column",
                "spec",
                "--format",
                "raw-blocks",
            ],
        )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed == [{"type": "heading", "content": {"deltaFormat": [{"insert": "Spec"}]}}]

    def test_empty_column_emits_empty(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_context_for_doc_column(None))
        result = runner.invoke(app, ["column", "doc", "get", "--item", "1", "--column", "spec"])
        assert result.exit_code == 0
        # Markdown path → empty string
        assert result.stdout.strip() in ("", '""')

    def test_non_doc_column_rejected(self, httpx_mock: HTTPXMock) -> None:
        """Passing a non-`doc` column type should not issue docs() lookups."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "items": [
                        {
                            "id": "1",
                            "name": "x",
                            "board": {
                                "id": "42",
                                "columns": [
                                    {
                                        "id": "spec",
                                        "title": "Spec",
                                        "type": "text",
                                        "settings_str": "{}",
                                    },
                                ],
                            },
                            "column_values": [],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["column", "doc", "get", "--item", "1", "--column", "spec"])
        assert result.exit_code != 0
        assert len(httpx_mock.get_requests()) == 1


# --- set ---


class TestDocSet:
    def test_creates_doc_when_column_empty(self, httpx_mock: HTTPXMock) -> None:
        # Preflight
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_context_for_doc_column(None))
        # create_doc
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "create_doc": {
                        "id": "700",
                        "object_id": 5000,
                        "url": "https://x/docs/5000",
                    }
                }
            ),
        )
        # create_doc_blocks
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_doc_blocks": [{"id": "b1", "type": "heading"}]}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "doc",
                "set",
                "--item",
                "1",
                "--column",
                "spec",
                "--markdown",
                "# Hello",
            ],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["created"] is True
        assert parsed["doc_id"] == "700"

    def test_appends_to_existing_doc(self, httpx_mock: HTTPXMock) -> None:
        # Preflight — column already has a doc
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_context_for_doc_column(_DOC_COLUMN_VALUE)
        )
        # docs() fetch — surface existing doc id
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "700", "object_id": 5000, "blocks": []}]}),
        )
        # create_doc_blocks
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_doc_blocks": [{"id": "b1", "type": "normal_text"}]}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "doc",
                "set",
                "--item",
                "1",
                "--column",
                "spec",
                "--markdown",
                "New line",
            ],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["created"] is False

    def test_from_file(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        md_file = tmp_path / "spec.md"
        md_file.write_text("# Title\n\nBody.\n")
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_context_for_doc_column(None))
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_doc": {"id": "700", "object_id": 5000, "url": "u"}}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_doc_blocks": [{"id": "b1", "type": "heading"}]}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "doc",
                "set",
                "--item",
                "1",
                "--column",
                "spec",
                "--from-file",
                str(md_file),
            ],
        )
        assert result.exit_code == 0, result.stdout

    def test_dry_run_skips_mutations(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_context_for_doc_column(None))
        result = runner.invoke(
            app,
            [
                "--dry-run",
                "column",
                "doc",
                "set",
                "--item",
                "1",
                "--column",
                "spec",
                "--markdown",
                "# Hi",
            ],
        )
        assert result.exit_code == 0
        # Only the preflight, no create_doc / create_doc_blocks
        assert len(httpx_mock.get_requests()) == 1
        parsed = json.loads(result.stdout)
        assert "steps" in parsed


# --- append ---


class TestDocAppend:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_context_for_doc_column(_DOC_COLUMN_VALUE)
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "700", "object_id": 5000, "blocks": []}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_doc_blocks": [{"id": "b1", "type": "bullet_list"}]}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "doc",
                "append",
                "--item",
                "1",
                "--column",
                "spec",
                "--markdown",
                "- point one",
            ],
        )
        assert result.exit_code == 0

    def test_refuses_on_empty_doc_column(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_context_for_doc_column(None))
        result = runner.invoke(
            app,
            [
                "column",
                "doc",
                "append",
                "--item",
                "1",
                "--column",
                "spec",
                "--markdown",
                "hi",
            ],
        )
        assert result.exit_code == 2


# --- clear ---


class TestDocClear:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_context_for_doc_column(_DOC_COLUMN_VALUE)
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_value": {"id": "1", "name": "Spec item"}}),
        )
        result = runner.invoke(
            app,
            ["column", "doc", "clear", "--item", "1", "--column", "spec"],
        )
        assert result.exit_code == 0
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["variables"]["value"] == "{}"
