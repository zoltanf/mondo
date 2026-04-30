"""`mondo column doc` subcommand group: get, set, append, clear.

The doc column holds a pointer (JSON value) to one or more workspace docs.
Reading content is a two-step process: extract the objectId from the column,
then query `docs(object_ids:...)` for the block tree.

Writing means either creating a new doc attached to the column
(`create_doc(location: { board: { item_id, column_id } })`) or appending
blocks to an existing doc (monday dropped the bulk `create_doc_blocks`; we
loop `create_doc_block` singular calls, chaining `after_block_id` so order
is preserved under concurrent edits).
"""

from __future__ import annotations

import json
import sys
from enum import StrEnum
from pathlib import Path
from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError, NotFoundError
from mondo.api.queries import (
    CHANGE_COLUMN_VALUE,
    COLUMN_CONTEXT,
    CREATE_DOC_BLOCK,
    CREATE_DOC_ON_ITEM,
    DOCS_BY_OBJECT_ID_BLOCKS_PAGE,
)
from mondo.cli._examples import epilog_for
from mondo.cli._exec import client_or_exit
from mondo.cli.context import GlobalOpts
from mondo.docs import (
    blocks_to_markdown,
    extract_doc_ids_from_column_value,
    markdown_to_blocks,
)

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)

_DOC_BLOCKS_PAGE_SIZE = 100


class DocFormat(StrEnum):
    markdown = "markdown"
    raw_blocks = "raw-blocks"


# ----- helpers -----


