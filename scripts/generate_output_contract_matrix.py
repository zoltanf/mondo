"""Generate a command-by-command stdout shape matrix for mondo.

Outputs:
- docs/output-contract-matrix.json
- docs/output-contract-matrix.md

The matrix is intentionally scoped to successful, non-dry-run stdout output.
It documents top-level field order for objects / list rows and annotates
variant-dependent fields in notes.
"""

from __future__ import annotations

import ast
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_DIR = REPO_ROOT / "src" / "mondo" / "cli"
QUERIES_FILE = REPO_ROOT / "src" / "mondo" / "api" / "queries.py"
OUT_JSON = REPO_ROOT / "docs" / "output-contract-matrix.json"
OUT_MD = REPO_ROOT / "docs" / "output-contract-matrix.md"


@dataclass
class Row:
    command: str
    output_type: str
    fields: list[str]
    notes: str
    source: str


SPECIAL_ROOT = {
    ("auth.py", "whoami"): "auth whoami",
    ("auth.py", "status"): "auth status",
    ("auth.py", "login"): "auth login",
    ("auth.py", "logout"): "auth logout",
    ("me.py", "me_command"): "me",
    ("me.py", "account_command"): "account",
    ("graphql.py", "graphql_command"): "graphql",
    ("help.py", "help_command"): "help",
}

GROUP_ALIASES = {
    "import_": "import",
    "column_doc": "column doc",
}


