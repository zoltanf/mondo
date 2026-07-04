"""GraphQL queries/mutations for subitems (3c)."""

from __future__ import annotations

# Subitems are nested on a parent item; they have their own (hidden) board
# and column IDs. Listing = nested `items(ids:[parent]) { subitems { ... } }`.
SUBITEMS_LIST = """
query ($parent: ID!) {
  items(ids: [$parent]) {
    id
    name
    board { id name }
    subitems {
      id
      name
      state
      created_at
      creator { id name }
      board { id name }
      column_values { id type text value }
    }
  }
}
""".strip()


SUBITEM_GET = """
query ($id: ID!) {
  items(ids: [$id]) {
    id
    name
    state
    created_at
    updated_at
    creator { id name }
    board { id name }
    parent_item { id name }
    column_values { id type text value }
  }
}
""".strip()


SUBITEM_CREATE = """
mutation (
  $parent: ID!
  $name: String!
  $values: JSON
  $create_labels: Boolean
) {
  create_subitem(
    parent_item_id: $parent
    item_name: $name
    column_values: $values
    create_labels_if_missing: $create_labels
  ) {
    id
    name
    state
    board { id name }
    column_values { id type text value }
  }
}
""".strip()
