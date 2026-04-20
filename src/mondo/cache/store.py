"""CacheStore — JSON envelope persistence for a single entity type.

The store knows nothing about monday or GraphQL. It handles:
- Atomic writes (tmp file + os.replace)
- TTL + endpoint + schema validation on read
- Silent recovery from corrupt files
- 0700/0600 file modes
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from mondo.version import __version__

SCHEMA_VERSION = 1

EntityType = str  # "boards" | "workspaces" | "users" | "teams"


@dataclass
class CachedDirectory:
    """In-memory view of a freshness-validated cache envelope."""

    entity_type: EntityType
    fetched_at: datetime
    ttl_seconds: int
    api_endpoint: str
    entries: list[dict[str, Any]]

    @property
    def age(self) -> timedelta:
        return _utcnow() - self.fetched_at

    def is_fresh(self, now: datetime | None = None) -> bool:
        reference = now or _utcnow()
        return (reference - self.fetched_at).total_seconds() < self.ttl_seconds


class CacheStore:
    """Read/write/invalidate a single entity type's cache file.

    One `CacheStore` per (entity_type, cache_dir) pair. `api_endpoint` is used
    to reject envelopes written against a different monday endpoint (e.g. the
    user switched profiles to a different account).
    """

    def __init__(
        self,
        *,
        entity_type: EntityType,
        cache_dir: Path,
        api_endpoint: str,
        ttl_seconds: int,
    ) -> None:
        self._entity_type = entity_type
        self._cache_dir = cache_dir
        self._api_endpoint = api_endpoint
        self._ttl_seconds = ttl_seconds

    @property
    def entity_type(self) -> EntityType:
        return self._entity_type

    @property
    def path(self) -> Path:
        return self._cache_dir / f"{self._entity_type}.json"

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    def read(self) -> CachedDirectory | None:
        """Return a validated CachedDirectory, or None for cold/corrupt/expired.

        Never raises. On any parsing failure the file is deleted as a side
        effect — cache corruption is self-healing.
        """
        p = self.path
        if not p.exists():
            return None
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.debug(f"cache[{self._entity_type}]: corrupt file ({exc}); dropping")
            self._try_unlink(p)
            return None

        if not isinstance(raw, dict):
            logger.debug(f"cache[{self._entity_type}]: envelope not an object; dropping")
            self._try_unlink(p)
            return None

        try:
            if raw.get("schema_version") != SCHEMA_VERSION:
                logger.debug(
                    f"cache[{self._entity_type}]: schema_version mismatch "
                    f"({raw.get('schema_version')} != {SCHEMA_VERSION}); dropping"
                )
                self._try_unlink(p)
                return None

            if raw.get("api_endpoint") != self._api_endpoint:
                logger.debug(
                    f"cache[{self._entity_type}]: endpoint mismatch "
                    f"(envelope={raw.get('api_endpoint')!r} vs current={self._api_endpoint!r}); "
                    f"treating as cold"
                )
                return None

            fetched_at = _parse_utc(raw["fetched_at"])
            ttl_seconds = int(raw["ttl_seconds"])
            entries_raw = raw["entries"]
            if not isinstance(entries_raw, list):
                raise ValueError("entries must be a list")
        except (KeyError, TypeError, ValueError) as exc:
            logger.debug(f"cache[{self._entity_type}]: invalid envelope ({exc}); dropping")
            self._try_unlink(p)
            return None

        cached = CachedDirectory(
            entity_type=self._entity_type,
            fetched_at=fetched_at,
            ttl_seconds=ttl_seconds,
            api_endpoint=self._api_endpoint,
            entries=entries_raw,
        )
        if not cached.is_fresh():
            logger.debug(
                f"cache[{self._entity_type}]: expired "
                f"(age={cached.age}, ttl={ttl_seconds}s)"
            )
            return None
        return cached

    def write(self, entries: list[dict[str, Any]]) -> CachedDirectory:
        """Serialize `entries` to disk atomically. Returns the envelope view.

        On write failure (disk full, permission) logs a WARNING and still
        returns the in-memory envelope — cache is best-effort.
        """
        fetched_at = _utcnow()
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "fetched_at": _format_utc(fetched_at),
            "ttl_seconds": self._ttl_seconds,
            "api_endpoint": self._api_endpoint,
            "mondo_version": __version__,
            "count": len(entries),
            "entries": entries,
        }
        try:
            self._ensure_dir()
            self._atomic_write(envelope)
        except OSError as exc:
            logger.warning(f"cache[{self._entity_type}]: write failed ({exc}); serving in-memory")

        return CachedDirectory(
            entity_type=self._entity_type,
            fetched_at=fetched_at,
            ttl_seconds=self._ttl_seconds,
            api_endpoint=self._api_endpoint,
            entries=entries,
        )

    def invalidate(self) -> bool:
        """Delete the cache file. Returns True if a file was removed."""
        return self._try_unlink(self.path)

    def age(self) -> timedelta | None:
        """Age of the on-disk envelope regardless of freshness, or None if
        the file is missing/corrupt."""
        p = self.path
        if not p.exists():
            return None
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            fetched_at = _parse_utc(raw["fetched_at"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return _utcnow() - fetched_at

    def _ensure_dir(self) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        # Tighten permissions when the dir is freshly created. mkdir with
        # default mode may have left it at 0755 under a permissive umask;
        # chmod is idempotent.
        try:
            os.chmod(self._cache_dir, 0o700)
        except OSError:
            # Windows / restricted FS — best effort.
            pass

    def _atomic_write(self, envelope: dict[str, Any]) -> None:
        # Write to a tmp file in the same directory, then os.replace.
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{self._entity_type}.",
            suffix=".tmp",
            dir=str(self._cache_dir),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(envelope, fh, ensure_ascii=False)
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
            os.replace(tmp_path, self.path)
        except Exception:
            self._try_unlink(Path(tmp_path))
            raise

    @staticmethod
    def _try_unlink(p: Path) -> bool:
        try:
            p.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            logger.debug(f"cache: unlink failed for {p} ({exc})")
            return False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _format_utc(dt: datetime) -> str:
    """ISO-8601 with `Z` suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(raw: str) -> datetime:
    """Parse ISO-8601 timestamps; accept both `Z` and `+00:00`."""
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
