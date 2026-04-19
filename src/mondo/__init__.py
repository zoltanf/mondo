"""mondo package."""

from __future__ import annotations

import sys

# Windows' default stdout codec is cp1252, which can't encode characters Rich
# injects into help output (e.g. U+200B zero-width space). Reconfigure to UTF-8
# before any output so `mondo --help` doesn't crash with UnicodeEncodeError.
# Safe no-op on macOS/Linux (already UTF-8).
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from mondo.version import __version__

__all__ = ["__version__"]
