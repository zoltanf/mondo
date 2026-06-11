"""`--object-id` on doc subcommands + the object-id-vs-internal-id guardrail (#24).

The URL-visible `object_id` (the `/docs/<id>` URL segment) is the only id a
human or a pasted URL ever provides; sending it where the internal id belongs
historically produced an opaque monday 500. Every doc subcommand that targets
a doc now accepts `--object-id` (resolved via a cheap head query), and `--doc`
failures probe whether the id is actually an object id.
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

OBJECT_ID = "5098297247"
INTERNAL_ID = "8519623"


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


def _head_hit() -> dict:
    return _ok(
        {
            "docs": [
                {
                    "id": INTERNAL_ID,
                    "object_id": OBJECT_ID,
                    "name": "Mondo Test Doc",
                    "url": "https://acct.monday.com/docs/" + OBJECT_ID,
                }
            ]
        }
    )


def _bodies(httpx_mock: HTTPXMock) -> list[dict]:
    return [json.loads(r.content) for r in httpx_mock.get_requests()]


class TestExportMarkdownObjectId:
    def test_object_id_resolves_then_exports(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_head_hit())
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "export_markdown_from_doc": {
                        "success": True,
                        "markdown": "# Hello",
                        "error": None,
                    }
                }
            ),
        )
        result = runner.invoke(
            app, ["doc", "export-markdown", "--object-id", OBJECT_ID]
        )
        assert result.exit_code == 0, result.output
        assert result.stdout.strip() == "# Hello"
        head, export = _bodies(httpx_mock)
        assert head["variables"] == {"objs": [int(OBJECT_ID)]}
        assert export["variables"]["doc"] == int(INTERNAL_ID)

    def test_doc_and_object_id_together_is_usage_error(
        self, httpx_mock: HTTPXMock
    ) -> None:
        result = runner.invoke(
            app,
            ["doc", "export-markdown", "--doc", INTERNAL_ID, "--object-id", OBJECT_ID],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_neither_flag_is_usage_error(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["doc", "export-markdown"])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_object_id_miss_exits_6(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"docs": []}))
        result = runner.invoke(
            app, ["doc", "export-markdown", "--object-id", OBJECT_ID]
        )
        assert result.exit_code == 6
        assert "not found" in result.stderr

    def test_500_with_object_id_as_doc_gets_targeted_hint(
        self, httpx_mock: HTTPXMock
    ) -> None:
        # The observed failure: object id sent as --doc → mutation-level 500.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "export_markdown_from_doc": {
                        "success": False,
                        "error": "Fetcher response returned NON-OK status=500 "
                        "statusText=Internal Server Error",
                        "markdown": "",
                    }
                }
            ),
        )
        # Probe resolves the id as an object_id → targeted hint.
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_head_hit())
        result = runner.invoke(app, ["doc", "export-markdown", "--doc", OBJECT_ID])
        assert result.exit_code == 5
        assert "status=500" in result.stderr
        assert f"--object-id {OBJECT_ID}" in result.stderr
        assert "looks like a URL-visible object id" in result.stderr

    def test_graphql_error_with_object_id_as_doc_gets_targeted_hint(
        self, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json={
                "errors": [
                    {
                        "message": "Internal server error",
                        "extensions": {"code": "INTERNAL_SERVER_ERROR"},
                    }
                ]
            },
        )
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_head_hit())
        result = runner.invoke(app, ["doc", "export-markdown", "--doc", OBJECT_ID])
        assert result.exit_code != 0
        assert f"--object-id {OBJECT_ID}" in result.stderr

    def test_500_with_real_internal_id_no_hint(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "export_markdown_from_doc": {
                        "success": False,
                        "error": "boom",
                        "markdown": "",
                    }
                }
            ),
        )
        # Probe misses — the id is not an object id; no hint.
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"docs": []}))
        result = runner.invoke(app, ["doc", "export-markdown", "--doc", INTERNAL_ID])
        assert result.exit_code == 5
        assert "--object-id" not in result.stderr


MUTATION_CASES = [
    (
        ["doc", "rename", "--name", "n"],
        {"update_doc_name": {"id": INTERNAL_ID}},
    ),
    (
        ["doc", "delete"],
        {"delete_doc": {"id": INTERNAL_ID}},
    ),
    (
        ["doc", "add-markdown", "--markdown", "# Hi"],
        {
            "add_content_to_doc_from_markdown": {
                "success": True,
                "block_ids": ["b1"],
                "error": None,
            }
        },
    ),
    (
        ["doc", "version-history"],
        {"doc_version_history": {"points": []}},
    ),
    (
        ["doc", "version-diff", "--date", "2026-01-02", "--prev-date", "2026-01-01"],
        {"doc_version_diff": {"blocks": []}},
    ),
]


class TestUniformObjectIdSurface:
    """Every doc subcommand that targets a doc accepts --doc XOR --object-id."""

    @pytest.mark.parametrize(("args", "payload"), MUTATION_CASES)
    def test_object_id_resolves_to_internal_id(
        self, httpx_mock: HTTPXMock, args: list[str], payload: dict
    ) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_head_hit())
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok(payload))
        result = runner.invoke(app, [*args, "--object-id", OBJECT_ID])
        assert result.exit_code == 0, result.output
        assert _bodies(httpx_mock)[-1]["variables"]["doc"] == int(INTERNAL_ID)

    @pytest.mark.parametrize(
        "args",
        [
            ["doc", "export-markdown"],
            ["doc", "rename", "--name", "n"],
            ["doc", "delete"],
            ["doc", "duplicate"],
            ["doc", "add-markdown", "--markdown", "# Hi"],
            ["doc", "add-block", "--type", "normal_text", "--content", "{}"],
            ["doc", "add-content", "--markdown", "# Hi"],
            ["doc", "version-history"],
            ["doc", "version-diff", "--date", "d", "--prev-date", "p"],
        ],
    )
    def test_both_flags_is_usage_error(
        self, httpx_mock: HTTPXMock, args: list[str]
    ) -> None:
        result = runner.invoke(
            app, [*args, "--doc", INTERNAL_ID, "--object-id", OBJECT_ID]
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_add_block_object_id(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_head_hit())
        # Pre-fetch of existing blocks (append semantics).
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": INTERNAL_ID,
                            "object_id": OBJECT_ID,
                            "name": "D",
                            "blocks": [],
                        }
                    ]
                }
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok({"create_doc_block": {"id": "b9"}})
        )
        result = runner.invoke(
            app,
            [
                "doc", "add-block",
                "--object-id", OBJECT_ID,
                "--type", "normal_text",
                "--content", '{"deltaFormat": [{"insert": "hi"}]}',
            ],
        )
        assert result.exit_code == 0, result.output
        assert _bodies(httpx_mock)[-1]["variables"]["doc"] == int(INTERNAL_ID)

    def test_rename_doc_url_accepted_on_object_id(
        self, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_head_hit())
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_doc_name": {"id": INTERNAL_ID}}),
        )
        result = runner.invoke(
            app,
            [
                "doc", "rename",
                "--object-id", f"https://acct.monday.com/docs/{OBJECT_ID}",
                "--name", "renamed",
            ],
        )
        assert result.exit_code == 0, result.output
        assert _bodies(httpx_mock)[-1]["variables"]["doc"] == int(INTERNAL_ID)
