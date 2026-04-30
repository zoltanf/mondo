"""JMESPath projection helper.

Applied *before* formatting so `--query` reshapes the data before the table /
csv / json renderer sees it (matches az CLI's `--query` semantics).
"""

from __future__ import annotations

from typing import Any

import jmespath  # type: ignore[import-untyped]
from jmespath.exceptions import JMESPathError  # type: ignore[import-untyped]
from jmespath.parser import Parser  # type: ignore[import-untyped]


def apply_query(data: Any, expression: str | None) -> Any:
    """Project `data` through a JMESPath expression, or return it unchanged.

    Raises ValueError on invalid JMESPath so the caller can surface a usage
    error with the correct exit code.
    """
    if not expression:
        return data
    try:
        return jmespath.search(expression, data)
    except JMESPathError as e:
        raise ValueError(f"invalid JMESPath expression: {e}") from e


def extract_query_leaf_fields(expression: str | None) -> frozenset[str]:
    """Return every leaf identifier appearing as a `field` node in the parsed AST.

    Used by `emit()` to diff against the GraphQL selection set and warn when a
    projection references a field the query never selected. Multi-select-dict
    keys are aliases — they live on `key_val_pair` nodes, *not* `field` nodes,
    so they are correctly excluded. Function names live on
    `function_expression` nodes and are likewise excluded.

    Returns an empty frozenset on a parse error: surfacing a JMESPath syntax
    error is `apply_query`'s job, not this helper's.
    """
    if not expression:
        return frozenset()
    try:
        ast = Parser().parse(expression).parsed
    except JMESPathError:
        return frozenset()
    leaves: set[str] = set()
    _collect_field_leaves(ast, leaves)
    return frozenset(leaves)


def _collect_field_leaves(node: Any, out: set[str]) -> None:
    if not isinstance(node, dict):
        return
    if node.get("type") == "field":
        value = node.get("value")
        if isinstance(value, str):
            out.add(value)
    for child in node.get("children") or []:
        _collect_field_leaves(child, out)
