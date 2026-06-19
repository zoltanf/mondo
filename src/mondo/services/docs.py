"""Business logic for the `mondo doc` command group.

Block inspection and object-id/doc-id resolution extracted from
:mod:`mondo.cli.doc`. The Typer callbacks own argument parsing, emission,
polling, and exit-code mapping; everything here takes plain arguments,
returns plain data, and raises domain errors from :mod:`mondo.api.errors`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mondo.api.errors import MondoError
from mondo.api.queries import DOC_HEAD_BY_OBJECT_ID

if TYPE_CHECKING:
    from mondo.api.client import MondayClient
    from mondo.cli.context import GlobalOpts


def last_block_id(doc: dict[str, Any]) -> str | None:
    blocks = doc.get("blocks") or []
    if not blocks:
        return None
    last = blocks[-1]
    if not isinstance(last, dict):
        return None
    last_id = last.get("id")
    return str(last_id) if last_id else None


def resolve_doc_id_from_object_id(
    opts: GlobalOpts, client: MondayClient, object_id: int
) -> int | None:
    """Map a URL-visible `object_id` to its internal `doc_id` via the docs
    directory cache (auto-populated on miss). Returns None when the
    object_id isn't visible — the caller falls back to a live fetch.
    """
    from mondo.cache.directory import get_docs as _cache_get_docs

    target = str(object_id)
    store = opts.build_cache_store("docs")
    try:
        cached = _cache_get_docs(client, store=store, refresh=False)
    except MondoError:
        return None
    for entry in cached.entries:
        if str(entry.get("object_id")) == target:
            raw = entry.get("id")
            try:
                return int(raw) if raw is not None else None
            except TypeError, ValueError:
                return None
    return None


def object_id_hint_with_client(client: MondayClient, doc_id: int) -> str | None:
    """Probe whether a failing `--doc` id is actually a URL-visible object_id
    (the id a human copies out of a `/docs/<id>` URL). Returns the targeted
    hint when it resolves; never raises — the probe must not mask the
    original error.
    """
    try:
        result = client.execute(DOC_HEAD_BY_OBJECT_ID, {"objs": [doc_id]})
        docs = (result.get("data") or {}).get("docs") or []
    except Exception:
        return None
    if not docs:
        return None
    return (
        f"hint: {doc_id} looks like a URL-visible object id, not an internal "
        f"doc id — retry with --object-id {doc_id}"
    )


def object_id_hint(opts: GlobalOpts, doc_id: int) -> str | None:
    """`object_id_hint_with_client` with a fresh short-lived client."""
    try:
        client = opts.build_client()
        with client:
            return object_id_hint_with_client(client, doc_id)
    except Exception:
        return None
