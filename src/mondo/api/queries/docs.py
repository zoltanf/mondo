"""GraphQL queries/mutations for docs — the Doc column pointer + blocks,
and workspace docs (3e).
"""

from __future__ import annotations

from typing import Any

# --- docs (the Doc column → workspace doc pointer + blocks) ---

# Fetch a doc's full block tree by object_id (extracted from the doc column).
DOCS_BY_OBJECT_ID = """
query ($objs: [ID!]!) {
  docs(object_ids: $objs) {
    id
    object_id
    name
    doc_kind
    doc_folder_id
    created_at
    updated_at
    url
    relative_url
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


# Fetch one page of blocks for a doc selected by object_id.
# Used to assemble full docs without relying on the default `blocks` page size.
DOCS_BY_OBJECT_ID_BLOCKS_PAGE = """
query ($objs: [ID!]!, $limit: Int!, $page: Int!) {
  docs(object_ids: $objs) {
    id
    object_id
    name
    doc_kind
    doc_folder_id
    created_at
    updated_at
    url
    relative_url
    workspace_id
    blocks(limit: $limit, page: $page) {
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


def build_docs_list_query(
    *,
    ids: list[int] | None = None,
    object_ids: list[int] | None = None,
    workspace_ids: list[int] | None = None,
    order_by: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build a page-based docs list query containing only the filter args
    that are actually set.

    Monday's `docs(...)` has the same server-side quirk as `boards(...)`:
    passing `workspace_ids: null` silently scopes the result set to a single
    (default) workspace instead of returning docs from every accessible
    workspace. Safest to never send null-valued filters, so we build the
    query and variables dynamically.
    """
    var_decls: list[str] = ["$limit: Int!", "$page: Int!"]
    args: list[str] = ["limit: $limit", "page: $page"]
    variables: dict[str, Any] = {}

    if ids:
        var_decls.append("$ids: [ID!]")
        args.append("ids: $ids")
        variables["ids"] = ids
    if object_ids:
        var_decls.append("$objectIds: [ID!]")
        args.append("object_ids: $objectIds")
        variables["objectIds"] = object_ids
    if workspace_ids:
        var_decls.append("$workspaceIds: [ID!]")
        args.append("workspace_ids: $workspaceIds")
        variables["workspaceIds"] = workspace_ids
    if order_by is not None:
        var_decls.append("$orderBy: DocsOrderBy")
        args.append("order_by: $orderBy")
        variables["orderBy"] = order_by

    fields = [
        "id",
        "object_id",
        "name",
        "doc_kind",
        "doc_folder_id",
        "created_at",
        "updated_at",
        "url",
        "relative_url",
        "workspace_id",
        "created_by { id name }",
    ]

    query = (
        f"query ({', '.join(var_decls)}) {{\n"
        f"  docs({', '.join(args)}) {{\n"
        f"    {' '.join(fields)}\n"
        f"  }}\n"
        f"}}"
    )
    return query, variables


DOC_GET_BY_ID = """
query ($ids: [ID!]!) {
  docs(ids: $ids) {
    id
    object_id
    name
    doc_kind
    doc_folder_id
    created_at
    updated_at
    url
    relative_url
    workspace_id
    created_by { id name }
    blocks { id type content parent_block_id }
  }
}
""".strip()


# Fetch one page of blocks for a doc selected by internal id.
# Used to assemble full docs without relying on the default `blocks` page size.
DOC_GET_BY_ID_BLOCKS_PAGE = """
query ($ids: [ID!]!, $limit: Int!, $page: Int!) {
  docs(ids: $ids) {
    id
    object_id
    name
    doc_kind
    doc_folder_id
    created_at
    updated_at
    url
    relative_url
    workspace_id
    created_by { id name }
    blocks(limit: $limit, page: $page) {
      id
      type
      content
      parent_block_id
    }
  }
}
""".strip()


# Create a new doc inside a workspace (vs. the already-shipped
# CREATE_DOC_ON_ITEM which creates one attached to a doc-column on an item).
CREATE_DOC_IN_WORKSPACE = """
mutation ($workspace: ID!, $name: String!, $kind: BoardKind, $folder: ID) {
  create_doc(
    location: {
      workspace: {
        workspace_id: $workspace
        name: $name
        kind: $kind
        folder_id: $folder
      }
    }
  ) {
    id
    object_id
    name
    url
  }
}
""".strip()


UPDATE_DOC_NAME = """
mutation ($doc: ID!, $name: String!) {
  update_doc_name(docId: $doc, name: $name)
}
""".strip()


DUPLICATE_DOC = """
mutation ($doc: ID!, $dup: DuplicateType) {
  duplicate_doc(docId: $doc, duplicateType: $dup)
}
""".strip()


# Slim head lookup for resolving a doc by object_id without paging blocks.
# Used by `doc duplicate` to translate monday's returned object_id into the
# internal id (which downstream commands like `doc get`/`doc delete` expect).
DOC_HEAD_BY_OBJECT_ID = """
query ($objs: [ID!]!) {
  docs(object_ids: $objs) {
    id
    object_id
    name
    url
  }
}
""".strip()


DELETE_DOC = """
mutation ($doc: ID!) {
  delete_doc(docId: $doc)
}
""".strip()


EXPORT_MARKDOWN_FROM_DOC = """
query ($doc: ID!, $blocks: [String!]) {
  export_markdown_from_doc(docId: $doc, blockIds: $blocks) {
    error
    markdown
    success
  }
}
""".strip()


ADD_CONTENT_TO_DOC_FROM_MARKDOWN = """
mutation ($doc: ID!, $md: String!, $after: String) {
  add_content_to_doc_from_markdown(
    docId: $doc
    markdown: $md
    afterBlockId: $after
  ) {
    success
    block_ids
    error
  }
}
""".strip()


IMPORT_DOC_FROM_HTML = """
mutation (
  $html: String!
  $workspace: ID!
  $title: String
  $folder: ID
  $kind: DocKind
) {
  import_doc_from_html(
    html: $html
    workspaceId: $workspace
    title: $title
    folderId: $folder
    kind: $kind
  ) {
    error
    success
    doc_id
  }
}
""".strip()


DOC_VERSION_HISTORY = """
query ($doc: ID!, $since: String, $until: String) {
  doc_version_history(doc_id: $doc, since: $since, until: $until) {
    doc_id
    restoring_points {
      date
      user_ids
      type
    }
  }
}
""".strip()


DOC_VERSION_DIFF = """
query ($doc: ID!, $date: String!, $prev: String!) {
  doc_version_diff(doc_id: $doc, date: $date, prev_date: $prev) {
    doc_id
    date
    prev_date
    blocks {
      id
      type
      content
      summary
      parent_block_id
      changes {
        added
        deleted
        changed
      }
    }
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
