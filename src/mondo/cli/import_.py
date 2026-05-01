"""`mondo import` command group — bulk-create items on a board from a CSV.

Row flow per CSV line:

1. Meta columns (`name`, optional `group`) are consumed directly.
2. Remaining columns are mapped to monday column IDs — either by matching
   the CSV header to a board column title (default) or via an explicit
   `--mapping mapping.yaml` file.
3. Values are dispatched through the same ColumnCodec registry used by
   `mondo item create`, so smart shorthand (`Done`, `2026-04-25`, ...)
   works here too.
4. Optional `--idempotency-name` pre-fetches existing item names on the
   board; rows whose name already exists are skipped without a mutation.

This command emits one result object per row, and a tailing summary.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError, NotFoundError, UsageError
from mondo.api.pagination import iter_items_page
from mondo.api.queries import (
    CREATE_OR_GET_TAG,
    ITEM_CREATE,
)
from mondo.cli._column_cache import fetch_board_columns, invalidate_columns_cache
from mondo.cli._examples import epilog_for
from mondo.cli._exec import client_or_exit, handle_mondo_error_or_exit
from mondo.cli._resolve import resolve_required_id
from mondo.cli.context import GlobalOpts
from mondo.columns import UnknownColumnTypeError, parse_value

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


# ----- helpers -----


def _parse_settings(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _load_mapping(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    from ruamel.yaml import YAML

    yaml = YAML(typ="safe")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.load(f) or {}
    if not isinstance(data, dict):
        raise UsageError(f"--mapping {path} must be a YAML mapping at top level.")
    return data


def _build_header_to_column_id(
    headers: list[str],
    mapping: dict[str, Any],
    board_columns: list[dict[str, Any]],
    name_col: str,
    group_col: str,
) -> dict[str, str]:
    """Return {csv_header: monday_column_id} for header → column resolution.

    Priority per header:
    1. Explicit entry in mapping['columns']
    2. Case-insensitive title match against the board's columns
    3. Ignore (header is dropped from the write)
    """
    explicit = mapping.get("columns") or {}
    by_title = {c.get("title", "").casefold(): c.get("id") for c in board_columns if c.get("id")}
    resolved: dict[str, str] = {}
    for header in headers:
        if header in {name_col, group_col, "id", "state"}:
            continue
        if header in explicit:
            resolved[header] = str(explicit[header])
            continue
        hit = by_title.get(header.casefold())
        if hit:
            resolved[header] = hit
    return resolved


def _fetch_board_columns(
    opts: GlobalOpts, client: MondayClient, board_id: int
) -> list[dict[str, Any]]:
    try:
        return fetch_board_columns(opts, client, board_id)
    except NotFoundError:
        raise typer.Exit(code=6) from None


def _fetch_existing_names(client: MondayClient, board_id: int) -> set[str]:
    """Pre-fetch all existing (active) item names on a board for idempotency guard."""
    names: set[str] = set()
    for it in iter_items_page(client, board_id=board_id):
        name = it.get("name")
        if name:
            names.add(name)
    return names


def _resolve_tag_names_to_ids(client: MondayClient, board_id: int, value: str) -> str:
    parts = [p.strip() for p in value.split(",") if p.strip()]
    ids: list[int] = []
    for part in parts:
        if part.isdigit() or (part.startswith("-") and part[1:].isdigit()):
            ids.append(int(part))
            continue
        data = client.execute(CREATE_OR_GET_TAG, {"name": part, "board": board_id})
        tag = ((data.get("data") or {}).get("create_or_get_tag")) or {}
        if not tag.get("id"):
            raise MondoError(f"create_or_get_tag returned no id for {part!r}")
        ids.append(int(tag["id"]))
    return ",".join(str(i) for i in ids)


def _encode_row(
    client: MondayClient,
    board_id: int,
    row_values: dict[str, str],
    header_to_col_id: dict[str, str],
    col_defs: dict[str, dict[str, Any]],
    *,
    create_labels: bool = False,
) -> dict[str, Any]:
    """Turn a CSV row (header → string value) into a monday column_values dict."""
    out: dict[str, Any] = {}
    for header, raw in row_values.items():
        if raw == "" or raw is None:
            continue
        col_id = header_to_col_id.get(header)
        if col_id is None:
            continue
        definition = col_defs.get(col_id)
        if definition is None:
            out[col_id] = raw
            continue
        col_type = definition.get("type")
        if not isinstance(col_type, str):
            out[col_id] = raw
            continue
        settings = _parse_settings(definition.get("settings_str"))
        if col_type == "tags":
            raw = _resolve_tag_names_to_ids(client, board_id, raw)
        try:
            out[col_id] = parse_value(col_type, raw, settings, create_labels=create_labels)
        except UnknownColumnTypeError:
            out[col_id] = raw
        except ValueError as e:
            raise ValueError(f"column {col_id}={raw!r}: {e}") from e
    return out


# ----- command -----


@app.command("board", epilog=epilog_for("import board"))
def board_cmd(
    ctx: typer.Context,
    board_pos: int | None = typer.Argument(
        None, metavar="[BOARD_ID]", help="Board ID (positional)."
    ),
    board_flag: int | None = typer.Option(None, "--board", help="Board ID (flag form)."),
    source: Path = typer.Option(..., "--from", help="CSV file to read rows from."),
    mapping_path: Path | None = typer.Option(
        None, "--mapping", help="YAML file with header → column_id overrides."
    ),
    default_group: str | None = typer.Option(
        None,
        "--group",
        help="Default group ID for rows whose 'group' column is empty.",
    ),
    name_column: str = typer.Option(
        "name",
        "--name-column",
        help="CSV header that carries the item name (default: 'name').",
    ),
    group_column: str = typer.Option(
        "group",
        "--group-column",
        help="CSV header that carries the group ID (default: 'group').",
    ),
    create_labels_if_missing: bool = typer.Option(
        False, "--create-labels-if-missing", help="Auto-create missing status/dropdown labels."
    ),
    idempotency_name: bool = typer.Option(
        False,
        "--idempotency-name",
        help=(
            "Before importing, list existing item names on the board; skip rows "
            "whose name already exists. O(board size) extra queries at startup."
        ),
    ),
    delimiter: str = typer.Option(",", "--delimiter", help="CSV delimiter (default ',')."),
) -> None:
    """Bulk-create items on a board from a CSV file."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    board_id = resolve_required_id(board_pos, board_flag, flag_name="--board", resource="board")

    try:
        mapping = _load_mapping(mapping_path)
    except UsageError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from e

    name_col = mapping.get("name_column", name_column) or name_column
    group_col = mapping.get("group_column", group_column) or group_column

    client = client_or_exit(opts)

    results: list[dict[str, Any]] = []
    created = skipped = failed = 0

    try:
        with client, source.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh, delimiter=delimiter)
            headers = list(reader.fieldnames or [])
            if name_col not in headers:
                typer.secho(
                    f"error: --name-column {name_col!r} missing from CSV headers {headers}.",
                    fg=typer.colors.RED,
                    err=True,
                )
                raise typer.Exit(code=2)

            board_columns = _fetch_board_columns(opts, client, board_id)
            col_defs = {c["id"]: c for c in board_columns if c.get("id")}
            header_to_col_id = _build_header_to_column_id(
                headers, mapping, board_columns, name_col, group_col
            )

            existing_names: set[str] = set()
            if idempotency_name:
                existing_names = _fetch_existing_names(client, board_id)

            for row in reader:
                name = (row.get(name_col) or "").strip()
                if not name:
                    results.append({"status": "failed", "error": "empty name", "row": row})
                    failed += 1
                    continue

                if idempotency_name and name in existing_names:
                    results.append({"status": "skipped", "name": name, "reason": "name exists"})
                    skipped += 1
                    continue

                try:
                    col_values = _encode_row(
                        client,
                        board_id,
                        {h: row.get(h, "") for h in headers},
                        header_to_col_id,
                        col_defs,
                        create_labels=create_labels_if_missing,
                    )
                except ValueError as e:
                    results.append({"status": "failed", "name": name, "error": str(e)})
                    failed += 1
                    continue

                group_id = (row.get(group_col) or "").strip() or default_group
                variables = {
                    "board": board_id,
                    "name": name,
                    "group": group_id,
                    "values": json.dumps(col_values) if col_values else None,
                    "create_labels": create_labels_if_missing if create_labels_if_missing else None,
                    "prm": None,
                    "relto": None,
                }

                if opts.dry_run:
                    results.append({"status": "dry-run", "name": name, "variables": variables})
                    continue

                try:
                    result = client.execute(ITEM_CREATE, variables=variables)
                    item = ((result.get("data") or {}).get("create_item")) or {}
                    results.append(
                        {"status": "created", "id": item.get("id"), "name": item.get("name")}
                    )
                    created += 1
                    if idempotency_name and item.get("name"):
                        existing_names.add(item["name"])
                except MondoError as e:
                    results.append({"status": "failed", "name": name, "error": str(e)})
                    failed += 1
    except MondoError as e:
        handle_mondo_error_or_exit(e)
    except FileNotFoundError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from e

    if create_labels_if_missing and created > 0:
        # Batch may have minted status/dropdown labels in settings_str; a
        # single post-run invalidation is enough since the next read will
        # re-fetch fresh defs for the whole board.
        invalidate_columns_cache(opts, board_id)

    summary = {
        "created": created,
        "skipped": skipped,
        "failed": failed,
        "total": len(results),
    }
    opts.emit({"summary": summary, "results": results})

    if failed > 0:
        raise typer.Exit(code=1)
