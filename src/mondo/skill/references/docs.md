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
  {"id": 5095668848, "object_id": "5098297247", "name": "Spec — login flow"},
  {"id": 5095668849, "object_id": "5098297248", "name": "Spec — auth middleware"}
]
```

*Gotcha:* `id` is monday's internal numeric doc id; `object_id` is the (also numeric) URL-visible doc id (`/docs/<object_id>`). `--no-cache` is a good idea immediately after a write — the docs directory cache TTL is 8h, and `doc get` has its own short-TTL per-doc cache (`docs_blocks/<id>.json`, 5m) which is invalidated by every doc-write path (`add-block`, `add-content`, `add-markdown`, `set`/`replace`, `clear`, `import-html`, `rename`, `delete`, `update-block`, `delete-block`, plus `column doc set/append/clear`). Name filters (`--name-contains`, `--name-matches`, `--name-fuzzy`) are client-side and work with or without `--workspace`.

## Get a doc — JSON, Markdown, MDX, or HTML

```bash
# Structured JSON (blocks, deltas, types):
mondo doc get --id 5095668848 --format json -o json

# Or address by object_id (the URL form):
mondo doc get --object-id 5098297247 --format json -o json

# Render to Markdown (--object-id for the URL-visible id, --doc for the internal id):
mondo doc export-markdown --object-id 5098297247
mondo doc export-markdown --doc 5095668848

# Client-side render via `doc get` (prints to stdout) — markdown, mdx, or html:
mondo doc get --object-id 5098297247 --format markdown
mondo doc get --object-id 5098297247 --format mdx
mondo doc get --object-id 5098297247 --format html
```

`doc get --format` renders client-side and supports `markdown`, `mdx`, and `html`; `doc export-markdown` is monday's server-side markdown renderer (markdown only — the API offers no server-side HTML/MDX export). All print to stdout by default.

- **mdx** is the markdown rendering with JSX-significant characters (`<`, `{`) escaped in prose (never inside code fences); monday notice/callout boxes stay as GFM `> [!NOTE]` blockquotes.
- **html** is a single self-contained document (inline `<style>`, base64-embedded images) — see below.

*Note:* `export-markdown` is always live (it has no per-doc cache), so `--no-cache` / `--refresh-cache` are accepted as no-ops purely for symmetry with the other doc commands.

### Write to a file (and handle embedded images)

Add `--out FILE` to write the rendered doc to a file (valid for `markdown`, `mdx`, and `html`; rejected with exit 2 for `json`).

For **markdown** and **mdx**, embedded monday images are downloaded into the **same folder** and referenced by a local `<assetId>-<name>` filename — because the raw `protected_static` image URLs only resolve in a logged-in browser, so the bare file is useless off-platform.

```bash
mondo doc get --object-id 5098297247 --format markdown --out ./spec.md
mondo doc get --object-id 5098297247 --format mdx --out ./spec.mdx
mondo doc export-markdown --object-id 5098297247 --out ./spec.md
```

```json
{"out": "spec.md", "images": ["238776078-image-from-clipboard.png", "238776079-diagram.png"]}
```

For **html**, images are base64-embedded directly in the file (no sidecar assets), so the output is a single portable file — this holds even when printing to stdout. The summary reports the embedded image *count*, not filenames:

```bash
mondo doc get --object-id 5098297247 --format html --out ./spec.html
```

```json
{"out": "spec.html", "images": 3}
```

*Gotchas:* Pass `--no-images` to skip downloading/embedding and leave the original (browser-only) monday URLs in place — for markdown/mdx the `images` field then lists the local filenames actually written (images inside table cells are downloaded too, so references aren't orphaned).

```json
{
  "id": 5095668848,
  "object_id": "5098297247",
  "name": "Spec — login flow",
  "blocks": [
    {"type": "large_title",  "content": {"deltaFormat": [{"insert": "Section A"}]}},
    {"type": "normal_text",  "content": {"deltaFormat": [{"insert": "bullet item one"}]}}
  ]
}
```

*Gotcha:* `--id`/`--doc` is monday's internal id; `--object-id` is the id you see in `/docs/<id>` URLs. The doc-*targeting* subcommands (`get`, `export-markdown`, `add-block`, `add-content`, `add-markdown`, `set`/`replace`, `clear`, `rename`, `duplicate`, `delete`, `version-history`, `version-diff`) accept `--object-id` — when a URL or a human gave you the id, that's the flag to use. Sending an object id through `--doc` fails (historically as an opaque 500); mondo now detects it and tells you to retry with `--object-id`. The two *block*-scoped commands are the exception: `update-block` and `delete-block` operate on a globally-unique block id, so they take `--id`/`--block` (or the positional `BLOCK_ID`) and do **not** accept `--object-id`. Block types use `snake_case` on input (`normal_text`, `medium_title`, `bulleted_list`); read paths sometimes return them with spaces — match either form.

## Create a doc

```bash
mondo doc create --workspace 592446 --name "Spec — Q3 launch"
mondo doc create --workspace 592446 --name "Spec — Q3 launch" --folder 123456  # inside a folder
```

```json
{"id": 5095668850, "object_id": "5098297249", "name": "Spec — Q3 launch", "url": "https://acct.monday.com/docs/5098297249"}
```

*Gotcha:* the new doc starts empty. Add content with `add-markdown`, `add-content`, or per-block `add-block`. The create payload always carries `url` (`--with-url` is accepted for symmetry with `board create` / `item create` but is a no-op). If create fails with `USER_UNAUTHORIZED` / "not permitted to create", that's a workspace doc-creation license/policy limit, not a bad token — the error envelope carries a `suggestion` saying so, so don't waste a turn re-checking auth.

## Add markdown to a doc

```bash
mondo doc add-markdown --doc 5095668850 --markdown "# Heading\n\nbody paragraph.\n\n- bullet"
```

Or read from stdin:

```bash
cat spec.md | mondo doc add-markdown --doc 5095668850 --from-stdin
```

```json
{"success": true, "block_ids": ["abc123", "def456", "ghi789"], "error": null, "blocks_added": 3}
```

`blocks_added` is the reliable count (length of `block_ids`); the rest is monday's raw `{success, block_ids, error}` envelope.

*Gotcha:* `add-markdown` (monday's server-side parser) and `add-content` (which loops `create_doc_block` per block) are **separate commands, not aliases** — both append to the end. `add-markdown` auto-chunks large markdown on top-level block boundaries, so big docs no longer fail with a 500; empty/whitespace-only input is refused before any API call. To overwrite the whole doc **in place** (preserving its id / object_id / URL), use `doc set` (alias `doc replace`) — it writes the new markdown first (also auto-chunked), then deletes the prior blocks, so a failed write leaves the original content intact (no half-blanked doc); if a multi-chunk write fails partway, the blocks it already added are rolled back. Empty markdown is refused (use `doc delete` to remove the doc itself):

```bash
mondo doc set --doc 5095668850 --from-file spec.md
mondo doc replace --object-id 5098297249 --markdown "# Fresh body"
```

For surgical edits, fetch + diff blocks manually with `add-block` / `delete-block`.

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

## Clear a doc — empty the body, keep the doc

```bash
mondo doc clear --doc 5095668850
```

```json
{"id": 5095668850, "cleared_blocks": 7}
```

*Gotcha:* `doc clear` removes every block but **keeps the document** — its id / object_id / URL are preserved (unlike `doc delete`, which removes the doc). An already-empty doc is a no-op (`cleared_blocks: 0`). Supports `--dry-run`. This is the standalone-doc analogue of `column doc clear` (which instead unlinks a doc from a *column*).

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
