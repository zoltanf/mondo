"""GraphQL queries for favorites (3h, read-only)."""

from __future__ import annotations

# monday-api.md §14 mentions favorites but not exact mutation names, so
# we expose read-only for now. Expand if monday's SDL confirms the
# add/remove mutation shape.
FAVORITES_LIST = """
query {
  favorites {
    id
    accountId
    folderId
    position
    createdAt
    updatedAt
    object {
      id
      type
    }
  }
}
""".strip()
