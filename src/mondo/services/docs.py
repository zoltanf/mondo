"""Business logic for the `mondo doc` command group.

Block inspection and object-id/doc-id resolution extracted from
:mod:`mondo.cli.doc`. The Typer callbacks own argument parsing, emission,
polling, and exit-code mapping; everything here takes plain arguments,
returns plain data, and raises domain errors from :mod:`mondo.api.errors`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mondo.api.errors import MondoError, ValidationError
from mondo.api.queries import (
    ADD_CONTENT_TO_DOC_FROM_MARKDOWN,
    DOC_GET_BY_ID_BLOCKS_PAGE,
    DOC_HEAD_BY_OBJECT_ID,
)

_DOC_BLOCKS_PAGE_SIZE = 100


class PartialDocAddError(ValidationError):
    """A multi-chunk add that failed *after* earlier chunks already wrote
    blocks. Carries the ids those chunks created (top-level + nested children)
    so the caller can roll back exactly that content — never a concurrent edit.
    """

    def __init__(self, message: str, block_ids: list[str]) -> None:
        super().__init__(message)
        self.block_ids = block_ids


if TYPE_CHECKING:
    from mondo.api.client import MondayClient
    from mondo.domain.context import CacheStoreOpts, ClientFactoryOpts


def last_block_id(doc: dict[str, Any]) -> str | None:
    blocks = doc.get("blocks") or []
    if not blocks:
        return None
    last = blocks[-1]
    if not isinstance(last, dict):
        return None
    last_id = last.get("id")
    return str(last_id) if last_id else None


def top_level_block_ids(doc: dict[str, Any]) -> list[str]:
    """Ids of a doc's top-level blocks (those without a `parent_block_id`).

    Deleting a container block (e.g. a `table`) cascades its child blocks
    server-side, and a follow-up delete of an already-cascaded child id 400s,
    so callers that delete a doc's blocks must restrict to top-level ids.
    """
    return [
        str(b["id"])
        for b in (doc.get("blocks") or [])
        if isinstance(b, dict) and b.get("id") and not b.get("parent_block_id")
    ]


def _last_root_block_id(
    client: MondayClient, doc_id: int, *, among: set[str] | None = None
) -> str | None:
    """Return the id of a doc's last TOP-LEVEL block (no `parent_block_id`).

    `add_content_to_doc_from_markdown`'s `block_ids` return list also contains
    nested child blocks (e.g. table cells); anchoring the next chunk's
    `afterBlockId` to such a child is rejected server-side with
    INTERNAL_SERVER_ERROR. We re-read the doc and take a root block as the safe
    insertion anchor instead.

    `among` restricts the result to blocks whose id is in that set — used to
    anchor the next chunk to the *previous chunk's* own last root block, so a
    multi-chunk insert stays contiguous even when the initial `after` points
    into the middle of the doc. Without this, the anchor would jump to the
    whole doc's tail and scatter later chunks past pre-existing content.
    """
    page = 1
    last_root: str | None = None
    while True:
        data = client.execute(
            DOC_GET_BY_ID_BLOCKS_PAGE,
            variables={"ids": [doc_id], "limit": _DOC_BLOCKS_PAGE_SIZE, "page": page},
        )
        docs = (data.get("data") or {}).get("docs") or []
        if not docs:
            break
        blocks = docs[0].get("blocks") or []
        for b in blocks:
            if isinstance(b, dict) and b.get("id") and not b.get("parent_block_id"):
                bid = str(b["id"])
                if among is None or bid in among:
                    last_root = bid
        if len(blocks) < _DOC_BLOCKS_PAGE_SIZE:
            break
        page += 1
    return last_root


def add_markdown_chunked(
    client: MondayClient,
    doc_id: int,
    md: str,
    *,
    after: str | None,
) -> dict[str, Any]:
    """Add markdown to a doc via `add_content_to_doc_from_markdown`, splitting
    large input into safe chunks (issue #59).

    A single call with a large doc (~18KB) returns INTERNAL_SERVER_ERROR and
    writes nothing, so we split on top-level block boundaries and loop. Between
    chunks the next `afterBlockId` is re-resolved to the doc's last *root*
    block — the returned `block_ids` can include nested children (e.g. table
    cells), and anchoring to one of those is itself rejected with
    INTERNAL_SERVER_ERROR. Block ids are accumulated across chunks. Returns the
    merged `{success, block_ids, error}` envelope.

    A failed chunk short-circuits and surfaces a clear error noting how much
    content (if any) was already added — the caller decides what to do with a
    partial write.
    """
    from mondo.docs import split_markdown_for_upload

    chunks = split_markdown_for_upload(md)
    if not chunks:
        return {"success": True, "block_ids": [], "error": None}

    all_block_ids: list[str] = []
    prev_after = after
    for idx, chunk in enumerate(chunks):
        try:
            data = client.execute(
                ADD_CONTENT_TO_DOC_FROM_MARKDOWN,
                variables={"doc": doc_id, "md": chunk, "after": prev_after},
            )
            result = (data.get("data") or {}).get("add_content_to_doc_from_markdown") or {}
            if not result.get("success"):
                raise ValidationError(
                    result.get("error") or "add_content_to_doc_from_markdown failed"
                )
            all_block_ids.extend(result.get("block_ids") or [])
            # Only re-fetch the anchor when more chunks remain (saves one read on
            # the common single-chunk path). Anchor to the last root block *this
            # chunk* produced, so the next chunk lands right after it — not after
            # the whole doc's tail (which would scatter chunks when `after`
            # points mid-doc).
            if idx < len(chunks) - 1:
                prev_after = (
                    _last_root_block_id(client, doc_id, among=set(result.get("block_ids") or []))
                    or prev_after
                )
        except MondoError as e:
            # ANY failure (success:false, a raised network/server error, or a
            # failed anchor re-fetch) after earlier chunks already wrote blocks
            # must carry the created ids so `doc set` can roll back exactly that
            # content. A first-chunk failure wrote nothing, so it surfaces as-is.
            if all_block_ids and not isinstance(e, PartialDocAddError):
                raise PartialDocAddError(
                    f"{e} (partial content added: {len(all_block_ids)} blocks before the failure)",
                    list(all_block_ids),
                ) from e
            raise

    return {"success": True, "block_ids": all_block_ids, "error": None}


def resolve_doc_id_from_object_id(
    opts: CacheStoreOpts, client: MondayClient, object_id: int
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


def object_id_hint(opts: ClientFactoryOpts, doc_id: int) -> str | None:
    """`object_id_hint_with_client` with a fresh short-lived client."""
    try:
        client = opts.build_client()
        with client:
            return object_id_hint_with_client(client, doc_id)
    except Exception:
        return None
