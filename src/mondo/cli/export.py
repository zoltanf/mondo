"""`mondo export` command group — dump a board to CSV / JSON / XLSX / Markdown.

Uses cursor pagination (reused from `item list`) plus a one-shot column-title
fetch for readable headers. Formats:

- csv / tsv: RFC 4180, one row per item, columns = meta + one-per-board-column
- json: list of objects keyed by column id + metadata
- xlsx: one sheet for items (+ one for subitems if --include-subitems)
- md:  GFM-style pipe table

Output defaults to stdout for csv/tsv/json/md, and requires `--out` for xlsx
(binary format).
"""

from __future__ import annotations

import csv
import io
import json
from enum import StrEnum
from pathlib import Path
from typing import Any

import typer
from openpyxl import Workbook  # type: ignore[import-untyped]

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError, NotFoundError
from mondo.api.pagination import MAX_PAGE_SIZE, iter_items_page
from mondo.api.queries import (
    ITEMS_PAGE_INITIAL_WITH_SUBITEMS,
    ITEMS_PAGE_NEXT_WITH_SUBITEMS,
)
from mondo.cli._column_cache import fetch_board_columns
from mondo.cli._examples import epilog_for
from mondo.cli._exec import client_or_exit
from mondo.cli._resolve import resolve_required_id
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


class ExportFormat(StrEnum):
    csv = "csv"
    tsv = "tsv"
    json = "json"
    xlsx = "xlsx"
    md = "md"


META_FIELDS = ("id", "name", "state", "group")


# ----- helpers -----


def _fetch_columns(
    opts: GlobalOpts, client: MondayClient, board_id: int
) -> list[dict[str, Any]]:
    """Return [{id, title, type}] for the board, in display order."""
    try:
        cols = fetch_board_columns(opts, client, board_id)
    except NotFoundError:
        raise typer.Exit(code=6) from None
    return [
        {"id": c.get("id"), "title": c.get("title"), "type": c.get("type")}
        for c in cols
        if not c.get("archived")
    ]


def _column_text(item: dict[str, Any], col_id: str) -> str:
    for cv in item.get("column_values") or []:
        if cv.get("id") == col_id:
            return cv.get("text") or ""
    return ""


def _item_row(item: dict[str, Any], columns: list[dict[str, Any]]) -> dict[str, Any]:
    """Flat dict: {meta fields + one key per column title}."""
    row: dict[str, Any] = {
        "id": item.get("id"),
        "name": item.get("name"),
        "state": item.get("state"),
        "group": (item.get("group") or {}).get("title"),
    }
    for col in columns:
        row[col["title"]] = _column_text(item, col["id"])
    return row


def _subitem_row(
    subitem: dict[str, Any], parent: dict[str, Any], columns: list[dict[str, Any]]
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "parent_item_id": parent.get("id"),
        "parent_item_name": parent.get("name"),
        "id": subitem.get("id"),
        "name": subitem.get("name"),
        "state": subitem.get("state"),
    }
    for col in columns:
        row[col["title"]] = _column_text(subitem, col["id"])
    return row


# ----- format writers -----


