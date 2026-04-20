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

    def test_unfiltered_omits_workspace_ids_arg(self, httpx_mock: HTTPXMock) -> None:
        """Monday silently scopes docs() to a single workspace when
        `workspace_ids: null` is sent. Unfiltered `doc list` must omit the
        arg entirely so monday returns docs across every accessible workspace.
        """
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"docs": []}))
        result = runner.invoke(app, ["doc", "list"])
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        for forbidden in ("ids: $ids", "object_ids:", "workspace_ids:", "order_by:"):
            assert forbidden not in body["query"], (
                f"{forbidden} leaked into unfiltered query: {body['query']}"
            )
        assert body["variables"].keys() == {"limit", "page"}


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

    def test_accepts_url_for_object_id(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "7",
                            "object_id": "99",
                            "name": "X",
                            "blocks": [],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(
            app,
            [
                "doc",
                "get",
                "--object-id",
                "https://marktguru.monday.com/boards/99",
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert _last_body(httpx_mock)["variables"] == {"objs": [99]}

    def test_accepts_url_for_id(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "docs": [
                        {
                            "id": "7",
                            "object_id": "77",
                            "name": "X",
                            "blocks": [],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(
            app,
            ["doc", "get", "--id", "https://marktguru.monday.com/boards/7"],
        )
        assert result.exit_code == 0, result.stdout
        assert _last_body(httpx_mock)["variables"] == {"ids": [7]}

    def test_not_found_falls_back_to_board_get(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"docs": []}))
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "99", "name": "Real board", "type": "board"}]}),
        )
        result = runner.invoke(app, ["doc", "get", "--object-id", "99"])
        assert result.exit_code == 6
        assert "regular board" in result.stderr
        assert "mondo board get 99" in result.stderr

    def test_not_found_generic_when_board_also_missing(
        self, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"docs": []}))
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": []}))
        result = runner.invoke(app, ["doc", "get", "--object-id", "99"])
        assert result.exit_code == 6
        assert "not found" in result.stderr
        assert "regular board" not in result.stderr

    def test_not_found_no_fallback_for_internal_id(
        self, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"docs": []}))
        result = runner.invoke(app, ["doc", "get", "--id", "999"])
        assert result.exit_code == 6
        # Only one HTTP call — no BOARD_GET probe on --id path.
        assert len(httpx_mock.get_requests()) == 1


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
    def test_add_block_single_on_empty_doc(self, httpx_mock: HTTPXMock) -> None:
        # Pre-fetch: empty doc → no `after` seed
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "10", "blocks": []}]}),
        )
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

    def test_add_block_single_seeds_from_last_block(self, httpx_mock: HTTPXMock) -> None:
        # Pre-fetch: doc has blocks → `after` seeds from last block id
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"docs": [{"id": "10", "blocks": [{"id": "last-block"}]}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_doc_block": {"id": "b1", "type": "divider"}}),
        )
        result = runner.invoke(
            app,
            [
                "doc",
                "add-block",
                "--doc",
                "10",
                "--type",
                "divider",
                "--content",
                "{}",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["after"] == "last-block"

    def test_add_block_with_after_and_parent(self, httpx_mock: HTTPXMock) -> None:
        # Explicit --after skips the pre-fetch
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
        # Only one HTTP request (no pre-fetch when --after is explicit)
        assert len(httpx_mock.get_requests()) == 1

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
        # content must be a JSON-encoded STRING for monday's JSON scalar, not
        # a raw object (matches the create_doc_block pattern).
        assert isinstance(v["content"], str)
        assert json.loads(v["content"]) == {"deltaFormat": [{"insert": "new"}]}

    def test_delete_block(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_doc_block": {"id": "b1"}}),
        )
        result = runner.invoke(app, ["doc", "delete-block", "--id", "b1"])
        assert result.exit_code == 0, result.stdout
