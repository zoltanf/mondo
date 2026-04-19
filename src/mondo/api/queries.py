"""GraphQL queries and mutations used by mondo commands.

Kept inline as string constants (not `.graphql` files) — the query set is
small and lives in one place. All mutations use variables to avoid the
double-JSON escape trap (monday-api.md §11.4).
"""

from __future__ import annotations

from typing import Any

# --- me / account ---

ME_QUERY = """
query {
  me {
    id
    name
    email
    is_admin
    account { id name slug tier }
  }
}
""".strip()


# --- items: single item by id ---

ITEM_GET = """
query ($id: ID!) {
  items(ids: [$id]) {
    id
    name
    state
    created_at
    updated_at
    creator { id name }
    group { id title }
    board { id name }
    column_values { id type text value }
  }
}
""".strip()


ITEM_GET_WITH_UPDATES = """
query ($id: ID!) {
  items(ids: [$id]) {
    id
    name
    state
    created_at
    updated_at
    creator { id name }
    group { id title }
    board { id name }
    column_values { id type text value }
    updates(limit: 100) {
      id
      body
      text_body
      creator { id name }
      created_at
    }
  }
}
""".strip()


ITEM_GET_WITH_SUBITEMS = """
query ($id: ID!) {
  items(ids: [$id]) {
    id
    name
    state
    created_at
    updated_at
    creator { id name }
    group { id title }
    board { id name }
    column_values { id type text value }
    subitems {
      id
      name
      state
      column_values { id type text value }
    }
  }
}
""".strip()


# --- items: cursor-paginated list ---

ITEMS_PAGE_INITIAL = """
query ($boards: [ID!]!, $limit: Int!, $qp: ItemsQuery) {
  boards(ids: $boards) {
    items_page(limit: $limit, query_params: $qp) {
      cursor
      items {
        id
        name
        state
        group { id title }
        column_values { id type text value }
      }
    }
  }
}
""".strip()


ITEMS_PAGE_NEXT = """
query ($cursor: String!, $limit: Int!) {
  next_items_page(cursor: $cursor, limit: $limit) {
    cursor
    items {
      id
      name
      state
      group { id title }
      column_values { id type text value }
    }
  }
}
""".strip()


# Export-oriented variants that also pull subitems (field selection costs
# extra complexity; only use when --include-subitems is on).
ITEMS_PAGE_INITIAL_WITH_SUBITEMS = """
query ($boards: [ID!]!, $limit: Int!, $qp: ItemsQuery) {
  boards(ids: $boards) {
    items_page(limit: $limit, query_params: $qp) {
      cursor
      items {
        id
        name
        state
        group { id title }
        column_values { id type text value }
        subitems {
          id
          name
          state
          column_values { id type text value }
        }
      }
    }
  }
}
""".strip()


ITEMS_PAGE_NEXT_WITH_SUBITEMS = """
query ($cursor: String!, $limit: Int!) {
  next_items_page(cursor: $cursor, limit: $limit) {
    cursor
    items {
      id
      name
      state
      group { id title }
      column_values { id type text value }
      subitems {
        id
        name
        state
        column_values { id type text value }
      }
    }
  }
}
""".strip()


# --- mutations ---

ITEM_CREATE = """
mutation (
  $board: ID!
  $name: String!
  $group: String
  $values: JSON
  $create_labels: Boolean
  $prm: PositionRelative
  $relto: ID
) {
  create_item(
    board_id: $board
    item_name: $name
    group_id: $group
    column_values: $values
    create_labels_if_missing: $create_labels
    position_relative_method: $prm
    relative_to: $relto
  ) {
    id
    name
    state
    created_at
    group { id title }
    board { id name }
  }
}
""".strip()


ITEM_RENAME = """
mutation ($board: ID!, $id: ID!, $name: String!) {
  change_simple_column_value(
    board_id: $board
    item_id: $id
    column_id: "name"
    value: $name
  ) {
    id
    name
  }
}
""".strip()


ITEM_DUPLICATE = """
mutation ($board: ID!, $id: ID!, $with_updates: Boolean) {
  duplicate_item(board_id: $board, item_id: $id, with_updates: $with_updates) {
    id
    name
    state
    group { id title }
  }
}
""".strip()


ITEM_ARCHIVE = """
mutation ($id: ID!) {
  archive_item(item_id: $id) {
    id
    name
    state
  }
}
""".strip()


ITEM_DELETE = """
mutation ($id: ID!) {
  delete_item(item_id: $id) {
    id
    name
    state
  }
}
""".strip()


ITEM_MOVE_GROUP = """
mutation ($id: ID!, $group: String!) {
  move_item_to_group(item_id: $id, group_id: $group) {
    id
    name
    group { id title }
  }
}
""".strip()


