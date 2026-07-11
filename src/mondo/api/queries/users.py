"""GraphQL queries/mutations for users (3a)."""

from __future__ import annotations

# monday-api.md §14. Migrated to API 2026-07: `kind`/`non_active`/`newest_first`
# args were removed; use `user_kind`/`status`/`sort`. The deprecated boolean
# User fields (is_admin/is_guest/is_view_only/enabled/is_pending) are replaced
# by `kind`/`status`; mondo derives the legacy booleans in `normalize_user`.
USERS_LIST_PAGE = """
query (
  $limit: Int!
  $page: Int!
  $ids: [ID!]
  $userKind: UserKindFilterInput
  $emails: [String!]
  $name: String
  $status: [UserStatus!]
  $sort: [UsersSortInput!]
) {
  users(
    limit: $limit
    page: $page
    ids: $ids
    user_kind: $userKind
    emails: $emails
    name: $name
    status: $status
    sort: $sort
  ) {
    id
    name
    email
    kind
    status
    created_at
    last_activity
    title
  }
}
""".strip()


USER_GET = """
query ($ids: [ID!]!) {
  users(ids: $ids) {
    id
    name
    email
    kind
    status
    created_at
    last_activity
    title
    photo_url { thumb }
    teams { id name }
    account { id name slug tier }
  }
}
""".strip()


USERS_DEACTIVATE = """
mutation ($ids: [ID!]!) {
  deactivate_users(user_ids: $ids) {
    deactivated_users { id name status }
    errors { message code user_id }
  }
}
""".strip()


USERS_ACTIVATE = """
mutation ($ids: [ID!]!) {
  activate_users(user_ids: $ids) {
    activated_users { id name status }
    errors { message code user_id }
  }
}
""".strip()


# update_multiple_users_as_X — one mutation per target role. The API exposes
# four distinct mutations instead of a role-enum argument.
USERS_UPDATE_AS_ADMINS = """
mutation ($ids: [ID!]!) {
  update_multiple_users_as_admins(user_ids: $ids) {
    updated_users { id name kind }
    errors { message code user_id }
  }
}
""".strip()


USERS_UPDATE_AS_MEMBERS = """
mutation ($ids: [ID!]!) {
  update_multiple_users_as_members(user_ids: $ids) {
    updated_users { id name kind }
    errors { message code user_id }
  }
}
""".strip()


USERS_UPDATE_AS_GUESTS = """
mutation ($ids: [ID!]!) {
  update_multiple_users_as_guests(user_ids: $ids) {
    updated_users { id name kind }
    errors { message code user_id }
  }
}
""".strip()


USERS_UPDATE_AS_VIEWERS = """
mutation ($ids: [ID!]!) {
  update_multiple_users_as_viewers(user_ids: $ids) {
    updated_users { id name kind }
    errors { message code user_id }
  }
}
""".strip()


ADD_USERS_TO_TEAM = """
mutation ($team: ID!, $users: [ID!]!) {
  add_users_to_team(team_id: $team, user_ids: $users) {
    successful_users { id name }
    failed_users { id message }
  }
}
""".strip()


REMOVE_USERS_FROM_TEAM = """
mutation ($team: ID!, $users: [ID!]!) {
  remove_users_from_team(team_id: $team, user_ids: $users) {
    successful_users { id name }
    failed_users { id message }
  }
}
""".strip()