def _exec(client: MondayClient, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    result = client.execute(query, variables=variables)
    return result.get("data") or {}


def _fetch_doc_column_value(
    client: MondayClient, item_id: int, column_id: str
) -> tuple[int, str | None]:
    """Return (board_id, raw_value). Raises NotFoundError on missing item/column."""
    data = _exec(client, COLUMN_CONTEXT, {"id": item_id, "cols": [column_id]})
    items = data.get("items") or []
    if not items:
        raise NotFoundError(f"item {item_id} not found")
    board = items[0].get("board") or {}
    board_id = int(board.get("id") or 0)
    if not board_id:
        raise NotFoundError(f"item {item_id} has no board")
    # Confirm column exists and is actually a doc column
    defs = {c["id"]: c for c in (board.get("columns") or [])}
    if column_id not in defs:
        raise NotFoundError(f"column {column_id!r} not on item {item_id}'s board")
    if defs[column_id].get("type") != "doc":
        raise typer.BadParameter(
            f"column {column_id!r} is type {defs[column_id].get('type')!r}, not 'doc'"
        )
    values = {v["id"]: v for v in (items[0].get("column_values") or [])}
    raw = values.get(column_id, {}).get("value")
    return board_id, raw


def _fetch_doc_blocks(client: MondayClient, object_id: int) -> dict[str, Any]:
    page = 1
    merged: dict[str, Any] | None = None
    all_blocks: list[dict[str, Any]] = []

    while True:
        data = _exec(
            client,
            DOCS_BY_OBJECT_ID_BLOCKS_PAGE,
            {"objs": [object_id], "limit": _DOC_BLOCKS_PAGE_SIZE, "page": page},
        )
        docs = data.get("docs") or []
        if not docs:
            raise NotFoundError(f"no workspace doc found for object_id {object_id}")
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


def create_blocks(
    client: MondayClient,
    doc_id: int,
    blocks: list[dict[str, Any]],
    *,
    after_block_id: str | None = None,
    parent_block_id: str | None = None,
) -> list[dict[str, Any]]:
    """Append `blocks` to `doc_id` in order, chaining via `after_block_id`.

    monday removed the bulk `create_doc_blocks` mutation; a loop of
    `create_doc_block` is the canonical replacement. Chaining keeps the
    user-specified order stable even if other clients are writing concurrently.

    Without an `after_block_id`, monday inserts at the *top* of the doc; pass
    the existing last block's id to get true append semantics.

    If a block carries a `_children` list (set by `markdown_to_blocks` for
    GFM callout containers — `notice` / `callout`), each child is created
    with `parent_block_id` pointing at the parent's API-returned id.
    Siblings inside a container form their own `after_block_id` chain.
    """
    created: list[dict[str, Any]] = []
    prev_id: str | None = after_block_id
    for block in blocks:
        data = _exec(
            client,
            CREATE_DOC_BLOCK,
            {
                "doc": doc_id,
                "type": block["type"],
                "content": json.dumps(block.get("content") or {}),
                "after": prev_id,
                "parent": parent_block_id,
            },
        )
        result = data.get("create_doc_block") or {}
        created.append(result)
        new_id = result.get("id")
        if new_id:
            prev_id = str(new_id)
            children = block.get("_children") or []
            if children:
                create_blocks(
                    client,
                    doc_id,
                    children,
                    after_block_id=None,
                    parent_block_id=str(new_id),
                )
    return created


def _last_block_id(doc: dict[str, Any]) -> str | None:
    """Pluck the id of the last top-level block on a doc, or None if empty."""
    blocks = doc.get("blocks") or []
    if not blocks:
        return None
    last = blocks[-1]
    last_id = last.get("id") if isinstance(last, dict) else None
    return str(last_id) if last_id else None


# ----- commands -----


@app.command("get", epilog=epilog_for("column doc get"))
def get_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--item", help="Item ID."),
    column_id: str = typer.Option(..., "--column", help="Doc column ID."),
    fmt: DocFormat = typer.Option(
        DocFormat.markdown,
        "--format",
        help="markdown: concatenated Markdown text; raw-blocks: the block JSON.",
    ),
) -> None:
    """Fetch a doc column's content and render as Markdown or raw blocks."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    client = client_or_exit(opts)

    try:
        with client:
            _board_id, raw_value = _fetch_doc_column_value(client, item_id, column_id)
            object_ids = extract_doc_ids_from_column_value(raw_value)
            if not object_ids:
                typer.secho(
                    f"doc column {column_id!r} on item {item_id} is empty.",
                    fg=typer.colors.YELLOW,
                    err=True,
                )
                if fmt == DocFormat.markdown:
                    typer.echo("")
                else:
                    opts.emit([])
                return

            doc = _fetch_doc_blocks(client, object_ids[0])
    except NotFoundError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6) from e
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    blocks = doc.get("blocks") or []

    if fmt == DocFormat.raw_blocks:
        opts.emit(blocks)
        return
    typer.echo(blocks_to_markdown(blocks))


@app.command("set", epilog=epilog_for("column doc set"))
def set_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--item", help="Item ID."),
    column_id: str = typer.Option(..., "--column", help="Doc column ID."),
    from_file: Path | None = typer.Option(
        None, "--from-file", help="Read markdown content from a file."
    ),
    markdown: str | None = typer.Option(None, "--markdown", help="Inline markdown content."),
    from_stdin: bool = typer.Option(False, "--from-stdin", help="Read markdown from stdin."),
) -> None:
    """Create the doc (if empty) and populate it from markdown. If the column
    already points to a doc, the new blocks are appended (use `doc clear` first
    to replace). Workflow:
    1. Empty column: `create_doc(board={item_id,column_id})` → loop `create_doc_block`
    2. Existing doc: loop `create_doc_block`
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)

    md = _read_markdown_source(markdown, from_file, from_stdin)
    blocks = markdown_to_blocks(md)
    if not blocks:
        typer.secho("error: no content to write.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    client = client_or_exit(opts)
    try:
        with client:
            _board_id, raw_value = _fetch_doc_column_value(client, item_id, column_id)
            object_ids = extract_doc_ids_from_column_value(raw_value)

            if not object_ids:
                if opts.dry_run:
                    opts.emit(
                        {
                            "steps": [
                                {
                                    "query": CREATE_DOC_ON_ITEM,
                                    "variables": {"item": item_id, "col": column_id},
                                },
                                {
                                    "query": f"{CREATE_DOC_BLOCK} (looped per block)",
                                    "variables": {"doc": "<new-doc-id>", "blocks": blocks},
                                },
                            ]
                        }
                    )
                    raise typer.Exit(0)
                created = _exec(client, CREATE_DOC_ON_ITEM, {"item": item_id, "col": column_id})
                doc = created.get("create_doc") or {}
                doc_id = doc.get("id")
                if not doc_id:
                    raise MondoError("create_doc returned no id")
                create_blocks(client, int(doc_id), blocks)
                opts.emit(
                    {
                        "doc_id": doc_id,
                        "object_id": doc.get("object_id"),
                        "url": doc.get("url"),
                        "blocks_created": len(blocks),
                        "created": True,
                    }
                )
                return

            # Existing doc: append blocks (after the current last block)
            doc = _fetch_doc_blocks(client, object_ids[0])
            doc_id = doc.get("id")
            if not doc_id:
                raise MondoError("existing doc has no id")
            if opts.dry_run:
                opts.emit(
                    {
                        "query": f"{CREATE_DOC_BLOCK} (looped per block)",
                        "variables": {"doc": int(doc_id), "blocks": blocks},
                    }
                )
                raise typer.Exit(0)
            create_blocks(client, int(doc_id), blocks, after_block_id=_last_block_id(doc))
            opts.emit(
                {
                    "doc_id": doc_id,
                    "object_id": doc.get("object_id"),
                    "url": doc.get("url"),
                    "blocks_created": len(blocks),
                    "created": False,
                }
            )
    except NotFoundError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6) from e
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e


