"""Live integration tests for the standalone-doc markdown round-trip.

Two contracts:
- Strict subset (headings, paragraphs, lists, blockquotes, code, hr) round-trips.
- Rich markdown (tables, images, inline formatting, nested lists) lossily
  degrades to a stable golden file. Regenerate with MONDO_UPDATE_GOLDEN=1.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any

import pytest

from ._helpers import (
    CleanupPlan,
    invoke,
    invoke_json,
    wait_for,
)

FIXTURES = Path(__file__).parent / "fixtures" / "doc_roundtrip"


def _normalize_md(text: str) -> str:
    """Trim trailing whitespace + collapse blank-line runs (preserves intra-line content)."""
    lines = [line.rstrip() for line in text.splitlines()]
    out: list[str] = []
    blank = False
    for line in lines:
        if line == "":
            if not blank:
                out.append("")
            blank = True
        else:
            out.append(line)
            blank = False
    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


_LIST_PREFIX_RE = re.compile(r"^(\s*)([-*+]|\d+\.)\s+")


def _canonicalize_line(line: str) -> str:
    """Reduce whitespace differences from monday's markdown formatter.

    - Strip leading/trailing whitespace.
    - Collapse runs of internal whitespace to a single space.
    - Normalise the spacing after a list marker (`-  foo` -> `- foo`).
    """
    stripped = line.strip()
    m = _LIST_PREFIX_RE.match(line)
    if m:
        marker = m.group(2)
        rest = line[m.end():].strip()
        return f"{marker} {rest}"
    return re.sub(r"\s+", " ", stripped)


def _create_throwaway_doc(workspace_id: int, name: str, cleanup_plan: CleanupPlan) -> int:
    created = invoke_json(
        [
            "doc", "create",
            "--workspace", str(workspace_id),
            "--name", name,
        ]
    )
    doc_id = int(created["id"])
    cleanup_plan.add(
        f"doc {doc_id}", "doc", "delete", "--doc", str(doc_id),
    )
    return doc_id


@pytest.mark.integration
def test_live_doc_markdown_strict_roundtrip_equality(
    live_workspace_id: int, cleanup_plan: CleanupPlan
) -> None:
    """Headings/lists/blockquote/code/hr round-trip with content-equivalence after normalisation."""
    suffix = uuid.uuid4().hex[:8]
    strict_md = (FIXTURES / "strict_input.md").read_text(encoding="utf-8")
    doc_id = _create_throwaway_doc(
        live_workspace_id, f"E2E Strict MD {suffix}", cleanup_plan
    )

    invoke_json(
        [
            "doc", "add-markdown",
            "--doc", str(doc_id),
            "--markdown", strict_md,
        ]
    )

    def _exported() -> str:
        result = invoke(
            ["doc", "export-markdown", "--doc", str(doc_id)],
            expect_exit=0,
        )
        text = result.stdout
        assert text.strip(), "export-markdown empty"
        return text

    exported = wait_for("doc export visible", _exported)

    # Tolerant comparison: every non-blank input line must appear, in order,
    # in the export, after canonicalising whitespace + list-marker spacing.
    in_lines = [
        _canonicalize_line(line)
        for line in _normalize_md(strict_md).splitlines()
        if line.strip()
    ]
    out_lines = [
        _canonicalize_line(line)
        for line in _normalize_md(exported).splitlines()
        if line.strip()
    ]
    out_idx = 0
    missing: list[str] = []
    for expected in in_lines:
        while out_idx < len(out_lines) and out_lines[out_idx] != expected:
            out_idx += 1
        if out_idx >= len(out_lines):
            missing.append(expected)
        else:
            out_idx += 1
    assert not missing, (
        "strict markdown lines missing from export (round-trip lossy):\n"
        f"missing: {missing}\n--- exported ---\n{exported}"
    )


@pytest.mark.integration
def test_live_doc_markdown_rich_roundtrip_golden(
    live_workspace_id: int, cleanup_plan: CleanupPlan
) -> None:
    """Rich markdown round-trip pinned to a golden file capturing real degradation.

    Regenerate via:
        MONDO_UPDATE_GOLDEN=1 uv run pytest \
            tests/integration/test_live_doc_md_roundtrip.py::test_live_doc_markdown_rich_roundtrip_golden
    """
    suffix = uuid.uuid4().hex[:8]
    rich_md = (FIXTURES / "rich_input.md").read_text(encoding="utf-8")
    golden_path = FIXTURES / "rich_expected_export.md"

    doc_id = _create_throwaway_doc(
        live_workspace_id, f"E2E Rich MD {suffix}", cleanup_plan
    )
    invoke_json(
        [
            "doc", "add-markdown",
            "--doc", str(doc_id),
            "--markdown", rich_md,
        ]
    )

    def _exported() -> str:
        result = invoke(
            ["doc", "export-markdown", "--doc", str(doc_id)],
            expect_exit=0,
        )
        text = result.stdout
        assert text.strip(), "export-markdown empty"
        return text

    exported = _normalize_md(wait_for("doc export visible", _exported))

    if os.environ.get("MONDO_UPDATE_GOLDEN") == "1":
        golden_path.write_text(exported, encoding="utf-8")
        pytest.skip(f"updated golden: {golden_path}")

    if not golden_path.exists():
        pytest.fail(
            f"golden file missing at {golden_path}. "
            "Run with MONDO_UPDATE_GOLDEN=1 to record the current export as the new golden."
        )

    expected = _normalize_md(golden_path.read_text(encoding="utf-8"))
    assert exported == expected, (
        "rich markdown round-trip diverged from golden. "
        "If the change is intentional, regenerate with MONDO_UPDATE_GOLDEN=1.\n"
        f"--- exported ---\n{exported}\n--- expected ---\n{expected}"
    )


@pytest.mark.integration
def test_live_doc_duplicate_preserves_content(
    live_workspace_id: int, cleanup_plan: CleanupPlan
) -> None:
    """`mondo doc duplicate` carries blocks over."""
    suffix = uuid.uuid4().hex[:8]
    src_md = (FIXTURES / "strict_input.md").read_text(encoding="utf-8")
    src_doc_id = _create_throwaway_doc(
        live_workspace_id, f"E2E Doc Dup Src {suffix}", cleanup_plan
    )
    invoke_json(
        [
            "doc", "add-markdown",
            "--doc", str(src_doc_id),
            "--markdown", src_md,
        ]
    )

    def _src_blocks_landed() -> list[dict[str, Any]]:
        fetched = invoke_json(
            ["doc", "get", "--id", str(src_doc_id), "--format", "json"]
        )
        blocks = fetched.get("blocks") or []
        assert blocks, "src doc has no blocks yet"
        return blocks

    src_blocks = wait_for("src blocks visible", _src_blocks_landed)
    src_block_count = len(src_blocks)

    duplicated = invoke_json(["doc", "duplicate", "--doc", str(src_doc_id)])
    dup_id = int(duplicated.get("id") or duplicated.get("doc", {}).get("id"))
    cleanup_plan.add(
        f"dup doc {dup_id}", "doc", "delete", "--doc", str(dup_id),
    )

    def _dup_matches() -> None:
        fetched = invoke_json(
            ["doc", "get", "--id", str(dup_id), "--format", "json"]
        )
        blocks = fetched.get("blocks") or []
        assert len(blocks) == src_block_count, (
            f"duplicate has {len(blocks)} blocks; expected {src_block_count}"
        )

    wait_for("duplicate has same block count", _dup_matches)


@pytest.mark.integration
def test_live_doc_rename_visible_in_listing(
    live_workspace_id: int, cleanup_plan: CleanupPlan
) -> None:
    """`mondo doc rename` is reflected in name-contains listings."""
    suffix = uuid.uuid4().hex[:8]
    original_name = f"E2E Doc Rename Before {suffix}"
    new_name = f"E2E Doc Rename After {suffix}"

    doc_id = _create_throwaway_doc(live_workspace_id, original_name, cleanup_plan)
    invoke_json(["doc", "rename", "--doc", str(doc_id), "--name", new_name])

    def _rename_visible() -> None:
        # name-contains lookup by the new-name needle.
        listing = invoke_json(
            [
                "doc", "list",
                "--no-cache",
                "--workspace", str(live_workspace_id),
                "--name-contains", suffix,
            ]
        )
        names = [d.get("name") for d in listing]
        assert new_name in names, f"new name {new_name!r} missing from listing: {names[-10:]}"
        assert original_name not in names, f"old name still listed: {names[-10:]}"
        # And `doc get` reports the new name.
        got = invoke_json(["doc", "get", "--id", str(doc_id), "--format", "json"])
        assert got.get("name") == new_name, f"doc get name={got.get('name')!r}"

    wait_for("rename visible", _rename_visible)
