"""Unit tests for the WeasyPrint-backed PDF renderer (`mondo.cli._pdf`).

WeasyPrint is never invoked for real here: `subprocess.run` is monkeypatched to
a fake that writes (or refuses to write) the output file, so the temp-file
handling, argv, output verification, and failure paths are exercised without a
real converter on CI.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mondo.api.errors import MondoError
from mondo.cli import _pdf


def test_find_weasyprint_uses_which(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_pdf.shutil, "which", lambda name: "/opt/bin/weasyprint")
    assert _pdf.find_weasyprint() == "/opt/bin/weasyprint"
    monkeypatch.setattr(_pdf.shutil, "which", lambda name: None)
    assert _pdf.find_weasyprint() is None


def test_install_hint_branches_per_os(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_pdf.platform, "system", lambda: "Darwin")
    assert "brew install weasyprint" in _pdf.install_hint()
    monkeypatch.setattr(_pdf.platform, "system", lambda: "Windows")
    win = _pdf.install_hint()
    assert "brew" not in win
    assert "pipx" in win or "pip install" in win


def test_render_pdf_missing_weasyprint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(_pdf, "find_weasyprint", lambda: None)
    with pytest.raises(MondoError) as exc:
        _pdf.render_pdf("<html></html>", tmp_path / "out.pdf")
    assert "WeasyPrint" in str(exc.value)
    assert not (tmp_path / "out.pdf").exists()


def test_render_pdf_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        captured["argv"] = argv
        # argv = [exe, input_html, output_pdf]; emulate WeasyPrint writing a PDF.
        Path(argv[2]).write_bytes(b"%PDF-1.7\n...")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(_pdf, "find_weasyprint", lambda: "/usr/bin/weasyprint")
    monkeypatch.setattr(_pdf.subprocess, "run", fake_run)

    out = tmp_path / "nested" / "doc.pdf"
    _pdf.render_pdf("<html><body>hi</body></html>", out)

    assert out.exists()
    assert out.read_bytes().startswith(b"%PDF")
    argv = captured["argv"]
    assert argv[0] == "/usr/bin/weasyprint"
    assert argv[1].endswith("input.html")
    assert argv[2].endswith(".pdf")  # temp output on out's filesystem


def test_render_pdf_failure_preserves_existing_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed render must not clobber a PDF already at `out` (atomic install)."""

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="nope\n")

    monkeypatch.setattr(_pdf, "find_weasyprint", lambda: "/usr/bin/weasyprint")
    monkeypatch.setattr(_pdf.subprocess, "run", fake_run)

    out = tmp_path / "doc.pdf"
    out.write_bytes(b"OLD-PDF")
    with pytest.raises(MondoError):
        _pdf.render_pdf("<html></html>", out)
    assert out.read_bytes() == b"OLD-PDF"  # untouched
    # No temp .pdf left behind in the output dir.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["doc.pdf"]


def test_render_pdf_nonzero_exit_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom: bad css\n")

    monkeypatch.setattr(_pdf, "find_weasyprint", lambda: "/usr/bin/weasyprint")
    monkeypatch.setattr(_pdf.subprocess, "run", fake_run)

    out = tmp_path / "doc.pdf"
    with pytest.raises(MondoError) as exc:
        _pdf.render_pdf("<html></html>", out)
    assert "boom: bad css" in str(exc.value)
    assert not out.exists()


def test_render_pdf_empty_output_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        Path(argv[2]).write_bytes(b"")  # exit 0 but produced nothing usable
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(_pdf, "find_weasyprint", lambda: "/usr/bin/weasyprint")
    monkeypatch.setattr(_pdf.subprocess, "run", fake_run)

    out = tmp_path / "doc.pdf"
    with pytest.raises(MondoError):
        _pdf.render_pdf("<html></html>", out)
    assert not out.exists()


def test_render_pdf_timeout_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(argv, 1)

    monkeypatch.setattr(_pdf, "find_weasyprint", lambda: "/usr/bin/weasyprint")
    monkeypatch.setattr(_pdf.subprocess, "run", fake_run)

    with pytest.raises(MondoError) as exc:
        _pdf.render_pdf("<html></html>", tmp_path / "doc.pdf")
    assert "timed out" in str(exc.value).lower()
