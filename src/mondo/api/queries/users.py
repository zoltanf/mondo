"""GraphQL queries/mutations for users (3a)."""

from __future__ import annotations

# monday-api.md §14. UserKind: all|non_guests|guests|non_pending.
USERS_LIST_PAGE = """
query (
  $limit: Int!
  $page: Int!
  $ids: [ID!]
  $kind: UserKind
  $emails: [String!]
  $name: String
  $nonActive: Boolean
  $newestFirst: Boolean
) {
  users(
    limit: $limit
    page: $page
    ids: $ids
    kind: $kind
    emails: $emails
    name: $name
    non_active: $nonActive
    newest_first: $newestFirst
  ) {
    id
    name
    email
    enabled
    is_admin
    is_guest
    is_pending
    is_view_only
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
    enabled
    is_admin
    is_guest
    is_pending
    is_view_only
    created_at
    last_activity
    title
    photo_thumb
    teams { id name }
    account { id name slug tier }
  }
}
""".strip()


USERS_DEACTIVATE = """
mutation ($ids: [ID!]!) {
  deactivate_users(user_ids: $ids) {
    deactivated_users { id name enabled }
    errors { message code user_id }
  }
}
""".strip()


USERS_ACTIVATE = """
mutation ($ids: [ID!]!) {
  activate_users(user_ids: $ids) {
    activated_users { id name enabled }
    errors { message code user_id }
  }
}
""".strip()


# update_multiple_users_as_X — one mutation per target role. The API exposes
# four distinct mutations instead of a role-enum argument.
USERS_UPDATE_AS_ADMINS = """
mutation ($ids: [ID!]!) {
  update_multiple_users_as_admins(user_ids: $ids) {
    updated_users { id name is_admin }
    errors { message code user_id }
  }
}
""".strip()


USERS_UPDATE_AS_MEMBERS = """
mutation ($ids: [ID!]!) {
  update_multiple_users_as_members(user_ids: $ids) {
    updated_users { id name is_admin }
    errors { message code user_id }
  }
}
""".strip()


USERS_UPDATE_AS_GUESTS = """
mutation ($ids: [ID!]!) {
  update_multiple_users_as_guests(user_ids: $ids) {
    updated_users { id name is_guest }
    errors { message code user_id }
  }
}
""".strip()


USERS_UPDATE_AS_VIEWERS = """
mutation ($ids: [ID!]!) {
  update_multiple_users_as_viewers(user_ids: $ids) {
    updated_users { id name is_view_only }
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
