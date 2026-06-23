# Project notes for Claude

## Working principles

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## Releasing

Cut releases with `scripts/release.sh <version>` (e.g.
`scripts/release.sh 0.9.0`). It bumps `src/mondo/version.py` +
`pyproject.toml`, refreshes `uv.lock`, runs the non-integration test
suite, commits `chore(release): v<version>`, tags `v<version>`, and
pushes `main` + the tag. The tag push triggers
`.github/workflows/release.yml`, which builds the four platform
binaries, creates the GitHub Release, and updates the Homebrew tap at
`zoltanf/homebrew-mondo`. Pass `--skip-tests` only in emergencies.

Preconditions enforced by the script: clean working tree, on `main`,
local in sync with `origin/main`, tag not already present.

**Always confirm the exact new version number with me before running
the release script.** Don't infer the bump (patch/minor/major) and run
it unprompted — state the current version and the proposed new version,
and wait for my explicit go-ahead.

## Live test environment

`.env` (gitignored) holds the live monday.com API token and the IDs of
the dedicated playground board / doc. `.env.example` (committed) lists
the required keys. To set it up:

```bash
cp .env.example .env
# fill in MONDAY_API_TOKEN and MONDAY_TEST_TOKEN with the real token
```

`tests/integration/conftest.py` calls `load_dotenv(..., override=False)`
at collection time, so the live integration suite picks the values up
automatically. Existing shell env vars still win, which keeps CI safe.

For ad-hoc CLI use outside pytest, `uv run` does not load `.env` —
either export the vars in your shell, or pass them inline:

```bash
MONDAY_API_TOKEN=$(grep ^MONDAY_API_TOKEN= .env | cut -d= -f2-) \
    uv run mondo auth status
```

Variables `.env` sets:

- `MONDAY_API_TOKEN` — auth token for the marktguru workspace.
- `MONDAY_TEST_TOKEN` — same value, mirrored. Gates the live integration
  suite (`tests/integration/test_live_writes.py` skips unless this is
  set, even if `MONDAY_API_TOKEN` is). Treat setting it as opt-in to
  mutating real resources.
- `MONDO_TEST_BOARD_NAME` / `MONDO_TEST_BOARD_ID` / `MONDO_TEST_BOARD_URL`
  — the dedicated playground board (`5094861043`). Reused by the
  per-feature live tests so they don't pay for folder/board setup.
- `MONDO_TEST_WORKSPACE_ID` / `MONDAY_TEST_WORKSPACE_ID` — same value,
  two names. The original fixture reads `MONDAY_TEST_WORKSPACE_ID`;
  newer code uses the `MONDO_`-prefixed form.
- `MONDO_TEST_DOC_ID` / `MONDO_TEST_DOC_URL` — pre-prepared "Mondo Test
  Doc" in workspace `592446`, exercising every block type the markdown
  renderer cares about (notice box, check lists, bulleted lists, code,
  divider, table cells, normal text, and image blocks — one top-level
  plus two inside a table, relied on by `test_live_doc_images.py`).
  Read-only doc tests skip unless this is set.
  - The value `5095668848` is the **URL-visible `object_id`** (the
    last segment of `https://marktguru.monday.com/docs/5095668848`),
    NOT the internal numeric id. The matching internal id is
    `8519623`. When calling the CLI, route this env var through
    `--object-id` (e.g. `mondo doc get --object-id $MONDO_TEST_DOC_ID`)
    — passing it to `--id` returns `not found`. The existing
    `live_test_doc_id` fixture in `tests/integration/conftest.py`
    returns the env var unchanged; tests that consume it
    (`test_live_writes.py::test_live_doc_read_with_notice_box`) pass
    it via `--object-id`.

The board lives in workspace `592446` ("monday.com Playground").

**Always assume mutations on the test board / docs are real and visible
to other account members.** Each test cleans up via the `cleanup_plan`
fixture (LIFO), but a crashed run can still leave artefacts — spot-check
the board URL after the suite finishes and remove leftover `E2E *`
groups, items, or docs by hand.

### Test layout

Live integration tests live under `tests/integration/`, split by feature:

- `_helpers.py` — `invoke`, `invoke_json`, `wait_for`, `CleanupPlan`,
  cleanup runner. Shared by every test file.
- `conftest.py` — function-scoped fixtures (`live_workspace_id`,
  `cleanup_plan`, `live_test_board_id`, `live_test_doc_id`) and the
  session-scoped `pm_board_session` fixture (+ `session_cleanup_plan`).
