# Admin

User / team / webhook / tag / activity / favorite / notify / validation / complexity surfaces. Most are *not* covered by the live integration tests, so examples here are sourced from `mondo <group> --help` and the bundled epilog examples — pair them with `--dry-run` when you're acting on real data.

## Users

```bash
mondo user list -o json                      # served from local cache when available
mondo user get --id 12345 -o json            # includes teams + account
mondo user deactivate --id 12345
mondo user activate   --id 12345
mondo user update-role --id 12345 --role member|admin|guest|viewer
mondo user add-to-team      --id 12345 --team 678
mondo user remove-from-team --id 12345 --team 678
```

*Gotcha:* role / activation changes are real and propagate immediately. Run with `--dry-run` first to confirm the GraphQL payload. The `user list` cache TTL is 24h — `--no-cache` for fresh state.

## Teams

```bash
mondo team list -o json                  # optional: --name <fuzzy>
mondo team get --id 678
mondo team create --name "Platform"
mondo team delete --id 678               # permanent
mondo team add-users      --id 678 --user 12345
mondo team remove-users   --id 678 --user 12345
mondo team assign-owners  --id 678 --user 12345
mondo team remove-owners  --id 678 --user 12345
```

*Gotcha:* `team delete` is **immediate and permanent** — no soft-archive. `team list --name <needle>` does fuzzy name match (Levenshtein, threshold 70).

## Webhooks

```bash
# Subscribe to item creates on a board:
mondo webhook create \
  --board 5094861043 \
  --url https://example.com/hook \
  --event create_item

# Watch a specific column's value changes:
mondo webhook create \
  --board 5094861043 \
  --url https://example.com/hook \
  --event change_specific_column_value \
  --config '{"columnId":"status"}'

mondo webhook list   --board 5094861043
mondo webhook delete --id 99999
```

*Gotcha:* the receiving URL must answer monday's challenge handshake on creation; otherwise the webhook is rejected. `--config` accepts a JSON object whose schema depends on the event — see the monday docs or `mondo webhook create --help`.

## Tags

```bash
mondo tag list -o json                                   # account-level (public) tags
mondo tag get --id 1001
mondo tag create-or-get --board 5094861043 --name urgent  # idempotent on a board
```

*Gotcha:* there are **two** kinds of tags — account-level (public) and board-level. `tag list` returns only account-level. To inspect a board's tags, use `mondo board get --id <id>` and read its `tags[]`.

## Activity logs

```bash
# Last ~7 days of activity (retention varies by plan):
mondo activity board --board 5094861043 -o json

# Time-bounded + user-filtered:
mondo activity board \
  --board 5094861043 \
  --since 2026-04-01T00:00:00Z \
  --until 2026-04-18T23:59:59Z \
  --user 12345

# Narrowed to one item + column:
mondo activity board \
  --board 5094861043 \
  --item 9876543210 \
  --column e2e_status \
  --max-items 1000
```

*Gotcha:* retention is roughly 7 days on non-Enterprise plans — older entries silently disappear. Pagination is automatic up to `--max-items`. Time bounds are RFC 3339 (`Z` suffix for UTC).

## Favorites

```bash
mondo favorite list -o json
```

*Gotcha:* read-only — there's no `add` / `remove` favorite command. Returns boards, dashboards, workspaces, and docs the authenticated user has favourited.

## Notifications

```bash
# Notify one user about an item:
mondo notify send \
  --user 12345 \
  --target 9876543210 \
  --target-type Project \
  --text "FYI — please review."

# Notify about an update; --internal suppresses the email:
mondo notify send \
  --user 12345 \
  --target 4242424299 \
  --target-type Post \
  --text "Reply ready" \
  --internal
```

*Gotcha:* monday's `create_notification` mutation is **single-user**. To notify a team, loop with `mondo notify send` per user. `--target-type` is the resource kind (`Project` for items, `Post` for updates, `Board`, etc.).

## Validation rules

```bash
mondo validation --help    # subcommands: list / create / delete / etc.
```

*Gotcha:* the validation surface is mutation-heavy and varies by monday plan. `--dry-run` is your friend.

## Complexity budget

Every read query reports a complexity cost; over-budget queries are throttled with HTTP 429-equivalent (mondo exit code 4, with `retry_in_seconds` in the error envelope).

```bash
mondo complexity status -o json
```

```json
{"reset_in_seconds": 42, "before": 10000000, "after": 9874321, "query": 125679}
```

*Gotcha:* `before / after / query` show the consumed budget per request. To stay under budget on big lists, prefer `--filter` (server-side) and `-q` (projection) over fetching everything and filtering client-side. See `mondo help complexity` for the deep-dive.

## Schema introspection

```bash
mondo schema -o json                       # what fields each read command selects
mondo help --dump-spec -o json             # full machine-readable command tree
```

*Gotcha:* `mondo schema` is the answer when you're wondering "what does `mondo item get` actually request from monday?" — it prints the GraphQL field set per command. Useful for debugging missing fields in the response.

## Authenticated user / account

```bash
mondo me -o json
mondo account -o json
```

*Gotcha:* `me` returns id, name, teams, and the account block; `account` is the account/tier/plan summary alone. Both are useful sanity checks before acting on real data ("am I on the right account?").
