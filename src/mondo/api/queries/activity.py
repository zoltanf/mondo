"""GraphQL queries for activity logs (3h)."""

from __future__ import annotations

# Nested-only query (§14). `from`/`to` are ISO-8601 strings. `data` is a
# JSON-encoded string with before/after values.
BOARD_ACTIVITY_LOGS = """
query (
  $board: ID!
  $limit: Int!
  $page: Int!
  $userIds: [ID!]
  $columnIds: [String!]
  $groupIds: [String!]
  $itemIds: [ID!]
  $fromDate: ISO8601DateTime
  $toDate: ISO8601DateTime
) {
  boards(ids: [$board]) {
    id
    activity_logs(
      limit: $limit
      page: $page
      user_ids: $userIds
      column_ids: $columnIds
      group_ids: $groupIds
      item_ids: $itemIds
      from: $fromDate
      to: $toDate
    ) {
      id
      event
      entity
      user_id
      created_at
      account_id
      data
    }
  }
}
""".strip()
