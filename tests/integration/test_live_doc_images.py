"""Live integration tests for image download on doc markdown export.

Both export paths must download embedded monday images into the markdown's
folder and reference them by local filename instead of the browser-only
`protected_static` URL:

- `doc get --format markdown --out` (our client-side block renderer).
- `doc export-markdown --out` (monday's server-side markdown).

Gated by MONDO_TEST_DOC_ID; the prepared doc carries image blocks (one
top-level, two inside a table).
"""

from __future__ import annotations

import re

import pytest

from ._helpers import invoke, invoke_json

# `![alt](<assetId>-<name>)` — a localized (downloaded) image reference.
_LOCAL_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((\d+-[^)]+)\)")


@pytest.mark.integration
def test_live_doc_get_markdown_downloads_images(live_test_doc_id: int, tmp_path) -> None:
    out = tmp_path / "doc.md"
    summary = invoke_json(
        [
            "doc", "get",
            "--object-id", str(live_test_doc_id),
            "--format", "markdown",
            "--out", str(out),
        ]
    )
    assert out.exists(), "markdown file not written"
    md = out.read_text()

    images = summary.get("images") or []
    assert images, f"expected downloaded images, got summary: {summary}"
    for fname in images:
        assert re.match(r"\d+-", fname), f"unexpected filename scheme: {fname}"
        downloaded = tmp_path / fname
        assert downloaded.exists() and downloaded.stat().st_size > 0, fname
        assert f"]({fname})" in md, f"{fname} downloaded but not referenced"

    # Every image block was downloaded, so no browser-only URL should survive.
    assert "protected_static" not in md, md


@pytest.mark.integration
def test_live_doc_export_markdown_downloads_images(
    live_test_doc_id: int, tmp_path
) -> None:
    out = tmp_path / "exp.md"
    summary = invoke_json(
        [
            "doc", "export-markdown",
            "--object-id", str(live_test_doc_id),
            "--out", str(out),
        ]
    )
    assert out.exists(), "markdown file not written"
    md = out.read_text()

    # `images` is the list of localized filenames (same shape as `doc get`).
    localized = summary.get("images") or []
    assert localized, summary
    refs = _LOCAL_IMAGE_RE.findall(md)
    assert refs, f"no localized image references in export markdown:\n{md}"
    assert set(refs) == set(localized), (refs, localized)
    for fname in refs:
        downloaded = tmp_path / fname
        assert downloaded.exists() and downloaded.stat().st_size > 0, fname

    # The server emits images inside table cells too; all must be localized.
    assert "protected_static" not in md, md


@pytest.mark.integration
def test_live_doc_export_no_images_keeps_urls(live_test_doc_id: int, tmp_path) -> None:
    """`--no-images` writes the file but downloads nothing and leaves the
    monday image URLs in place — for both export paths."""
    get_out = tmp_path / "get.md"
    invoke_json(
        [
            "doc", "get",
            "--object-id", str(live_test_doc_id),
            "--format", "markdown",
            "--out", str(get_out),
            "--no-images",
        ]
    )
    exp_out = tmp_path / "exp.md"
    invoke_json(
        [
            "doc", "export-markdown",
            "--object-id", str(live_test_doc_id),
            "--out", str(exp_out),
            "--no-images",
        ]
    )

    # No image files downloaded into the folder.
    assert not list(tmp_path.glob("*.png")), list(tmp_path.glob("*.png"))
    # URLs preserved, not rewritten to local filenames.
    assert "protected_static" in get_out.read_text()
    assert "protected_static" in exp_out.read_text()


@pytest.mark.integration
def test_live_doc_get_out_rejected_without_markdown(live_test_doc_id: int, tmp_path) -> None:
    """`--out` only makes sense for markdown output; JSON must be rejected
    before any fetch (exit 2)."""
    result = invoke(
        [
            "doc", "get",
            "--object-id", str(live_test_doc_id),
            "--format", "json",
            "--out", str(tmp_path / "doc.md"),
        ],
        expect_exit=None,
    )
    assert result.exit_code == 2, result.stderr
    assert "--out is only valid with --format markdown" in result.stderr