@app.command("append", epilog=epilog_for("column doc append"))
def append_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--item", help="Item ID."),
    column_id: str = typer.Option(..., "--column", help="Doc column ID."),
    from_file: Path | None = typer.Option(None, "--from-file", help="Markdown file."),
    markdown: str | None = typer.Option(None, "--markdown", help="Inline markdown."),
    from_stdin: bool = typer.Option(False, "--from-stdin", help="Read markdown from stdin."),
) -> None:
    """Append markdown blocks to an existing doc. Fails if the doc column is empty
    (use `doc set` to create one)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)

    md = _read_markdown_source(markdown, from_file, from_stdin)
    blocks = markdown_to_blocks(md)
    if not blocks:
        typer.secho("error: no content to append.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    client = client_or_exit(opts)
    try:
        with client:
            _board_id, raw_value = _fetch_doc_column_value(client, item_id, column_id)
            object_ids = extract_doc_ids_from_column_value(raw_value)
            if not object_ids:
                typer.secho(
                    "error: doc column is empty. Use `mondo column doc set` first.",
                    fg=typer.colors.RED,
                    err=True,
                )
                raise typer.Exit(code=2)
            doc = _fetch_doc_blocks(client, object_ids[0])
            doc_id = doc.get("id")
            if not doc_id:
                raise MondoError("doc has no id")
            if opts.dry_run:
                opts.emit(
                    {
                        "query": f"{CREATE_DOC_BLOCK} (looped per block)",
                        "variables": {"doc": int(doc_id), "blocks": blocks},
                    }
                )
                raise typer.Exit(0)
            create_blocks(client, int(doc_id), blocks, after_block_id=_last_block_id(doc))
    except NotFoundError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6) from e
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    opts.emit({"doc_id": doc.get("id"), "blocks_created": len(blocks)})


@app.command("clear", epilog=epilog_for("column doc clear"))
def clear_cmd(
    ctx: typer.Context,
    item_id: int = typer.Option(..., "--item", help="Item ID."),
    column_id: str = typer.Option(..., "--column", help="Doc column ID."),
) -> None:
    """Clear the doc column pointer on the item. Does NOT delete the underlying
    workspace doc — it just unlinks it from this item."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    client = client_or_exit(opts)

    try:
        with client:
            board_id, _raw = _fetch_doc_column_value(client, item_id, column_id)
            if opts.dry_run:
                opts.emit(
                    {
                        "query": CHANGE_COLUMN_VALUE,
                        "variables": {
                            "item": item_id,
                            "board": board_id,
                            "col": column_id,
                            "value": "{}",
                            "create_labels": None,
                        },
                    }
                )
                raise typer.Exit(0)
            data = _exec(
                client,
                CHANGE_COLUMN_VALUE,
                {
                    "item": item_id,
                    "board": board_id,
                    "col": column_id,
                    "value": json.dumps({}),
                    "create_labels": None,
                },
            )
    except NotFoundError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6) from e
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    opts.emit(data.get("change_column_value") or {})


# ----- shared helpers -----


def _read_markdown_source(inline: str | None, path: Path | None, from_stdin: bool) -> str:
    """One-of-three source selector: --markdown / --from-file / --from-stdin."""
    sources = [inline is not None, path is not None, from_stdin]
    count = sum(sources)
    if count == 0:
        typer.secho(
            "error: provide --markdown, --from-file, or --from-stdin.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    if count > 1:
        typer.secho(
            "error: --markdown, --from-file, and --from-stdin are mutually exclusive.",
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
