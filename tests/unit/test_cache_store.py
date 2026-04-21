"""Unit tests for mondo.cache.store."""

from __future__ import annotations

import json
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mondo.cache.store import (
    SCHEMA_VERSION,
    CachedDirectory,
    CacheStore,
    _format_utc,
    _parse_utc,
)

ENDPOINT = "https://api.monday.com/v2"


def _store(tmp_path: Path, entity: str = "boards", ttl: int = 60) -> CacheStore:
    return CacheStore(
        entity_type=entity,
        cache_dir=tmp_path / "cache",
        api_endpoint=ENDPOINT,
        ttl_seconds=ttl,
    )


def test_read_returns_none_on_cold_cache(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.read() is None


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    entries = [{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}]

    written = store.write(entries)

    assert isinstance(written, CachedDirectory)
    assert written.entries == entries
    assert written.entity_type == "boards"

    reloaded = store.read()
    assert reloaded is not None
    assert reloaded.entries == entries
    assert reloaded.api_endpoint == ENDPOINT


def test_write_produces_valid_envelope(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write([{"id": 1}])

    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == SCHEMA_VERSION
    assert raw["api_endpoint"] == ENDPOINT
    assert raw["ttl_seconds"] == 60
    assert raw["count"] == 1
    assert raw["entries"] == [{"id": 1}]
    assert "fetched_at" in raw
    assert "mondo_version" in raw


def test_file_and_dir_modes_are_locked_down(tmp_path: Path) -> None:
    if sys.platform.startswith("win"):
        pytest.skip("POSIX mode bits only")
    store = _store(tmp_path)
    store.write([{"id": 1}])
    dir_mode = stat.S_IMODE(store.path.parent.stat().st_mode)
    file_mode = stat.S_IMODE(store.path.stat().st_mode)
    assert dir_mode == 0o700
    assert file_mode == 0o600


def test_corrupt_file_is_dropped_and_returns_none(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("not json at all", encoding="utf-8")

    assert store.read() is None
    assert not store.path.exists()


def test_envelope_with_wrong_schema_version_is_dropped(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps(
            {
                "schema_version": 999,
                "fetched_at": _format_utc(datetime.now(UTC)),
                "ttl_seconds": 60,
                "api_endpoint": ENDPOINT,
                "entries": [],
            }
        ),
        encoding="utf-8",
    )
    assert store.read() is None
    assert not store.path.exists()


def test_endpoint_mismatch_returns_none_without_deleting(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "fetched_at": _format_utc(datetime.now(UTC)),
                "ttl_seconds": 60,
                "api_endpoint": "https://other.endpoint/v2",
                "entries": [{"id": 1}],
            }
        ),
        encoding="utf-8",
    )
    assert store.read() is None
    # Endpoint mismatch is a graceful skip, not a corruption: file is kept
    # so switching profiles back doesn't re-warm the cache from scratch.
    assert store.path.exists()


def test_expired_envelope_returns_none(tmp_path: Path) -> None:
    store = _store(tmp_path, ttl=60)
    ancient = datetime.now(UTC) - timedelta(hours=1)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "fetched_at": _format_utc(ancient),
                "ttl_seconds": 60,
                "api_endpoint": ENDPOINT,
                "entries": [{"id": 1}],
            }
        ),
        encoding="utf-8",
    )
    assert store.read() is None


def test_invalidate_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write([{"id": 1}])
    assert store.invalidate() is True
    assert store.invalidate() is False
    assert not store.path.exists()


def test_age_reports_even_when_expired(tmp_path: Path) -> None:
    store = _store(tmp_path, ttl=60)
    store.write([{"id": 1}])
    age = store.age()
    assert age is not None
    assert age < timedelta(seconds=5)


def test_age_returns_none_when_missing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.age() is None


def test_atomic_write_leaves_no_tmp_files(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write([{"id": 1}])
    leftovers = [p for p in store.path.parent.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_parse_and_format_utc_roundtrip() -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    formatted = _format_utc(now)
    assert formatted.endswith("Z")
    parsed = _parse_utc(formatted)
    assert parsed == now


def test_parse_utc_accepts_offset_form() -> None:
    parsed = _parse_utc("2026-04-20T10:15:00+00:00")
    assert parsed.tzinfo is not None
    assert parsed.year == 2026


# ----- scope (per-board columns cache) -----


def _scoped_store(tmp_path: Path, scope: str, *, ttl: int = 60) -> CacheStore:
    return CacheStore(
        entity_type="columns",
        cache_dir=tmp_path / "cache",
        api_endpoint=ENDPOINT,
        ttl_seconds=ttl,
        scope=scope,
    )


def test_scope_puts_file_in_entity_subdir(tmp_path: Path) -> None:
    store = _scoped_store(tmp_path, scope="12345")
    assert store.path == tmp_path / "cache" / "columns" / "12345.json"


def test_scope_roundtrip_writes_and_reads_independently(tmp_path: Path) -> None:
    a = _scoped_store(tmp_path, scope="1")
    b = _scoped_store(tmp_path, scope="2")
    a.write([{"id": "col_a"}])
    b.write([{"id": "col_b"}])
    loaded_a = a.read()
    loaded_b = b.read()
    assert loaded_a is not None and loaded_a.entries == [{"id": "col_a"}]
    assert loaded_b is not None and loaded_b.entries == [{"id": "col_b"}]
    assert a.path != b.path


def test_scope_invalidate_does_not_affect_other_scopes(tmp_path: Path) -> None:
    a = _scoped_store(tmp_path, scope="1")
    b = _scoped_store(tmp_path, scope="2")
    a.write([{"id": "col_a"}])
    b.write([{"id": "col_b"}])
    assert a.invalidate() is True
    assert b.read() is not None


def test_scope_subdir_permissions_are_locked_down(tmp_path: Path) -> None:
    if sys.platform.startswith("win"):
        pytest.skip("POSIX mode bits only")
    store = _scoped_store(tmp_path, scope="42")
    store.write([{"id": "x"}])
    dir_mode = stat.S_IMODE(store.path.parent.stat().st_mode)
    file_mode = stat.S_IMODE(store.path.stat().st_mode)
    assert dir_mode == 0o700
    assert file_mode == 0o600


@pytest.mark.parametrize("bad_scope", ["", ".", "..", "a/b", "a\\b"])
def test_scope_rejects_unsafe_values(tmp_path: Path, bad_scope: str) -> None:
    with pytest.raises(ValueError):
        CacheStore(
            entity_type="columns",
            cache_dir=tmp_path / "cache",
            api_endpoint=ENDPOINT,
            ttl_seconds=60,
            scope=bad_scope,
        )


def test_scope_atomic_write_leaves_no_tmp_files(tmp_path: Path) -> None:
    store = _scoped_store(tmp_path, scope="99")
    store.write([{"id": 1}])
    leftovers = [p for p in store.path.parent.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []
