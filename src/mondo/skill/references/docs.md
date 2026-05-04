# Docs

Two distinct surfaces share this file:

- **Standalone workspace docs** — top-level rich documents that live in a workspace, listed in monday's "Docs" section. Commands: `mondo doc <cmd>`.
- **Doc columns on items** — a column of type `doc` that attaches a workdoc to a single item. Commands: `mondo column doc <cmd>`.

A `/boards/<id>` URL may resolve to a workdoc, not a board — see `mondo help boards-vs-docs`.

## List docs — all workspaces or scoped

`--workspace` is **optional**. Omitting it returns docs across **all workspaces** the authenticated user can see. Pass it (repeatably) to restrict.

```bash
mondo doc list -o json                                          # all docs, every workspace
mondo doc list --name-contains "bonsy" -o json                 # cross-workspace name search
mondo doc list --name-fuzzy "bonsi" --fuzzy-score -o json      # cross-workspace fuzzy search
mondo doc list --workspace 592446 --no-cache -o json           # docs in one workspace
mondo doc list --workspace 592446 --name-contains "Spec" -o json
mondo doc list --workspace 592446 --workspace 699169 -o json   # multiple workspaces
```

```json
[
  {"id": 5095668848, "object_id": "abcd1234", "name": "Spec — login flow"},
  {"id": 5095668849, "object_id": "abcd1235", "name": "Spec — auth middleware"}
]
```

*Gotcha:* `id` is monday's internal numeric doc id; `object_id` is the UUID-style doc id used in URLs (`/docs/<object_id>`). `--no-cache` is a good idea immediately after a write — the doc cache TTL is 24h. Name filters (`--name-contains`, `--name-matches`, `--name-fuzzy`) are client-side and work with or without `--workspace`.

## Get a doc — JSON or Markdown

```bash
# Structured JSON (blocks, deltas, types):
mondo doc get --id 5095668848 --format json -o json

# Or address by object_id (the URL form):
mondo doc get --object-id abcd1234 --format json -o json

# Render to Markdown:
mondo doc export-markdown --doc 5095668848
```

```json
{
  "id": 5095668848,
  "object_id": "abcd1234",
  "name": "Spec — login flow",
  "blocks": [
    {"type": "large_title",  "content": {"deltaFormat": [{"insert": "Section A"}]}},
    {"type": "normal_text",  "content": {"deltaFormat": [{"insert": "bullet item one"}]}}
  ]
}
```

*Gotcha:* `--id` is the numeric, `--object-id` is the UUID. Block types use `snake_case` on input (`normal_text`, `medium_title`, `bulleted_list`); read paths sometimes return them with spaces — match either form.

## Create a doc

```bash
mondo doc create --workspace 592446 --name "Spec — Q3 launch"
```

```json
{"id": 5095668850, "object_id": "abcd1239", "name": "Spec — Q3 launch", "blocks": []}
```

*Gotcha:* the new doc starts empty. Add content with `add-markdown`, `add-content`, or per-block `add-block`.

## Add markdown to a doc

```bash
mondo doc add-markdown --doc 5095668850 --markdown "# Heading\n\nbody paragraph.\n\n- bullet"
```

Or read from stdin:

```bash
cat spec.md | mondo doc add-markdown --doc 5095668850 --from-stdin
```

```json
{"id": 5095668850, "blocks_added": 4}
```

*Gotcha:* `add-markdown` (and the alias `add-content`) appends to the end. To overwrite, delete the doc and recreate, or fetch + diff blocks manually with `add-block` / `delete-block` for surgical edits.

## Markdown round-trip — what actually round-trips

The **strict subset** round-trips with content equality after whitespace normalisation: headings, paragraphs, bulleted/numbered lists, blockquotes, code blocks, horizontal rules.

**Rich markdown** (tables, images, inline bold/italic/link, nested lists) lossily degrades — the export differs from the input. The repo pins this via a golden file at `tests/integration/fixtures/doc_roundtrip/rich_expected_export.md`.

```bash
# Round-trip pattern:
mondo doc add-markdown --doc 5095668850 --markdown "$(cat strict_input.md)"
mondo doc export-markdown --doc 5095668850 > exported.md
```

*Gotcha:* if you need pixel-perfect markdown out, stick to the strict subset on input. For richer formatting, accept that the export will look different and treat monday as the source of truth.

## Duplicate / rename a doc

```bash
mondo doc duplicate --doc 5095668850
mondo doc rename --doc 5095668850 --name "Spec — Q3 launch (v2)"
```

```json
{"id": 5095668870, "name": "Spec — Q3 launch — Copy"}
```

*Gotcha:* `doc duplicate` and `doc rename` may currently `xfail` against monday's API due to an `Int!` vs `ID!` schema mismatch — check the test status if these regress (`tests/integration/test_live_doc_md_roundtrip.py::test_live_doc_duplicate_preserves_content`). If you need a guaranteed copy, export-markdown + create + add-markdown is a safe fallback.

## Delete a doc

```bash
mondo doc delete --doc 5095668850
```

*Gotcha:* deleting a doc that's **referenced by a doc-column** breaks that column's pointer — the column will appear empty in the UI. Either clear the doc-column first (`column doc clear`) or accept the break.

---

## Doc columns — set, get, append, clear

Doc columns store a pointer to a doc. mondo manages both the doc and the column linkage for you.

### Set a doc column from a markdown file

```bash
mondo column doc set \
  --item 9876543210 \
  --column e2e_doc \
  --from-file ./spec.md
```

Or from stdin:

```bash
cat spec.md | mondo column doc set \
  --item 9876543210 --column e2e_doc --from-stdin
```

Or inline:

```bash
mondo column doc set \
  --item 9876543210 --column e2e_doc \
  --markdown "## Spec\n\nbody."
```

```json
{"item_id": "9876543210", "column_id": "e2e_doc", "doc_id": "abcd5555", "blocks_written": 4}
```

*Gotcha:* `set` **overwrites** the existing doc content (or creates a fresh doc if the column was empty). The column points to the same doc id across writes — the underlying doc is reused.

### Read a doc column as Markdown

```bash
mondo column doc get \
  --item 9876543210 --column e2e_doc \
  --format markdown
```

```markdown
# Spec

body paragraph.

- bullet item one
```

*Gotcha:* the exporter prepends a title block derived from the column title (e.g. `Spec Doc: ...`). Strip that line if you only want the body.

### Append to a doc column

```bash
mondo column doc append \
  --item 9876543210 --column e2e_doc \
  --from-file ./more.md
```

*Gotcha:* `append` preserves prior blocks and adds the new content at the end. Use `set` to overwrite, `append` to extend.

### Clear a doc column

```bash
mondo column doc clear \
  --item 9876543210 --column e2e_doc
```

*Gotcha:* `clear` unlinks the doc from the column but doesn't delete the doc itself. After clear, `column doc get` may exit `0` with empty markdown OR exit `6` (not found) — both are valid; branch on exit code.
