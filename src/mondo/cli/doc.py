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
from typing import TYPE_CHECKING, Any

import typer

from mondo.api.errors import MondoError
from mondo.api.queries import (
    ADD_CONTENT_TO_DOC_FROM_MARKDOWN,
    CREATE_DOC_BLOCK,
    CREATE_DOC_IN_WORKSPACE,
    DELETE_DOC,
    DELETE_DOC_BLOCK,
    DOC_GET_BY_ID_BLOCKS_PAGE,
    DOC_VERSION_DIFF,
    DOC_VERSION_HISTORY,
    DOCS_BY_OBJECT_ID_BLOCKS_PAGE,
    DUPLICATE_DOC,
    EXPORT_MARKDOWN_FROM_DOC,
    IMPORT_DOC_FROM_HTML,
    UPDATE_DOC_BLOCK,
    UPDATE_DOC_NAME,
)
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
) -> None:
    """Fetch a single doc by id or object_id, with its full block tree."""
    from mondo.cli._normalize import normalize_doc_entry
    from mondo.docs import blocks_to_markdown

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
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
    client = client_or_exit(opts)
    try:
        with client:
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
    ref = f"id={doc_id}" if doc_id is not None else f"object_id={object_id}"
    typer.secho(f"doc {ref} not found.", fg=typer.colors.RED, err=True)


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
    doc_id: int = typer.Option(..., "--doc", help="Doc ID (internal id, NOT object_id)."),
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
    parsed_content = parse_json_flag(content, flag_name="--content")
    if opts.dry_run:
        dry_run_and_exit(
            opts,
            CREATE_DOC_BLOCK,
            {
                "doc": doc_id,
                "type": block_type,
                "content": json.dumps(parsed_content),
                "after": after,
                "parent": parent_block,
            },
        )
    client = client_or_exit(opts)
    try:
        with client:
            effective_after = after
            if effective_after is None:
                existing_doc = _fetch_doc_by_id_all_blocks(client, doc_id)
                if existing_doc is None:
                    typer.secho(f"doc id={doc_id} not found.", fg=typer.colors.RED, err=True)
                    raise typer.Exit(code=6)
                effective_after = _last_block_id(existing_doc)
            data = exec_or_exit(
                client,
                CREATE_DOC_BLOCK,
                {
                    "doc": doc_id,
                    "type": block_type,
                    "content": json.dumps(parsed_content),
                    "after": effective_after,
                    "parent": parent_block,
                },
            )
    except MondoError as e:
        handle_mondo_error_or_exit(e)
    opts.emit(data.get("create_doc_block") or {})


