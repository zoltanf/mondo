# Complexity budget & rate limits

monday.com enforces a **complexity budget** per API token, refilled every
minute. Each query's cost depends on its shape (page sizes, fields asked
for, nesting depth) — not just the count of requests. `mondo` meters this
transparently so agents and interactive users can stay inside the budget.

## Live inspection

    mondo complexity status

Prints the current budget: how much is available, what the per-minute cap
is, and when the next reset occurs. This is a cheap query — safe to poll.

## Per-call visibility

Every `mondo` command (except `mondo graphql`) logs a drain line to stderr
when `--debug` is set:

    mondo --debug item list --board 42
    # 2026-04-19T10:12:34 | complexity drain: cost=3400 budget=996600/1000000

- `cost` = complexity consumed by that one call (after retries).
- `budget` = `remaining/cap` after the call returned.

## How the meter works

`mondo` rewrites every outbound query to include the `complexity { query
before after reset_in_x_seconds }` sibling field. The numbers come straight
from the server, not a client-side guess. A session-local counter
(`client.meter`) surfaces them to programmatic consumers; `mondo complexity
status` surfaces them to humans.

The raw-passthrough command `mondo graphql` is **exempt** — what you type
is what gets sent. If you're running a large hand-rolled mutation via
`mondo graphql` and want metering, wrap it in a codec-dispatching subcommand
instead, or add the complexity field yourself.

## Cost model: column_values on `item list`

On boards beyond a few hundred items, the full `column_values` selection
dominates `item list` cost — roughly **3x** the per-page complexity and
wall time of the bare item fields (live measurement on a 1,300-item board:
~2.9s per 500-item page for `id name` only vs ~8.7s with full
column_values).

Two ways to stop paying for values you don't read:

- `--fields id,name` (any `--fields` set that never reads `column_values`)
  auto-drops `column_values` from the GraphQL query — no extra flag needed.
  A `-q` JMESPath never auto-slims: it can read fields inside predicates
  yet still return whole rows, so use `-q` to shape and `--fields` to slim.
- `--columns status,person` fetches just those column values, server-side.
  Also available on `item get`. Unknown column ids are silently omitted by
  the API (no error, just missing from `column_values`).

## When the budget runs out

Exit code **4** means complexity exhausted after retries. `mondo` retries
with exponential backoff until it gives up. If you're seeing 4's:

- Drop concurrency / stop running parallel commands on the same token.
- Ask for smaller page sizes (`--limit 50` instead of the default max).
- Narrow `item list` server-side: `--columns col1,col2` or `--fields id,name`.
- Project with `-q` to drop expensive nested fields you don't need.
- Use `mondo aggregate` instead of pulling every item when you just want totals.

The reset is per-minute — waiting 60s is the simplest recovery.

See also: `mondo help exit-codes`, `mondo help output`.
