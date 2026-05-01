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
