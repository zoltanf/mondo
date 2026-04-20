"""`mondo doc` — workspace-level docs (Phase 3e).

Distinct from the `doc` **column** type (which is handled by
`mondo column doc`). Workspace docs are standalone documents inside a
workspace with a block-structured body. The CLI covers:

- `list` / `get` — page-based listing with optional workspace / object-id
  filters; get emits the full block tree (or a markdown rendering).
- `create` — bootstrap a doc inside a workspace (`CreateDocInput.workspace`).
- `add-block` / `add-content` — single / bulk block inserts. `add-content`
  feeds a markdown file through `docs.markdown_to_blocks` (reused from
  Phase 1f).
- `update-block` / `delete-block` — edit individual blocks.
- `delete` — left un-wired (monday has no top-level `delete_doc` mutation);
  we surface the limitation with a pointer.
"""

from __future__ import annotations

import json
import sys
from enum import StrEnum
from pathlib import Path
from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError
from mondo.api.pagination import iter_boards_page
from mondo.api.queries import (
    CREATE_DOC_BLOCK,
    CREATE_DOC_IN_WORKSPACE,
    DELETE_DOC_BLOCK,
    DOC_GET_BY_ID,
    DOCS_BY_OBJECT_ID,
    DOCS_LIST_PAGE,
    UPDATE_DOC_BLOCK,
)
from mondo.cli._examples import epilog_for
from mondo.cli._resolve import resolve_required_id
from mondo.cli.context import GlobalOpts
from mondo.docs import blocks_to_markdown, markdown_to_blocks

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


# ----- helpers -----


def _client_or_exit(opts: GlobalOpts) -> MondayClient:
    try:
        return opts.build_client()
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e


