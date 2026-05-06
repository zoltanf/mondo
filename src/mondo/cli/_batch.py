"""GraphQL multi-mutation aliasing for `mondo item create --batch`.

Build a single GraphQL document with aliases `m_0..m_{N-1}` so a chunk of N
items lands in one HTTP call instead of N. Variable scopes are flattened by
suffixing each declaration (e.g. `$board_0, $name_0, $values_0`,
`$board_1, ...`).

Two pure helpers — no I/O, fully unit-testable:

- `build_aliased_mutation(template, count)` -> (query, var_names)
- `parse_aliased_response(response, chunk)` -> list of per-row result dicts

`var_names` is the ordered list of variables declared by the original
template (without leading `$`). Callers iterate the chunk and build the
flattened variables dict by setting `out[f"{name}_{i}"] = value_for_row_i`.
"""

from __future__ import annotations

import re
from typing import Any

# `mutation ( $a: T! $b: T ) { body }` — DOTALL so the body can span lines.
# Greedy `.*` for body so the closing `}` matches the outermost brace.
_HEADER_RE = re.compile(
    r"^\s*mutation\s*\((?P<vars>.*?)\)\s*\{(?P<body>.*)\}\s*$",
    re.DOTALL,
)
_VAR_DECL_RE = re.compile(r"\$(\w+)\s*:\s*([^\s,]+)")
_VAR_REF_RE = re.compile(r"\$(\w+)")

ALIAS_PREFIX = "m_"


def build_aliased_mutation(template: str, count: int) -> tuple[str, list[str]]:
    """Compose a multi-mutation document by aliasing `template` `count` times.

    Returns:
        query: GraphQL document with aliases m_0..m_{count-1} and per-row
            suffixed variables ($var_0, $var_1, ...).
        var_names: ordered list of variable names declared by the original
            template (without leading `$`). Callers populate the flattened
            variables dict by setting `vars[f"{name}_{i}"] = value`.

    Raises ValueError when the template doesn't look like a single
    `mutation (...) { ... }` document or has no variables.
    """
    if count < 1:
        raise ValueError("count must be >= 1")
    m = _HEADER_RE.match(template.strip())
    if not m:
        raise ValueError(
            "template must be a single `mutation (...) { ... }` document"
        )
    var_decls = _VAR_DECL_RE.findall(m.group("vars"))
    if not var_decls:
        raise ValueError("template has no $variables")
    var_names = [name for name, _type in var_decls]
    body = m.group("body").strip()

    decl_lines: list[str] = []
    body_lines: list[str] = []
    for i in range(count):
        for name, type_ in var_decls:
            decl_lines.append(f"  ${name}_{i}: {type_}")
        rewritten = _VAR_REF_RE.sub(lambda mm, j=i: f"${mm.group(1)}_{j}", body)
        body_lines.append(f"  {ALIAS_PREFIX}{i}: {rewritten.strip()}")

    decl_section = "\n".join(decl_lines)
    body_section = "\n".join(body_lines)
    return f"mutation (\n{decl_section}\n) {{\n{body_section}\n}}", var_names


def parse_aliased_response(
    response: dict[str, Any],
    chunk: list[dict[str, Any]],
    *,
    base_index: int = 0,
) -> list[dict[str, Any]]:
    """Map a multi-mutation response back to per-row result envelopes.

    `chunk` is the slice of input rows that this response covers (in order).
    `base_index` is the row index of `chunk[0]` within the original full
    input array — populated into each result so the caller can correlate
    after multiple chunks.

    Each returned dict contains `ok`, `name`, `row_index`, and either `id`
    + `data` (success) or `error` (failure). Errors are looked up via
    monday's standard `errors[*].path[0]`, which carries the alias name
    (`m_0`, `m_1`, ...) for per-mutation failures.
    """
    data = response.get("data") or {}
    errors = response.get("errors") or []

    error_by_alias: dict[str, str] = {}
    for err in errors:
        path = err.get("path") or []
        if path:
            alias = str(path[0])
            # Per-mutation errors target the alias directly. Top-level
            # errors (no path or path under top-level) are merged into a
            # generic message and applied to any alias missing data.
            error_by_alias[alias] = err.get("message") or "unknown error"
    fallback_error = ""
    if errors and not error_by_alias:
        fallback_error = errors[0].get("message") or "unknown error"

    results: list[dict[str, Any]] = []
    for i, row in enumerate(chunk):
        alias = f"{ALIAS_PREFIX}{i}"
        row_name = row.get("name", "")
        absolute_index = base_index + i
        if alias in error_by_alias:
            results.append(
                {
                    "ok": False,
                    "row_index": absolute_index,
                    "name": row_name,
                    "error": error_by_alias[alias],
                }
            )
            continue
        payload = data.get(alias)
        if payload:
            results.append(
                {
                    "ok": True,
                    "row_index": absolute_index,
                    "name": row_name,
                    "id": str(payload.get("id")) if payload.get("id") else None,
                    "data": payload,
                }
            )
            continue
        # No data, no aliased error — fall back to the global error or a
        # defensive "no result" message.
        results.append(
            {
                "ok": False,
                "row_index": absolute_index,
                "name": row_name,
                "error": fallback_error or "no result",
            }
        )
    return results


def chunk_inputs[T](items: list[T], size: int) -> list[list[T]]:
    """Split `items` into consecutive chunks of `size` (last may be shorter)."""
    if size < 1:
        raise ValueError("size must be >= 1")
    return [items[i : i + size] for i in range(0, len(items), size)]
