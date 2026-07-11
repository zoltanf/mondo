"""GraphQL queries/mutations for subitems (3c)."""

from __future__ import annotations

from ._fragments import COLUMN_VALUES_SELECTION

# Subitems are nested on a parent item; they have their own (hidden) board
# and column IDs. Listing = nested `items(ids:[parent]) { subitems { ... } }`.
SUBITEMS_LIST = f"""
query ($parent: ID!) {{
  items(ids: [$parent]) {{
    id
    name
    board {{ id name }}
    subitems {{
      id
      name
      state
      created_at
      creator {{ id name }}
      board {{ id name }}
      column_values {{ {COLUMN_VALUES_SELECTION} }}
    }}
  }}
}}
""".strip()


SUBITEM_GET = f"""
query ($id: ID!) {{
  items(ids: [$id]) {{
    id
    name
    state
    created_at
    updated_at
    creator {{ id name }}
    board {{ id name }}
    parent_item {{ id name }}
    column_values {{ {COLUMN_VALUES_SELECTION} }}
  }}
}}
""".strip()


SUBITEM_CREATE = f"""
mutation (
  $parent: ID!
  $name: String!
  $values: JSON
  $create_labels: Boolean
) {{
  create_subitem(
    parent_item_id: $parent
    item_name: $name
    column_values: $values
    create_labels_if_missing: $create_labels
  ) {{
    id
    name
    state
    board {{ id name }}
    column_values {{ {COLUMN_VALUES_SELECTION} }}
  }}
}}
""".strip()
