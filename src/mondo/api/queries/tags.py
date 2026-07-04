"""GraphQL queries for tags (3h)."""

from __future__ import annotations

# Account-level public tags; private/shareable tags live nested under
# boards (see `mondo board get` for board.tags).
TAGS_LIST = """
query ($ids: [ID!]) {
  tags(ids: $ids) {
    id
    name
    color
  }
}
""".strip()


# Fallback for board-scoped (private / shareable) tags — the ones
# `create_or_get_tag` returns that don't show up in account-level `tags(ids:)`.
TAG_BY_BOARD = """
query ($board: ID!) {
  boards(ids: [$board]) {
    id
    tags {
      id
      name
      color
    }
  }
}
""".strip()