@app.command("add-content", epilog=epilog_for("doc add-content"))
def add_content_cmd(
    ctx: typer.Context,
    doc_id: int = typer.Option(..., "--doc", help="Doc ID (internal id)."),
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
    md = _load_markdown(markdown, from_file, from_stdin)
    blocks = markdown_to_blocks(md)
    if not blocks:
        typer.secho(
            "error: input produced no blocks (empty or unsupported markdown).",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=5)
    if opts.dry_run:
        dry_run_and_exit(
            opts,
            f"{CREATE_DOC_BLOCK} (looped per block)",
            {"doc": doc_id, "blocks": blocks},
        )
    client = client_or_exit(opts)
    created: list[dict[str, Any]] = []
    try:
        with client:
            # Seed `after_block_id` from the doc's current last block so blocks
            # land at the end (monday's default for `after=null` is TOP insert).
            existing_doc = _fetch_doc_by_id_all_blocks(client, doc_id)
            if existing_doc is None:
                typer.secho(f"doc id={doc_id} not found.", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=6)
            prev_id = _last_block_id(existing_doc)
            for block in blocks:
                data = exec_or_exit(
                    client,
                    CREATE_DOC_BLOCK,
                    {
                        "doc": doc_id,
                        "type": block["type"],
                        "content": json.dumps(block.get("content") or {}),
                        "after": prev_id,
                        "parent": None,
                    },
                )
                result = data.get("create_doc_block") or {}
                created.append(result)
                new_id = result.get("id")
                if new_id:
                    prev_id = str(new_id)
    except MondoError as e:
        handle_mondo_error_or_exit(e)
    opts.emit(created)


@app.command("add-markdown", epilog=epilog_for("doc add-markdown"))
def add_markdown_cmd(
    ctx: typer.Context,
    doc_id: int = typer.Option(..., "--doc", help="Doc ID (internal id)."),
    markdown: str | None = typer.Option(None, "--markdown", help="Markdown source."),
    from_file: Path | None = typer.Option(None, "--from-file", help="Load markdown from a file."),
    from_stdin: bool = typer.Option(False, "--from-stdin", help="Load markdown from stdin."),
    after: str | None = typer.Option(None, "--after", help="Insert after this block ID."),
) -> None:
    """Append markdown using monday's server-side markdown parser."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    md = _load_markdown(markdown, from_file, from_stdin)
    variables = {"doc": doc_id, "md": md, "after": after}
    data = execute(opts, ADD_CONTENT_TO_DOC_FROM_MARKDOWN, variables)
    opts.emit(data.get("add_content_to_doc_from_markdown") or {})


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
    opts.emit(data.get("import_doc_from_html") or {})


@app.command("rename", epilog=epilog_for("doc rename"))
def rename_cmd(
    ctx: typer.Context,
    doc_id: int = typer.Option(..., "--doc", help="Doc ID (internal id)."),
    name: str = typer.Option(..., "--name", help="New document title."),
) -> None:
    """Rename a doc."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    data = execute(opts, UPDATE_DOC_NAME, {"doc": doc_id, "name": name})
    opts.emit(data.get("update_doc_name"))


@app.command("duplicate", epilog=epilog_for("doc duplicate"))
def duplicate_cmd(
    ctx: typer.Context,
    doc_id: int = typer.Option(..., "--doc", help="Doc ID (internal id)."),
    duplicate_type: DuplicateDocType | None = typer.Option(
        None,
        "--duplicate-type",
        help="Copy only content, or content+updates.",
        case_sensitive=False,
    ),
) -> None:
    """Duplicate a doc."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    data = execute(
        opts,
        DUPLICATE_DOC,
        {"doc": doc_id, "dup": duplicate_type.value if duplicate_type else None},
    )
    opts.emit(data.get("duplicate_doc"))


@app.command("delete", epilog=epilog_for("doc delete"))
def delete_cmd(
    ctx: typer.Context,
    doc_id: int = typer.Option(..., "--doc", help="Doc ID (internal id)."),
) -> None:
    """Delete a doc."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    data = execute(opts, DELETE_DOC, {"doc": doc_id})
    opts.emit(data.get("delete_doc"))


@app.command("export-markdown", epilog=epilog_for("doc export-markdown"))
def export_markdown_cmd(
    ctx: typer.Context,
    doc_id: int = typer.Option(..., "--doc", help="Doc ID (internal id)."),
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
    data = execute(
        opts,
        EXPORT_MARKDOWN_FROM_DOC,
        {"doc": doc_id, "blocks": block_id or None},
    )
    result = data.get("export_markdown_from_doc") or {}
    if raw:
        opts.emit(result)
        return
    if not result.get("success"):
        err = result.get("error") or "export_markdown_from_doc failed"
        typer.secho(f"error: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=5)
    typer.echo(result.get("markdown") or "")


@app.command("version-history", epilog=epilog_for("doc version-history"))
def version_history_cmd(
    ctx: typer.Context,
    doc_id: int = typer.Option(..., "--doc", help="Doc ID (internal id)."),
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
    data = execute(opts, DOC_VERSION_HISTORY, {"doc": doc_id, "since": since, "until": until})
    opts.emit(data.get("doc_version_history") or {})


@app.command("version-diff", epilog=epilog_for("doc version-diff"))
def version_diff_cmd(
    ctx: typer.Context,
    doc_id: int = typer.Option(..., "--doc", help="Doc ID (internal id)."),
    date: str = typer.Option(..., "--date", help="Newer restoring-point ISO8601 timestamp."),
    prev_date: str = typer.Option(
        ...,
        "--prev-date",
        help="Older restoring-point ISO8601 timestamp.",
    ),
) -> None:
    """Fetch block-level diff between two restoring points (API 2026-04+)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    data = execute(opts, DOC_VERSION_DIFF, {"doc": doc_id, "date": date, "prev": prev_date})
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
    opts.emit(data.get("delete_doc_block") or {})