def _exec_or_exit(client: MondayClient, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    try:
        result = client.execute(query, variables=variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    return result.get("data") or {}


def _dry_run(opts: GlobalOpts, query: str, variables: dict[str, Any]) -> None:
    opts.emit({"query": query, "variables": variables})
    raise typer.Exit(0)


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


# ----- read commands -----


@app.command("list", epilog=epilog_for("doc list"))
def list_cmd(
    ctx: typer.Context,
    workspace: list[int] | None = typer.Option(
        None, "--workspace", help="Restrict to workspace IDs (repeatable)."
    ),
    object_id: list[int] | None = typer.Option(
        None, "--object-id", help="Filter by doc object_id (repeatable)."
    ),
    order_by: DocsOrderBy | None = typer.Option(
        None, "--order-by", help="created_at or used_at.", case_sensitive=False
    ),
    limit: int = typer.Option(100, "--limit", help="Page size."),
    max_items: int | None = typer.Option(
        None, "--max-items", help="Stop after this many docs total."
    ),
) -> None:
    """List docs (page-based)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables: dict[str, Any] = {
        "ids": None,
        "objectIds": object_id or None,
        "workspaceIds": workspace or None,
        "orderBy": order_by.value if order_by else None,
    }
    if opts.dry_run:
        opts.emit(
            {
                "query": "<docs page iterator>",
                "variables": {**variables, "limit": limit, "max_items": max_items},
            }
        )
        raise typer.Exit(0)
    client = _client_or_exit(opts)
    try:
        with client:
            items = list(
                iter_boards_page(
                    client,
                    query=DOCS_LIST_PAGE,
                    variables=variables,
                    collection_key="docs",
                    limit=limit,
                    max_items=max_items,
                )
            )
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(items)


@app.command("get", epilog=epilog_for("doc get"))
def get_cmd(
    ctx: typer.Context,
    doc_id: int | None = typer.Option(None, "--id", help="Internal doc ID."),
    object_id: int | None = typer.Option(
        None, "--object-id", help="URL-visible numeric object_id."
    ),
    fmt: DocFormat = typer.Option(
        DocFormat.json,
        "--format",
        help="Emit raw JSON (blocks as-is) or render blocks to markdown.",
        case_sensitive=False,
    ),
) -> None:
    """Fetch a single doc by id or object_id, with its full block tree."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    sources = sum(x is not None for x in (doc_id, object_id))
    if sources != 1:
        typer.secho(
            "error: pass exactly one of --id or --object-id.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    if doc_id is not None:
        query = DOC_GET_BY_ID
        variables = {"ids": [doc_id]}
    else:
        assert object_id is not None  # guaranteed by the sources != 1 check above
        query = DOCS_BY_OBJECT_ID
        variables = {"objs": [object_id]}

    if opts.dry_run:
        _dry_run(opts, query, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, query, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    docs = data.get("docs") or []
    if not docs:
        ref = f"id={doc_id}" if doc_id is not None else f"object_id={object_id}"
        typer.secho(f"doc {ref} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
    doc = docs[0]
    if fmt is DocFormat.markdown:
        blocks = doc.get("blocks") or []
        typer.echo(blocks_to_markdown(blocks))
        return
    opts.emit(doc)


# ----- write commands -----


@app.command("create", epilog=epilog_for("doc create"))
def create_cmd(
    ctx: typer.Context,
    workspace: int = typer.Option(..., "--workspace", help="Target workspace ID."),
    name: str | None = typer.Option(None, "--name", help="Doc name."),
    kind: DocKind | None = typer.Option(
        None, "--kind", help="public / private / share.", case_sensitive=False
    ),
) -> None:
    """Create a new doc inside a workspace."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {
        "workspace": workspace,
        "name": name,
        "kind": kind.value if kind else None,
    }
    if opts.dry_run:
        _dry_run(opts, CREATE_DOC_IN_WORKSPACE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, CREATE_DOC_IN_WORKSPACE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("create_doc") or {})


@app.command("add-block", epilog=epilog_for("doc add-block"))
def add_block_cmd(
    ctx: typer.Context,
    doc_id: int = typer.Option(..., "--doc", help="Doc ID (internal id, NOT object_id)."),
    block_type: str = typer.Option(
        ...,
        "--type",
        help="Block type (normal_text, heading, bullet_list, numbered_list, "
        "quote, code, divider, …).",
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
    try:
        parsed_content = json.loads(content)
    except json.JSONDecodeError as e:
        typer.secho(f"error: --content is not valid JSON: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from e
    if opts.dry_run:
        _dry_run(
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
    client = _client_or_exit(opts)
    try:
        with client:
            effective_after = after
            if effective_after is None:
                pre = _exec_or_exit(client, DOC_GET_BY_ID, {"ids": [doc_id]})
                docs_list = pre.get("docs") or []
                existing = (docs_list[0].get("blocks") or []) if docs_list else []
                if existing:
                    effective_after = str(existing[-1].get("id"))
            data = _exec_or_exit(
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
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
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
        _dry_run(
            opts,
            f"{CREATE_DOC_BLOCK} (looped per block)",
            {"doc": doc_id, "blocks": blocks},
        )
    client = _client_or_exit(opts)
    created: list[dict[str, Any]] = []
    try:
        with client:
            # Seed `after_block_id` from the doc's current last block so blocks
            # land at the end (monday's default for `after=null` is TOP insert).
            pre = _exec_or_exit(client, DOC_GET_BY_ID, {"ids": [doc_id]})
            docs_list = pre.get("docs") or []
            existing_blocks = (docs_list[0].get("blocks") or []) if docs_list else []
            prev_id: str | None = str(existing_blocks[-1].get("id")) if existing_blocks else None
            for block in blocks:
                data = _exec_or_exit(
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
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(created)


@app.command("update-block", epilog=epilog_for("doc update-block"))
def update_block_cmd(
    ctx: typer.Context,
    id_pos: str | None = typer.Argument(None, metavar="[BLOCK_ID]", help="Block ID (positional)."),
    id_flag: str | None = typer.Option(None, "--id", help="Block ID (flag form)."),
    content: str = typer.Option(
        ..., "--content", metavar="JSON", help="Replacement content as JSON."
    ),
) -> None:
    """Replace a single block's content."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    block_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="block")
    try:
        parsed_content = json.loads(content)
    except json.JSONDecodeError as e:
        typer.secho(f"error: --content is not valid JSON: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from e
    # monday's JSON scalar wants the content as a JSON-encoded string (matches
    # what create_doc_block does). We validated the JSON above; now re-stringify.
    variables = {"block": block_id, "content": json.dumps(parsed_content)}
    if opts.dry_run:
        _dry_run(opts, UPDATE_DOC_BLOCK, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, UPDATE_DOC_BLOCK, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("update_doc_block") or {})


@app.command("delete-block", epilog=epilog_for("doc delete-block"))
def delete_block_cmd(
    ctx: typer.Context,
    id_pos: str | None = typer.Argument(None, metavar="[BLOCK_ID]", help="Block ID (positional)."),
    id_flag: str | None = typer.Option(None, "--id", help="Block ID (flag form)."),
) -> None:
    """Delete a single block from a doc."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    block_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="block")
    variables = {"block": block_id}
    if opts.dry_run:
        _dry_run(opts, DELETE_DOC_BLOCK, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, DELETE_DOC_BLOCK, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("delete_doc_block") or {})