def _write_csv(rows: list[dict[str, Any]], headers: list[str], delimiter: str, stream: Any) -> None:
    writer = csv.DictWriter(
        stream,
        fieldnames=headers,
        delimiter=delimiter,
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\n",
        extrasaction="ignore",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({h: row.get(h, "") for h in headers})


def _write_json(payload: Any, stream: Any) -> None:
    json.dump(payload, stream, indent=2, ensure_ascii=False)
    stream.write("\n")


def _write_markdown(rows: list[dict[str, Any]], headers: list[str], stream: Any) -> None:
    def esc(v: Any) -> str:
        return str(v if v is not None else "").replace("|", "\\|").replace("\n", " ")

    stream.write("| " + " | ".join(headers) + " |\n")
    stream.write("|" + "|".join(["---"] * len(headers)) + "|\n")
    for row in rows:
        stream.write("| " + " | ".join(esc(row.get(h, "")) for h in headers) + " |\n")


def _write_xlsx(
    items_rows: list[dict[str, Any]],
    items_headers: list[str],
    subitems_rows: list[dict[str, Any]] | None,
    subitems_headers: list[str] | None,
    out_path: Path,
) -> None:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "items"
    ws.append(items_headers)
    for row in items_rows:
        ws.append([row.get(h, "") for h in items_headers])
    if subitems_rows is not None and subitems_headers is not None:
        sws = wb.create_sheet("subitems")
        sws.append(subitems_headers)
        for row in subitems_rows:
            sws.append([row.get(h, "") for h in subitems_headers])
    wb.save(out_path)


# ----- command -----


@app.command("board", epilog=epilog_for("export board"))
def board_cmd(
    ctx: typer.Context,
    board_pos: int | None = typer.Argument(
        None, metavar="[BOARD_ID]", help="Board ID (positional)."
    ),
    board_flag: int | None = typer.Option(None, "--board", help="Board ID (flag form)."),
    fmt: ExportFormat = typer.Option(
        ExportFormat.csv,
        "--format",
        "-f",
        help="Output format.",
        case_sensitive=False,
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Output file path. Required for xlsx. Omit to write to stdout.",
    ),
    include_subitems: bool = typer.Option(
        False, "--include-subitems", help="Also export each item's subitems."
    ),
    limit: int = typer.Option(MAX_PAGE_SIZE, "--limit", help=f"Page size (max {MAX_PAGE_SIZE})."),
    max_items: int | None = typer.Option(
        None, "--max-items", help="Stop after this many items total."
    ),
) -> None:
    """Export a board's items (and optionally subitems) in the chosen format."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    board_id = resolve_required_id(board_pos, board_flag, flag_name="--board", resource="board")

    if fmt is ExportFormat.xlsx and out is None:
        typer.secho(
            "error: xlsx is a binary format; pass --out PATH.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    client = client_or_exit(opts)
    try:
        with client:
            columns = _fetch_columns(opts, client, board_id)
            query_initial = None
            query_next = None
            if include_subitems:
                query_initial = ITEMS_PAGE_INITIAL_WITH_SUBITEMS
                query_next = ITEMS_PAGE_NEXT_WITH_SUBITEMS
            iterator_kwargs: dict[str, Any] = {
                "board_id": board_id,
                "limit": limit,
                "max_items": max_items,
            }
            if query_initial is not None and query_next is not None:
                iterator_kwargs["query_initial"] = query_initial
                iterator_kwargs["query_next"] = query_next

            items = list(iter_items_page(client, **iterator_kwargs))
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    col_titles = [c["title"] for c in columns]
    item_headers = [*META_FIELDS, *col_titles]
    item_rows = [_item_row(it, columns) for it in items]

    subitem_headers: list[str] | None = None
    subitem_rows: list[dict[str, Any]] | None = None
    if include_subitems:
        subitem_headers = ["parent_item_id", "parent_item_name", "id", "name", "state", *col_titles]
        subitem_rows = []
        for parent in items:
            for sub in parent.get("subitems") or []:
                subitem_rows.append(_subitem_row(sub, parent, columns))

    _dispatch(fmt, item_rows, item_headers, subitem_rows, subitem_headers, out)


def _dispatch(
    fmt: ExportFormat,
    item_rows: list[dict[str, Any]],
    item_headers: list[str],
    subitem_rows: list[dict[str, Any]] | None,
    subitem_headers: list[str] | None,
    out: Path | None,
) -> None:
    if fmt is ExportFormat.xlsx:
        assert out is not None
        _write_xlsx(item_rows, item_headers, subitem_rows, subitem_headers, out)
        return

    buf: Any = out.open("w", encoding="utf-8", newline="") if out is not None else io.StringIO()

    try:
        if fmt is ExportFormat.csv:
            _write_csv(item_rows, item_headers, ",", buf)
            if subitem_rows is not None and subitem_headers is not None:
                buf.write("\n")
                _write_csv(subitem_rows, subitem_headers, ",", buf)
        elif fmt is ExportFormat.tsv:
            _write_csv(item_rows, item_headers, "\t", buf)
            if subitem_rows is not None and subitem_headers is not None:
                buf.write("\n")
                _write_csv(subitem_rows, subitem_headers, "\t", buf)
        elif fmt is ExportFormat.json:
            payload: dict[str, Any] = {"items": item_rows}
            if subitem_rows is not None:
                payload["subitems"] = subitem_rows
            _write_json(payload, buf)
        elif fmt is ExportFormat.md:
            _write_markdown(item_rows, item_headers, buf)
            if subitem_rows is not None and subitem_headers is not None:
                buf.write("\n### Subitems\n\n")
                _write_markdown(subitem_rows, subitem_headers, buf)
    finally:
        if out is not None:
            buf.close()
        else:
            typer.echo(buf.getvalue(), nl=False)
