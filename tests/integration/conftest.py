"""Auto-load `.env` for the live integration suite.

Existing environment values win over the file (override=False), so CI
secrets and ad-hoc `MONDAY_TEST_TOKEN=... pytest` invocations still
take precedence. The file lives at the repo root; this conftest is
scoped to `tests/integration/` so unit tests never see the live token.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env", override=False)
