"""GraphQL queries/mutations for folders (3h)."""

from __future__ import annotations

from typing import Any


def build_folders_list_query(
    *,
    ids: list[int] | None = None,
    workspace_ids: list[int] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build a page-based folders list query containing only active filters.

    Monday's `folders(...)` behaves like `boards(...)` / `docs(...)`: sending
    `workspace_ids: null` can undercount or mis-scope the result set versus
    omitting the argument entirely. Build the query dynamically so unfiltered
    folder listings truly span every accessible workspace.
    """
    var_decls: list[str] = ["$limit: Int!", "$page: Int!"]
    args: list[str] = ["limit: $limit", "page: $page"]
    variables: dict[str, Any] = {}

    if ids:
        var_decls.append("$ids: [ID!]")
        args.append("ids: $ids")
        variables["ids"] = ids
    if workspace_ids:
        var_decls.append("$workspaceIds: [ID!]")
        args.append("workspace_ids: $workspaceIds")
        variables["workspaceIds"] = workspace_ids

    return (
        f"""
query ({", ".join(var_decls)}) {{
  folders({", ".join(args)}) {{
    id
    name
    color
    created_at
    owner_id
    parent {{ id name }}
    workspace {{ id name }}
  }}
}}
""".strip(),
        variables,
    )


FOLDER_GET = """
query ($ids: [ID!]!) {
  folders(ids: $ids) {
    id
    name
    color
    created_at
    owner_id
    parent { id name }
    workspace { id name }
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
  $position: DynamicPosition
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