MANUAL_ROWS: dict[str, Row] = {
    "activity board": Row(
        command="activity board",
        output_type="list[object]",
        fields=[
            "id",
            "event",
            "entity",
            "user_id",
            "created_at",
            "account_id",
            "data",
        ],
        notes="Raw board activity log rows from boards[].activity_logs[].",
        source="BOARD_ACTIVITY_LOGS.boards[].activity_logs[]",
    ),
    "aggregate board": Row(
        command="aggregate board",
        output_type="list[object]",
        fields=["<alias 1>", "<alias 2>", "..."],
        notes=(
            "Dynamic flattened rows. Group-by aliases come first, then select aliases in the "
            "order requested on the CLI."
        ),
        source="_flatten_results(aggregate.results[].entries[])",
    ),
    "auth login": Row(
        command="auth login",
        output_type="text-message",
        fields=[],
        notes="No structured payload. Prints a confirmation line after storing the token.",
        source="typer.secho",
    ),
    "auth logout": Row(
        command="auth logout",
        output_type="text-message",
        fields=[],
        notes="No structured payload. Prints a confirmation line after removing the token.",
        source="typer.secho",
    ),
    "auth whoami": Row(
        command="auth whoami",
        output_type="object",
        fields=["id", "name", "email", "is_admin", "account{id,name,slug,tier}"],
        notes="Thin passthrough of the ME query's me object.",
        source="ME_QUERY.me",
    ),
    "auth status": Row(
        command="auth status",
        output_type="object",
        fields=[
            "profile",
            "token_source",
            "keyring_key",
            "config_file",
            "api_version",
            "user_id",
            "user_name",
            "user_email",
            "is_admin",
            "account_id",
            "account_name",
            "account_slug",
            "account_tier",
        ],
        notes="Custom flattened identity/status payload.",
        source="auth.status payload",
    ),
    "board duplicate": Row(
        command="board duplicate",
        output_type="object",
        fields=["board{id,name,state,board_kind,workspace_id}", "_wait?"],
        notes=(
            "Base payload is duplicate_board.board. When --wait is used, _wait is appended last "
            "with final_items_count and source_items_count."
        ),
        source="BOARD_DUPLICATE.duplicate_board + duplicate_payload",
    ),
    "board get": Row(
        command="board get",
        output_type="object",
        fields=[
            "id",
            "name",
            "description",
            "state",
            "board_kind",
            "type",
            "board_folder_id",
            "workspace_id",
            "items_count",
            "updated_at",
            "permissions",
            "workspace{id,name,kind}",
            "owners{id,name}",
            "subscribers{id,name}",
            "top_group{id,title}",
            "groups{id,title,color,position,archived}",
            "columns{id,title,type,description,archived}",
            "tags{id,name,color}",
            "url?",
        ],
        notes="with_url appends a synthesized url last. Unlike board list, keys are not normalized.",
        source="BOARD_GET.boards[0] + optional synthesized url",
    ),
    "board list": Row(
        command="board list",
        output_type="list[object]",
        fields=[
            "id",
            "name",
            "description",
            "state",
            "workspace_id",
            "created_at",
            "updated_at",
            "type",
            "items_count?",
            "kind",
            "folder_id",
            "_fuzzy_score?",
            "workspace_name?",
            "url?",
        ],
        notes=(
            "Normalized: board_kind -> kind, board_folder_id -> folder_id. items_count appears only "
            "with --with-item-counts. _fuzzy_score is appended by --fuzzy-score. workspace_name is "
            "best-effort enrichment. url is appended by --with-url."
        ),
        source="build_boards_list_query + normalize_board_entry + decorators",
    ),
    "board update": Row(
        command="board update",
        output_type="object | scalar",
        fields=["success?", "<updated board metadata?>"],
        notes=(
            "Emits monday's update_board payload directly. Legacy stringified JSON is parsed "
            "before emit; non-JSON scalars pass through unchanged."
        ),
        source='_decode_json_string_payload(data.get("update_board"))',
    ),
    "cache clear": Row(
        command="cache clear",
        output_type="list[object]",
        fields=["type", "path", "removed", "board?"],
        notes="Column-scope rows include board and order as type, board, path, removed.",
        source="cache.clear results",
    ),
    "cache refresh": Row(
        command="cache refresh",
        output_type="list[object]",
        fields=["type", "fetched_at", "count", "board?"],
        notes="Column-scope rows include board and order as type, board, fetched_at, count.",
        source="cache.refresh results",
    ),
    "cache status": Row(
        command="cache status",
        output_type="list[object]",
        fields=["type", "path", "fetched_at", "age", "ttl_seconds", "fresh", "entries", "board?"],
        notes="Column-scope rows append board last.",
        source="cache.status rows",
    ),
    "column doc append": Row(
        command="column doc append",
        output_type="object",
        fields=["doc_id", "blocks_created"],
        notes="Dry-run emits a query/variables object instead.",
        source="column_doc.append payload",
    ),
    "column doc clear": Row(
        command="column doc clear",
        output_type="object",
        fields=["id", "name", "column_values{id,type,text,value}"],
        notes="Same root shape as change_column_value.",
        source="CHANGE_COLUMN_VALUE.change_column_value",
    ),
    "column doc get": Row(
        command="column doc get",
        output_type="string | list[object]",
        fields=["id", "type", "content", "parent_block_id"],
        notes="Default format is markdown string. --format raw-blocks emits the blocks list above.",
        source="DOCS_BY_OBJECT_ID.docs[0].blocks[] | blocks_to_markdown",
    ),
    "column doc set": Row(
        command="column doc set",
        output_type="object",
        fields=["doc_id", "object_id", "url", "blocks_created", "created"],
        notes="When the column is empty, created=true. When appending to an existing doc, created=false.",
        source="column_doc.set payload",
    ),
    "column get": Row(
        command="column get",
        output_type="scalar | object",
        fields=["id", "type", "text", "value"],
        notes="Default output is a rendered scalar/string. --raw emits the current column_values row.",
        source="COLUMN_CONTEXT.items[0].column_values[] | render_value",
    ),
    "column clear": Row(
        command="column clear",
        output_type="object",
        fields=["id", "name", "column_values{id,type,text,value}"],
        notes="Successful non-dry-run output is the changed item payload for the cleared column.",
        source="CHANGE_COLUMN_VALUE.change_column_value",
    ),
    "column labels": Row(
        command="column labels",
        output_type="list[object]",
        fields=["index,label | id,name"],
        notes="Status columns emit {index,label}; dropdown columns emit {id,name}.",
        source="iter_status_labels | iter_dropdown_labels",
    ),
    "column list": Row(
        command="column list",
        output_type="list[object]",
        fields=["id", "title", "type", "archived"],
        notes="Derived from cached/live column defs; settings_str is intentionally omitted.",
        source="column.list simplified rows",
    ),
    "column set": Row(
        command="column set",
        output_type="object",
        fields=["id", "name", "column_values{id,type,text,value}"],
        notes="Successful non-dry-run output is the changed item payload for the targeted column.",
        source="CHANGE_COLUMN_VALUE.change_column_value",
    ),
    "column set-many": Row(
        command="column set-many",
        output_type="object",
        fields=["id", "name", "column_values{id,type,text,value}"],
        notes="Successful non-dry-run output is the changed item payload with all returned column values.",
        source="CHANGE_MULTIPLE_COLUMN_VALUES.change_multiple_column_values",
    ),
    "complexity status": Row(
        command="complexity status",
        output_type="object",
        fields=[
            "samples",
            "last_query_cost",
            "budget_before",
            "budget_after",
            "reset_in_seconds",
            "total_cost",
        ],
        notes="Custom meter snapshot after one probe query.",
        source="ComplexityMeter.to_dict()",
    ),
    "doc add-content": Row(
        command="doc add-content",
        output_type="list[object]",
        fields=["id", "type", "content", "parent_block_id"],
        notes="One emitted row per created block.",
        source="CREATE_DOC_BLOCK.create_doc_block[]",
    ),
    "doc add-block": Row(
        command="doc add-block",
        output_type="object",
        fields=["id", "type", "content", "parent_block_id"],
        notes="Single created block payload.",
        source="CREATE_DOC_BLOCK.create_doc_block",
    ),
    "doc get": Row(
        command="doc get",
        output_type="object | string",
        fields=[
            "id",
            "object_id",
            "name",
            "doc_kind",
            "doc_folder_id",
            "created_at",
            "updated_at",
            "url",
            "relative_url",
            "workspace_id",
            "created_by{id,name}",
            "blocks{id,type,content,parent_block_id}",
        ],
        notes="Default format is JSON object above. --format markdown prints markdown text instead.",
        source="DOC_GET_BY_ID.docs[0] | DOCS_BY_OBJECT_ID.docs[0]",
    ),
    "doc list": Row(
        command="doc list",
        output_type="list[object]",
        fields=[
            "id",
            "object_id",
            "name",
            "created_at",
            "updated_at",
            "workspace_id",
            "created_by{id,name}",
            "kind",
            "folder_id",
            "_fuzzy_score?",
            "workspace_name?",
            "url?",
            "relative_url?",
        ],
        notes=(
            "Normalized: doc_kind -> kind, doc_folder_id -> folder_id. url/relative_url are removed "
            "unless --with-url is passed. _fuzzy_score is appended by --fuzzy-score. workspace_name "
            "is best-effort enrichment."
        ),
        source="build_docs_list_query + normalize_doc_entry + decorators",
    ),
    "export board": Row(
        command="export board",
        output_type="format-specific",
        fields=["items{id,name,state,group,<column titles...>}", "subitems{...}?"],
        notes=(
            "json emits {items, subitems?}. csv/tsv/md emit item rows with header order "
            "id, name, state, group, then board column titles in display order. xlsx writes files only."
        ),
        source="_item_row / _subitem_row / _dispatch",
    ),
    "file download": Row(
        command="file download",
        output_type="object | list[object]",
        fields=["asset_id", "name", "out", "bytes"],
        notes="One object for a single asset; list of the same row shape for multiple assets.",
        source="file.download results",
    ),
    "file upload": Row(
        command="file upload",
        output_type="object",
        fields=["id", "name", "url", "uploaded_by", "uploaded_at"],
        notes=(
            "Both item-column and update upload paths return an Asset-like payload. Dry-run emits "
            "endpoint/query/variables/filename instead."
        ),
        source="FILE_UPLOAD_ITEM.add_file_to_column | FILE_UPLOAD_UPDATE.add_file_to_update",
    ),
    "folder list": Row(
        command="folder list",
        output_type="list[object]",
        fields=[
            "id",
            "name",
            "color",
            "workspace_id",
            "workspace_name",
            "parent_id",
            "parent_name",
            "created_at",
            "owner_id",
        ],
        notes="Explicit normalized flat folder shape.",
        source="normalize_folder_entry",
    ),
    "folder tree": Row(
        command="folder tree",
        output_type="string | list[object]",
        fields=["workspace_id", "workspace_name", "folders{id,name,color,sub_folders[...] }"],
        notes="table output is an ASCII tree string. Non-table formats emit the structured tree above.",
        source="_build_tree_node + tree renderer",
    ),
    "graphql": Row(
        command="graphql",
        output_type="dynamic object",
        fields=["data?", "errors?", "extensions?"],
        notes="Raw GraphQL response envelope from monday; shape depends entirely on the submitted query.",
        source="client.execute(..., raw=True)",
    ),
    "help": Row(
        command="help",
        output_type="text | object",
        fields=["<dump-spec object>"],
        notes="Normal invocation prints help text. --dump-spec emits the full CLI contract object.",
        source="help topic renderer | _dump_spec(root_app)",
    ),
    "import board": Row(
        command="import board",
        output_type="object",
        fields=["summary", "results"],
        notes=(
            "summary order is created, skipped, failed, total. results rows vary by status: "
            "created{id,name}, skipped{name,reason}, failed{name,error} / failed{error,row}, "
            "dry-run{name,variables}."
        ),
        source="import.board summary/results payload",
    ),
    "item get": Row(
        command="item get",
        output_type="object",
        fields=[
            "id",
            "name",
            "state",
            "created_at",
            "updated_at",
            "creator{id,name}",
            "group{id,title}",
            "board{id,name}",
            "column_values{id,type,text,value}",
            "updates{id,body,text_body,creator{id,name},created_at}?",
            "subitems{id,name,state,column_values{id,type,text,value}}?",
            "url?",
        ],
        notes=(
            "Base command omits url unless --with-url is passed. --include-updates appends updates; "
            "--include-subitems appends subitems instead."
        ),
        source="ITEM_GET | ITEM_GET_WITH_UPDATES | ITEM_GET_WITH_SUBITEMS",
    ),
    "item create": Row(
        command="item create",
        output_type="object",
        fields=["id", "name", "state", "created_at", "group{id,title}", "board{id,name}"],
        notes="Create payload only; column_values are not echoed back here.",
        source="ITEM_CREATE.create_item",
    ),
    "item list": Row(
        command="item list",
        output_type="list[object]",
        fields=["id", "name", "state", "group{id,title}", "column_values{id,type,text,value}"],
        notes="Rows come from items_page / next_items_page. No additional normalization is applied.",
        source="ITEMS_PAGE_INITIAL.items[] / ITEMS_PAGE_NEXT.items[]",
    ),
    "subitem get": Row(
        command="subitem get",
        output_type="object",
        fields=[
            "id",
            "name",
            "state",
            "created_at",
            "updated_at",
            "creator{id,name}",
            "group{id,title}",
            "board{id,name}",
            "column_values{id,type,text,value}",
            "url?",
        ],
        notes="Uses ITEM_GET shape, then strips url unless --with-url is passed.",
        source="ITEM_GET.items[0]",
    ),
    "update list": Row(
        command="update list",
        output_type="list[object]",
        fields=[
            "id",
            "body",
            "text_body",
            "creator{id,name}",
            "item_id?",
            "created_at",
            "updated_at",
            "replies{id,body,creator{id,name}}?",
            "likes{id}?",
            "pinned_to_top{item_id}?",
        ],
        notes=(
            "Account-wide mode returns UPDATES_LIST_PAGE rows with item_id. --item mode returns the "
            "nested richer update shape with replies/likes/pinned_to_top and no top-level item_id."
        ),
        source="UPDATES_LIST_PAGE.updates[] | UPDATES_FOR_ITEM.items[0].updates[]",
    ),
    "validation create": Row(
        command="validation create",
        output_type="error",
        fields=[],
        notes="No success payload. Command always exits 2 because monday removed the mutation.",
        source="_mutation_removed",
    ),
    "validation update": Row(
        command="validation update",
        output_type="error",
        fields=[],
        notes="No success payload. Command always exits 2 because monday removed the mutation.",
        source="_mutation_removed",
    ),
    "validation delete": Row(
        command="validation delete",
        output_type="error",
        fields=[],
        notes="No success payload. Command always exits 2 because monday removed the mutation.",
        source="_mutation_removed",
    ),
    "tag get": Row(
        command="tag get",
        output_type="object",
        fields=["id", "name", "color"],
        notes="Looks in account-level tags first; with --board it falls back to board.tags. Emitted shape is the same.",
        source="TAGS_LIST.tags[0] | TAG_BY_BOARD.boards[0].tags[0]",
    ),
    "team list": Row(
        command="team list",
        output_type="list[object]",
        fields=["id", "name", "picture_url", "is_guest", "users{id,name}", "owners{id,name}", "_fuzzy_score?"],
        notes="When --fuzzy-score is used, _fuzzy_score is appended last.",
        source="TEAMS_LIST.teams[]",
    ),
    "user list": Row(
        command="user list",
        output_type="list[object]",
        fields=[
            "id",
            "name",
            "email",
            "enabled",
            "is_admin",
            "is_guest",
            "is_pending",
            "is_view_only",
            "created_at",
            "last_activity",
            "title",
            "photo_thumb",
            "teams{id,name}",
            "account{id,name,slug,tier}",
            "_fuzzy_score?",
        ],
        notes="When --fuzzy-score is used, _fuzzy_score is appended last.",
        source="USERS_LIST_PAGE.users[]",
    ),
    "user update-role": Row(
        command="user update-role",
        output_type="object",
        fields=["updated_users{id,name,is_admin|is_guest|is_view_only}", "errors{message,code,user_id}"],
        notes="The updated_users subfield varies slightly by target role but keeps the same top-level order.",
        source="USERS_UPDATE_AS_*",
    ),
    "workspace list": Row(
        command="workspace list",
        output_type="list[object]",
        fields=["id", "name", "kind", "description", "state", "created_at", "_fuzzy_score?"],
        notes="When --fuzzy-score is used, _fuzzy_score is appended last.",
        source="WORKSPACES_LIST_PAGE.workspaces[]",
    ),
}


