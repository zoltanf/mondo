"""GraphQL queries/mutations for groups (2c)."""

from __future__ import annotations

GROUPS_LIST = """
query ($board: ID!) {
  boards(ids: [$board]) {
    id
    name
    groups {
      id
      title
      color
      position
      archived
      deleted
    }
  }
}
""".strip()


GROUP_CREATE = """
mutation (
  $board: ID!
  $name: String!
  $color: String
  $relativeTo: String
  $prm: PositionRelative
  $position: String
) {
  create_group(
    board_id: $board
    group_name: $name
    group_color: $color
    relative_to: $relativeTo
    position_relative_method: $prm
    position: $position
  ) {
    id
    title
    color
    position
  }
}
""".strip()


GROUP_UPDATE = """
mutation (
  $board: ID!
  $group: String!
  $attribute: GroupAttributes!
  $value: String!
) {
  update_group(
    board_id: $board
    group_id: $group
    group_attribute: $attribute
    new_value: $value
  ) {
    id
    title
    color
    position
  }
}
""".strip()


GROUP_DUPLICATE = """
mutation (
  $board: ID!
  $group: String!
  $title: String
  $addToTop: Boolean
) {
  duplicate_group(
    board_id: $board
    group_id: $group
    group_title: $title
    add_to_top: $addToTop
  ) {
    id
    title
    color
    position
  }
}
""".strip()


GROUP_ARCHIVE = """
mutation ($board: ID!, $group: String!) {
  archive_group(board_id: $board, group_id: $group) {
    id
    title
    archived
  }
}
""".strip()


GROUP_DELETE = """
mutation ($board: ID!, $group: String!) {
  delete_group(board_id: $board, group_id: $group) {
    id
    title
    deleted
  }
}
""".strip()
