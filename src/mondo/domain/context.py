"""Structural context Protocols for the service layer.

Service functions need a few read-only knobs and factory methods off the
CLI's ``GlobalOpts`` dataclass, but must not import ``mondo.cli`` (that would
invert the dependency arrow). These ``Protocol`` classes capture only the
attributes/methods the services actually touch; ``GlobalOpts`` conforms
structurally without inheriting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from mondo.api.client import MondayClient
    from mondo.cache import CacheStore
    from mondo.cache.store import EntityType


class ProjectionOpts(Protocol):
    """The ``--query`` / ``--fields`` projection flags."""

    query: str | None
    fields: str | None


class ColumnsCacheOpts(ProjectionOpts, Protocol):
    """Projection flags plus the per-board columns cache-store factory the
    item service needs for codec preflight."""

    def columns_cache_store(self, board_id: int, *, no_cache: bool = ...) -> CacheStore | None: ...


class CacheStoreOpts(Protocol):
    """Builds a cache store for a given entity type/scope."""

    def build_cache_store(
        self, entity_type: EntityType, *, scope: str | None = ...
    ) -> CacheStore: ...


class ClientFactoryOpts(Protocol):
    """Builds a ready-to-use monday client for the current invocation."""

    def build_client(self) -> MondayClient: ...
