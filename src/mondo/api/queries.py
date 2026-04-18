"""GraphQL queries and mutations used by mondo commands.

Kept inline as string constants (not `.graphql` files) — the query set is
small and lives in one place. All mutations use variables to avoid the
double-JSON escape trap (monday-api.md §11.4).
"""

from __future__ import annotations

# --- me / account ---

ME_QUERY = """
query {
  me {
    id
    name
    email
    is_admin
    account { id name slug tier }
  }
}
""".strip()


# --- items: single item by id ---

ITEM_GET = """
query ($id: ID!) {
  items(ids: [$id]) {
    id
    name
    state
    created_at
    updated_at
    creator { id name }
    group { id title }
    board { id name }
    column_values { id type text value }
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

ITEMS_PAGE_INITIAL = """
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
      }
    }
  }
}
""".strip()


ITEMS_PAGE_NEXT = """
query ($cursor: String!, $limit: Int!) {
  next_items_page(cursor: $cursor, limit: $limit) {
    cursor
    items {
      id
      name
      state
      group { id title }
      column_values { id type text value }
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
    state
    created_at
    group { id title }
    board { id name }
  }
}
""".strip()


ITEM_RENAME = """
mutation ($board: ID!, $id: ID!, $name: String!) {
  change_item_name(board_id: $board, item_id: $id, new_name: $name) {
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


# --- columns: list / get / context ---

COLUMNS_ON_BOARD = """
query ($board: ID!) {
  boards(ids: [$board]) {
    id
    name
    columns {
      id
      title
      type
      description
      archived
      settings_str
    }
  }
}
""".strip()


# Single-round-trip fetch for `column get/set/clear`:
# item.board.id + column definition (from board.columns) + current value.
COLUMN_CONTEXT = """
query ($id: ID!, $cols: [String!]!) {
  items(ids: [$id]) {
    id
    name
    board {
      id
      columns(ids: $cols) {
        id
        title
        type
        settings_str
      }
    }
    column_values(ids: $cols) {
      id
      type
      text
      value
    }
  }
}
""".strip()


CHANGE_COLUMN_VALUE = """
mutation (
  $item: ID!
  $board: ID!
  $col: String!
  $value: JSON!
  $create_labels: Boolean
) {
  change_column_value(
    item_id: $item
    board_id: $board
    column_id: $col
    value: $value
    create_labels_if_missing: $create_labels
  ) {
    id
    name
    column_values(ids: [$col]) { id type text value }
  }
}
""".strip()


CHANGE_MULTIPLE_COLUMN_VALUES = """
mutation (
  $item: ID!
  $board: ID!
  $values: JSON!
  $create_labels: Boolean
) {
  change_multiple_column_values(
    item_id: $item
    board_id: $board
    column_values: $values
    create_labels_if_missing: $create_labels
  ) {
    id
    name
    column_values { id type text value }
  }
}
""".strip()


CREATE_OR_GET_TAG = """
mutation ($name: String!, $board: ID!) {
  create_or_get_tag(tag_name: $name, board_id: $board) {
    id
    name
  }
}
""".strip()