AUTO_NOTES: dict[str, str] = {
    "team list": "When --fuzzy-score is used, _fuzzy_score is appended last.",
    "user list": "When --fuzzy-score is used, _fuzzy_score is appended last.",
    "workspace list": "When --fuzzy-score is used, _fuzzy_score is appended last.",
}


def load_query_constants() -> dict[str, str]:
    src = QUERIES_FILE.read_text()
    tree = ast.parse(src)
    out: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value: Any = None
        try:
            value = ast.literal_eval(node.value)
        except Exception:
            if (
                isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "strip"
            ):
                try:
                    value = ast.literal_eval(node.value.func.value)
                except Exception:
                    value = None
        if isinstance(value, str) and ("query " in value or "mutation " in value):
            out[target.id] = value.strip()
    return out


def skip_ws(s: str, i: int) -> int:
    while i < len(s) and s[i].isspace():
        i += 1
    return i


def read_name(s: str, i: int) -> tuple[str | None, int]:
    i = skip_ws(s, i)
    start = i
    if i < len(s) and (s[i].isalpha() or s[i] == "_"):
        i += 1
        while i < len(s) and (s[i].isalnum() or s[i] == "_"):
            i += 1
        return s[start:i], i
    return None, i


def skip_parens(s: str, i: int) -> int:
    if i >= len(s) or s[i] != "(":
        return i
    depth = 0
    while i < len(s):
        ch = s[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return i


def parse_selection_set(s: str, i: int = 0) -> tuple[list[tuple[str, Any]], int]:
    i = skip_ws(s, i)
    if s[i] != "{":
        raise ValueError("selection set must start with '{'")
    i += 1
    fields: list[tuple[str, Any]] = []
    while i < len(s):
        i = skip_ws(s, i)
        if i >= len(s):
            break
        if s[i] == "}":
            return fields, i + 1
        if s.startswith("...", i):
            while i < len(s) and s[i] not in "{}":
                i += 1
            if i < len(s) and s[i] == "{":
                _, i = parse_selection_set(s, i)
            continue
        name, i = read_name(s, i)
        if not name:
            i += 1
            continue
        i = skip_ws(s, i)
        if i < len(s) and s[i] == ":":
            _, i = read_name(s, i + 1)
            i = skip_ws(s, i)
        if i < len(s) and s[i] == "(":
            i = skip_parens(s, i)
        i = skip_ws(s, i)
        if i < len(s) and s[i] == "{":
            sub, i = parse_selection_set(s, i)
            fields.append((name, sub))
        else:
            fields.append((name, None))
    return fields, i


def parse_graphql_tree(gql: str) -> list[tuple[str, Any]]:
    i = gql.find("{")
    if i < 0:
        return []
    tree, _ = parse_selection_set(gql, i)
    return tree


def shape_at_path(tree: list[tuple[str, Any]], path: list[str]) -> list[tuple[str, Any]] | None:
    current = tree
    for idx, part in enumerate(path):
        for name, sub in current:
            if name == part:
                if idx == len(path) - 1:
                    return sub if isinstance(sub, list) else []
                if not isinstance(sub, list):
                    return None
                current = sub
                break
        else:
            return None
    return current


def format_fields(shape: list[tuple[str, Any]]) -> list[str]:
    out: list[str] = []
    for name, sub in shape:
        if isinstance(sub, list) and sub:
            inner = ",".join(format_fields(sub))
            out.append(f"{name}{{{inner}}}")
        else:
            out.append(name)
    return out


def command_name_for(path: Path, fn: ast.FunctionDef) -> str | None:
    special = SPECIAL_ROOT.get((path.name, fn.name))
    if special is not None:
        return special
    for dec in fn.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        if not isinstance(dec.func, ast.Attribute) or dec.func.attr != "command":
            continue
        if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
            leaf = dec.args[0].value
        else:
            leaf = fn.name.removesuffix("_cmd").replace("_", "-")
        group = GROUP_ALIASES.get(path.stem, path.stem)
        return f"{group} {leaf}"
    return None


def extract_query_names(fn: ast.FunctionDef) -> list[str]:
    names: list[str] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id not in {"execute", "execute_read"}:
            continue
        if len(node.args) < 2:
            continue
        arg = node.args[1]
        if isinstance(arg, ast.Name):
            names.append(arg.id)
    return names


def extract_emits(src: str, fn: ast.FunctionDef) -> list[tuple[int, str]]:
    emits: list[tuple[int, str]] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "emit":
            continue
        if not node.args:
            continue
        seg = ast.get_source_segment(src, node.args[0]) or ""
        emits.append((node.lineno, " ".join(seg.split())))
    return sorted(emits)


def infer_auto_row(
    command: str,
    query_names: list[str],
    emit_expr: str,
    query_trees: dict[str, list[tuple[str, Any]]],
) -> Row | None:
    if not query_names:
        return None
    query_name = query_names[0]
    tree = query_trees.get(query_name)
    if tree is None:
        return None

    m = re.search(r'data\.get\("([A-Za-z0-9_]+)"\)', emit_expr)
    if m:
        root_key = m.group(1)
        shape = shape_at_path(tree, [root_key])
        if shape is None:
            return None
        return Row(
            command=command,
            output_type="object" if "or {}" in emit_expr else "list[object]",
            fields=format_fields(shape),
            notes=AUTO_NOTES.get(command, ""),
            source=f"{query_name}.{root_key}",
        )

    m = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\[0\]", emit_expr)
    if m:
        root_key = tree[0][0]
        shape = shape_at_path(tree, [root_key])
        if shape is None:
            return None
        return Row(
            command=command,
            output_type="object",
            fields=format_fields(shape),
            notes=AUTO_NOTES.get(command, ""),
            source=f"{query_name}.{root_key}[0]",
        )

    m = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)\[0\]\.get\("([A-Za-z0-9_]+)"\) or \[\]', emit_expr)
    if m:
        root_key = tree[0][0]
        nested = m.group(2)
        shape = shape_at_path(tree, [root_key, nested])
        if shape is None:
            return None
        return Row(
            command=command,
            output_type="list[object]",
            fields=format_fields(shape),
            notes=AUTO_NOTES.get(command, ""),
            source=f"{query_name}.{root_key}[0].{nested}[]",
        )

    m = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)\.get\("([A-Za-z0-9_]+)"\) or \{\}', emit_expr)
    if m:
        root_key = tree[0][0]
        nested = m.group(2)
        shape = shape_at_path(tree, [root_key, nested])
        if shape is None:
            return None
        return Row(
            command=command,
            output_type="object",
            fields=format_fields(shape),
            notes=AUTO_NOTES.get(command, ""),
            source=f"{query_name}.{root_key}.{nested}",
        )

    if emit_expr == "me":
        shape = shape_at_path(tree, [tree[0][0]])
        if shape is None:
            return None
        return Row(
            command=command,
            output_type="object",
            fields=format_fields(shape),
            notes=AUTO_NOTES.get(command, ""),
            source=f"{query_name}.{tree[0][0]}",
        )

    return None


