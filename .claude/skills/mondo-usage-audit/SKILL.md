---
name: mondo-usage-audit
description: >-
  Audit how the `mondo` CLI and the `mondo` skill are actually being used by
  analysing local Claude Code session logs since the last release — surfacing
  errors, stumbling blocks, cold (skill-not-loaded) sessions, discoverability
  gaps, zero-use features, latency hot-spots, and concrete skill/CLI
  improvements. Use this whenever you want to check mondo's real-world agent
  usage: "audit mondo usage", "how are agents using mondo", "what friction is
  mondo hitting", "analyse my session logs for mondo problems", "what should I
  improve in the mondo skill or CLI", "do the mondo usage review again", or as
  a routine post-release health check. Run it from the Mondo repo.
---

# Mondo usage audit

You are auditing **how agents actually use mondo in the wild** by mining the
user's local Claude Code transcripts (`~/.claude/projects/*/*.jsonl`). The goal
is to make the `mondo` CLI and the `mondo` skill as easy to use as possible —
for agents first (that's all these logs show) and humans by extension.

The deliverable is a **prioritised report**: what's breaking, what's confusing,
what's slow, what's never discovered, and the cheapest changes that would fix
the most friction. Then offer to act on it.

## Why this is mostly a reading-and-judgement task

A bundled script does the mechanical part — finding every mondo invocation,
matching results, timing calls, counting patterns. **That's the easy 20%.** The
value is in the 80% the script can't do: tracing a recurring error to its real
cause, telling a genuine CLI gap from an agent's shell bug, and ranking fixes by
leverage. The single biggest finding of the original audit was *not in mondo at
all* — it was a stale cheat sheet in a project's `CLAUDE.md` teaching wrong flag
syntax. Keep that in mind: **friction surfaces in the logs; its cause is often
upstream of the CLI.**

One hard limit, state it in the report: these logs show **agent** usage only.
There is no interactive-human signal here, so "easy for humans" can only be
inferred, not measured.

## Workflow

### 1. Run the scanner

From the Mondo repo root (so it can auto-detect the last release tag):

```bash
python3 .claude/skills/mondo-usage-audit/scripts/scan_mondo_usage.py
```

By default it scans every transcript modified since the newest `vX.Y.Z` tag's
commit date. Right after a release that window is tiny — for a meaningful audit,
widen it to the *previous* release or a fixed date:

```bash
# wider window — last ~2 weeks regardless of tags
python3 .claude/skills/mondo-usage-audit/scripts/scan_mondo_usage.py \
    --since 2026-05-31T00:00:00+00:00
```

The script prints a full summary and writes the complete record set to
`/tmp/mondo_usage.json` for drill-down. Read the whole summary before forming
any conclusions — the sections are designed to be read top to bottom.

By default it **excludes the Mondo repo's own transcripts** — those are full of
commit messages, `gh issue` bodies and benchmark scripts that mention `mondo`
but aren't real consumer usage. You're auditing how *other* projects use mondo.
Pass `--include-self` only if you specifically want the dev sessions too.

### 2. Read the scanner output — what each section is telling you

- **SCOPE** — headline counts. The ratio that matters most: *sessions using
  mondo* vs *skill-loaded*. A high **cold** count means agents drive the CLI
  without loading the skill — almost all flag-guessing and graphql escapes come
  from cold sessions. Note the success rate and the stderr-suppression %.
- **SUBCOMMAND FREQUENCY** — what agents reach for. The long tail and the
  *absent* commands are as informative as the top.
- **PER-SESSION CONTEXT** — `COLD`/`REFS`/`SKILL` per session, plus `JOB` for
  headless/cron runs and the first user message. Use this to find *which kinds
  of sessions* (which slash commands, which projects) run cold. That's where
  the root cause usually lives.
- **ERRORS** — every failed invocation with its command and result. Read them
  all. Classify each (see step 4) — do not assume an error is mondo's fault.
- **RAW GRAPHQL ESCAPES** — every `mondo graphql` call. Each one is a signal:
  either a real capability gap, or a discoverability miss (the CLI already does
  it and the agent didn't know). Decide which for each cluster.
- **FRICTION SIGNALS** — `graphql --query` misuse (query is positional;
  `-q/--query` is the global JMESPath filter), redundant `-o json`,
  `--no-cache`, errors hidden by `2>/dev/null`, retry-after-error pairs.
- **FEATURE-USAGE PROBES** — recently-shipped sugar. Near-zero here means a
  *discoverability* gap, not a capability gap. Don't propose building things
  that already exist and aren't being found.
- **PERFORMANCE** — latency percentiles and per-subcommand medians over
  *attributable single-call* invocations (multi-command bash blocks and
  idle/approval gaps are excluded so the numbers reflect mondo, not the shell).
  The per-subcommand median table is the trustworthy view; the slowest list
  shows the worst genuine single calls.

### 3. Drill into anything that needs context

The summary counts; `/tmp/mondo_usage.json` has the full commands and result
text. Examples:

```bash
# every command + result snippet for a specific error pattern
jq -r '.invocations[] | select(.command|test("graphql --query")) | .command' /tmp/mondo_usage.json
# the project an error came from, to go read that project's CLAUDE.md / slash command
jq -r '.invocations[] | select(.error) | .file' /tmp/mondo_usage.json | sort -u
```

### 4. Trace root causes — do NOT stop at "the CLI errored"

For each recurring error or escape, ask **where the agent got the wrong idea**:

- **Stale cheat sheets.** Read the `CLAUDE.md` of the projects that generated
  the errors (the `file` field points at the transcript; its `cwd`/first user
  message tells you the project). A `CLAUDE.md` "Key Commands" block teaching
  `--board-id` / `mondo graphql --query` / `item rename <id> "name"` will
  poison every agent in that project regardless of how good the CLI is. This was
  the #1 finding last time. Fixing it costs nothing in the mondo repo.
- **Slash commands / workflow skills that skip the mondo skill.** If cold
  sessions cluster around specific commands (e.g. `/ticket-triage`), read those
  command definitions — they likely write mondo commands from memory instead of
  invoking the skill. The fix is "invoke the mondo skill first", not new CLI.
- **Skill drift.** Compare the *installed* skill with the repo source — if they
  disagree, agents are running stale guidance:
  ```bash
  diff -ru ~/.claude/skills/mondo src/mondo/skill 2>/dev/null
  ```
- **Genuine CLI/skill gaps.** Only after ruling out the above: a real missing
  flag, a dead-end error message, a feature that should exist (e.g. last time:
  `board create --with-url`, a `name`-column error that should point at
  `item rename`, `file url --asset` to print a `public_url` without
  downloading).

Classify every error into one of: **real mondo issue**, **agent shell bug**
(zsh `declare -A`, broken f-string quoting — not mondo's fault), **permission-
classifier denial** (Claude Code blocked an unrequested write — behavioural,
maybe a skill operating-norm note), or **monday-server variance** (500s,
cold-cache slowness — not actionable in mondo). Report the breakdown honestly;
inflating the mondo bug count helps no one.

### 5. Cross-reference open issues before recommending anything

Avoid filing duplicates and acknowledge work already in flight:

```bash
gh issue list --repo zoltanf/mondo --state open --limit 50
gh pr list --repo zoltanf/mondo --state open --limit 30
```

Map each finding to: already-fixed, has-an-open-issue/PR, or net-new.

### 6. Performance pass — verify hot-spots with read-only live benchmarks

The latency table tells you *where* time goes; a quick live benchmark tells you
*why*, and what a fix would buy. **Read-only only** — `list`/`get` against the
playground/test board from `.env`, never mutations. Useful probes the original
audit used to decompose the `item list` cost and the cold-directory tail:

```bash
TOKEN=$(grep ^MONDAY_API_TOKEN= .env | cut -d= -f2-)
# full column_values vs slim — quantifies the per-page tax on item list
MONDAY_API_TOKEN=$TOKEN /usr/bin/time -p mondo item list --board <big_board> -o json >/dev/null
MONDAY_API_TOKEN=$TOKEN /usr/bin/time -p mondo item list --board <big_board> --fields id,name -o json >/dev/null
# warm cache vs cold (cold ≈ first lookup of the workday)
MONDAY_API_TOKEN=$TOKEN /usr/bin/time -p mondo board list >/dev/null
MONDAY_API_TOKEN=$TOKEN /usr/bin/time -p mondo board list --no-cache >/dev/null
```

Note that monday's own server time is highly variable (identical queries have
been seen at 118s cold / 21s warm) — run a couple of times and report ranges,
not single numbers. Attribute slowness correctly: mondo overhead vs payload
shape vs monday server vs cold cache.

### 7. Write the report

Use the structure below. Lead with the highest-leverage finding (often *not* a
mondo code change). Every recommendation needs evidence from the logs (a count,
a date, an observed failure) and a rough leverage estimate. Separate what's
working from what's broken — confirming the good parts (e.g. "did you mean"
suggestions self-correcting flag errors) is part of the picture.

```markdown
# Mondo usage analysis — <window> (<N> days)

**Scope:** <N> transcripts scanned, <N> sessions used mondo, <N> CLI
invocations, <N> errors (<X>% success), <N> skill invocations,
<N> --help lookups, <N> raw graphql escapes.

## Headline finding
<the single highest-leverage thing — name it and quantify the damage>

## Stumbling blocks observed in the wild
<table or list: pattern | what's wrong | observed damage (count + dates)>

## What's working well
<the safeguards that earned their keep — keep these, don't regress them>

## Discoverability / zero-use features
<shipped capability nobody found; the fix is exposure, not building>

## Not a mondo problem (for completeness)
<agent shell bugs, permission denials, monday-server variance — counted and set aside>

## Recommendations, ranked by leverage
1. <often: fix a project CLAUDE.md / slash command — zero cost in the repo>
2. <skill change: canonical-flags table, operating norms>
3. <CLI change: the real gaps, each as its own issue>

## Performance
<latency hot-spots, what the live benchmark showed, ranked changes>

> Caveat: logs show agent usage only — no interactive-human signal.
```

### 8. Offer to act

End by offering concrete follow-ups, not a vague "want me to help?":

- Fix the stale cheat sheets / slash commands directly (verify each flag against
  the current source before editing — the whole point is to stop teaching wrong
  syntax).
- Add a "canonical flags / common mistakes" table or operating norms to the
  mondo skill (`src/mondo/skill/`), and keep the installed copy in sync.
- File the net-new CLI findings as focused GitHub issues on `zoltanf/mondo`
  (one per independent change, matching the repo's issue style).

## Scanner reference

`scripts/scan_mondo_usage.py` flags:

- `--since <ISO>` — cutoff override (e.g. `2026-05-31T00:00:00+00:00`). Default:
  newest `vX.Y.Z` tag's commit date.
- `--repo <path>` — Mondo repo for tag auto-detect (default: cwd).
- `--root <path>` — logs root (default: `~/.claude/projects`).
- `--json-out <path>` — full record set (default: `/tmp/mondo_usage.json`).
- `--top <n>` — subcommands to list (default: 40).
- `--include-self` — keep the Mondo repo's own dev transcripts (excluded by
  default; they're commit/benchmark noise, not consumer usage).

When new mondo features ship, add them to `FEATURE_PROBES` in the script so the
discoverability check keeps measuring the current surface.
