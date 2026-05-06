# Project notes for Claude

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
- `MONDO_TEST_DOC_ID` / `MONDO_TEST_DOC_URL` — pre-prepared doc with
  notice-box blocks (`5095668848`). Read-only doc tests skip unless
  this is set.

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
- `test_live_boards.py` — `board duplicate` (3 variants) + `board move`.
- `test_live_folders.py` — folder tree, parent linking, rename, delete
  archives contained boards.
- `test_live_doc_column.py` — `column doc set/get/append/clear`.
- `test_live_doc_md_roundtrip.py` — standalone-doc markdown round-trip
  (strict subset + rich golden) plus `doc duplicate`/`doc rename`
  (currently `xfail`-pinned for the `Int!` vs `ID!` schema mismatch).
- `test_live_subitems.py` — subitem create/list/columns/delete.
- `test_live_updates.py` — update create/reply/edit/pin/like/delete.
- `test_live_files.py` — file upload to a file column + download
  round-trip.
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
