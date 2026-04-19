"""End-to-end CLI tests for `mondo doc ...` — workspace docs (Phase 3e)."""

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


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


def _last_body(httpx_mock: HTTPXMock) -> dict:
    return json.loads(httpx_mock.get_requests()[-1].content)


# --- list ---


class TestList:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {"id": "1", "object_id": "100", "name": "A"},
                        {"id": "2", "object_id": "200", "name": "B"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["doc", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [d["id"] for d in parsed] == ["1", "2"]

    def test_filters(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"docs": []}))
        result = runner.invoke(
            app,
            [
                "doc",
                "list",
                "--workspace",
                "42",
                "--workspace",
                "43",
                "--object-id",
                "100",
                "--order-by",
                "used_at",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["workspaceIds"] == [42, 43]
        assert v["objectIds"] == [100]
        assert v["orderBy"] == "used_at"


# --- get ---


class TestGet:
    def test_by_id(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "7",
                            "object_id": "77",
                            "name": "Spec",
                            "blocks": [],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["doc", "get", "--id", "7"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["id"] == "7"

    def test_by_object_id(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "7",
                            "object_id": "77",
                            "blocks": [],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["doc", "get", "--object-id", "77"])
        assert result.exit_code == 0, result.stdout

    def test_requires_one_of_id_object_id(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["doc", "get"])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_both_id_and_object_id_exit_2(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["doc", "get", "--id", "1", "--object-id", "2"])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_markdown_format(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "7",
                            "blocks": [
                                {
                                    "id": "b1",
                                    "type": "normal_text",
                                    "content": {"deltaFormat": [{"insert": "Hi"}]},
                                }
                            ],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["doc", "get", "--id", "7", "--format", "markdown"])
        assert result.exit_code == 0, result.stdout
        assert "Hi" in result.stdout

    def test_missing_exits_6(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"docs": []}))
        result = runner.invoke(app, ["doc", "get", "--id", "999"])
        assert result.exit_code == 6


# --- create ---


class TestCreate:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "create_doc": {
                        "id": "10",
                        "object_id": "100",
                        "name": "New",
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            [
                "doc",
                "create",
                "--workspace",
                "42",
                "--name",
                "New",
                "--kind",
                "private",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"workspace": 42, "name": "New", "kind": "private"}


# --- blocks ---


class TestBlocks:
    def test_add_block_single(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_doc_block": {"id": "b1", "type": "normal_text"}}),
        )
        result = runner.invoke(
            app,
            [
                "doc",
                "add-block",
                "--doc",
                "10",
                "--type",
                "normal_text",
                "--content",
                '{"deltaFormat":[{"insert":"hi"}]}',
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["doc"] == 10
        assert v["type"] == "normal_text"
        assert json.loads(v["content"]) == {"deltaFormat": [{"insert": "hi"}]}
        assert v["after"] is None
        assert v["parent"] is None

    def test_add_block_with_after_and_parent(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_doc_block": {"id": "b1"}}),
        )
        result = runner.invoke(
            app,
            [
                "doc",
                "add-block",
                "--doc",
                "10",
                "--type",
                "normal_text",
                "--content",
                '{"deltaFormat":[{"insert":"hi"}]}',
                "--after",
                "pre",
                "--parent-block",
                "parent",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["after"] == "pre"
        assert v["parent"] == "parent"

    def test_add_block_invalid_json(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            [
                "doc",
                "add-block",
                "--doc",
                "10",
                "--type",
                "normal_text",
                "--content",
                "{not json",
            ],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_add_content_from_markdown(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        src = tmp_path / "spec.md"
        src.write_text("# Title\n\nParagraph.\n\n- one\n- two\n")
        # Pre-fetch for existing doc blocks (empty doc → first append has after=None)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "10", "blocks": []}]}),
        )
        # 4 blocks → 4 singular create_doc_block calls. Chain via after_block_id.
        for block_id in ("b1", "b2", "b3", "b4"):
            httpx_mock.add_response(
                url=ENDPOINT,
                method="POST",
                json=_ok({"create_doc_block": {"id": block_id, "type": "normal_text"}}),
            )
        result = runner.invoke(
            app,
            [
                "doc",
                "add-content",
                "--doc",
                "10",
                "--from-file",
                str(src),
            ],
        )
        assert result.exit_code == 0, result.stdout
        bodies = [json.loads(r.content) for r in httpx_mock.get_requests()]
        # 1 pre-fetch + one request per block
        assert len(bodies) == 5
        # First create call has no `after` (empty doc); subsequent chain
        assert bodies[1]["variables"]["after"] is None
        assert bodies[2]["variables"]["after"] == "b1"
        assert bodies[3]["variables"]["after"] == "b2"
        assert bodies[4]["variables"]["after"] == "b3"

    def test_add_content_seeds_from_last_block_on_nonempty_doc(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        """Append semantics: if the doc already has blocks, the first new
        block goes after the existing last one (monday's default for
        after=null is TOP insert, which breaks append)."""
        src = tmp_path / "spec.md"
        src.write_text("Paragraph\n")
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {"docs": [{"id": "10", "blocks": [{"id": "existing-last", "type": "quote"}]}]}
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_doc_block": {"id": "new-b1", "type": "normal_text"}}),
        )
        result = runner.invoke(
            app,
            ["doc", "add-content", "--doc", "10", "--from-file", str(src)],
        )
        assert result.exit_code == 0, result.stdout
        bodies = [json.loads(r.content) for r in httpx_mock.get_requests()]
        assert bodies[1]["variables"]["after"] == "existing-last"

    def test_add_content_empty_input_exit_5(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        empty = tmp_path / "e.md"
        empty.write_text("")
        result = runner.invoke(
            app,
            ["doc", "add-content", "--doc", "10", "--from-file", str(empty)],
        )
        assert result.exit_code == 5
        assert httpx_mock.get_requests() == []

    def test_update_block(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_doc_block": {"id": "b1", "type": "normal_text"}}),
        )
        result = runner.invoke(
            app,
            [
                "doc",
                "update-block",
                "--id",
                "b1",
                "--content",
                '{"deltaFormat":[{"insert":"new"}]}',
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["block"] == "b1"
        assert v["content"] == {"deltaFormat": [{"insert": "new"}]}

    def test_delete_block(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_doc_block": {"id": "b1"}}),
        )
        result = runner.invoke(app, ["doc", "delete-block", "--id", "b1"])
        assert result.exit_code == 0, result.stdout
