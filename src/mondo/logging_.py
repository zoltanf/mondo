"""Logging setup for mondo.

- Uses loguru (simpler configuration, JSON-friendly, thread-safe).
- Redacts registered secrets (API tokens) before records leave the process.
- Also redacts unregistered bearer-like blobs as a defence in depth.
"""

from __future__ import annotations

import re
import sys
from typing import TYPE_CHECKING, Any, TextIO

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Mapping

# Registered secrets: exact string replacement. Short strings (< MIN_SECRET_LEN)
# are ignored to avoid accidentally redacting common words.
_SECRETS: set[str] = set()
MIN_SECRET_LEN = 12

# Generic bearer-token pattern — 25+ alphanumeric (plus `._-`) chars that are
# almost certainly not a natural English word. Defensive catch-all.
_BEARER_RE = re.compile(r"\b[A-Za-z0-9._-]{25,}\b")


def register_secret(value: str | None) -> None:
    """Register an exact string to be replaced with `***` in every log record.

    Short or empty values are ignored. Safe to call multiple times with the
    same value.
    """
    if not value or len(value) < MIN_SECRET_LEN:
        return
    _SECRETS.add(value)


def redact(text: str) -> str:
    """Apply all registered secret replacements, then the bearer-like fallback."""
    for secret in _SECRETS:
        if secret in text:
            text = text.replace(secret, "***")
    # Fallback: anything that *looks* like a bearer token gets redacted.
    return _BEARER_RE.sub("***", text)


def _redaction_patcher(record: Mapping[str, Any]) -> None:
    """Loguru patcher hook — redacts the rendered message in-place."""
    record["message"] = redact(record["message"])  # type: ignore[index]


def configure_logging(
    *,
    verbose: bool = False,
    debug: bool = False,
    sink: TextIO | None = None,
) -> None:
    """Configure loguru's global sink.

    - Default: WARNING+ to stderr
    - verbose: INFO+
    - debug:   DEBUG+ (includes GraphQL wire logs added elsewhere)
    """
    level = "DEBUG" if debug else "INFO" if verbose else "WARNING"
    logger.remove()
    logger.configure(patcher=_redaction_patcher)
    logger.add(
        sink or sys.stderr,
        level=level,
        format=(
            "<green>{time:HH:mm:ss}</green> "
            "<level>{level: <8}</level> "
            "<cyan>{name}</cyan> "
            "| {message}"
        ),
        colorize=False,
        backtrace=debug,
        diagnose=debug,
    )
