"""GraphQL queries/mutations for teams (3b)."""

from __future__ import annotations

TEAMS_LIST = """
query ($ids: [ID!]) {
  teams(ids: $ids) {
    id
    name
    picture_url
    is_guest
    users { id name }
    owners { id name }
  }
}
""".strip()


TEAM_CREATE = """
mutation ($input: CreateTeamAttributesInput!, $options: CreateTeamOptionsInput) {
  create_team(input: $input, options: $options) {
    id
    name
    is_guest
  }
}
""".strip()


TEAM_DELETE = """
mutation ($id: ID!) {
  delete_team(team_id: $id) {
    id
    name
  }
}
""".strip()


ASSIGN_TEAM_OWNERS = """
mutation ($team: ID!, $users: [ID!]!) {
  assign_team_owners(team_id: $team, user_ids: $users) {
    successful_users { id name }
    failed_users { id message }
  }
}
""".strip()


REMOVE_TEAM_OWNERS = """
mutation ($team: ID!, $users: [ID!]!) {
  remove_team_owners(team_id: $team, user_ids: $users) {
    successful_users { id name }
    failed_users { id message }
  }
}
""".strip()
