"""GraphQL queries/mutations for files / assets (3g)."""

from __future__ import annotations

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
