---
name: monday-api-watch
description: Check whether the monday.com GraphQL API changed since the last check — diff live schema introspection snapshots against committed baselines, track API-version lifecycle (is mondo's pinned version ageing out?), and surface deprecations/removals that hit mondo's queries. Use for "did the monday API change", "check monday API deprecations", "is our API version still supported", or as a routine (pre-release or monthly) API-drift check. Run from the Mondo repo with MONDAY_API_TOKEN available.
---

# monday API watch

Detect monday.com API changes that matter to mondo. monday publishes **no
RSS/machine-readable changelog** (the changelog page is lazy-loaded JS), so
the reliable detector is the API itself: the `versions` query for lifecycle,
and normalized schema-introspection snapshots for the actual surface.

State lives next to this skill:

- `STATE.md` — last-checked date, lifecycle table, known mondo-relevant changes.
- `baseline/<version>.txt` — normalized schema snapshots from the last check.

## Workflow

### 1. Lifecycle check

```bash
TOKEN=$(grep ^MONDAY_API_TOKEN= .env | cut -d= -f2-)
MONDAY_API_TOKEN=$TOKEN python3 .claude/skills/monday-api-watch/scripts/snapshot_monday_schema.py --versions
```

Compare against the table in `STATE.md`. Alarm conditions:

- mondo's pinned version (`DEFAULT_API_VERSION` in
  `src/mondo/config/loader.py`) is no longer listed, or moved past
  maintenance → **urgent**: bump the pin.
- A new version became `current` → do step 2 for it.

### 2. Schema diff — pinned + current

Snapshot the pinned version and the current stable, diff against baselines:

```bash
for V in 2026-01 2026-07; do   # pinned + current — adjust as versions rotate
  MONDAY_API_TOKEN=$TOKEN python3 .claude/skills/monday-api-watch/scripts/snapshot_monday_schema.py \
      --api-version $V > /tmp/monday-schema-$V.txt
  diff .claude/skills/monday-api-watch/baseline/$V.txt /tmp/monday-schema-$V.txt || true
done
```

An empty diff = no API change since last check; update the date in `STATE.md`
and stop. For non-empty diffs, focus on lines matching what mondo actually
queries — grep the diff for the types mondo touches (`Board`, `Item`, `Group`,
`Column`, `User`, `Team`, `Update`, `Doc`, `DocumentBlock`, `Workspace`,
`Folder`, `Asset`, `Webhook`, `Tag`, `ActivityLogType`), and cross-reference
`src/mondo/api/queries/*.py` to see whether a removed/deprecated field or
argument is one mondo sends. A `[deprecated: ...]` marker appearing on a field
mondo uses is the early warning; a removed line is a break.

If a new version reached `current` and there is no baseline for it yet,
snapshot it and diff it against the *previous* current version's baseline to
enumerate the migration surface.

### 3. Context from the docs (optional, for the "why")

WebFetch the release notes / changelog for human-readable context on whatever
the diff surfaced (URLs in `STATE.md`). The diff is the ground truth; the docs
explain intent and removal timelines.

### 4. Update state

- Overwrite `baseline/<version>.txt` with the fresh snapshots.
- Add/retire baseline files as versions rotate (keep: pinned + current;
  drop versions monday no longer serves).
- Update `STATE.md`: last-checked date, lifecycle table, and the
  "known changes that affect mondo" list (add new findings, delete entries
  that mondo has since migrated past).
- Commit the changes.

### 5. Report and act

Report: lifecycle status, schema deltas hitting mondo's queries, and deadlines
(when does the pinned version die; when do deprecated fields get removed).
For each actionable finding, offer to file a focused GitHub issue on
`zoltanf/mondo` or fix it directly (e.g. migrate a query off a deprecated
field, bump the pin).
