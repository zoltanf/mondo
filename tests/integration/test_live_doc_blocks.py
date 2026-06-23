"""Live integration tests for per-block doc editing and HTML/markdown
import paths not covered by the markdown round-trip suite:
`doc add-block`, `doc update-block`, `doc delete-block`, `doc replace`,
`doc import-html`, and a tolerant smoke for `doc version-history`.

Each test creates its own throwaway workspace doc and hard-deletes it.
Block content uses monday's `deltaFormat` shape; block ids are
globally-unique so `update-block`/`delete-block` take `--id` (not
`--object-id`).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from ._helpers import CleanupPlan, invoke, invoke_json, wait_for


def _new_doc(workspace_id: int, cleanup_plan: CleanupPlan, label: str) -> dict[str, Any]:
    suffix = uuid.uuid4().hex[:8]
    doc = invoke_json(
        ["doc", "create", "--workspace", str(workspace_id), "--name", f"E2E {label} {suffix}"]
    )
    cleanup_plan.add(f"doc {doc['id']}", "doc", "delete", "--doc", str(doc["id"]))
    return doc


def _blocks(object_id: int | str) -> list[dict[str, Any]]:
    got = invoke_json(["doc", "get", "--object-id", str(object_id), "--no-cache"])
    return got.get("blocks") or []


@pytest.mark.integration
def test_live_doc_add_update_delete_block(
    live_workspace_id: int, cleanup_plan: CleanupPlan
) -> None:
    doc = _new_doc(live_workspace_id, cleanup_plan, "Blocks")
    object_id = doc["object_id"]

    added = invoke_json(
        [
            "doc",
            "add-block",
            "--object-id",
            str(object_id),
            "--type",
            "normal_text",
            "--content",
            json.dumps({"deltaFormat": [{"insert": "first block"}]}),
        ]
    )
    block_id = added["id"]

    def _added() -> None:
        payload = json.dumps(_blocks(object_id))
        assert block_id in payload and "first block" in payload, payload

    wait_for("block added", _added)

    invoke_json(
        [
            "doc",
            "update-block",
            "--id",
            block_id,
            "--content",
            json.dumps({"deltaFormat": [{"insert": "updated block"}]}),
        ]
    )

    def _updated() -> None:
        payload = json.dumps(_blocks(object_id))
        assert "updated block" in payload, payload

    wait_for("block updated", _updated)

    invoke_json(["doc", "delete-block", "--id", block_id])

    def _deleted() -> None:
        ids = {b.get("id") for b in _blocks(object_id)}
        assert block_id not in ids, f"block {block_id} still present"

    wait_for("block deleted", _deleted)


@pytest.mark.integration
def test_live_doc_replace(live_workspace_id: int, cleanup_plan: CleanupPlan) -> None:
    """`doc replace` swaps the full body in place; the doc id is preserved."""
    doc = _new_doc(live_workspace_id, cleanup_plan, "Replace")
    object_id = doc["object_id"]

    invoke_json(
        [
            "doc",
            "add-markdown",
            "--object-id",
            str(object_id),
            "--markdown",
            "# Original\n\noriginal body",
        ]
    )

    result = invoke_json(
        [
            "doc",
            "replace",
            "--object-id",
            str(object_id),
            "--markdown",
            "# Replaced\n\nbrand new body",
        ]
    )
    assert result.get("success") is True, result

    def _replaced() -> None:
        md = invoke(
            [
                "doc", "get", "--object-id", str(object_id),
                "--format", "markdown", "--engine", "server", "--no-cache",
            ]
        ).stdout
        assert "Replaced" in md and "Original" not in md, md

    wait_for("doc replaced", _replaced)


@pytest.mark.integration
def test_live_doc_import_html(live_workspace_id: int, cleanup_plan: CleanupPlan) -> None:
    """`doc import-html` creates a new doc from HTML; returns {success, doc_id}."""
    suffix = uuid.uuid4().hex[:8]
    result = invoke_json(
        [
            "doc",
            "import-html",
            "--workspace",
            str(live_workspace_id),
            "--html",
            "<h1>E2E HTML Import</h1><p>imported body text</p>",
            "--title",
            f"E2E HTML {suffix}",
        ]
    )
    assert result.get("success") is True, result
    doc_id = result["doc_id"]
    cleanup_plan.add(f"html doc {doc_id}", "doc", "delete", "--doc", str(doc_id))

    def _has_content() -> None:
        got = invoke_json(["doc", "get", "--doc", str(doc_id), "--no-cache"])
        payload = json.dumps(got.get("blocks") or [])
        assert "imported body" in payload or "HTML Import" in payload, payload

    wait_for("imported html content present", _has_content)


@pytest.mark.integration
def test_live_doc_version_history_smoke(live_workspace_id: int, cleanup_plan: CleanupPlan) -> None:
    """`doc version-history` (API 2026-04+) is exercised for command wiring.

    monday's `doc_version_history` field is absent before 2026-04 and is
    currently server-side unstable on a fresh doc, so we only assert the
    command itself is wired (no usage/auth error) and, when it does return,
    yields a list.
    """
    doc = _new_doc(live_workspace_id, cleanup_plan, "Versions")
    result = invoke(
        [
            "--api-version",
            "2026-04",
            "doc",
            "version-history",
            "--object-id",
            str(doc["object_id"]),
        ],
        expect_exit=None,
    )
    # 0 = data returned (a list). 1 = the known monday-side instability on
    # the `doc_version_history` endpoint — accepted ONLY when the error is an
    # internal server error, so a real schema/query regression (e.g. "Cannot
    # query field", auth, or a usage error) still fails the test loudly.
    assert result.exit_code in (0, 1), result.stderr
    if result.exit_code == 0:
        assert isinstance(json.loads(result.stdout), list)
    else:
        err = result.stderr.lower()
        assert "internal server error" in err or "internal_server_error" in err, (
            f"version-history failed for an unexpected reason: {result.stderr}"
        )
