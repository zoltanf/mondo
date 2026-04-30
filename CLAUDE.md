# Project notes for Claude

## Live test environment

`_local_test_env.sh` (gitignored) exports a real monday.com API token and
the IDs of a dedicated test board. Source it before running anything that
needs live access:

```bash
source ./_local_test_env.sh
```

Variables it sets:

- `MONDAY_API_TOKEN` — auth token for the marktguru workspace
- `MONDO_TEST_BOARD_NAME="Mondo Test Board"` — human label
- `MONDO_TEST_BOARD_ID="5094861043"` — board for live smoke tests
- `MONDO_TEST_BOARD_URL` — convenience link

The script also runs `uv run mondo auth status` at the end, so sourcing
prints that JSON to the shell. Pipe to `>/dev/null 2>&1` if you don't
want it in your output. The board lives in workspace `592446`
("monday.com Playground").

The integration suite at `tests/integration/test_live_writes.py` is gated
on a *different* env var, `MONDAY_TEST_TOKEN`, so sourcing the env file
alone won't run it — set `MONDAY_TEST_TOKEN=$MONDAY_API_TOKEN` if you
want to include it in `pytest`.

**Always assume mutations on the test board are real and visible to other
account members.** Clean up after yourself (delete duplicated boards,
clear test updates) so the board doesn't drift.
