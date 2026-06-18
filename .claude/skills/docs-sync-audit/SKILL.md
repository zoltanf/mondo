---
name: docs-sync-audit
description: >-
  Check whether mondo's documentation has kept up with recently-shipped CLI
  features, then open a PR with the fixes. Audits every doc surface — README,
  CLAUDE.md, the bundled `mondo` skill (SKILL.md + references/), the in-CLI
  `mondo help` topics, and the generated output-contract-matrix — against the
  command/flag delta of the last few versions, using the CLI's own `--help` as
  ground truth. Use whenever you want to confirm the docs are current: "are the
  docs up to date", "check docs vs recent changes", "audit the help/skill/
  references", "did we document the last couple of versions", or as a routine
  pre/post-release doc-sync check. Run it from the Mondo repo.
---

# Docs sync audit

You are checking whether **the documentation describes what the CLI actually
does today**, after a burst of feature work. Code ships faster than docs; the
job is to find every place a recently-added command or flag is undocumented,
mis-documented, or where the docs still describe the *old* behaviour — then fix
it on a branch and open a PR.

The deliverable is a **PR that closes the doc debt**, preceded by a short
prioritised report so the user can scope it ("do all" vs "just the real gaps").

## Why this is mostly reading and judgement

The mechanical part — listing what changed and grepping the docs — is the easy
20%. The value is the 80% a grep can't do: distinguishing a doc that is *wrong*
(actively teaches stale behaviour — the dangerous case) from one that is merely
*silent* on a new feature (missing mention — lower stakes), and knowing which
surface is the right home for each fix so you don't bloat a narrow help topic.

**The CLI is the source of truth.** Never trust the docs OR the commit messages
about what a flag does — run the command's `--help` and confirm. A feature can
be half-reverted, renamed, or gated; the help output is what users actually get.

## The doc surfaces (audit all of these)

| Surface | Path | What it is | Fix style |
|---|---|---|---|
| README | `README.md` | Human cheat-sheet + command reference blocks | Edit directly |
| Project notes | `CLAUDE.md` | Maintainer/agent working notes | Rarely needs feature edits — only if it describes CLI behaviour |
| **Skill** | `src/mondo/skill/SKILL.md` + `src/mondo/skill/references/*.md` | **Primary agent-facing docs** — highest value | Edit references; **bump `SKILL.md` version** |
| In-CLI help | `src/mondo/help/*.md` | Shown via `mondo help <topic>` | Edit the *on-topic* file only; keep surgical |
| Contract matrix | `docs/output-contract-matrix.{md,json}` | Command→output-shape contract | **Generated — never hand-edit; fix the generator + regenerate** |
| Maintainer skills | `.claude/skills/*/SKILL.md` | Internal workflows (this skill, usage-audit, issues-triage) | Usually generic; only fix concrete stale refs |

The `docs/*.md` files other than the matrix (`plan.md`, `implementation-*.md`,
`monday-api.md`, …) are historical design docs — **out of scope**, do not
"freshen" them.

## Workflow

### 1. Pick the window

Default: everything since the previous release the user cares about. List the
feature/fix/doc commits in range:

```bash
git log --oneline                      # eyeball recent tags + commits
git tag --sort=-creatordate | head     # release tags
git log --oneline <old_tag>..HEAD      # commits in the window
```

If the user names versions ("last couple of versions"), translate to a tag
range. Skip `chore(release)`, `ci:`, and pure-refactor commits — you want
user-visible surface changes.

### 2. Extract the feature/flag delta

For each `feat`/`fix` commit, find the **concrete new commands and flags** — not
the prose. The commit body usually names them; confirm against the diff:

```bash
git show --stat <sha>                  # which files / which command modules
git show <sha> -- src/mondo/cli/       # the actual new flags / commands
```

Produce a lettered checklist (A, B, C, …) of testable items, each phrased as a
concrete flag/command with its contract, e.g. `doc get --format markdown --out
FILE + --no-images opt-out`. This checklist is what every surface gets measured
against.

### 3. Ground-truth from `--help`

