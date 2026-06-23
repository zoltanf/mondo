"""Live integration test for `doc get --format pdf` (issue #68).

PDF is produced client-side via WeasyPrint (monday has no PDF export). The test
is doubly gated: it needs the prepared live doc (MONDO_TEST_DOC_ID) *and* a
real `weasyprint` on PATH — CI has neither, so it skips cleanly there.
"""

from __future__ import annotations

import shutil

import pytest

from ._helpers import invoke_json

_HAS_WEASYPRINT = shutil.which("weasyprint") is not None


@pytest.mark.integration
@pytest.mark.skipif(not _HAS_WEASYPRINT, reason="weasyprint not installed")
def test_live_doc_get_pdf(live_test_doc_id: int, tmp_path) -> None:
    out = tmp_path / "doc.pdf"
    summary = invoke_json(
        [
            "doc",
            "get",
            "--object-id",
            str(live_test_doc_id),
            "--format",
            "pdf",
            "--out",
            str(out),
        ]
    )
    assert summary["engine"] == "weasyprint"
    assert summary["out"] == str(out)
    assert out.exists() and out.stat().st_size > 0
    # A real PDF starts with the `%PDF-` magic.
    assert out.read_bytes()[:5] == b"%PDF-"
