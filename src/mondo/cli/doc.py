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

import contextlib
import json
import re
import sys
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, NoReturn

import typer

from mondo.api.errors import MondoError, NotFoundError, ValidationError
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
    usage_error_or_exit,
)
from mondo.cli._json_flag import parse_json_flag
from mondo.cli._resolve import resolve_required_id
from mondo.cli._url import MondayIdParam
from mondo.cli.context import GlobalOpts
from mondo.services.docs import (
    last_block_id,
    object_id_hint,
    object_id_hint_with_client,
    resolve_doc_id_from_object_id,
    top_level_block_ids,
)

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
    mdx = "mdx"
    html = "html"
    pdf = "pdf"


class DuplicateDocType(StrEnum):
    duplicate_doc_with_content = "duplicate_doc_with_content"
    duplicate_doc_with_content_and_updates = "duplicate_doc_with_content_and_updates"


# ----- helpers -----

_DOC_BLOCKS_PAGE_SIZE = 100

# Image `src` neutralization for PDF export. WeasyPrint dereferences URLs while
# converting, so before HTML reaches it we keep ONLY raster base64 data URIs
# produced by the embed path and blank everything else: remote/`file://` URLs
# from (untrusted) doc content AND `data:image/svg+xml` — an SVG can pull in
# external resources when WeasyPrint renders it, so a `data:` allowlist alone is
# not an SSRF boundary. Safe on our own output: image src/alt are HTML-escaped,
# so no literal `"` appears inside an attribute value.
_IMG_SRC = re.compile(r'src="([^"]*)"')
_SAFE_PDF_IMG_SRC = re.compile(r"data:image/(?:png|jpe?g|gif|webp|bmp);base64,", re.IGNORECASE)


def _sanitize_pdf_image_srcs(html_text: str) -> str:
    """Blank every `<img>` src that isn't a raster base64 data URI."""
    return _IMG_SRC.sub(
        lambda m: m.group(0) if _SAFE_PDF_IMG_SRC.match(m.group(1)) else 'src=""',
        html_text,
    )

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
        usage_error_or_exit("provide --markdown, --from-file @path, or --from-stdin")
    if sources > 1:
        usage_error_or_exit("--markdown, --from-file, and --from-stdin are mutually exclusive")
    if path is not None:
        return path.read_text()
    if from_stdin:
        return sys.stdin.read()
    assert inline is not None
    return inline


