"""GraphQL queries/mutations for me, account, aggregate, validation, and notify."""

from __future__ import annotations

ME_QUERY = """
query {
  me {
    id
    name
    email
    kind
    account { id name slug tier }
  }
}
""".strip()


# --- notify / me / account / aggregate / validation (3i) ---

CREATE_NOTIFICATION = """
mutation (
  $user: ID!
  $target: ID!
  $targetType: NotificationTargetType!
  $text: String!
) {
  create_notification(
    user_id: $user
    target_id: $target
    target_type: $targetType
    text: $text
  ) {
    id
    text
  }
}
""".strip()


# `me` exposes the authenticated user. `account` is only reachable through
# `me { account { ... } }` (no root `accounts` query) — see §14.
ME_FULL = """
query {
  me {
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
    account {
      id
      name
      slug
      tier
      country_code
      first_day_of_the_week
      active_members_count
      logo
      plan { max_users tier period version }
      products { id kind }
    }
  }
}
""".strip()


ACCOUNT_ONLY = """
query {
  me {
    account {
      id
      name
      slug
      tier
      country_code
      first_day_of_the_week
      active_members_count
      logo
      plan { max_users tier period version }
      products { id kind }
    }
  }
}
""".strip()


# Aggregation API (2026-01+). Returns [AggregateGroupByResult { ... }].
# 2026-07 removed the typed `value_*` variants from AggregateGroupByResult;
# only the generic `value: JSON` remains.
AGGREGATE_BOARD = """
query ($q: AggregateQueryInput!) {
  aggregate(query: $q) {
    results {
      entries {
        alias
        value {
          __typename
          ... on AggregateBasicAggregationResult { result }
          ... on AggregateGroupByResult { value }
        }
      }
    }
  }
}
""".strip()


# Validation rules — read-only since API 2026-01. The per-rule CRUD
# mutations (`create_validation_rule`, `update_validation_rule`,
# `delete_validation_rule`) were dropped from the schema; rule
# management is UI-only now. The root `validations(id, type)` query
# returns `{required_column_ids, rules: JSON}`.
VALIDATIONS_LIST = """
query ($id: ID!) {
  validations(id: $id, type: board) {
    required_column_ids
    rules
  }
}
""".strip()
