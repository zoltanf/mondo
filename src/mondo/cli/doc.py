"""`mondo doc` — workspace-level docs (Phase 3e).

Distinct from the `doc` **column** type (which is handled by
`mondo column doc`). Workspace docs are standalone documents inside a
workspace with a block-structured body. The CLI covers:

- `list` / `get` — page-based listing with optional workspace / object-id
  filters; get emits the full block tree (or a markdown rendering).
- `create` — bootstrap a doc inside a workspace (`CreateDocInput.workspace`).
- `add-block` / `add-content` — single / bulk block inserts.
- `add-markdown` / `import-html` — server-side markdown/html conversion flows.
- `update-block` / `delete-block` — edit individual blocks.
- `rename` / `duplicate` / `delete` — document-level mutations.
- `export-markdown` / `version-history` / `version-diff` — read-side extras.
"""

from __future__ import annotations

import json
import re
import sys
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, NoReturn

import typer

from mondo.api.errors import MondoError, NotFoundError
from mondo.api.queries import (
    ADD_CONTENT_TO_DOC_FROM_MARKDOWN,
    CREATE_DOC_BLOCK,
    CREATE_DOC_IN_WORKSPACE,
    DELETE_DOC,
    DELETE_DOC_BLOCK,
    DOC_GET_BY_ID_BLOCKS_PAGE,
    DOC_HEAD_BY_OBJECT_ID,
    DOC_VERSION_DIFF,
    DOC_VERSION_HISTORY,
    DOCS_BY_OBJECT_ID_BLOCKS_PAGE,
    DUPLICATE_DOC,
    EXPORT_MARKDOWN_FROM_DOC,
    IMPORT_DOC_FROM_HTML,
    UPDATE_DOC_BLOCK,
    UPDATE_DOC_NAME,
)
from mondo.cli._cache_invalidate import invalidate_all_scopes, invalidate_entity
from mondo.cli._examples import epilog_for
from mondo.cli._exec import (
    client_or_exit,
    dry_run_and_exit,
    exec_or_exit,
    execute,
    handle_mondo_error_or_exit,
)
from mondo.cli._json_flag import parse_json_flag
from mondo.cli._resolve import resolve_required_id
from mondo.cli._url import MondayIdParam
from mondo.cli.context import GlobalOpts

if TYPE_CHECKING:
    from mondo.api.client import MondayClient

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


class DocKind(StrEnum):
    public = "public"
    private = "private"
    share = "share"


class DocsOrderBy(StrEnum):
    created_at = "created_at"
    used_at = "used_at"


class DocFormat(StrEnum):
    json = "json"
    markdown = "markdown"


class DuplicateDocType(StrEnum):
    duplicate_doc_with_content = "duplicate_doc_with_content"
    duplicate_doc_with_content_and_updates = "duplicate_doc_with_content_and_updates"


# ----- helpers -----

_DOC_BLOCKS_PAGE_SIZE = 100

# The `--doc` XOR `--object-id` pair shared by every doc-targeting subcommand
# (same shared-option pattern as the Poll*Opt trio in `mondo.cli._exec`).
DocIdOpt = Annotated[
    int | None,
    typer.Option(
        "--doc",
        help="Internal doc ID (not the URL-visible object_id).",
    ),
]
DocObjectIdOpt = Annotated[
    int | None,
    typer.Option(
        "--object-id",
        help="URL-visible doc object_id (or monday.com /docs/<id> URL).",
        click_type=MondayIdParam(),
    ),
]


