"""GraphQL queries/mutations for items (get, list, and CRUD mutations)."""

from __future__ import annotations

# --- items: single item by id ---

ITEM_GET = """
query ($id: ID!) {
  items(ids: [$id]) {
    id
    name
    state
    created_at
    updated_at
    url
    creator { id name }
    group { id title }
    board { id name }
    column_values { id type text value }
  }
}
""".strip()


# Minimal board-id lookup used by `item rename` to auto-resolve --board
# from an explicit item id.
ITEM_BOARD_LOOKUP = """
query ($id: ID!) {
  items(ids: [$id]) {
    board { id }
  }
}
""".strip()


ITEM_GET_WITH_UPDATES = """
query ($id: ID!) {
  items(ids: [$id]) {
    id
    name
    state
    created_at
    updated_at
    url
    creator { id name }
    group { id title }
    board { id name }
    column_values { id type text value }
    updates(limit: 100) {
      id
      body
      text_body
      creator { id name }
      created_at
    }
  }
}
""".strip()


ITEM_GET_WITH_SUBITEMS = """
query ($id: ID!) {
  items(ids: [$id]) {
    id
    name
    state
    created_at
    updated_at
    url
    creator { id name }
    group { id title }
    board { id name }
    column_values { id type text value }
    subitems {
      id
      name
      state
      column_values { id type text value }
    }
  }
}
""".strip()


# --- items: cursor-paginated list ---


def build_items_page_queries(
    *,
    column_values: str = "full",
) -> tuple[str, str]:
    """Return ``(initial, next)`` items_page queries. Single source of
    truth for the `item list` item shape.

    On large boards the full ``column_values`` selection is ~3x the
    per-page complexity of the bare item fields, so narrowing it
    server-side is the main lever for `item list` performance.
    ``column_values`` picks the selection:

    - ``"full"`` (default): the canonical full selection
      (``ITEMS_PAGE_INITIAL`` / ``ITEMS_PAGE_NEXT`` are built from this).
    - ``"ids"``: narrow to ``column_values(ids: $cols)``. Both queries
      gain a ``$cols: [String!]!`` variable the caller must bind.
    - ``"none"``: drop ``column_values`` entirely
      (the ``--fields id,name`` auto-slim path).
    """
    cols_decl = ""
    fields = ["id", "name", "state", "group { id title }"]
    if column_values == "full":
        fields.append("column_values { id type text value }")
    elif column_values == "ids":
        cols_decl = ", $cols: [String!]!"
        fields.append("column_values(ids: $cols) { id type text value }")
    elif column_values != "none":
        raise ValueError(f"unknown column_values mode: {column_values!r}")
    initial = f"""
query ($boards: [ID!]!, $limit: Int!, $qp: ItemsQuery{cols_decl}) {{
  boards(ids: $boards) {{
    items_page(limit: $limit, query_params: $qp) {{
      cursor
      items {{
        {"\n        ".join(fields)}
      }}
    }}
  }}
}}
""".strip()
    next_q = f"""
query ($cursor: String!, $limit: Int!{cols_decl}) {{
  next_items_page(cursor: $cursor, limit: $limit) {{
    cursor
    items {{
      {"\n      ".join(fields)}
    }}
  }}
}}
""".strip()
    return initial, next_q


ITEMS_PAGE_INITIAL, ITEMS_PAGE_NEXT = build_items_page_queries()


# Single-item variant of the server-side column narrowing above.
ITEM_GET_WITH_COLUMNS = """
query ($id: ID!, $cols: [String!]!) {
  items(ids: [$id]) {
    id
    name
    state
    created_at
    updated_at
    url
    creator { id name }
    group { id title }
    board { id name }
    column_values(ids: $cols) { id type text value }
  }
}
""".strip()


# Export-oriented variants that also pull subitems (field selection costs
# extra complexity; only use when --include-subitems is on).
ITEMS_PAGE_INITIAL_WITH_SUBITEMS = """
query ($boards: [ID!]!, $limit: Int!, $qp: ItemsQuery) {
  boards(ids: $boards) {
    items_page(limit: $limit, query_params: $qp) {
      cursor
      items {
        id
        name
        state
        group { id title }
        column_values { id type text value }
        subitems {
          id
          name
          state
          column_values { id type text value }
        }
      }
    }
  }
}
""".strip()


ITEMS_PAGE_NEXT_WITH_SUBITEMS = """
query ($cursor: String!, $limit: Int!) {
  next_items_page(cursor: $cursor, limit: $limit) {
    cursor
    items {
      id
      name
      state
      group { id title }
      column_values { id type text value }
      subitems {
        id
        name
        state
        column_values { id type text value }
      }
    }
  }
}
""".strip()


# --- mutations ---

ITEM_CREATE = """
mutation (
  $board: ID!
  $name: String!
  $group: String
  $values: JSON
  $create_labels: Boolean
  $prm: PositionRelative
  $relto: ID
) {
  create_item(
    board_id: $board
    item_name: $name
    group_id: $group
    column_values: $values
    create_labels_if_missing: $create_labels
    position_relative_method: $prm
    relative_to: $relto
  ) {
    id
    name
    url
    state
    created_at
    group { id title }
    board { id name }
  }
}
""".strip()


ITEM_RENAME = """
mutation ($board: ID!, $id: ID!, $name: String!) {
  change_simple_column_value(
    board_id: $board
    item_id: $id
    column_id: "name"
    value: $name
  ) {
    id
    name
  }
}
""".strip()


ITEM_DUPLICATE = """
mutation ($board: ID!, $id: ID!, $with_updates: Boolean) {
  duplicate_item(board_id: $board, item_id: $id, with_updates: $with_updates) {
    id
    name
    state
    group { id title }
  }
}
""".strip()


ITEM_ARCHIVE = """
mutation ($id: ID!) {
  archive_item(item_id: $id) {
    id
    name
    state
  }
}
""".strip()


ITEM_DELETE = """
mutation ($id: ID!) {
  delete_item(item_id: $id) {
    id
    name
    state
  }
}
""".strip()


ITEM_MOVE_GROUP = """
mutation ($id: ID!, $group: String!) {
  move_item_to_group(item_id: $id, group_id: $group) {
    id
    name
    group { id title }
  }
}
""".strip()


# `move_item_to_board` — cross-board relocation. Takes optional
# `columns_mapping` + `subitems_columns_mapping` so users can translate
# source column IDs to destination IDs when the schemas differ. Each
# mapping entry is `{ source: ID!, target: ID }`; a null/omitted
# `target` drops the source column on the destination.
ITEM_MOVE_BOARD = """
mutation (
  $id: ID!
  $board: ID!
  $group: ID!
  $columns: [ColumnMappingInput!]
  $subitemColumns: [ColumnMappingInput!]
) {
  move_item_to_board(
    item_id: $id
    board_id: $board
    group_id: $group
    columns_mapping: $columns
    subitems_columns_mapping: $subitemColumns
  ) {
    id
    name
    state
    board { id name }
    group { id title }
  }
}
""".strip()
