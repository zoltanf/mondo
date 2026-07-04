"""GraphQL queries/mutations for webhooks (3f)."""

from __future__ import annotations

WEBHOOKS_LIST = """
query ($board: ID!, $appOnly: Boolean) {
  webhooks(board_id: $board, app_webhooks_only: $appOnly) {
    id
    board_id
    event
    config
  }
}
""".strip()


WEBHOOK_CREATE = """
mutation (
  $board: ID!
  $url: String!
  $event: WebhookEventType!
  $config: JSON
) {
  create_webhook(board_id: $board, url: $url, event: $event, config: $config) {
    id
    board_id
    event
  }
}
""".strip()


WEBHOOK_DELETE = """
mutation ($id: ID!) {
  delete_webhook(id: $id) {
    id
    board_id
  }
}
""".strip()
