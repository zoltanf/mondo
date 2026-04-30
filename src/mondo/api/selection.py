"""Extract the set of leaf field names appearing in a GraphQL document.

Used by the projection-warning machinery in `emit()` to flag JMESPath leaves
that reference identifiers the GraphQL query never selected — the silent-null
class of bug an agent can't see.

The extractor is intentionally permissive: it returns the *union* of every
leaf identifier under any selection block, with no nesting context. Aliases
(`alias: real_field`) are not used by mondo's queries, so they aren't
modelled. Type names from inline fragments (`... on TypeName`), GraphQL
keywords, variables (`$x`), and identifiers inside argument lists are all
excluded.
"""

from __future__ import annotations

import re
from functools import lru_cache

_OP_KEYWORDS = frozenset(
    {
        "query",
        "mutation",
        "subscription",
        "fragment",
        "on",
        "true",
        "false",
        "null",
    }
)

_LINE_COMMENT_RE = re.compile(r"#[^\n]*")
_PARENS_RE = re.compile(r"\([^()]*\)")
_FRAGMENT_INLINE_RE = re.compile(r"\.\.\.\s*on\s+\w+")
_FRAGMENT_SPREAD_RE = re.compile(r"\.\.\.\s*\w+")
_TOKEN_RE = re.compile(r"\{|\}|[A-Za-z_]\w*")


@lru_cache(maxsize=256)
def extract_selected_fields(graphql: str) -> frozenset[str]:
    """Return every leaf identifier appearing in any selection block.

    Permissive — does not distinguish between top-level and nested fields.
    Argument-list contents, variables (`$x`), type names from inline fragments
    (`... on TypeName`), fragment-spread names, and GraphQL operation keywords
    are all excluded. The result includes meta-fields like `__typename`.
    """
    src = _LINE_COMMENT_RE.sub("", graphql)

    # Strip argument lists `( ... )`, including nested ones.
    while True:
        new = _PARENS_RE.sub("", src)
        if new == src:
            break
        src = new

    # Strip fragments. Inline fragments first so `... on TypeName` doesn't
    # leave a bare `TypeName` behind for the spread regex to half-match.
    src = _FRAGMENT_INLINE_RE.sub("", src)
    src = _FRAGMENT_SPREAD_RE.sub("", src)

    fields: set[str] = set()
    depth = 0
    for match in _TOKEN_RE.finditer(src):
        tok = match.group()
        if tok == "{":
            depth += 1
        elif tok == "}":
            depth -= 1
        elif depth > 0 and tok not in _OP_KEYWORDS:
            fields.add(tok)
    return frozenset(fields)
