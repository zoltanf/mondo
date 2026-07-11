"""GraphQL queries/mutations for columns (list/get/context + structural)."""

from __future__ import annotations

from ._fragments import COLUMN_VALUES_SELECTION

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
COLUMN_CONTEXT = f"""
query ($id: ID!, $cols: [String!]!) {{
  items(ids: [$id]) {{
    id
    name
    board {{
      id
      columns(ids: $cols) {{
        id
        title
        type
        settings_str
      }}
    }}
    column_values(ids: $cols) {{ {COLUMN_VALUES_SELECTION} }}
  }}
}}
""".strip()


CHANGE_COLUMN_VALUE = f"""
mutation (
  $item: ID!
  $board: ID!
  $col: String!
  $value: JSON!
  $create_labels: Boolean
) {{
  change_column_value(
    item_id: $item
    board_id: $board
    column_id: $col
    value: $value
    create_labels_if_missing: $create_labels
  ) {{
    id
    name
    column_values(ids: [$col]) {{ {COLUMN_VALUES_SELECTION} }}
  }}
}}
""".strip()


CHANGE_MULTIPLE_COLUMN_VALUES = f"""
mutation (
  $item: ID!
  $board: ID!
  $values: JSON!
  $create_labels: Boolean
) {{
  change_multiple_column_values(
    item_id: $item
    board_id: $board
    column_values: $values
    create_labels_if_missing: $create_labels
  ) {{
    id
    name
    column_values {{ {COLUMN_VALUES_SELECTION} }}
  }}
}}
""".strip()


CREATE_OR_GET_TAG = """
mutation ($name: String!, $board: ID!) {
  create_or_get_tag(tag_name: $name, board_id: $board) {
    id
    name
  }
}
""".strip()


# --- columns: structural (2b) ---

COLUMN_CREATE = """
mutation (
  $board: ID!
  $title: String!
  $type: ColumnType!
  $description: String
  $defaults: JSON
  $id: String
  $after: ID
) {
  create_column(
    board_id: $board
    title: $title
    column_type: $type
    description: $description
    defaults: $defaults
    id: $id
    after_column_id: $after
  ) {
    id
    title
    type
    description
    archived
  }
}
""".strip()


COLUMN_RENAME = """
mutation ($board: ID!, $col: String!, $title: String!) {
  change_column_title(board_id: $board, column_id: $col, title: $title) {
    id
    title
    type
  }
}
""".strip()


COLUMN_CHANGE_METADATA = """
mutation (
  $board: ID!
  $col: String!
  $property: ColumnProperty!
  $value: String!
) {
  change_column_metadata(
    board_id: $board
    column_id: $col
    column_property: $property
    value: $value
  ) {
    id
    title
    type
    description
  }
}
""".strip()


COLUMN_DELETE = """
mutation ($board: ID!, $col: String!) {
  delete_column(board_id: $board, column_id: $col) {
    id
    title
    archived
  }
}
""".strip()
