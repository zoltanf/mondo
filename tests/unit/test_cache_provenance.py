"""Tests for the cache provenance line emitted by `_cache_flags.emit_cache_provenance`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mondo.cache.store import CachedDirectory, CacheStore
from mondo.cli._cache_flags import _format_age, emit_cache_provenance
from mondo.cli.context import GlobalOpts


def _opts(*, output: str | None = "json") -> GlobalOpts:
    return GlobalOpts(
        profile_name=None,
        flag_token=None,
        flag_api_version=None,
        verbose=False,
        debug=False,
        output=output,
    )


def _cached(*, from_cache: bool, age_seconds: int = 90) -> CachedDirectory:
    return CachedDirectory(
        entity_type="boards",
        fetched_at=datetime.now(UTC) - timedelta(seconds=age_seconds),
        ttl_seconds=900,
        api_endpoint="https://api.monday.com/v2",
        entries=[{"id": "1"}, {"id": "2"}],
        from_cache=from_cache,
    )


class TestFormatAge:
    @pytest.mark.parametrize(
        "seconds, expected",
        [(0, "0s"), (45, "45s"), (60, "1m"), (3599, "59m"), (3600, "1h"), (86400, "1d"), (86400 * 3, "3d")],
    )
    def test_compact_format(self, seconds: int, expected: str) -> None:
        assert _format_age(seconds) == expected


class TestEmitCacheProvenance:
    def test_emits_when_from_cache(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        emit_cache_provenance(_opts(), _cached(from_cache=True))
        captured = capsys.readouterr()
        assert "cache: hit" in captured.err
        assert "entity=boards" in captured.err
        assert "count=2" in captured.err

    def test_silent_when_freshly_fetched(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        emit_cache_provenance(_opts(), _cached(from_cache=False))
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_silent_in_table_mode(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        emit_cache_provenance(_opts(output="table"), _cached(from_cache=True))
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_envar_suppresses(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MONDO_NO_CACHE_NOTICE", "1")
        emit_cache_provenance(_opts(), _cached(from_cache=True))
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_explain_overrides_envar(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("MONDO_NO_CACHE_NOTICE", "1")
        store = CacheStore(
            entity_type="boards",
            cache_dir=tmp_path,
            api_endpoint="https://api.monday.com/v2",
            ttl_seconds=900,
        )
        emit_cache_provenance(
            _opts(), _cached(from_cache=True), store=store, explain=True
        )
        captured = capsys.readouterr()
        assert "cache: hit" in captured.err
        assert "ttl=900s" in captured.err
        assert "fetched_at=" in captured.err
        assert str(store.path) in captured.err

    def test_explain_overrides_table_mode(
        self,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        store = CacheStore(
            entity_type="boards",
            cache_dir=tmp_path,
            api_endpoint="https://api.monday.com/v2",
            ttl_seconds=900,
        )
        emit_cache_provenance(
            _opts(output="table"),
            _cached(from_cache=True),
            store=store,
            explain=True,
        )
        captured = capsys.readouterr()
        assert "cache: hit" in captured.err

    def test_compact_form_is_one_line(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        emit_cache_provenance(_opts(), _cached(from_cache=True))
        captured = capsys.readouterr()
        assert captured.err.count("\n") == 1

    def test_age_format_uses_compact_units(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        emit_cache_provenance(_opts(), _cached(from_cache=True, age_seconds=120))
        captured = capsys.readouterr()
        assert "age=2m" in captured.err


class TestCacheStoreReadSetsFromCache:
    """When the on-disk cache exists and is fresh, `store.read()` returns
    a `CachedDirectory(from_cache=True)`. A freshly-written one is False."""

    def test_freshly_written_is_not_from_cache(self, tmp_path: Path) -> None:
        store = CacheStore(
            entity_type="boards",
            cache_dir=tmp_path,
            api_endpoint="https://api.monday.com/v2",
            ttl_seconds=900,
        )
        cached = store.write([{"id": "1"}])
        assert cached.from_cache is False

    def test_read_after_write_is_from_cache(self, tmp_path: Path) -> None:
        store = CacheStore(
            entity_type="boards",
            cache_dir=tmp_path,
            api_endpoint="https://api.monday.com/v2",
            ttl_seconds=900,
        )
        store.write([{"id": "1"}])
        cached = store.read()
        assert cached is not None
        assert cached.from_cache is True
