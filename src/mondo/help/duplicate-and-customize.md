# Duplicate a template board, then customize it

End-to-end walkthrough: copy a template board, rename its groups,
seed items in bulk, and post a markdown update. The point is to
chain the primitives without paying a round-trip per step.

After `board duplicate`, group ids are unstable strings like
`duplicate_of_objective_2__we_t` and item ids don't exist until you
create them. So the customize phase wants **title-based selectors**
and **bulk primitives** rather than list-then-act.

## Step 1 — Duplicate

    mondo board duplicate 1234567890 \
        --type duplicate_board_with_structure \
        --workspace 42 --folder 67890 \
        --name "MgApps Squad OKRs Q2 2026" \
        --wait

Without `--workspace` the copy lands in the source board's workspace
(monday's own default would otherwise drop it into the caller's main
workspace). `--folder` is optional.

`--wait` blocks until the copy's `items_count` stabilises and emits a
`_wait` envelope on the response:

    {
      "board": { "id": 9876543210, "name": "MgApps Squad OKRs Q2 2026" },
      "_wait": { "final_items_count": 0, "expected": 0, "matched": true }
    }

For `duplicate_board_with_structure` the expected count is **0** —
`matched: true` confirms a clean structure-only copy. For
`duplicate_board_with_pulses` and `duplicate_board_with_pulses_and_updates`,
`expected` is the source board's item count.

Exit 8 (timeout) means the copy is still being populated server-side;
re-run with a longer `--timeout`. Exit codes are stable; see
`mondo help exit-codes`.

## Step 2 — Locate target groups by title (skip the lookup)

The naive flow is "list groups, map titles → ids, emit one rename per
group." That's 1 + N HTTP calls and N points of failure. Two faster
options:

**By title, one at a time.** `mondo group rename` (and `update`,
`column rename`, `item rename`) accept `--name-contains` /
`--name-matches` / `--name-fuzzy` against the current title:

    mondo group rename --board 9876543210 \
        --name-contains "Objective 2" \
        --title "Objective 2: We have launched..."

**If you do need the id list** (e.g. to feed it into a script):

    mondo group list --board 9876543210 -q '[*].{title:title,id:id}'

See `mondo help batch-operations` for the full filter vocabulary,
ambiguous-match behaviour, and `--first`.

## Step 3 — Bulk seed items

Seeding N items as N separate `mondo item create` calls is N HTTP
round-trips. `--batch` collapses them into one GraphQL document:

    cat > items.json <<'EOF'
    [
      {"name": "KR 1.1", "group_id": "topics", "columns": ["status=Working on it"]},
      {"name": "KR 1.2", "group_id": "topics"},
      {"name": "KR 2.1", "group_id": "group_two"}
    ]
    EOF

    mondo --dry-run item create --board 9876543210 --batch items.json
    mondo item create --board 9876543210 --batch items.json

See `mondo help batch-operations` for the per-row JSON schema, chunk
sizing, and the result-envelope shape.

## Step 4 — Post a markdown update

Markdown is the default body format (Phase 1.5). No `--markdown` flag
needed:

    mondo update create --item 1122334455 --body "**Why**: aligns with North Star OKR. **Owner**: @alice."

The body is converted to monday's HTML at send time. Pass `--html` if
you have HTML you want to send verbatim (e.g. `<mention>` tags).

For longer bodies, load from a file or stdin:

    mondo update create --item 1122334455 --from-file ./why.md
    cat ./why.md | mondo update create --item 1122334455 --from-stdin

## Replay safety

`mondo` does not yet have idempotency keys (Phase 4.2 deferred). A
re-run of `--batch items.json` will create a second set of items.
Until that lands:

- Use `--dry-run` for every mutating step in a fresh script.
- For the duplicate itself, capture the new board id in a shell var
  and never re-run the `duplicate` line on retry — only the steps
  downstream of it.

## See also

- `mondo help batch-operations` — `--name-contains` selectors and the
  `--batch` JSON contract.
- `mondo help agent-tips` — projection warnings, `mondo schema`, the
  structured error envelope.
- `mondo help agent-workflow` — exit code semantics, retry rules,
  entity-typed flag aliases.
- `mondo help codecs` — `--column K=V` value parsing per column type.
- `mondo help graphql` — escape hatch for anything `mondo` doesn't
  wrap yet.