Confirm each checklist item **actually exists and behaves as the commit claims**:

```bash
uv run mondo <group> <cmd> --help
```

Note exact flag names, mutual exclusions, defaults, and any "no-op accepted for
symmetry" semantics — those nuances are exactly what docs get wrong. Drop any
checklist item the CLI doesn't actually have.

### 4. Audit each surface against the checklist (fan out)

This is fast in parallel: spawn one read-only agent per surface (README; skill
SKILL.md + references; `help/*.md` + a `--help` ground-truth pass; contract
matrix + maintainer skills). Give each agent the **full lettered checklist** and
have it report, per letter: **PRESENT** (quote the line), **PARTIAL** (what's
missing), or **MISSING** — plus any surface that describes *outdated* behaviour.
Each agent returns only its discrepancies, not file dumps.

When measuring the contract matrix, also check the generator
(`scripts/generate_output_contract_matrix.py`): rows it "could not auto-infer"
(conditional `--out`-style branches) need a `MANUAL_ROW`.

### 5. Classify and report

Rank findings by stakes, and report before editing:

1. **WRONG** — doc states stale behaviour (e.g. "images are dropped",
   "cache flags rejected"). Actively misleads. Fix first.
2. **MISSING (high)** — a marquee feature absent from the **skill references**.
   Agents drive off these, so silence here is the costliest "missing".
3. **MISSING (low)** — cross-reference gaps in README / help topics.
4. **Polish** — minor omissions.

Give the user the prioritised list and let them scope. (Last run: nothing was
WRONG — all gaps were missing mentions + one stale generated matrix row.)

### 6. Fix on a branch

```bash
git checkout -b docs/sync-<version>-doc-surfaces
```

Editing rules, by surface:

- **Skill references** (`src/mondo/skill/references/*.md`): add the feature where
  it belongs topically. Then **bump `src/mondo/skill/SKILL.md` `version:`** (minor
  bump, e.g. `1.3.0` → `1.4.0`) — the freshness checker uses it to nudge a
  re-pull of the bundled skill. This is mandatory on any skill-surface change.
- **Help topics** (`src/mondo/help/*.md`): edit only the file whose topic owns
  the feature; keep additions tight and on-topic (a URL-disambiguation topic
  shouldn't grow a full doc-write tutorial — link to the reference instead).
- **Contract matrix**: edit `MANUAL_ROWS` / row notes in
  `scripts/generate_output_contract_matrix.py`, then regenerate — never hand-edit
  the `.md`/`.json`:
  ```bash
  uv run python scripts/generate_output_contract_matrix.py
  ```
- **README**: edit the command-reference blocks directly.

Honour the repo's working principles (CLAUDE.md): surgical changes, match
existing style, no speculative additions.

### 7. Verify

```bash
uv run pytest -q -k "matrix or help or skill or contract"
```

These cover the generated matrix, help-topic loading, and skill packaging. Fix
any failure before opening the PR.

### 8. Open the PR

```bash
git push -u origin docs/sync-<version>-doc-surfaces
gh pr create --title "docs: sync doc surfaces with <version> features" --body "..."
```

PR body: lead with the audit finding (what was wrong vs merely missing), list
the per-surface changes, and state the verification (matrix regenerated, tests
passed). Use the repo's PR trailer:

```
🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Confirm with the user before merging — opening the PR is the skill's job; merging
is theirs unless they said otherwise.

## Gotchas learned

- **Commit messages lie by omission.** A `feat` body lists the happy path; the
  `--help` is authoritative. Always ground-truth before documenting.
- **The matrix is generated.** Hand-edits get clobbered on the next regenerate.
  Conditional output branches (`--out` → `{out, images}`) need `MANUAL_ROWS`.
- **Skill version bump is load-bearing**, not cosmetic — skip it and installed
  copies never re-pull the new references.
- **Most "missing" is in the skill, not the README.** The README usually gets
  updated with the feature PR; the bundled skill references are the surface that
  silently lags, and they're the one agents actually read.
- **Don't freshen historical design docs** under `docs/` — only the matrix there
  is live.
