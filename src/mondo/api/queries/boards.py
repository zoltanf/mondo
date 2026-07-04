"""GraphQL queries/mutations for boards."""

from __future__ import annotations

from typing import Any


def build_boards_list_query(
    *,
    state: str | None = None,
    kind: str | None = None,
    workspace_ids: list[int] | None = None,
    order_by: str | None = None,
    with_item_counts: bool = False,
    with_tags: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Build a page-based boards list query containing only the filter args
    that are actually set.

    Monday's `boards(...)` has a server-side quirk: passing `workspace_ids:
    null` silently drops arbitrary boards from the result set (vs. omitting
    the argument entirely, which returns everything). Safest to never send
    null-valued filters, so we build the query and variables dict dynamically.

    `items_count` costs ~500k complexity per page of 100 — by default it is
    omitted; pass `with_item_counts=True` to include it. `with_tags=True`
    pulls each board's tags into the response (small but not free; cached
    listings don't include them).
    """
    var_decls: list[str] = ["$limit: Int!", "$page: Int!"]
    args: list[str] = [
        "limit: $limit",
        "page: $page",
        "hierarchy_types: [classic, multi_level]",
    ]
    variables: dict[str, Any] = {}

    if state is not None:
        var_decls.append("$state: State")
        args.append("state: $state")
        variables["state"] = state
    if kind is not None:
        var_decls.append("$kind: BoardKind")
        args.append("board_kind: $kind")
        variables["kind"] = kind
    if workspace_ids:
        var_decls.append("$workspaceIds: [ID]")
        args.append("workspace_ids: $workspaceIds")
        variables["workspaceIds"] = workspace_ids
    if order_by is not None:
        var_decls.append("$orderBy: BoardsOrderBy")
        args.append("order_by: $orderBy")
        variables["orderBy"] = order_by

    fields = [
        "id",
        "name",
        "description",
        "state",
        "board_kind",
        "board_folder_id",
        "workspace_id",
        # Nested object for parity with `BOARD_GET`. JMESPath projections like
        # `[*].workspace.name` or `[*].workspace` worked on `board get` but
        # returned `null` from `board list` until this was added.
        "workspace { id name }",
        "hierarchy_type",
        "created_at",
        "updated_at",
        # monday's `boards()` returns both real boards and workdoc-backing
        # boards. `type` is how the schema distinguishes them — observed
        # values: "board", "document", "sub_items_board", "custom_object".
        "type",
    ]
    if with_item_counts:
        fields.append("items_count")
    if with_tags:
        fields.append("tags { id name color }")

    query = (
        f"query ({', '.join(var_decls)}) {{\n"
        f"  boards({', '.join(args)}) {{\n"
        f"    {' '.join(fields)}\n"
        f"  }}\n"
        f"}}"
    )
    return query, variables


# Lightweight variant for polling: only the fields the `--wait` path needs.
# Avoids pulling columns/groups/subscribers/tags every 2s during long waits.
BOARD_ITEMS_COUNT = """
query ($ids: [ID!]!) {
  boards(ids: $ids) {
    id
    items_count
  }
}
""".strip()


# Detailed single-board fetch. Field list is reused by `BOARD_GET_WITH_VIEWS`
# below so opt-in flags don't drift from the default.
_BOARD_GET_DEFAULT_FIELDS = (
    "id",
    "name",
    "description",
    "state",
    "board_kind",
    "type",
    "board_folder_id",
    "workspace_id",
    "hierarchy_type",
    "items_count",
    "updated_at",
    "permissions",
    "workspace { id name kind }",
    "owners { id name }",
    "subscribers { id name }",
    "top_group { id title }",
    "groups { id title color position archived }",
    "columns { id title type description archived }",
    "tags { id name color }",
)


def _build_board_get_query(*fields: str) -> str:
    return f"query ($id: ID!) {{\n  boards(ids: [$id]) {{\n    {' '.join(fields)}\n  }}\n}}"


BOARD_GET = _build_board_get_query(*_BOARD_GET_DEFAULT_FIELDS)


# `mondo board get --with-views` — adds the (expensive) views array. monday's
# `Board.views` returns a `BoardView` per saved view (table/kanban/timeline/
# etc.), with each view's settings serialized as `settings_str` (JSON).
BOARD_GET_WITH_VIEWS = _build_board_get_query(
    *_BOARD_GET_DEFAULT_FIELDS,
    "views { id name type settings_str }",
)


BOARD_CREATE = """
mutation (
  $name: String!
  $kind: BoardKind!
  $description: String
  $folder: ID
  $workspace: ID
  $template: ID
  $ownerIds: [ID!]
  $ownerTeamIds: [ID!]
  $subscriberIds: [ID!]
  $subscriberTeamIds: [ID!]
  $empty: Boolean
) {
  create_board(
    board_name: $name
    board_kind: $kind
    description: $description
    folder_id: $folder
    workspace_id: $workspace
    template_id: $template
    board_owner_ids: $ownerIds
    board_owner_team_ids: $ownerTeamIds
    board_subscriber_ids: $subscriberIds
    board_subscriber_teams_ids: $subscriberTeamIds
    empty: $empty
  ) {
    id
    name
    description
    state
    board_kind
    workspace_id
    board_folder_id
    url
  }
}
""".strip()


BOARD_DUPLICATE = """
mutation (
  $board: ID!
  $duplicateType: DuplicateBoardType!
  $name: String
  $workspace: ID
  $folder: ID
  $keepSubscribers: Boolean
) {
  duplicate_board(
    board_id: $board
    duplicate_type: $duplicateType
    board_name: $name
    workspace_id: $workspace
    folder_id: $folder
    keep_subscribers: $keepSubscribers
  ) {
    board {
      id
      name
      state
      board_kind
      workspace_id
    }
  }
}
""".strip()


BOARD_UPDATE = """
mutation ($board: ID!, $attribute: BoardAttributes!, $value: String!) {
  update_board(board_id: $board, board_attribute: $attribute, new_value: $value)
}
""".strip()


BOARD_SET_PERMISSION = """
mutation ($board: ID!, $role: BoardBasicRoleName!) {
  set_board_permission(board_id: $board, basic_role_name: $role) {
    edit_permissions
    failed_actions
  }
}
""".strip()


BOARD_UPDATE_HIERARCHY = """
mutation ($board: ID!, $attributes: UpdateBoardHierarchyAttributesInput!) {
  update_board_hierarchy(board_id: $board, attributes: $attributes) {
    success
  }
}
""".strip()


BOARD_ARCHIVE = """
mutation ($board: ID!) {
  archive_board(board_id: $board) {
    id
    name
    state
  }
}
""".strip()


BOARD_DELETE = """
mutation ($board: ID!) {
  delete_board(board_id: $board) {
    id
    name
    state
  }
}
""".strip()
