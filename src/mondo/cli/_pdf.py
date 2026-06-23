"""WeasyPrint-backed PDF rendering for `doc get --format pdf` (issue #68).

monday's API exposes no PDF export, so PDF is produced client-side: the doc is
rendered to a single self-contained HTML document (`blocks_to_html`, with
base64-embedded images and print CSS) and handed to WeasyPrint.

WeasyPrint is *not* bundled — it pulls native pango/cairo libraries that don't
fit the pure-Python PyInstaller build — so it's detected on `PATH` and the user
is prompted to install it on first use. One engine, one flow: no registry, no
fallback converter.
"""

from __future__ import annotations

import contextlib
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

from mondo.api.errors import MondoError

# WeasyPrint is fast for ordinary docs; this only guards a pathological hang.
_TIMEOUT_S = 120


def find_weasyprint() -> str | None:
    """Absolute path to the `weasyprint` CLI on `PATH`, or None if absent."""
    return shutil.which("weasyprint")


def install_hint() -> str:
    """Per-OS guidance for installing WeasyPrint (brew can't serve Windows)."""
    if platform.system() == "Windows":
        return (
            "WeasyPrint is required for PDF export. Install it with "
            "`pipx install weasyprint` plus the GTK runtime "
            "(see https://doc.courtbouillon.org/weasyprint/stable/first_steps.html), "
            "or use `--format html` and print to PDF from your browser."
        )
    return (
        "WeasyPrint is required for PDF export. Install it with "
        "`brew install weasyprint`, or use `--format html` and print to PDF "
        "from your browser."
    )


def render_pdf(html_text: str, out: Path) -> None:
    """Render `html_text` to a PDF at `out` via WeasyPrint.

    The PDF is written to a temp file on the same filesystem as `out` and moved
    into place with `os.replace`, so the install is atomic and a failure never
    truncates or clobbers an existing PDF at `out`. Raises `MondoError` if
    WeasyPrint is missing, times out, fails to produce a usable PDF, or the
    output can't be written.
    """
    exe = find_weasyprint()
    if exe is None:
        raise MondoError(install_hint())

    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(suffix=".pdf", dir=out.parent)
        os.close(fd)
    except OSError as e:
        raise MondoError(f"failed to prepare PDF output at {out}: {e}") from e

    dst = Path(tmp_name)
    try:
        with tempfile.TemporaryDirectory(prefix="mondo-pdf-") as tmp:
            src = Path(tmp) / "input.html"
            src.write_text(html_text, encoding="utf-8")
            try:
                proc = subprocess.run(
                    [exe, str(src), str(dst)],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=_TIMEOUT_S,
                    check=False,
                )
            except subprocess.TimeoutExpired as e:
                raise MondoError(f"WeasyPrint timed out after {_TIMEOUT_S}s") from e
            except OSError as e:
                raise MondoError(f"failed to run WeasyPrint: {e}") from e

            if proc.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
                tail = "\n".join((proc.stderr or "").strip().splitlines()[-5:])
                detail = tail or f"exit code {proc.returncode}"
                raise MondoError(f"WeasyPrint failed to render the PDF:\n{detail}")

        os.replace(dst, out)
    except OSError as e:
        raise MondoError(f"failed to write PDF to {out}: {e}") from e
    finally:
        # Clean up the temp output if it wasn't moved into place (os.replace
        # consumes it on success, so this is a no-op then).
        with contextlib.suppress(OSError):
            if dst.exists():
                dst.unlink()
