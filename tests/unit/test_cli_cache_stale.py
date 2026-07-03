"""Tests for `mondo cache clear --stale` and the `cache status` stale hint.

Staleness is purely age-based (a file older than its configured TTL), so
these tests fabricate cache envelopes with a backdated `fetched_at` rather
than waiting for a TTL to elapse.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mondo.cache.store import SCHEMA_VERSION
from mondo.cli.main import app

ENDPOINT = "https://api.monday.com/v2"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")
    monkeypatch.setenv("MONDO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MONDO_CACHE_ENABLED", "true")
    monkeypatch.setenv("MONDO_NO_CACHE_NOTICE", "1")


def _write_envelope(
    path: Path, *, ttl_seconds: int, age_seconds: int, endpoint: str = ENDPOINT
) -> None:
    """Write a valid cache envelope whose `fetched_at` is `age_seconds` old."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fetched = datetime.now(UTC) - timedelta(seconds=age_seconds)
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "fetched_at": fetched.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ttl_seconds": ttl_seconds,
        "api_endpoint": endpoint,
        "mondo_version": "0",
        "count": 1,
        "entries": [{"id": "1", "name": "x"}],
    }
    path.write_text(json.dumps(envelope), encoding="utf-8")


def _items_dir(tmp_path: Path) -> Path:
    # items TTL defaults to 60s.
    return tmp_path / "cache" / "default" / "items"


# -- clear --stale ----------------------------------------------------------


class TestClearStale:
    def test_removes_expired_keeps_fresh(self, tmp_path: Path) -> None:
        d = _items_dir(tmp_path)
        stale = d / "111.json"
        fresh = d / "222.json"
        _write_envelope(stale, ttl_seconds=60, age_seconds=120)
        _write_envelope(fresh, ttl_seconds=60, age_seconds=5)

        result = runner.invoke(app, ["cache", "clear", "items", "--stale"])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)

        assert [r["board"] for r in rows] == ["111"]
        assert rows[0]["removed"] is True
        assert not stale.exists()
        assert fresh.exists()

    def test_nothing_removed_when_all_fresh(self, tmp_path: Path) -> None:
        _write_envelope(_items_dir(tmp_path) / "222.json", ttl_seconds=60, age_seconds=5)
        result = runner.invoke(app, ["cache", "clear", "items", "--stale"])
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout) == []

    def test_dry_run_preserves_stale_file(self, tmp_path: Path) -> None:
        stale = _items_dir(tmp_path) / "111.json"
        _write_envelope(stale, ttl_seconds=60, age_seconds=120)

        result = runner.invoke(app, ["--dry-run", "cache", "clear", "items", "--stale"])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        assert rows[0]["board"] == "111"
        assert rows[0]["action"] == "clear"
        assert stale.exists()

    def test_all_types_only_touches_stale(self, tmp_path: Path) -> None:
        stale = _items_dir(tmp_path) / "111.json"
        fresh = _items_dir(tmp_path) / "222.json"
        _write_envelope(stale, ttl_seconds=60, age_seconds=120)
        _write_envelope(fresh, ttl_seconds=60, age_seconds=5)

        result = runner.invoke(app, ["cache", "clear", "--stale"])
        assert result.exit_code == 0, result.stdout
        rows = json.loads(result.stdout)
        # Only the one expired items file; fresh files and cold single-file
        # types are left alone.
        assert all(r.get("removed") is True for r in rows)
        assert {r["board"] for r in rows} == {"111"}
        assert not stale.exists()
        assert fresh.exists()


# -- status stale field + hint ----------------------------------------------


class TestStatusStale:
    def test_row_has_stale_field(self, tmp_path: Path) -> None:
        _write_envelope(_items_dir(tmp_path) / "111.json", ttl_seconds=60, age_seconds=120)
        _write_envelope(_items_dir(tmp_path) / "222.json", ttl_seconds=60, age_seconds=5)
        result = runner.invoke(app, ["cache", "status", "items"])
        assert result.exit_code == 0, result.stdout
        rows = {r["board"]: r for r in json.loads(result.stdout)}
        assert rows["111"]["stale"] is True
        assert rows["111"]["fresh"] is False
        assert rows["222"]["stale"] is False
        assert rows["222"]["fresh"] is True

    def test_hint_shown_in_table_format(self, tmp_path: Path) -> None:
        _write_envelope(_items_dir(tmp_path) / "111.json", ttl_seconds=60, age_seconds=120)
        result = runner.invoke(app, ["-o", "table", "cache", "status", "items"])
        assert result.exit_code == 0, result.stdout
        assert "clear --stale" in result.stderr

    def test_no_hint_in_json_format(self, tmp_path: Path) -> None:
        _write_envelope(_items_dir(tmp_path) / "111.json", ttl_seconds=60, age_seconds=120)
        result = runner.invoke(app, ["-o", "json", "cache", "status", "items"])
        assert result.exit_code == 0, result.stdout
        assert "clear --stale" not in (result.stderr or "")

    def test_no_hint_when_nothing_stale(self, tmp_path: Path) -> None:
        _write_envelope(_items_dir(tmp_path) / "222.json", ttl_seconds=60, age_seconds=5)
        result = runner.invoke(app, ["-o", "table", "cache", "status", "items"])
        assert result.exit_code == 0, result.stdout
        assert "clear --stale" not in (result.stderr or "")