def _load_html(inline: str | None, path: Path | None, from_stdin: bool) -> str:
    sources = sum(x is not None and x is not False for x in (inline, path, from_stdin))
    if sources == 0:
        usage_error_or_exit("provide --html, --from-file @path, or --from-stdin")
    if sources > 1:
        usage_error_or_exit("--html, --from-file, and --from-stdin are mutually exclusive")
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
        needle_lower, pattern = compile_name_filter(name_contains, name_matches, name_fuzzy)
    except UsageError as e:
        usage_error_or_exit(str(e))

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

    from mondo.api.pagination import fetch_pages_concurrent
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
                    for entry in fetch_pages_concurrent(
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
        help="Emit raw JSON (blocks as-is) or render blocks to markdown, mdx, html, or pdf.",
        case_sensitive=False,
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        help=(
            "Write the rendered doc to this file (requires --format "
            "markdown/mdx/html/pdf; required for pdf). For markdown/mdx, embedded "
            "images are downloaded into the same folder and referenced by local "
            "filename; for html they are base64-embedded so the file is "
            "self-contained. pdf renders the self-contained html via WeasyPrint "
            "(install on first use: `brew install weasyprint`). Without --out, "
            "output goes to stdout (markdown/mdx keep monday image URLs; html "
            "still embeds images)."
        ),
    ),
    no_images: bool = typer.Option(
        False,
        "--no-images",
        help="Skip downloading/embedding images; keep their (browser-only) monday URLs.",
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

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    reject_mutually_exclusive(no_cache, refresh_cache)
    del with_url  # docs always carry `url` from monday; flag kept for symmetry
    _RENDER_FORMATS = {DocFormat.markdown, DocFormat.mdx, DocFormat.html, DocFormat.pdf}
    if out is not None and fmt not in _RENDER_FORMATS:
        usage_error_or_exit("--out is only valid with --format markdown, mdx, html, or pdf.")
    if fmt is DocFormat.pdf and out is None:
        usage_error_or_exit("--format pdf requires --out <file.pdf>.")
    sources = sum(x is not None for x in (doc_id, object_id))
    if sources != 1:
        usage_error_or_exit("pass exactly one of --id or --object-id.")

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
                resolved_doc_id = (
                    doc_id
                    if doc_id is not None
                    else resolve_doc_id_from_object_id(opts, client, object_id or 0)
                )
            else:
                resolved_doc_id = None

            if use_cache and resolved_doc_id is not None:
                from mondo.cache.directory import get_doc_blocks

                store = opts.build_cache_store("docs_blocks", scope=str(resolved_doc_id))
                try:
                    cached = get_doc_blocks(
                        client,
                        store=store,
                        doc_id=resolved_doc_id,
                        refresh=refresh_cache,
                    )
                    emit_cache_provenance(opts, cached, store=store, explain=explain_cache)
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

    if fmt is DocFormat.html:
        from mondo.docs import blocks_to_html

        blocks = doc.get("blocks") or []
        images: dict[str, tuple[str, str]] = {}
        if not no_images:
            from mondo.cli._doc_images import embed_doc_images

            images = embed_doc_images(opts, blocks)
        html_text = blocks_to_html(blocks, images=images, title=doc.get("name"))
        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(html_text, encoding="utf-8")
            opts.emit({"out": str(out), "images": len(images)})
            return
        typer.echo(html_text)
        return

    if fmt is DocFormat.pdf:
        # PDF = the same self-contained HTML handed to WeasyPrint (issue #68).
        # `--out` is guaranteed present by the up-front guard.
        assert out is not None
        from mondo.cli._doc_images import embed_doc_images
        from mondo.cli._pdf import find_weasyprint, install_hint, render_pdf
        from mondo.docs import blocks_to_html

        # Preflight before the (network) image embed so a first-time user without
        # WeasyPrint gets the install hint without paying for asset downloads.
        if find_weasyprint() is None:
            handle_mondo_error_or_exit(MondoError(install_hint()))

        blocks = doc.get("blocks") or []
        images = {} if no_images else embed_doc_images(opts, blocks)
        html_text = blocks_to_html(blocks, images=images, title=doc.get("name"))
        html_text = _sanitize_pdf_image_srcs(html_text)
        try:
            render_pdf(html_text, out)
        except MondoError as e:
            handle_mondo_error_or_exit(e)
        opts.emit({"out": str(out), "engine": "weasyprint", "images": len(images)})
        return

    if fmt in (DocFormat.markdown, DocFormat.mdx):
        from mondo.docs import blocks_to_markdown, blocks_to_mdx

        render = blocks_to_markdown if fmt is DocFormat.markdown else blocks_to_mdx
        blocks = doc.get("blocks") or []
        if out is not None:
            images = {}
            if not no_images:
                from mondo.cli._doc_images import download_doc_images

                images = download_doc_images(opts, blocks, out.parent)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(render(blocks, images=images), encoding="utf-8")
            opts.emit(
                {
                    "out": str(out),
                    "images": [ref for _, ref in images.values()],
                }
            )
            return
        typer.echo(render(blocks))
        return
    doc = normalize_doc_entry(doc)
    opts.emit(doc)


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


# ----- write commands -----


@app.command("create", epilog=epilog_for("doc create"))
def create_cmd(
    ctx: typer.Context,
    workspace: int = typer.Option(..., "--workspace", help="Target workspace ID."),
    name: str = typer.Option(..., "--name", help="Doc name."),
    kind: DocKind | None = typer.Option(
        None, "--kind", help="public / private / share.", case_sensitive=False
    ),
    folder_id: int | None = typer.Option(
        None, "--folder", help="Place the new doc directly inside this folder ID."
    ),
    with_url: bool = typer.Option(
        False,
        "--with-url",
        help="(No-op for docs — `url` is always present in the payload.)",
    ),
) -> None:
    """Create a new doc inside a workspace (optionally inside a folder)."""
    from mondo.cli._normalize import normalize_doc_entry

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    del with_url  # docs always carry `url` from monday; flag kept for symmetry
    variables = {
        "workspace": workspace,
        "name": name,
        "kind": kind.value if kind else None,
        "folder": folder_id,
    }
    if opts.dry_run:
        dry_run_and_exit(opts, CREATE_DOC_IN_WORKSPACE, variables)
    client = client_or_exit(opts)
    try:
        with client:
            result = client.execute(CREATE_DOC_IN_WORKSPACE, variables=variables)
            data = result.get("data") or {}
    except MondoError as e:
        # A bare USER_UNAUTHORIZED here almost always means the workspace
        # lacks a doc-creation license/policy for this account — not a broken
        # token. Surface that so callers don't burn time re-checking auth (#64).
        if e.code == "USER_UNAUTHORIZED" or "not permitted to create" in str(e):
            handle_mondo_error_or_exit(
                e,
                suggestion=(
                    "This usually means the workspace lacks a doc-creation "
                    "license/policy for your account rather than a token-permission "
                    "bug — ask an admin to verify doc-creation is enabled/licensed "
                    "for you in this workspace."
                ),
            )
        handle_mondo_error_or_exit(e)
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
            resolved_doc = _resolve_doc_in_client(opts, client, doc_id=doc_id, object_id=object_id)
            if opts.dry_run:
                dry_run_and_exit(opts, CREATE_DOC_BLOCK, _variables(resolved_doc, after))
            effective_after = after
            if effective_after is None:
                existing_doc = _fetch_doc_by_id_all_blocks(client, resolved_doc)
                if existing_doc is None:
                    _emit_doc_id_not_found(client, resolved_doc, probe=doc_id is not None)
                    raise typer.Exit(code=6)
                effective_after = last_block_id(existing_doc)
            data = exec_or_exit(client, CREATE_DOC_BLOCK, _variables(resolved_doc, effective_after))
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
        handle_mondo_error_or_exit(
            ValidationError("input produced no blocks (empty or unsupported markdown).")
        )
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
            resolved_doc = _resolve_doc_in_client(opts, client, doc_id=doc_id, object_id=object_id)
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
            prev_id = last_block_id(existing_doc)
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
    """Append markdown using monday's server-side markdown parser.

    Large input is auto-chunked on top-level block boundaries and looped, so a
    single oversized call can't trip monday's INTERNAL_SERVER_ERROR (#59).
    """
    from mondo.docs import normalize_markdown_tables
    from mondo.services.docs import add_markdown_chunked

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    _require_one_doc_flag(doc_id, object_id)
    md = normalize_markdown_tables(_load_markdown(markdown, from_file, from_stdin))
    if not md.strip():
        handle_mondo_error_or_exit(
            ValidationError("input produced no blocks (empty or unsupported markdown).")
        )

    if doc_id is not None and opts.dry_run:
        dry_run_and_exit(
            opts, f"{ADD_CONTENT_TO_DOC_FROM_MARKDOWN} (chunked)", {"doc": doc_id, "md": md}
        )
    client = client_or_exit(opts)
    try:
        with client:
            resolved_doc = _resolve_doc_in_client(opts, client, doc_id=doc_id, object_id=object_id)
            if opts.dry_run:
                dry_run_and_exit(
                    opts,
                    f"{ADD_CONTENT_TO_DOC_FROM_MARKDOWN} (chunked)",
                    {"doc": resolved_doc, "md": md},
                )
            try:
                result = add_markdown_chunked(client, resolved_doc, md, after=after)
            except MondoError as e:
                # A partial multi-chunk write may have already landed blocks;
                # drop the now-stale docs_blocks cache before surfacing the error.
                invalidate_entity(opts, "docs_blocks", scope=str(resolved_doc))
                suffix = None
                if doc_id is not None and int(e.exit_code) in _OBJECT_ID_HINT_EXIT_CODES:
                    suffix = object_id_hint_with_client(client, doc_id)
                handle_mondo_error_or_exit(e, human_suffix=suffix)
    except MondoError as e:
        handle_mondo_error_or_exit(e)

    invalidate_entity(opts, "docs_blocks", scope=str(resolved_doc))
    opts.emit({**result, "blocks_added": len(result.get("block_ids") or [])})


def _rollback_added_blocks(
    client: MondayClient, doc_id: int, *, added: list[str], keep: list[str]
) -> None:
    """Best-effort: delete the top-level blocks a failed chunked `set` already
    created, restoring the doc to its pre-add block set.

    `added` is the ids the add reported (top-level + nested children); `keep`
    is the doc's pre-add top-level ids. We delete only blocks that are BOTH
    currently top-level AND in `added` — so a concurrent edit landing between
    the original fetch and this rollback is never touched, and child ids (whose
    parent's deletion cascades them, and which 400 on direct delete) are
    skipped. Swallows its own errors — the caller surfaces the original failure.
    """
    targets = set(added) - set(keep)
    if not targets:
        return
    try:
        # _fetch_doc_by_id_all_blocks → exec_or_exit raises typer.Exit (not
        # MondoError) on failure; swallow both so a rollback hiccup can't mask
        # the original error.
        doc = _fetch_doc_by_id_all_blocks(client, doc_id)
    except MondoError, typer.Exit:
        return
    if doc is None:
        return
    for bid in top_level_block_ids(doc):
        if bid in targets:
            with contextlib.suppress(MondoError):
                client.execute(DELETE_DOC_BLOCK, variables={"block": bid})


def set_cmd(
    ctx: typer.Context,
    doc_id: DocIdOpt = None,
    object_id: DocObjectIdOpt = None,
    markdown: str | None = typer.Option(None, "--markdown", help="Markdown source."),
    from_file: Path | None = typer.Option(None, "--from-file", help="Load markdown from a file."),
    from_stdin: bool = typer.Option(False, "--from-stdin", help="Load markdown from stdin."),
) -> None:
    """Replace a doc's full content in place (alias: `doc replace`).

    Writes the new markdown via monday's server-side parser, then removes the
    doc's prior blocks. The new content is added *before* the old blocks are
    deleted, so a failed write leaves the original content intact rather than
    blanking the doc; if a multi-chunk add fails partway, the blocks it already
    appended are rolled back so the doc is left exactly as it was. The doc id /
    object_id / URL are preserved — only the body changes. Mirrors `column doc
    set` overwrite semantics.
    """
    from mondo.docs import normalize_markdown_tables
    from mondo.services.docs import PartialDocAddError, add_markdown_chunked

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    _require_one_doc_flag(doc_id, object_id)
    md = _load_markdown(markdown, from_file, from_stdin)
    if not md.strip():
        usage_error_or_exit(
            "refusing to replace doc content with empty markdown "
            "(use `doc delete` to remove the doc itself)."
        )
    md = normalize_markdown_tables(md)

    _plan = f"{ADD_CONTENT_TO_DOC_FROM_MARKDOWN} + {DELETE_DOC_BLOCK} (per prior block)"
    if doc_id is not None and opts.dry_run:
        dry_run_and_exit(opts, _plan, {"doc": doc_id, "md": md})

    client = client_or_exit(opts)
    try:
        with client:
            resolved_doc = _resolve_doc_in_client(opts, client, doc_id=doc_id, object_id=object_id)
            if opts.dry_run:
                dry_run_and_exit(opts, _plan, {"doc": resolved_doc, "md": md})
            existing_doc = _fetch_doc_by_id_all_blocks(client, resolved_doc)
            if existing_doc is None:
                _emit_doc_id_not_found(client, resolved_doc, probe=doc_id is not None)
                raise typer.Exit(code=6)
            # Only top-level blocks: deleting a container (e.g. a `table`)
            # cascades its children, and re-deleting a cascaded child id 400s.
            old_block_ids = top_level_block_ids(existing_doc)
            # Add the new content first (after the current last TOP-LEVEL
            # block); only once it lands do we delete the prior blocks. A failed
            # add leaves the doc untouched — no destructive half-state / data
            # loss. The anchor must be a root block: the doc's literal last
            # block may be a container child (e.g. a table cell), and anchoring
            # `add_content_to_doc_from_markdown` to a child id is rejected with
            # INTERNAL_SERVER_ERROR. Large markdown is auto-chunked (#59); all
            # chunks must succeed before any delete runs.
            try:
                result = add_markdown_chunked(
                    client,
                    resolved_doc,
                    md,
                    after=(old_block_ids[-1] if old_block_ids else None),
                )
            except MondoError as e:
                # No deletes have run, so the original content is intact; but a
                # partial multi-chunk add may have appended blocks. Roll back
                # exactly the blocks that add created (best-effort) so the failed
                # replace leaves the doc as it was, then drop the stale cache.
                if isinstance(e, PartialDocAddError):
                    _rollback_added_blocks(
                        client, resolved_doc, added=e.block_ids, keep=old_block_ids
                    )
                invalidate_entity(opts, "docs_blocks", scope=str(resolved_doc))
                suffix = None
                if doc_id is not None and int(e.exit_code) in _OBJECT_ID_HINT_EXIT_CODES:
                    suffix = object_id_hint_with_client(client, doc_id)
                handle_mondo_error_or_exit(e, human_suffix=suffix)
            # New content is in place; the doc is mutated now, so drop the cache
            # even if a subsequent delete fails partway.
            invalidate_entity(opts, "docs_blocks", scope=str(resolved_doc))
            for block_id in old_block_ids:
                exec_or_exit(client, DELETE_DOC_BLOCK, {"block": block_id})
    except MondoError as e:
        handle_mondo_error_or_exit(e)

    opts.emit({**result, "replaced_blocks": len(old_block_ids)})


app.command("set", epilog=epilog_for("doc set"))(set_cmd)
app.command("replace", epilog=epilog_for("doc replace"))(set_cmd)


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
        handle_mondo_error_or_exit(ValidationError("duplicate_doc returned no id"))
    lookup = execute(opts, DOC_HEAD_BY_OBJECT_ID, {"objs": [int(new_object_id)]})
    matches = lookup.get("docs") or []
    if not matches:
        handle_mondo_error_or_exit(
            ValidationError(
                f"duplicated doc with object_id={new_object_id} not visible in workspace lookup"
            )
        )
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


@app.command("clear", epilog=epilog_for("doc clear"))
def clear_cmd(
    ctx: typer.Context,
    doc_id: DocIdOpt = None,
    object_id: DocObjectIdOpt = None,
) -> None:
    """Remove all blocks from a doc, keeping the doc itself.

    Unlike `doc delete` (which removes the document), this empties the body
    while preserving the id / object_id / URL. An already-empty doc is a
    no-op (`cleared_blocks: 0`).
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    _require_one_doc_flag(doc_id, object_id)

    _plan = f"{DELETE_DOC_BLOCK} (per top-level block)"
    if doc_id is not None and opts.dry_run:
        dry_run_and_exit(opts, _plan, {"doc": doc_id})

    client = client_or_exit(opts)
    try:
        with client:
            resolved_doc = _resolve_doc_in_client(opts, client, doc_id=doc_id, object_id=object_id)
            if opts.dry_run:
                dry_run_and_exit(opts, _plan, {"doc": resolved_doc})
            existing_doc = _fetch_doc_by_id_all_blocks(client, resolved_doc)
            if existing_doc is None:
                _emit_doc_id_not_found(client, resolved_doc, probe=doc_id is not None)
                raise typer.Exit(code=6)
            block_ids = top_level_block_ids(existing_doc)
            if block_ids:
                # Deletes mutate the doc; drop the cache up front so a failure
                # partway through the loop can't leave a stale docs_blocks entry.
                invalidate_entity(opts, "docs_blocks", scope=str(resolved_doc))
            for block_id in block_ids:
                exec_or_exit(client, DELETE_DOC_BLOCK, {"block": block_id})
    except MondoError as e:
        handle_mondo_error_or_exit(e)

    opts.emit({"id": resolved_doc, "cleared_blocks": len(block_ids)})


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
    out: Path | None = typer.Option(
        None,
        "--out",
        help=(
            "Write the markdown to this file and download embedded images "
            "into the same folder, rewriting their URLs to local filenames. "
            "Without it, markdown goes to stdout with monday image URLs."
        ),
    ),
    no_images: bool = typer.Option(
        False,
        "--no-images",
        help="With --out, skip downloading images; keep their monday URLs.",
    ),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="No-op — export is always live (accepted for flag symmetry).",
        rich_help_panel="Cache",
    ),
    refresh_cache: bool = typer.Option(
        False,
        "--refresh-cache",
        help="No-op — export is always live (accepted for flag symmetry).",
        rich_help_panel="Cache",
    ),
) -> None:
    """Export doc content as markdown.

    Always fetched live (no per-doc cache is involved), so `--no-cache` /
    `--refresh-cache` are accepted as no-ops purely for symmetry with the
    other doc commands.
    """
    from mondo.cli._cache_flags import reject_mutually_exclusive

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    reject_mutually_exclusive(no_cache, refresh_cache)
    if raw and out is not None:
        usage_error_or_exit("--raw and --out are mutually exclusive.")
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
    from mondo.docs import coalesce_markdown_emphasis

    # Monday's exporter fragments contiguous bold runs into adjacent `**…**`
    # spans; rejoin them so the markdown reads as one span (#62).
    markdown = coalesce_markdown_emphasis(result.get("markdown") or "")
    if out is not None:
        from mondo.cli._doc_images import localize_markdown_images

        images: list[str] = []
        if not no_images:
            markdown, images = localize_markdown_images(opts, markdown, out.parent)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown)
        opts.emit({"out": str(out), "images": images})
        return
    typer.echo(markdown)


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
    doc_id: DocIdOpt = None,
    object_id: DocObjectIdOpt = None,
    content: str = typer.Option(
        ..., "--content", metavar="JSON", help="Replacement content as JSON."
    ),
) -> None:
    """Replace a single block's content.

    `--doc`/`--object-id` are accepted for symmetry with `add-block` but
    ignored: block IDs are globally unique, so the block ID alone targets it.
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    del doc_id, object_id  # flags kept for symmetry; block ID alone targets the block
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
    doc_id: DocIdOpt = None,
    object_id: DocObjectIdOpt = None,
) -> None:
    """Delete a single block from a doc.

    `--doc`/`--object-id` are accepted for symmetry with `add-block` but
    ignored: block IDs are globally unique, so the block ID alone targets it.
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    del doc_id, object_id  # flags kept for symmetry; block ID alone targets the block
    block_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="block")
    variables = {"block": block_id}
    data = execute(opts, DELETE_DOC_BLOCK, variables)
    invalidate_all_scopes(opts, "docs_blocks")
    opts.emit(data.get("delete_doc_block") or {})