# --- columns: list / get / context ---

COLUMNS_ON_BOARD = """
query ($board: ID!) {
  boards(ids: [$board]) {
    id
    name
    columns {
      id
      title
      type
      description
      archived
      settings_str
    }
  }
}
""".strip()


# Single-round-trip fetch for `column get/set/clear`:
# item.board.id + column definition (from board.columns) + current value.
COLUMN_CONTEXT = """
query ($id: ID!, $cols: [String!]!) {
  items(ids: [$id]) {
    id
    name
    board {
      id
      columns(ids: $cols) {
        id
        title
        type
        settings_str
      }
    }
    column_values(ids: $cols) {
      id
      type
      text
      value
    }
  }
}
""".strip()


CHANGE_COLUMN_VALUE = """
mutation (
  $item: ID!
  $board: ID!
  $col: String!
  $value: JSON!
  $create_labels: Boolean
) {
  change_column_value(
    item_id: $item
    board_id: $board
    column_id: $col
    value: $value
    create_labels_if_missing: $create_labels
  ) {
    id
    name
    column_values(ids: [$col]) { id type text value }
  }
}
""".strip()


CHANGE_MULTIPLE_COLUMN_VALUES = """
mutation (
  $item: ID!
  $board: ID!
  $values: JSON!
  $create_labels: Boolean
) {
  change_multiple_column_values(
    item_id: $item
    board_id: $board
    column_values: $values
    create_labels_if_missing: $create_labels
  ) {
    id
    name
    column_values { id type text value }
  }
}
""".strip()


CREATE_OR_GET_TAG = """
mutation ($name: String!, $board: ID!) {
  create_or_get_tag(tag_name: $name, board_id: $board) {
    id
    name
  }
}
""".strip()


# --- docs (the Doc column → workspace doc pointer + blocks) ---

# Fetch a doc's full block tree by object_id (extracted from the doc column).
DOCS_BY_OBJECT_ID = """
query ($objs: [ID!]!) {
  docs(object_ids: $objs) {
    id
    object_id
    name
    doc_kind
    url
    workspace_id
    blocks {
      id
      type
      content
      parent_block_id
    }
  }
}
""".strip()


# Create a new doc attached to an item's doc-column (populates the column).
CREATE_DOC_ON_ITEM = """
mutation ($item: ID!, $col: String!) {
  create_doc(location: { board: { item_id: $item, column_id: $col } }) {
    id
    object_id
    name
    url
  }
}
""".strip()


# Create a single block at the end of a doc. Monday's schema no longer exposes
# a bulk `create_doc_blocks` — callers loop this singular mutation, preserving
# the order by chaining `after_block_id` (first insertion has no predecessor;
# each subsequent one uses the previous block's id).
CREATE_DOC_BLOCK = """
mutation (
  $doc: ID!
  $type: DocBlockContentType!
  $content: JSON!
  $after: String
  $parent: String
) {
  create_doc_block(
    doc_id: $doc
    type: $type
    content: $content
    after_block_id: $after
    parent_block_id: $parent
  ) {
    id
    type
  }
}
""".strip()


# Delete a single doc block by id (used by `doc clear --replace`).
DELETE_DOC_BLOCK = """
mutation ($block: String!) {
  delete_doc_block(block_id: $block) {
    id
  }
}
""".strip()


# --- workspace docs (3e) — distinct from the `doc` column type ---

DOCS_LIST_PAGE = """
query (
  $limit: Int!
  $page: Int!
  $ids: [ID!]
  $objectIds: [ID!]
  $workspaceIds: [ID!]
  $orderBy: DocsOrderBy
) {
  docs(
    limit: $limit
    page: $page
    ids: $ids
    object_ids: $objectIds
    workspace_ids: $workspaceIds
    order_by: $orderBy
  ) {
    id
    object_id
    name
    doc_kind
    created_at
    url
    relative_url
    workspace_id
    created_by { id name }
  }
}
""".strip()


DOC_GET_BY_ID = """
query ($ids: [ID!]!) {
  docs(ids: $ids) {
    id
    object_id
    name
    doc_kind
    created_at
    url
    relative_url
    workspace_id
    created_by { id name }
    blocks { id type content parent_block_id }
  }
}
""".strip()


# Create a new doc inside a workspace (vs. the already-shipped
# CREATE_DOC_ON_ITEM which creates one attached to a doc-column on an item).
CREATE_DOC_IN_WORKSPACE = """
mutation ($workspace: ID!, $name: String!, $kind: BoardKind) {
  create_doc(
    location: {
      workspace: { workspace_id: $workspace, name: $name, kind: $kind }
    }
  ) {
    id
    object_id
    name
    url
  }
}
""".strip()


