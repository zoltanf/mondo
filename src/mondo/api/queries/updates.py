"""GraphQL queries/mutations for updates / item comments (3d)."""

from __future__ import annotations

# Root `updates(ids, limit, page)`. Page max is 100 since 2025-04 (§13).
UPDATES_LIST_PAGE = """
query ($limit: Int!, $page: Int!, $ids: [ID!]) {
  updates(limit: $limit, page: $page, ids: $ids) {
    id
    body
    text_body
    creator { id name }
    item_id
    created_at
    updated_at
  }
}
""".strip()


# Nested under an item — useful when scoping to a single item.
UPDATES_FOR_ITEM = """
query ($id: ID!, $limit: Int!, $page: Int!) {
  items(ids: [$id]) {
    id
    updates(limit: $limit, page: $page) {
      id
      body
      text_body
      creator { id name }
      created_at
      updated_at
      replies { id body creator { id name } }
      likes { id }
      pinned_to_top { item_id }
    }
  }
}
""".strip()


UPDATE_GET = """
query ($id: ID!) {
  updates(ids: [$id]) {
    id
    body
    text_body
    creator { id name }
    item_id
    created_at
    updated_at
    replies { id body creator { id name } created_at }
    assets { id name url file_extension }
    likes { id }
    pinned_to_top { item_id }
  }
}
""".strip()


UPDATE_CREATE = """
mutation ($item: ID, $parent: ID, $body: String!) {
  create_update(item_id: $item, parent_id: $parent, body: $body) {
    id
    body
    creator { id name }
    item_id
    created_at
  }
}
""".strip()


UPDATE_EDIT = """
mutation ($id: ID!, $body: String!) {
  edit_update(id: $id, body: $body) {
    id
    body
    updated_at
  }
}
""".strip()


UPDATE_DELETE = """
mutation ($id: ID!) {
  delete_update(id: $id) {
    id
  }
}
""".strip()


UPDATE_LIKE = """
mutation ($id: ID!) {
  like_update(update_id: $id) {
    id
  }
}
""".strip()


UPDATE_UNLIKE = """
mutation ($id: ID!) {
  unlike_update(update_id: $id) {
    id
  }
}
""".strip()


UPDATE_CLEAR_ITEM = """
mutation ($item: ID!) {
  clear_item_updates(item_id: $item) {
    id
    name
  }
}
""".strip()


UPDATE_PIN = """
mutation ($item: ID, $update: ID!) {
  pin_to_top(item_id: $item, id: $update) {
    id
    item_id
  }
}
""".strip()


UPDATE_UNPIN = """
mutation ($item: ID, $update: ID!) {
  unpin_from_top(item_id: $item, id: $update) {
    id
    item_id
  }
}
""".strip()