def build_rows() -> list[Row]:
    query_constants = load_query_constants()
    query_trees = {name: parse_graphql_tree(gql) for name, gql in query_constants.items()}

    rows: dict[str, Row] = dict(MANUAL_ROWS)
    for path in sorted(CLI_DIR.glob("*.py")):
        src = path.read_text()
        tree = ast.parse(src)
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            command = command_name_for(path, node)
            if command is None or command in rows:
                continue
            emits = extract_emits(src, node)
            query_names = extract_query_names(node)
            emit_expr = emits[-1][1] if emits else ""
            inferred = infer_auto_row(command, query_names, emit_expr, query_trees)
            if inferred is not None:
                rows[command] = inferred
                continue
            rows[command] = Row(
                command=command,
                output_type="manual-review",
                fields=[],
                notes=f"Could not auto-infer. Final emit expression: {emit_expr or '<none>'}",
                source=", ".join(query_names) or path.name,
            )

    return sorted(rows.values(), key=lambda r: (r.command.split()[0], r.command))


def write_outputs(rows: list[Row]) -> None:
    json_payload = [
        {
            "command": row.command,
            "output_type": row.output_type,
            "fields": row.fields,
            "notes": row.notes,
            "source": row.source,
        }
        for row in rows
    ]
    OUT_JSON.write_text(json.dumps(json_payload, indent=2, ensure_ascii=False) + "\n")

    groups: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        group = row.command.split()[0]
        groups[group].append(row)

    lines = [
        "# Output Contract Matrix",
        "",
        "Generated by `scripts/generate_output_contract_matrix.py`.",
        "",
        "Scope: successful, non-dry-run stdout output. `fields` are the top-level emitted keys in order.",
        "Nested object/list fields are shown inline as `field{sub1,sub2}`.",
        "",
    ]
    for group in sorted(groups):
        lines.append(f"## {group}")
        lines.append("")
        for row in groups[group]:
            fields = ", ".join(f"`{field}`" for field in row.fields) if row.fields else "none"
            lines.append(f"- `{row.command}`")
            lines.append(f"  type: `{row.output_type}`")
            lines.append(f"  fields: {fields}")
            lines.append(f"  source: `{row.source}`")
            if row.notes:
                lines.append(f"  notes: {row.notes}")
        lines.append("")
    OUT_MD.write_text("\n".join(lines))


def main() -> None:
    rows = build_rows()
    write_outputs(rows)
    unresolved = [row.command for row in rows if row.output_type == "manual-review"]
    print(f"wrote {len(rows)} rows")
    print(f"manual-review: {len(unresolved)}")
    for command in unresolved:
        print(command)


if __name__ == "__main__":
    main()