UPDATE_DOC_BLOCK = """
mutation ($block: String!, $content: JSON!) {
  update_doc_block(block_id: $block, content: $content) {
    id
    type
  }
}
""".strip()


# --- webhooks (3f) ---

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


# --- files / assets (3g) ---

# Run against /v2/file as multipart; see §11.5.23. `$file: File!` is the
# magic var name that monday's multipart resolver populates.
FILE_UPLOAD_ITEM = """
mutation ($file: File!, $item: ID!, $col: String!) {
  add_file_to_column(item_id: $item, column_id: $col, file: $file) {
    id
    name
    url
    file_extension
    file_size
  }
}
""".strip()


FILE_UPLOAD_UPDATE = """
mutation ($file: File!, $update: ID!) {
  add_file_to_update(update_id: $update, file: $file) {
    id
    name
    url
    file_extension
    file_size
  }
}
""".strip()


ASSETS_GET = """
query ($ids: [ID!]!) {
  assets(ids: $ids) {
    id
    name
    url
    url_thumbnail
    public_url
    file_extension
    file_size
    created_at
    uploaded_by { id name }
  }
}
""".strip()


# --- activity logs (3h) ---

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


# --- folders (3h) ---

FOLDERS_LIST_PAGE = """
query ($limit: Int!, $page: Int!, $ids: [ID!], $workspaceIds: [ID]) {
  folders(limit: $limit, page: $page, ids: $ids, workspace_ids: $workspaceIds) {
    id
    name
    color
    parent { id name }
    workspace { id name }
    children { id name }
  }
}
""".strip()


FOLDER_GET = """
query ($ids: [ID!]!) {
  folders(ids: $ids) {
    id
    name
    color
    parent { id name }
    workspace { id name }
    children { id name }
  }
}
""".strip()


FOLDER_CREATE = """
mutation (
  $name: String!
  $workspace: ID!
  $color: FolderColor
  $parent: ID
  $icon: FolderCustomIcon
  $fontWeight: FolderFontWeight
) {
  create_folder(
    name: $name
    workspace_id: $workspace
    color: $color
    parent_folder_id: $parent
    custom_icon: $icon
    font_weight: $fontWeight
  ) {
    id
    name
    color
  }
}
""".strip()


FOLDER_UPDATE = """
mutation (
  $id: ID!
  $name: String
  $color: FolderColor
  $productId: ID
  $position: FolderPosition
) {
  update_folder(
    folder_id: $id
    name: $name
    color: $color
    account_product_id: $productId
    position: $position
  ) {
    id
    name
    color
  }
}
""".strip()


FOLDER_DELETE = """
mutation ($id: ID!) {
  delete_folder(folder_id: $id) {
    id
    name
  }
}
""".strip()


# --- favorites (3h, read-only) ---

# monday-api.md §14 mentions favorites but not exact mutation names, so
# we expose read-only for now. Expand if monday's SDL confirms the
# add/remove mutation shape.
FAVORITES_LIST = """
query {
  favorites {
    id
    type
    created_at
    entity_id
    entity_details {
      ... on Board { id name }
      ... on Dashboard { id name }
      ... on Workspace { id name }
      ... on Document { id name }
    }
  }
}
""".strip()


# --- tags (3h) ---