def _load_markdown(inline: str | None, path: Path | None, from_stdin: bool) -> str:
    sources = sum(x is not None and x is not False for x in (inline, path, from_stdin))
    if sources == 0:
        typer.secho(
            "error: provide --markdown, --from-file @path, or --from-stdin",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    if sources > 1:
        typer.secho(
            "error: --markdown, --from-file, and --from-stdin are mutually exclusive",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    if path is not None:
        return path.read_text()
    if from_stdin:
        return sys.stdin.read()
    assert inline is not None
    return inline


def _load_html(inline: str | None, path: Path | None, from_stdin: bool) -> str:
    sources = sum(x is not None and x is not False for x in (inline, path, from_stdin))
    if sources == 0:
        typer.secho(
            "error: provide --html, --from-file @path, or --from-stdin",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    if sources > 1:
        typer.secho(
            "error: --html, --from-file, and --from-stdin are mutually exclusive",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    if path is not None:
        return path.read_text()
    if from_stdin:
        return sys.stdin.read()
    assert inline is not None
    return inline


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


def _last_block_id(doc: dict[str, Any]) -> str | None:
    blocks = doc.get("blocks") or []
    if not blocks:
        return None
    last = blocks[-1]
    if not isinstance(last, dict):
        return None
    last_id = last.get("id")
    return str(last_id) if last_id else None


# ----- read commands -----


@app.command("list", epilog=epilog_for("doc list"))
def list_cmd(
    ctx: typer.Context,
    workspace: list[int] | None = typer.Option(
        None,
        "--workspace",
        help="Restrict to workspace IDs (repeatable).",
        rich_help_panel="Filters",
    ),
    object_id: list[int] | None = typer.Option(
        None,
        "--object-id",
        help="Filter by doc object_id (repeatable).",
        rich_help_panel="Filters",
    ),
    kind: DocKind | None = typer.Option(
        None,
        "--kind",
        help="Filter by doc kind (public/private/share), client-side.",
        case_sensitive=False,
        rich_help_panel="Filters",
    ),
    order_by: DocsOrderBy | None = typer.Option(
        None,
        "--order-by",
        help="created_at or used_at.",
        case_sensitive=False,
        rich_help_panel="Filters",
    ),
    name_contains: str | None = typer.Option(
        None,
        "--name-contains",
        help="Client-side substring filter on doc name (case-insensitive).",
        rich_help_panel="Filters",
    ),
    name_matches: str | None = typer.Option(
        None,
        "--name-matches",
        help="Client-side regex filter on doc name.",
        rich_help_panel="Filters",
    ),
    name_fuzzy: str | None = typer.Option(
        None,
        "--name-fuzzy",
        help="Client-side fuzzy filter on doc name (tolerates typos).",
        rich_help_panel="Filters",
    ),
    fuzzy_threshold: int | None = typer.Option(
        None,
        "--fuzzy-threshold",
        help="Minimum fuzzy match score (0-100). Defaults to config/70.",
        rich_help_panel="Filters",
    ),
    fuzzy_score_flag: bool = typer.Option(
        False,
        "--fuzzy-score",
        help="Include `_fuzzy_score` field and sort by score desc.",
        rich_help_panel="Filters",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        help="Page size for live fetches; ignored when served from cache.",
        rich_help_panel="Pagination",
    ),
    max_items: int | None = typer.Option(
        None,
        "--max-items",
        help="Stop after this many docs total.",
        rich_help_panel="Pagination",
    ),
    with_url: bool = typer.Option(
        False,
        "--with-url",
        help="Include `url` and `relative_url` on every emitted doc.",
    ),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Skip the local directory cache; fetch live.",
        rich_help_panel="Cache",
    ),
    refresh_cache: bool = typer.Option(
        False,
        "--refresh-cache",
        help="Force-refresh the local directory cache before serving.",
        rich_help_panel="Cache",
    ),
    explain_cache: bool = typer.Option(
        False,
        "--explain-cache",
        help="Print verbose cache provenance to stderr (path, ttl, fetched_at).",
        rich_help_panel="Cache",
    ),
) -> None:
    """List docs (page-based).

    Use --name-contains / --name-matches / --name-fuzzy to narrow by name,
    --workspace to restrict to workspaces, and --kind to pick public/private/
    share. Served from the local directory cache when available.
    """
    from mondo.api.errors import UsageError
    from mondo.cli._cache_flags import reject_mutually_exclusive, resolve_cache_prefs
    from mondo.cli._filters import compile_name_filter

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    reject_mutually_exclusive(no_cache, refresh_cache)

    try:
        needle_lower, pattern = compile_name_filter(
            name_contains, name_matches, name_fuzzy
        )
    except UsageError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from e

    prefs = resolve_cache_prefs(opts, no_cache=no_cache, fuzzy_threshold=fuzzy_threshold)
    if prefs.use_cache:
        _list_via_cache(
            opts,
            workspace=workspace,
            object_id=object_id,
            kind=kind,
            order_by=order_by,
            needle_lower=needle_lower,
            pattern=pattern,
            name_fuzzy=name_fuzzy,
            fuzzy_threshold=prefs.fuzzy_threshold,
            fuzzy_score_flag=fuzzy_score_flag,
            max_items=max_items,
            refresh=refresh_cache,
            explain_cache=explain_cache,
            with_url=with_url,
        )
        return

    from mondo.api.queries import build_docs_list_query

    query, variables = build_docs_list_query(
        object_ids=object_id or None,
        workspace_ids=workspace or None,
        order_by=order_by.value if order_by else None,
    )
    if opts.dry_run:
        opts.emit(
            {
                "query": query,
                "variables": {
                    **variables,
                    "limit": limit,
                    "max_items": max_items,
                    "kind": kind.value if kind else None,
                    "name_contains": name_contains,
                    "name_matches": name_matches,
                    "name_fuzzy": name_fuzzy,
                },
            }
        )
        raise typer.Exit(0)
    # Client-side filters (kind / name_*) require fetching every page before
    # capping, otherwise we'd drop matches past the first `max_items` pre-filter
    # rows. When no client-side filter is active, let pagination stop early.
    client_side_filter_active = (
        kind is not None
        or needle_lower is not None
        or pattern is not None
        or name_fuzzy is not None
    )
    fetch_cap = None if client_side_filter_active else max_items

    from mondo.api.pagination import iter_boards_page
    from mondo.cli._filters import apply_fuzzy
    from mondo.cli._filters import name_matches as _name_matches
    from mondo.cli._list_decorate import enrich_workspaces_best_effort, strip_url_fields
    from mondo.cli._normalize import normalize_doc_entry

    client = client_or_exit(opts)
    try:
        with client:
            items = [
                d
                for d in (
                    normalize_doc_entry(entry)
                    for entry in iter_boards_page(
                        client,
                        query=query,
                        variables=variables,
                        collection_key="docs",
                        limit=limit,
                        max_items=fetch_cap,
                    )
                )
                if (kind is None or (d.get("kind") or "") == kind.value)
                and _name_matches(d, needle_lower, pattern)
            ]
    except MondoError as e:
        handle_mondo_error_or_exit(e)

    if name_fuzzy is not None:
        items = apply_fuzzy(
            items,
            name_fuzzy,
            threshold=prefs.fuzzy_threshold,
            include_score=fuzzy_score_flag,
        )

    if client_side_filter_active and max_items is not None:
        items = items[:max_items]

    if prefs.cfg.enabled and not no_cache:
        enrich_workspaces_best_effort(items, opts)
    if not with_url:
        strip_url_fields(items)

    # Re-normalize last so optional decorators don't break key-order invariants.
    items = [normalize_doc_entry(d) for d in items]
    opts.emit(items)


def _list_via_cache(
    opts: GlobalOpts,
    *,
    workspace: list[int] | None,
    object_id: list[int] | None,
    kind: DocKind | None,
    order_by: DocsOrderBy | None,
    needle_lower: str | None,
    pattern: re.Pattern[str] | None,
    name_fuzzy: str | None,
    fuzzy_threshold: int,
    fuzzy_score_flag: bool,
    max_items: int | None,
    refresh: bool,
    explain_cache: bool,
    with_url: bool,
) -> None:
    from mondo.cache.directory import get_docs as cache_get_docs
    from mondo.cli._cache_flags import emit_cache_provenance
    from mondo.cli._filters import apply_fuzzy
    from mondo.cli._filters import name_matches as _name_matches
    from mondo.cli._list_decorate import enrich_workspaces_best_effort, strip_url_fields
    from mondo.cli._normalize import normalize_doc_entry

    if opts.dry_run:
        opts.emit(
            {
                "cache": "docs",
                "refresh": refresh,
                "filters": {
                    "workspace_ids": workspace or None,
                    "object_ids": object_id or None,
                    "kind": kind.value if kind else None,
                    "order_by": order_by.value if order_by else None,
                    "name_fuzzy": name_fuzzy,
                    "fuzzy_threshold": fuzzy_threshold,
                    "max_items": max_items,
                },
            }
        )
        raise typer.Exit(0)

    client = client_or_exit(opts)
    store = opts.build_cache_store("docs")
    try:
        with client:
            cached = cache_get_docs(client, store=store, refresh=refresh)
    except MondoError as e:
        handle_mondo_error_or_exit(e)

    emit_cache_provenance(opts, cached, store=store, explain=explain_cache)

    entries = cached.entries
    if kind is not None:
        entries = [e for e in entries if (e.get("kind") or "") == kind.value]
    if workspace:
        wanted_ws = {str(w) for w in workspace}
        entries = [e for e in entries if str(e.get("workspace_id") or "") in wanted_ws]
    if object_id:
        wanted_obj = {str(o) for o in object_id}
        entries = [e for e in entries if str(e.get("object_id") or "") in wanted_obj]
    entries = [e for e in entries if _name_matches(e, needle_lower, pattern)]

    if order_by is not None:
        key = order_by.value
        entries = sorted(entries, key=lambda e: e.get(key) or "", reverse=True)

    if name_fuzzy is not None:
        entries = apply_fuzzy(
            entries,
            name_fuzzy,
            threshold=fuzzy_threshold,
            include_score=fuzzy_score_flag,
        )

    if max_items is not None:
        entries = entries[:max_items]

    enrich_workspaces_best_effort(entries, opts)
    if not with_url:
        strip_url_fields(entries)

    # Re-normalize last so optional decorators don't break key-order invariants.
    entries = [normalize_doc_entry(d) for d in entries]
    opts.emit(entries)


@app.command("get", epilog=epilog_for("doc get"))
def get_cmd(
    ctx: typer.Context,
    doc_id: int | None = typer.Option(
        None,
        "--id",
        "--doc",
        help="Internal doc ID (or monday.com URL).",
        click_type=MondayIdParam(),
    ),
    object_id: int | None = typer.Option(
        None,
        "--object-id",
        help="URL-visible numeric object_id (or monday.com URL).",
        click_type=MondayIdParam(),
    ),
    fmt: DocFormat = typer.Option(
        DocFormat.json,
        "--format",
        help="Emit raw JSON (blocks as-is) or render blocks to markdown.",
        case_sensitive=False,
    ),
    with_url: bool = typer.Option(
        False,
        "--with-url",
        help="(No-op for docs — `url` is always present in the payload.)",
    ),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Bypass the per-doc blocks cache; fetch live.",
        rich_help_panel="Cache",
    ),
    refresh_cache: bool = typer.Option(
        False,
        "--refresh-cache",
        help="Force-refresh the per-doc blocks cache before serving.",
        rich_help_panel="Cache",
    ),
    explain_cache: bool = typer.Option(
        False,
        "--explain-cache",
        help="Emit a verbose cache-hit line (path/ttl/fetched_at) on stderr.",
        rich_help_panel="Cache",
    ),
) -> None:
    """Fetch a single doc by id or object_id, with its full block tree.

    Served from `docs_blocks/<doc_id>.json` (default TTL 5m — set via
    `MONDO_CACHE_TTL_DOCS_BLOCKS`). `--object-id` callers resolve to
    `doc_id` via the existing docs directory cache so both paths share
    one on-disk cache key.
    """
    from mondo.cli._cache_flags import emit_cache_provenance, reject_mutually_exclusive
    from mondo.cli._normalize import normalize_doc_entry
    from mondo.docs import blocks_to_markdown

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    reject_mutually_exclusive(no_cache, refresh_cache)
    del with_url  # docs always carry `url` from monday; flag kept for symmetry
    sources = sum(x is not None for x in (doc_id, object_id))
    if sources != 1:
        typer.secho(
            "error: pass exactly one of --id or --object-id.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    if doc_id is not None:
        query = DOC_GET_BY_ID_BLOCKS_PAGE
        variables = {
            "ids": [doc_id],
            "limit": _DOC_BLOCKS_PAGE_SIZE,
            "page": "<1..N>",
        }
    else:
        assert object_id is not None  # guaranteed by the sources != 1 check above
        query = DOCS_BY_OBJECT_ID_BLOCKS_PAGE
        variables = {
            "objs": [object_id],
            "limit": _DOC_BLOCKS_PAGE_SIZE,
            "page": "<1..N>",
        }

    if opts.dry_run:
        dry_run_and_exit(opts, query, variables)
    cfg = opts.resolve_cache_config()
    use_cache = cfg.enabled and not no_cache

    client = client_or_exit(opts)
    doc: dict[str, Any] | None
    try:
        with client:
            if use_cache:
                resolved_doc_id = doc_id if doc_id is not None else _resolve_doc_id_from_object_id(
                    opts, client, object_id or 0
                )
            else:
                resolved_doc_id = None

            if use_cache and resolved_doc_id is not None:
                from mondo.cache.directory import get_doc_blocks

                store = opts.build_cache_store(
                    "docs_blocks", scope=str(resolved_doc_id)
                )
                try:
                    cached = get_doc_blocks(
                        client,
                        store=store,
                        doc_id=resolved_doc_id,
                        refresh=refresh_cache,
                    )
                    emit_cache_provenance(
                        opts, cached, store=store, explain=explain_cache
                    )
                    doc = cached.entries[0] if cached.entries else None
                except NotFoundError:
                    doc = None
            else:
                doc = (
                    _fetch_doc_by_id_all_blocks(client, doc_id)
                    if doc_id is not None
                    else _fetch_doc_by_object_id_all_blocks(client, object_id or 0)
                )
            if doc is None:
                _emit_doc_not_found(client, doc_id=doc_id, object_id=object_id)
                raise typer.Exit(code=6)
    except MondoError as e:
        handle_mondo_error_or_exit(e)

    if fmt is DocFormat.markdown:
        blocks = doc.get("blocks") or []
        typer.echo(blocks_to_markdown(blocks))
        return
    doc = normalize_doc_entry(doc)
    opts.emit(doc)


def _resolve_doc_id_from_object_id(
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
            except (TypeError, ValueError):
                return None
    return None


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


# Exit codes worth the object-id probe: generic server failure, validation,
# not-found, service error (a monday HTTP 5xx — the canonical symptom of an
# object id sent as --doc — maps to exit 7; the probe degrades safely if it
# also fails). Auth / rate-limit failures would just re-fail the probe.
_OBJECT_ID_HINT_EXIT_CODES = frozenset({1, 5, 6, 7})


def _object_id_hint_with_client(client: MondayClient, doc_id: int) -> str | None:
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


def _emit_doc_id_not_found(client: MondayClient, doc_id: int, *, probe: bool) -> None:
    """Standard `doc id=X not found.` line, plus the object-id retry hint
    when the id was user-supplied via `--doc` (`probe=True`)."""
    line = f"doc id={doc_id} not found."
    if probe:
        hint = _object_id_hint_with_client(client, doc_id)
        if hint is not None:
            line = f"{line}\n{hint}"
    typer.secho(line, fg=typer.colors.RED, err=True)


def _object_id_hint(opts: GlobalOpts, doc_id: int) -> str | None:
    """`_object_id_hint_with_client` with a fresh short-lived client."""
    try:
        client = opts.build_client()
        with client:
            return _object_id_hint_with_client(client, doc_id)
    except Exception:
        return None


def _fail_with_object_id_hint(opts: GlobalOpts, err_line: str, doc_id: int | None) -> NoReturn:
    """Emit a mutation-envelope failure and exit 5, appending the object-id
    retry hint when the failing id came from `--doc`.

    The observed failure mode for an object id sent as --doc is an opaque
    mutation-level 500 ("Fetcher response returned NON-OK status=500") —
    probe before giving up.
    """
    line = f"error: {err_line}"
    hint = _object_id_hint(opts, doc_id) if doc_id is not None else None
    if hint:
        line = f"{line}\n{hint}"
    typer.secho(line, fg=typer.colors.RED, err=True)
    raise typer.Exit(code=5)


def _resolve_object_id_live(client: MondayClient, object_id: int) -> int | None:
    """Map a URL-visible `object_id` to the internal doc id via a head query."""
    data = exec_or_exit(client, DOC_HEAD_BY_OBJECT_ID, {"objs": [object_id]})
    docs = data.get("docs") or []
    if not docs:
        return None
    try:
        return int(docs[0]["id"])
    except (KeyError, TypeError, ValueError):
        return None


def _require_one_doc_flag(doc_id: int | None, object_id: int | None) -> None:
    """Usage gate for commands taking `--doc` XOR `--object-id`."""
    if (doc_id is None) == (object_id is None):
        typer.secho(
            "error: pass exactly one of --doc or --object-id.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)


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
        resolved = _resolve_doc_id_from_object_id(opts, client, object_id)
    if resolved is None:
        resolved = _resolve_object_id_live(client, object_id)
    if resolved is None:
        typer.secho(f"doc object_id={object_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
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
                    suffix = _object_id_hint_with_client(client, doc_id)
                handle_mondo_error_or_exit(e, human_suffix=suffix)
            return (result.get("data") or {}), resolved
    except MondoError as e:
        handle_mondo_error_or_exit(e)


# ----- write commands -----


@app.command("create", epilog=epilog_for("doc create"))
def create_cmd(
    ctx: typer.Context,
    workspace: int = typer.Option(..., "--workspace", help="Target workspace ID."),
    name: str = typer.Option(..., "--name", help="Doc name."),
    kind: DocKind | None = typer.Option(
        None, "--kind", help="public / private / share.", case_sensitive=False
    ),
) -> None:
    """Create a new doc inside a workspace."""
    from mondo.cli._normalize import normalize_doc_entry

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {
        "workspace": workspace,
        "name": name,
        "kind": kind.value if kind else None,
    }
    data = execute(opts, CREATE_DOC_IN_WORKSPACE, variables)
    opts.emit(normalize_doc_entry(data.get("create_doc") or {}))


@app.command("add-block", epilog=epilog_for("doc add-block"))
def add_block_cmd(
    ctx: typer.Context,
    doc_id: DocIdOpt = None,
    object_id: DocObjectIdOpt = None,
    block_type: str = typer.Option(
        ...,
        "--type",
        help="Block type (normal_text, large_title, medium_title, small_title, "
        "bulleted_list, numbered_list, quote, code, divider, …).",
    ),
    content: str = typer.Option(..., "--content", metavar="JSON", help="Block content as JSON."),
    after: str | None = typer.Option(
        None,
        "--after",
        help="Insert after this block ID. Default: append to end of doc "
        "(monday treats a missing after_block_id as top-insert, so we "
        "pre-fetch the doc's last block for append semantics).",
    ),
    parent_block: str | None = typer.Option(
        None, "--parent-block", help="Nest under this block ID."
    ),
) -> None:
    """Append a single block to a doc."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    _require_one_doc_flag(doc_id, object_id)
    parsed_content = parse_json_flag(content, flag_name="--content")

    def _variables(doc: int, after_id: str | None) -> dict[str, Any]:
        return {
            "doc": doc,
            "type": block_type,
            "content": json.dumps(parsed_content),
            "after": after_id,
            "parent": parent_block,
        }

    if doc_id is not None and opts.dry_run:
        dry_run_and_exit(opts, CREATE_DOC_BLOCK, _variables(doc_id, after))
    client = client_or_exit(opts)
    try:
        with client:
            resolved_doc = _resolve_doc_in_client(
                opts, client, doc_id=doc_id, object_id=object_id
            )
            if opts.dry_run:
                dry_run_and_exit(opts, CREATE_DOC_BLOCK, _variables(resolved_doc, after))
            effective_after = after
            if effective_after is None:
                existing_doc = _fetch_doc_by_id_all_blocks(client, resolved_doc)
                if existing_doc is None:
                    _emit_doc_id_not_found(client, resolved_doc, probe=doc_id is not None)
                    raise typer.Exit(code=6)
                effective_after = _last_block_id(existing_doc)
            data = exec_or_exit(
                client, CREATE_DOC_BLOCK, _variables(resolved_doc, effective_after)
            )
    except MondoError as e:
        handle_mondo_error_or_exit(e)

    invalidate_entity(opts, "docs_blocks", scope=str(resolved_doc))
    opts.emit(data.get("create_doc_block") or {})


@app.command("add-content", epilog=epilog_for("doc add-content"))
def add_content_cmd(
    ctx: typer.Context,
    doc_id: DocIdOpt = None,
    object_id: DocObjectIdOpt = None,
    markdown: str | None = typer.Option(None, "--markdown", help="Markdown source."),
    from_file: Path | None = typer.Option(None, "--from-file", help="Load markdown from a file."),
    from_stdin: bool = typer.Option(False, "--from-stdin", help="Load markdown from stdin."),
) -> None:
    """Append markdown to a doc by looping `create_doc_block` per block.

    Monday removed the bulk `create_doc_blocks` mutation; we chain
    `after_block_id` so the rendered doc preserves the input order even
    under concurrent edits.

    Block types supported via `mondo.docs.markdown_to_blocks`: headings h1-h3,
    paragraphs, bullet / numbered lists, blockquotes, fenced code, horizontal rules.
    """
    from mondo.docs import markdown_to_blocks

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    _require_one_doc_flag(doc_id, object_id)
    md = _load_markdown(markdown, from_file, from_stdin)
    blocks = markdown_to_blocks(md)
    if not blocks:
        typer.secho(
            "error: input produced no blocks (empty or unsupported markdown).",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=5)
    if doc_id is not None and opts.dry_run:
        dry_run_and_exit(
            opts,
            f"{CREATE_DOC_BLOCK} (looped per block)",
            {"doc": doc_id, "blocks": blocks},
        )
    from mondo.cli.column_doc import create_blocks

    client = client_or_exit(opts)
    created: list[dict[str, Any]] = []
    try:
        with client:
            resolved_doc = _resolve_doc_in_client(
                opts, client, doc_id=doc_id, object_id=object_id
            )
            if opts.dry_run:
                dry_run_and_exit(
                    opts,
                    f"{CREATE_DOC_BLOCK} (looped per block)",
                    {"doc": resolved_doc, "blocks": blocks},
                )
            # Seed `after_block_id` from the doc's current last block so blocks
            # land at the end (monday's default for `after=null` is TOP insert).
            existing_doc = _fetch_doc_by_id_all_blocks(client, resolved_doc)
            if existing_doc is None:
                _emit_doc_id_not_found(client, resolved_doc, probe=doc_id is not None)
                raise typer.Exit(code=6)
            prev_id = _last_block_id(existing_doc)
            created = create_blocks(client, resolved_doc, blocks, after_block_id=prev_id)
    except MondoError as e:
        handle_mondo_error_or_exit(e)

    invalidate_entity(opts, "docs_blocks", scope=str(resolved_doc))
    opts.emit(created)


@app.command("add-markdown", epilog=epilog_for("doc add-markdown"))
def add_markdown_cmd(
    ctx: typer.Context,
    doc_id: DocIdOpt = None,
    object_id: DocObjectIdOpt = None,
    markdown: str | None = typer.Option(None, "--markdown", help="Markdown source."),
    from_file: Path | None = typer.Option(None, "--from-file", help="Load markdown from a file."),
    from_stdin: bool = typer.Option(False, "--from-stdin", help="Load markdown from stdin."),
    after: str | None = typer.Option(None, "--after", help="Insert after this block ID."),
) -> None:
    """Append markdown using monday's server-side markdown parser."""

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    md = _load_markdown(markdown, from_file, from_stdin)
    data, resolved_doc = _execute_doc_command(
        opts,
        ADD_CONTENT_TO_DOC_FROM_MARKDOWN,
        {"md": md, "after": after},
        doc_id=doc_id,
        object_id=object_id,
    )
    result = data.get("add_content_to_doc_from_markdown") or {}
    if not result.get("success"):
        _fail_with_object_id_hint(
            opts, result.get("error") or "add_content_to_doc_from_markdown failed", doc_id
        )
    invalidate_entity(opts, "docs_blocks", scope=str(resolved_doc))
    opts.emit(result)


@app.command("import-html", epilog=epilog_for("doc import-html"))
def import_html_cmd(
    ctx: typer.Context,
    workspace: int = typer.Option(..., "--workspace", help="Target workspace ID."),
    html: str | None = typer.Option(None, "--html", help="Raw HTML content."),
    from_file: Path | None = typer.Option(None, "--from-file", help="Load HTML from a file."),
    from_stdin: bool = typer.Option(False, "--from-stdin", help="Load HTML from stdin."),
    title: str | None = typer.Option(None, "--title", help="Optional doc title override."),
    folder_id: int | None = typer.Option(None, "--folder", help="Optional folder ID."),
    kind: DocKind | None = typer.Option(
        None,
        "--kind",
        help="Doc visibility (public/private/share).",
        case_sensitive=False,
    ),
) -> None:
    """Create a new doc by importing HTML content."""

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    rendered_html = _load_html(html, from_file, from_stdin)
    variables = {
        "html": rendered_html,
        "workspace": workspace,
        "title": title,
        "folder": folder_id,
        "kind": kind.value if kind else None,
    }
    data = execute(opts, IMPORT_DOC_FROM_HTML, variables)
    # New doc is created — drop the docs directory so subsequent `doc list`
    # picks it up. No per-doc-blocks cache to drop (new id).
    invalidate_entity(opts, "docs")
    opts.emit(data.get("import_doc_from_html") or {})


@app.command("rename", epilog=epilog_for("doc rename"))
def rename_cmd(
    ctx: typer.Context,
    doc_id: DocIdOpt = None,
    object_id: DocObjectIdOpt = None,
    name: str = typer.Option(..., "--name", help="New document title."),
) -> None:
    """Rename a doc."""

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    data, resolved_doc = _execute_doc_command(
        opts, UPDATE_DOC_NAME, {"name": name}, doc_id=doc_id, object_id=object_id
    )
    invalidate_entity(opts, "docs_blocks", scope=str(resolved_doc))
    invalidate_entity(opts, "docs")
    opts.emit(data.get("update_doc_name"))


@app.command("duplicate", epilog=epilog_for("doc duplicate"))
def duplicate_cmd(
    ctx: typer.Context,
    doc_id: DocIdOpt = None,
    object_id: DocObjectIdOpt = None,
    duplicate_type: DuplicateDocType = typer.Option(
        DuplicateDocType.duplicate_doc_with_content,
        "--duplicate-type",
        help="Copy only content, or content+updates.",
        case_sensitive=False,
    ),
) -> None:
    """Duplicate a doc."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    data, _ = _execute_doc_command(
        opts,
        DUPLICATE_DOC,
        {"dup": duplicate_type.value},
        doc_id=doc_id,
        object_id=object_id,
    )
    result = data.get("duplicate_doc") or {}
    if not result.get("success"):
        _fail_with_object_id_hint(opts, result.get("error") or "duplicate_doc failed", doc_id)
    new_object_id = result.get("id")
    if new_object_id is None:
        typer.secho(
            "error: duplicate_doc returned no id",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=5)
    lookup = execute(opts, DOC_HEAD_BY_OBJECT_ID, {"objs": [int(new_object_id)]})
    matches = lookup.get("docs") or []
    if not matches:
        typer.secho(
            f"error: duplicated doc with object_id={new_object_id} not "
            "visible in workspace lookup",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=5)
    new_doc = matches[0]
    opts.emit(
        {
            "id": new_doc.get("id"),
            "object_id": new_doc.get("object_id"),
            "name": new_doc.get("name"),
            "url": new_doc.get("url"),
        }
    )


@app.command("delete", epilog=epilog_for("doc delete"))
def delete_cmd(
    ctx: typer.Context,
    doc_id: DocIdOpt = None,
    object_id: DocObjectIdOpt = None,
) -> None:
    """Delete a doc."""

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    data, resolved_doc = _execute_doc_command(
        opts, DELETE_DOC, {}, doc_id=doc_id, object_id=object_id
    )
    invalidate_entity(opts, "docs_blocks", scope=str(resolved_doc))
    invalidate_entity(opts, "docs")
    opts.emit(data.get("delete_doc"))


@app.command("export-markdown", epilog=epilog_for("doc export-markdown"))
def export_markdown_cmd(
    ctx: typer.Context,
    doc_id: DocIdOpt = None,
    object_id: DocObjectIdOpt = None,
    block_id: list[str] | None = typer.Option(
        None,
        "--block",
        help="Block ID to export (repeatable). Default: export full doc.",
    ),
    raw: bool = typer.Option(
        False,
        "--raw",
        help="Emit API JSON envelope instead of plain markdown text.",
    ),
) -> None:
    """Export doc content as markdown."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    data, _ = _execute_doc_command(
        opts,
        EXPORT_MARKDOWN_FROM_DOC,
        {"blocks": block_id or None},
        doc_id=doc_id,
        object_id=object_id,
    )
    result = data.get("export_markdown_from_doc") or {}
    if raw:
        opts.emit(result)
        return
    if not result.get("success"):
        _fail_with_object_id_hint(
            opts, result.get("error") or "export_markdown_from_doc failed", doc_id
        )
    typer.echo(result.get("markdown") or "")


@app.command("version-history", epilog=epilog_for("doc version-history"))
def version_history_cmd(
    ctx: typer.Context,
    doc_id: DocIdOpt = None,
    object_id: DocObjectIdOpt = None,
    since: str | None = typer.Option(
        None,
        "--since",
        help="Optional lower-bound ISO8601 timestamp.",
    ),
    until: str | None = typer.Option(
        None,
        "--until",
        help="Optional upper-bound ISO8601 timestamp.",
    ),
) -> None:
    """Fetch restoring points for a doc (API 2026-04+)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    data, _ = _execute_doc_command(
        opts,
        DOC_VERSION_HISTORY,
        {"since": since, "until": until},
        doc_id=doc_id,
        object_id=object_id,
    )
    opts.emit(data.get("doc_version_history") or {})


@app.command("version-diff", epilog=epilog_for("doc version-diff"))
def version_diff_cmd(
    ctx: typer.Context,
    doc_id: DocIdOpt = None,
    object_id: DocObjectIdOpt = None,
    date: str = typer.Option(..., "--date", help="Newer restoring-point ISO8601 timestamp."),
    prev_date: str = typer.Option(
        ...,
        "--prev-date",
        help="Older restoring-point ISO8601 timestamp.",
    ),
) -> None:
    """Fetch block-level diff between two restoring points (API 2026-04+)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    data, _ = _execute_doc_command(
        opts,
        DOC_VERSION_DIFF,
        {"date": date, "prev": prev_date},
        doc_id=doc_id,
        object_id=object_id,
    )
    opts.emit(data.get("doc_version_diff") or {})


@app.command("update-block", epilog=epilog_for("doc update-block"))
def update_block_cmd(
    ctx: typer.Context,
    id_pos: str | None = typer.Argument(None, metavar="[BLOCK_ID]", help="Block ID (positional)."),
    id_flag: str | None = typer.Option(None, "--id", "--block", help="Block ID (flag form)."),
    content: str = typer.Option(
        ..., "--content", metavar="JSON", help="Replacement content as JSON."
    ),
) -> None:
    """Replace a single block's content."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    block_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="block")
    parsed_content = parse_json_flag(content, flag_name="--content")
    # monday's JSON scalar wants the content as a JSON-encoded string (matches
    # what create_doc_block does). We validated the JSON above; now re-stringify.
    variables = {"block": block_id, "content": json.dumps(parsed_content)}
    data = execute(opts, UPDATE_DOC_BLOCK, variables)
    # Block mutation only carries block_id, not doc_id — wildcard drop.
    invalidate_all_scopes(opts, "docs_blocks")
    opts.emit(data.get("update_doc_block") or {})


@app.command("delete-block", epilog=epilog_for("doc delete-block"))
def delete_block_cmd(
    ctx: typer.Context,
    id_pos: str | None = typer.Argument(None, metavar="[BLOCK_ID]", help="Block ID (positional)."),
    id_flag: str | None = typer.Option(None, "--id", "--block", help="Block ID (flag form)."),
) -> None:
    """Delete a single block from a doc."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    block_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="block")
    variables = {"block": block_id}
    data = execute(opts, DELETE_DOC_BLOCK, variables)
    invalidate_all_scopes(opts, "docs_blocks")
    opts.emit(data.get("delete_doc_block") or {})
