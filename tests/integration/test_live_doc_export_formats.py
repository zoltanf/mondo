"""Live integration tests for HTML and MDX doc export.

`doc get --format html|mdx` are client-side renderers (monday's API offers no
server-side HTML/MDX export). HTML produces a single self-contained file with
base64-embedded images; MDX reuses the markdown image pipeline (local files).

Gated by MONDO_TEST_DOC_ID; the prepared doc carries a notice box, table,
check list, code block, and image blocks (one top-level, two inside a table).
"""

from __future__ import annotations

import re

import pytest

from ._helpers import invoke, invoke_json

_LOCAL_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((\d+-[^)]+)\)")


@pytest.mark.integration
def test_live_doc_get_html_is_self_contained(live_test_doc_id: int, tmp_path) -> None:
    out = tmp_path / "doc.html"
    summary = invoke_json(
        ["doc", "get", "--object-id", str(live_test_doc_id), "--format", "html", "--out", str(out)]
    )
    assert out.exists(), "html file not written"
    html = out.read_text()

    assert html.startswith("<!DOCTYPE html>")
    assert "<title>" in html and "<style>" in html
    # Images are base64-embedded, so the file needs no sidecar assets and no
    # browser-only monday URL survives.
    assert summary.get("images", 0) > 0, summary
    assert "data:image/" in html
    assert "protected_static" not in html, "image URL leaked instead of embedding"
    assert not list(tmp_path.glob("*.png")), "html export must not write sidecar images"
    # Block fidelity: the prepared doc's notice box and table must render.
    assert '<aside class="notice">' in html
    assert "<table>" in html


@pytest.mark.integration
def test_live_doc_get_html_no_images_keeps_urls(live_test_doc_id: int, tmp_path) -> None:
    out = tmp_path / "doc.html"
    invoke_json(
        [
            "doc",
            "get",
            "--object-id",
            str(live_test_doc_id),
            "--format",
            "html",
            "--out",
            str(out),
            "--no-images",
        ]
    )
    html = out.read_text()
    assert "data:image/" not in html
    assert "protected_static" in html


@pytest.mark.integration
def test_live_doc_get_mdx_downloads_images(live_test_doc_id: int, tmp_path) -> None:
    out = tmp_path / "doc.mdx"
    summary = invoke_json(
        ["doc", "get", "--object-id", str(live_test_doc_id), "--format", "mdx", "--out", str(out)]
    )
    assert out.exists(), "mdx file not written"
    mdx = out.read_text()

    images = summary.get("images") or []
    assert images, summary
    for fname in images:
        assert re.match(r"\d+-", fname), f"unexpected filename scheme: {fname}"
        downloaded = tmp_path / fname
        assert downloaded.exists() and downloaded.stat().st_size > 0, fname
        assert f"]({fname})" in mdx
    assert "protected_static" not in mdx, mdx
    # MDX keeps monday callouts as GFM blockquotes.
    assert "> [!NOTE]" in mdx


@pytest.mark.integration
def test_live_doc_get_html_out_rejected_for_json(live_test_doc_id: int, tmp_path) -> None:
    result = invoke(
        [
            "doc",
            "get",
            "--object-id",
            str(live_test_doc_id),
            "--format",
            "json",
            "--out",
            str(tmp_path / "doc.json"),
        ],
        expect_exit=None,
    )
    assert result.exit_code == 2, result.stderr
    assert "markdown, mdx, or html" in result.stderr