# Account-level public tags; private/shareable tags live nested under
# boards (see `mondo board get` for board.tags).
TAGS_LIST = """
query ($ids: [ID!]) {
  tags(ids: $ids) {
    id
    name
    color
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
  $internal: Boolean
) {
  create_notification(
    user_id: $user
    target_id: $target
    target_type: $targetType
    text: $text
    internal: $internal
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
    is_admin
    is_guest
    is_view_only
    is_pending
    enabled
    created_at
    last_activity
    title
    photo_thumb
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
AGGREGATE_BOARD = """
query (
  $board: ID!
  $groupBy: [GroupByInput!]
  $select: [SelectInput!]
  $rules: [AggregateRuleInput!]
  $limit: Int
) {
  aggregate(
    board_id: $board
    group_by: $groupBy
    select: $select
    rules: $rules
    limit: $limit
  ) {
    group_by_values
    values
    value
  }
}
""".strip()


# Validation rules (2025-04+ Pro/Enterprise rollout).
VALIDATIONS_LIST = """
query ($board: ID!) {
  boards(ids: [$board]) {
    id
    validations {
      id
      column_id
      rule_type
      value
      description
    }
  }
}
""".strip()


VALIDATION_CREATE = """
mutation (
  $board: ID!
  $columnId: String!
  $ruleType: String!
  $value: JSON
  $description: String
) {
  create_validation_rule(
    board_id: $board
    column_id: $columnId
    rule_type: $ruleType
    value: $value
    description: $description
  ) {
    id
    column_id
    rule_type
  }
}
""".strip()


VALIDATION_UPDATE = """
mutation (
  $id: ID!
  $value: JSON
  $description: String
) {
  update_validation_rule(id: $id, value: $value, description: $description) {
    id
    rule_type
  }
}
""".strip()


VALIDATION_DELETE = """
mutation ($id: ID!) {
  delete_validation_rule(id: $id) {
    id
  }
}
""".strip()


# --- boards ---


def build_boards_list_query(
    *,
    state: str | None = None,
    kind: str | None = None,
    workspace_ids: list[int] | None = None,
    order_by: str | None = None,
    with_item_counts: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Build a page-based boards list query containing only the filter args
    that are actually set.

    Monday's `boards(...)` has a server-side quirk: passing `workspace_ids:
    null` silently drops arbitrary boards from the result set (vs. omitting
    the argument entirely, which returns everything). Safest to never send
    null-valued filters, so we build the query and variables dict dynamically.

    `items_count` costs ~500k complexity per page of 100 — by default it is
    omitted; pass `with_item_counts=True` to include it.
    """
    var_decls: list[str] = ["$limit: Int!", "$page: Int!"]
    args: list[str] = ["limit: $limit", "page: $page"]
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
        "updated_at",
    ]
    if with_item_counts:
        fields.append("items_count")

    query = (
        f"query ({', '.join(var_decls)}) {{\n"
        f"  boards({', '.join(args)}) {{\n"
        f"    {' '.join(fields)}\n"
        f"  }}\n"
        f"}}"
    )
    return query, variables


# Detailed single-board fetch.
BOARD_GET = """
query ($id: ID!) {
  boards(ids: [$id]) {
    id
    name
    description
    state
    board_kind
    board_folder_id
    workspace_id
    items_count
    updated_at
    permissions
    workspace { id name kind }
    owners { id name }
    subscribers { id name }
    top_group { id title }
    groups { id title color position archived }
    columns { id title type description archived }
    tags { id name color }
  }
}
""".strip()


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


# --- columns: structural (2b) ---

COLUMN_CREATE = """
mutation (
  $board: ID!
  $title: String!
  $type: ColumnType!
  $description: String
  $defaults: JSON
  $id: String
  $after: ID
) {
  create_column(
    board_id: $board
    title: $title
    column_type: $type
    description: $description
    defaults: $defaults
    id: $id
    after_column_id: $after
  ) {
    id
    title
    type
    description
    archived
  }
}
""".strip()


COLUMN_RENAME = """
mutation ($board: ID!, $col: String!, $title: String!) {
  change_column_title(board_id: $board, column_id: $col, title: $title) {
    id
    title
    type
  }
}
""".strip()


COLUMN_CHANGE_METADATA = """
mutation (
  $board: ID!
  $col: String!
  $property: ColumnProperty!
  $value: String!
) {
  change_column_metadata(
    board_id: $board
    column_id: $col
    column_property: $property
    value: $value
  ) {
    id
    title
    type
    description
  }
}
""".strip()


COLUMN_DELETE = """
mutation ($board: ID!, $col: String!) {
  delete_column(board_id: $board, column_id: $col) {
    id
    title
    archived
  }
}
""".strip()


# --- groups (2c) ---

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


# --- workspaces (2d) ---

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


# --- users (3a) ---

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


# --- teams (3b) ---

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


# --- subitems (3c) ---

# Subitems are nested on a parent item; they have their own (hidden) board
# and column IDs. Listing = nested `items(ids:[parent]) { subitems { ... } }`.
SUBITEMS_LIST = """
query ($parent: ID!) {
  items(ids: [$parent]) {
    id
    name
    board { id name }
    subitems {
      id
      name
      state
      created_at
      creator { id name }
      board { id name }
      column_values { id type text value }
    }
  }
}
""".strip()


SUBITEM_GET = """
query ($id: ID!) {
  items(ids: [$id]) {
    id
    name
    state
    created_at
    updated_at
    creator { id name }
    board { id name }
    parent_item { id name }
    column_values { id type text value }
  }
}
""".strip()


SUBITEM_CREATE = """
mutation (
  $parent: ID!
  $name: String!
  $values: JSON
  $create_labels: Boolean
) {
  create_subitem(
    parent_item_id: $parent
    item_name: $name
    column_values: $values
    create_labels_if_missing: $create_labels
  ) {
    id
    name
    state
    board { id name }
    column_values { id type text value }
  }
}
""".strip()


# --- updates / item comments (3d) ---

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
