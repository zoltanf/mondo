"""GraphQL queries/mutations for workspaces (2d)."""

from __future__ import annotations

# monday-api.md §14: workspaces(ids, limit, page, kind, state).
# `kind` is `open | closed` (NOT private).
WORKSPACES_LIST_PAGE = """
query (
  $limit: Int!
  $page: Int!
  $ids: [ID!]
  $kind: WorkspaceKind
  $state: State
) {
  workspaces(limit: $limit, page: $page, ids: $ids, kind: $kind, state: $state) {
    id
    name
    kind
    description
    state
    created_at
  }
}
""".strip()


WORKSPACE_GET = """
query ($id: ID!) {
  workspaces(ids: [$id]) {
    id
    name
    kind
    description
    state
    created_at
  }
}
""".strip()


WORKSPACE_CREATE = """
mutation (
  $name: String!
  $kind: WorkspaceKind!
  $description: String
  $accountProductId: ID
) {
  create_workspace(
    name: $name
    kind: $kind
    description: $description
    account_product_id: $accountProductId
  ) {
    id
    name
    kind
    description
    state
  }
}
""".strip()


# `update_workspace(id, attributes)` — attributes is an input object.
WORKSPACE_UPDATE = """
mutation ($id: ID!, $attributes: UpdateWorkspaceAttributesInput!) {
  update_workspace(id: $id, attributes: $attributes) {
    id
    name
    kind
    description
  }
}
""".strip()


WORKSPACE_DELETE = """
mutation ($id: ID!) {
  delete_workspace(workspace_id: $id) {
    id
  }
}
""".strip()


WORKSPACE_ADD_USERS = """
mutation (
  $id: ID!
  $users: [ID!]!
  $kind: WorkspaceSubscriberKind!
) {
  add_users_to_workspace(workspace_id: $id, user_ids: $users, kind: $kind) {
    id
    name
  }
}
""".strip()


WORKSPACE_REMOVE_USERS = """
mutation ($id: ID!, $users: [ID!]!) {
  delete_users_from_workspace(workspace_id: $id, user_ids: $users) {
    id
    name
  }
}
""".strip()


WORKSPACE_ADD_TEAMS = """
mutation (
  $id: ID!
  $teams: [ID!]!
  $kind: WorkspaceSubscriberKind!
) {
  add_teams_to_workspace(workspace_id: $id, team_ids: $teams, kind: $kind) {
    id
    name
  }
}
""".strip()


WORKSPACE_REMOVE_TEAMS = """
mutation ($id: ID!, $teams: [ID!]!) {
  delete_teams_from_workspace(workspace_id: $id, team_ids: $teams) {
    id
    name
  }
}
""".strip()