- `test_live_writes.py` — original lifecycle + per-feature tests
  (folder/board/group/columns/items, batch, error envelope, doc create).
- `test_live_pm_board.py` — PM-board CLI listing, JSON export,
  CSV export→import round-trip, markdown export smoke.
- `test_live_boards.py` — `board duplicate` (3 variants) + `board move`,
  plus `board update`/`board set-permission` and `board archive`
  (archived boards return exit 6 from `board get`).
- `test_live_folders.py` — folder tree, parent linking, rename, delete
  archives contained boards.
- `test_live_doc_column.py` — `column doc set/get/append/clear`.
- `test_live_doc_images.py` — `doc get --format markdown --out` (client
  renderer) and `doc get --format markdown --engine server --out`
  download embedded images into the markdown's folder and reference them
  by `<assetId>-<name>` local filename.
- `test_live_doc_md_roundtrip.py` — standalone-doc markdown round-trip
  (strict subset + rich golden) plus `doc duplicate`/`doc rename`
  (currently `xfail`-pinned for the `Int!` vs `ID!` schema mismatch).
- `test_live_subitems.py` — subitem create/list/columns/delete, plus
  rename/archive. `subitem move` is dry-run-only: every subitem lives in
  the subitems board's single `topics` group and monday refuses to create
  a second group there, so there's no real target group to move into.
- `test_live_updates.py` — update create/reply/edit/pin/like/delete,
  plus `update get` (single update + replies) and `update clear`.
- `test_live_item_ops.py` — item rename/duplicate/find/move/archive and
  `item move-to-board` (onto a structure-only duplicate so no
  `--column-mapping` is needed).
- `test_live_groups.py` — group archive/duplicate/reorder. The archive
  test registers no per-group cleanup: monday forbids deleting an
  archived group (exit 3); the session board teardown cascades it away.
- `test_live_column_types.py` — codec round-trips on a dedicated scratch
  board for every writable scalar type not exercised by the PM board
  (checkbox/rating/email/phone/link/country/world_clock/week/hour/
  timeline/location/tags); `board_relation`/`dependency` codec expansion
  via `--dry-run`; plus `column get-meta`/`change-metadata`/`rename`/
  `set-many`/`clear`.
- `test_live_doc_blocks.py` — per-block editing (`doc add-block`/
  `update-block`/`delete-block`, `deltaFormat` content), `doc replace`,
  `doc import-html`, and a tolerant smoke for `doc version-history`
  (the 2026-04 `doc_version_history` field is server-side unstable).
- `test_live_readonly.py` — non-mutating commands: `account`, `me`,
  `auth whoami`, `schema` (all + per-resource), `complexity status`,
  `favorite list`, `graphql` (read query), `aggregate board`,
  `activity board`.
- `test_live_admin.py` — real reads (`user list/get`, `team list/get`,
  board-scoped `tag get`) plus **dry-run-only** coverage of every
  org-level mutation (user role/activation/team-membership, `team
  create`/`add-users`, `workspace create`/`update`/`add-user`, `webhook
  create`, `notify send`). Dry-run prints the GraphQL mutation + asserts
  the dispatched field name without sending — never touches real
  users/teams/workspaces/webhooks/notifications.
- `test_live_files.py` — file upload to a file column + download
  round-trip.
- `test_live_cache.py` — read/write/invalidate cycle for every cache
  type (workspaces directory, tags, board_details, items, updates,
  docs_blocks). Each test re-enables the cache on top of the default
  `live_workspace_id` fixture (which disables it), warms the cache via
  a read, asserts the expected file appears at `<cache_dir>/default/
  <entity>/<scope>.json`, triggers the mutation, and verifies the
  file is gone. The doc test creates a throwaway workspace doc rather
  than depending on `MONDO_TEST_DOC_ID`. Also covers the `cache
  status`/`clear`/`refresh` management commands.
- `fixtures/doc_roundtrip/` — markdown inputs (`strict_input.md`,
  `rich_input.md`, `append_input.md`) and the golden output
  (`rich_expected_export.md`). Regenerate the golden with
  `MONDO_UPDATE_GOLDEN=1 uv run pytest tests/integration/test_live_doc_md_roundtrip.py::test_live_doc_markdown_rich_roundtrip_golden`.

### Session fixture caveat

`pm_board_session` builds a fresh PM board (folder + 8 columns + 3 groups
+ 5 items) once per pytest session and registers teardown on
`session_cleanup_plan`. If the session crashes mid-setup, the residual
`E2E PM Session *` folder must be deleted by hand from the playground
workspace.
