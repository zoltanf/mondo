"""Doc resolution + block-fetching helpers for `mondo doc`.

Extracted from `mondo.cli.doc` (pure move). These are CLI-layer helpers: they
freely use `GlobalOpts`, `typer.Exit`, and the shared `_exec` error handlers,
so they belong beside the commands rather than in `mondo.services`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NoReturn

import typer

from mondo.api.errors import MondoError, NotFoundError, ValidationError
from mondo.api.queries import (
    DOC_GET_BY_ID_BLOCKS_PAGE,
    DOC_HEAD_BY_OBJECT_ID,
    DOCS_BY_OBJECT_ID_BLOCKS_PAGE,
)
from mondo.cli._exec import (
    client_or_exit,
    dry_run_and_exit,
    exec_or_exit,
    handle_mondo_error_or_exit,
    usage_error_or_exit,
)
from mondo.cli.context import GlobalOpts
from mondo.services.docs import (
    object_id_hint,
    object_id_hint_with_client,
    resolve_doc_id_from_object_id,
)

if TYPE_CHECKING:
    from mondo.api.client import MondayClient

_DOC_BLOCKS_PAGE_SIZE = 100

# Exit codes worth the object-id probe: generic server failure, validation,
# not-found, service error (a monday HTTP 5xx — the canonical symptom of an
# object id sent as --doc — maps to exit 7; the probe degrades safely if it
# also fails). Auth / rate-limit failures would just re-fail the probe.
_OBJECT_ID_HINT_EXIT_CODES = frozenset({1, 5, 6, 7})


def _fetch_doc_with_all_blocks(
    client: MondayClient,
    *,
    query: str,
    identity: dict[str, Any],
) -> dict[str, Any] | None:
    """Fetch all block pages for a single doc and return one merged payload."""
    page = 1
    merged: dict[str, Any] | None = None
    all_blocks: list[dict[str, Any]] = []

    while True:
        data = exec_or_exit(
            client,
            query,
            {
                **identity,
                "limit": _DOC_BLOCKS_PAGE_SIZE,
                "page": page,
            },
        )
        docs = data.get("docs") or []
        if not docs:
            return None
        doc = docs[0]
        page_blocks = doc.get("blocks") or []

        if merged is None:
            merged = {k: v for k, v in doc.items() if k != "blocks"}
        if isinstance(page_blocks, list):
            all_blocks.extend(page_blocks)

        if len(page_blocks) < _DOC_BLOCKS_PAGE_SIZE:
            break
        page += 1

    assert merged is not None
    merged["blocks"] = all_blocks
    return merged


def _fetch_doc_by_id_all_blocks(client: MondayClient, doc_id: int) -> dict[str, Any] | None:
    return _fetch_doc_with_all_blocks(
        client,
        query=DOC_GET_BY_ID_BLOCKS_PAGE,
        identity={"ids": [doc_id]},
    )


def _fetch_doc_by_object_id_all_blocks(
    client: MondayClient, object_id: int
) -> dict[str, Any] | None:
    return _fetch_doc_with_all_blocks(
        client,
        query=DOCS_BY_OBJECT_ID_BLOCKS_PAGE,
        identity={"objs": [object_id]},
    )


def _emit_doc_not_found(
    client: MondayClient,
    *,
    doc_id: int | None,
    object_id: int | None,
) -> None:
    """Emit a helpful not-found message; probe BOARD_GET on --object-id
    misses to distinguish a real-board id from a genuine miss.

    Why: URLs of the form `/boards/<id>` commonly carry a real-board id;
    users who paste one into `doc get --object-id` deserve a specific
    "try board get" hint rather than a generic "not found". The probe is
    skipped for --id (internal doc ids don't overlap with board ids in
    practice).
    """
    from mondo.api.queries import BOARD_GET

    if object_id is not None:
        probe = exec_or_exit(client, BOARD_GET, {"id": object_id})
        boards = probe.get("boards") or []
        if boards and (boards[0].get("type") or "board") != "document":
            typer.secho(
                f"warning: id {object_id} is a regular board, not a workdoc. "
                f"Consider: mondo board get {object_id}",
                fg=typer.colors.YELLOW,
                err=True,
            )
            return
    if doc_id is not None:
        _emit_doc_id_not_found(client, doc_id, probe=True)
        return
    typer.secho(f"doc object_id={object_id} not found.", fg=typer.colors.RED, err=True)


def _emit_doc_id_not_found(client: MondayClient, doc_id: int, *, probe: bool) -> None:
    """Standard `doc id=X not found.` line, plus the object-id retry hint
    when the id was user-supplied via `--doc` (`probe=True`)."""
    line = f"doc id={doc_id} not found."
    if probe:
        hint = object_id_hint_with_client(client, doc_id)
        if hint is not None:
            line = f"{line}\n{hint}"
    typer.secho(line, fg=typer.colors.RED, err=True)


def _fail_with_object_id_hint(opts: GlobalOpts, err_line: str, doc_id: int | None) -> NoReturn:
    """Emit a mutation-envelope failure and exit 5, appending the object-id
    retry hint when the failing id came from `--doc`.

    The observed failure mode for an object id sent as --doc is an opaque
    mutation-level 500 ("Fetcher response returned NON-OK status=500") —
    probe before giving up.
    """
    hint = object_id_hint(opts, doc_id) if doc_id is not None else None
    handle_mondo_error_or_exit(ValidationError(err_line), human_suffix=hint)


def _resolve_object_id_live(client: MondayClient, object_id: int) -> int | None:
    """Map a URL-visible `object_id` to the internal doc id via a head query."""
    data = exec_or_exit(client, DOC_HEAD_BY_OBJECT_ID, {"objs": [object_id]})
    docs = data.get("docs") or []
    if not docs:
        return None
    try:
        return int(docs[0]["id"])
    except KeyError, TypeError, ValueError:
        return None


def _require_one_doc_flag(doc_id: int | None, object_id: int | None) -> None:
    """Usage gate for commands taking `--doc` XOR `--object-id`."""
    if (doc_id is None) == (object_id is None):
        usage_error_or_exit("pass exactly one of --doc or --object-id.")


def _resolve_doc_in_client(
    opts: GlobalOpts,
    client: MondayClient,
    *,
    doc_id: int | None,
    object_id: int | None,
) -> int:
    """Return the internal doc id, resolving `--object-id` on the given
    (already-open) client — docs directory cache first (when enabled),
    then the cheap live head query on a miss. A miss in both exits 6.
    A stale cache hit fails downstream identically to a live hit gone
    stale, so cache-first is safe.
    """
    if doc_id is not None:
        return doc_id
    assert object_id is not None
    resolved: int | None = None
    if opts.resolve_cache_config().enabled:
        resolved = resolve_doc_id_from_object_id(opts, client, object_id)
    if resolved is None:
        resolved = _resolve_object_id_live(client, object_id)
    if resolved is None:
        handle_mondo_error_or_exit(NotFoundError(f"doc object_id={object_id} not found."))
    return resolved


def _execute_doc_command(
    opts: GlobalOpts,
    query: str,
    variables: dict[str, Any],
    *,
    doc_id: int | None,
    object_id: int | None,
) -> tuple[dict[str, Any], int]:
    """Resolve `--doc` XOR `--object-id` and `execute()` on one shared client,
    plus the object-id-vs-internal-id guardrail: when a `--doc`-addressed call
    fails server-side and the id resolves as an object_id, append the targeted
    retry hint to the error output (probed on the still-open client).

    `variables` is the query payload minus `doc`; the resolved id is injected.
    Returns `(data, resolved_doc_id)`. Resolution runs even under `--dry-run`
    (read-side, same as codec preflights).
    """
    _require_one_doc_flag(doc_id, object_id)
    if doc_id is not None and opts.dry_run:
        dry_run_and_exit(opts, query, {"doc": doc_id, **variables})
    client = client_or_exit(opts)
    try:
        with client:
            resolved = _resolve_doc_in_client(opts, client, doc_id=doc_id, object_id=object_id)
            full_variables = {"doc": resolved, **variables}
            if opts.dry_run:
                dry_run_and_exit(opts, query, full_variables)
            try:
                result = client.execute(query, variables=full_variables)
            except MondoError as e:
                suffix = None
                if doc_id is not None and int(e.exit_code) in _OBJECT_ID_HINT_EXIT_CODES:
                    suffix = object_id_hint_with_client(client, doc_id)
                handle_mondo_error_or_exit(e, human_suffix=suffix)
            return (result.get("data") or {}), resolved
    except MondoError as e:
        handle_mondo_error_or_exit(e)
