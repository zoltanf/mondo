---
name: issues-triage
description: >-
  Sweep all open GitHub issues on the mondo repo and turn them into reviewed,
  tested pull requests — read every open issue, group them by the files they
  touch, implement each group in an isolated git worktree via parallel
  subagents (with unit tests + live playground verification), run
  /simplify + /code-review + /security-review on each branch, then open one PR
  per group. Use this when the user says things like "fix all the open
  issues", "triage the issues into PRs", "do the issue sweep", "clear the
  issue backlog", "open PRs for the open issues", or wants to repeat the
  start-of-session batch-fix flow. Run it from the mondo repo.
---

# Issues → PRs (batch issue sweep)

Turn the open-issue backlog into a small set of **reviewed, tested PRs** —
one per natural group of issues — using git worktrees and parallel subagents,
with the three review skills run on every branch before it ships.

This is a **high-cost, outward-facing** flow: it spawns many subagents, mutates
the live playground board, and creates public PRs. Stay in the loop, confirm
the two real decisions (issue grouping and, later, the release version), and
report faithfully.

## Preflight — environment (do this first, every run)

The toolchain is easy to get wrong; these bit us before:

- **`uv` may not be on PATH.** Run `export PATH="/opt/homebrew/bin:$PATH"` in
  every Bash call. If `uv` is genuinely missing, ask the user to `brew install
  uv` (it manages the Python 3.14 venv too).
- **Tests need the dev extra:** `uv run --extra dev python -m pytest -m "not
  integration" -q`. Plain `uv run python -m pytest` fails ("No module named
  pytest"). Establish a **green baseline on `main` before touching anything.**
- **Live CLI calls need the token from `.env`** (gitignored, lives in the
  **main repo**, not in worktrees):
  `export MONDAY_API_TOKEN=$(grep '^MONDAY_API_TOKEN=' /Users/<you>/Development/mondo/.env | cut -d= -f2-)`.
  If there's no `.env`, you can only verify via unit tests — say so. See
  CLAUDE.md for the playground IDs (board `5094861043`, workspace `592446`).
- **Verify the token** once with `uv run mondo auth status -o json`.
- **Live mutations are real and visible to others.** Every live check must
  clean up after itself (delete docs/columns/groups/folders it created), and
  you must **spot-check the playground at the end** for leftovers.

## Phase 1 — Triage

1. `gh issue list --state open --limit 100 --json number,title,labels,body`.
   Read every issue body in full (`gh issue view <n>`).
2. For each issue, decide the **fix shape** and the **files it touches**
   (CLI module under `src/mondo/cli/`, `src/mondo/api/queries.py`, the bundled
   skill references under `src/mondo/skill/references/`, tests).
3. **If an issue's feasibility depends on an API fact you don't know** (e.g.
   "does the GraphQL schema support X?"), settle it with a **read-only schema
   introspection** before promising an implementation:
   `uv run mondo graphql '{ __type(name:"SomeInput"){ inputFields{ name } } }'`
   or `{ __schema{ mutationType{ fields{ name } } } }`. (This is how #37 turned
   out to be a real feature — `CreateDocWorkspaceInput.folder_id` exists — not
   the docs-only fallback we'd assumed.)

## Phase 2 — Group and confirm

Group issues into PRs by the **files they touch**:

- Issues touching **disjoint files** → separate PRs, developed in **parallel
  worktrees** (safe, no conflicts).
- Issues touching the **same file(s)** (common for the shared CLI module or
  `references/<area>.md`) → **one PR**, because separate branches off `main`
  would conflict on those files at merge time.

Then **ask the user to confirm the grouping** (use AskUserQuestion) — and in
the same breath surface any feasibility unknown that changes scope. Don't infer
silently. This is one of only two decisions that are genuinely the user's.

## Phase 3 — Implement in worktrees (parallel subagents)

1. Create one worktree + branch per group, off `main`:
   `git worktree add -b <branch> /Users/<you>/Development/mondo-wt/<group> main`.
2. Launch **one implementation subagent per worktree, in a single message** so
   they run concurrently (`Agent`, `general-purpose`). Give each a **precise
   spec** (exact flag names, payload shapes, error/exit-code behaviour) drawn
   from your own reading — don't make the subagent rediscover it. Each subagent must:
   - Work **only** in its assigned worktree path.
   - Follow CLAUDE.md: surgical, minimal, style-matching changes.
   - **Write/update unit tests** and get `uv run --extra dev python -m pytest -m
     "not integration" -q` green.
   - `ruff check` / `ruff format` its changed files.
   - **Live-verify** its feature on the playground with cleanup (skip if no
     `.env`; say so).
   - Commit on its branch (do NOT push, do NOT open a PR). Commit trailer:
     `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
3. When they return, sanity-check each branch: `git log --format=... main..<branch>`,
   `git diff --name-only main..<branch>` — confirm authorship and that file
   scopes are disjoint across branches.

> Subagents can introduce **unrelated regressions** (one corrupted two
> `except (A, B):` clauses into Python-2 syntax outside its task). The review
> phase exists partly to catch this — don't skip it.

## Phase 4 — Review every branch (the quality gate the user asked for)

The review skills operate on the **current branch's diff vs `main`**, so run
them from the **main checkout** on a checked-out branch. A branch checked out in
a worktree can't be checked out in `main`, so first:

```
git worktree remove /Users/<you>/Development/mondo-wt/<group>   # commits are safe on the branch
git checkout <branch>
```

Then, per branch:

1. **`/simplify`** — apply quality cleanups (reuse/simplification/efficiency/
   altitude). Skip findings that change behaviour or reach outside the diff;
   note the skip.
2. **`/code-review`** (effort `high` for non-trivial diffs) — fix real
   correctness bugs. This is where the destructive `doc set` (delete-before-add
   → data loss) got reworked to write-first/delete-after; take its findings
   seriously and **re-verify live** when you change runtime behaviour.
3. **`/security-review`** — for a tiny/docs-only diff with no new data flow,
   a documented direct assessment is proportionate; for anything building
   payloads or touching I/O, run it properly.
4. Re-run the full non-integration suite. Fold the review fixes into the
   branch (`git commit --amend` for a single feature commit; correct the commit
   message if the design changed).

## Phase 5 — Open the PRs

`git push -u origin <branch>` then `gh pr create`.

- **Auto-close gotcha:** GitHub only closes an issue when the closing keyword
  precedes **each** number. `Resolves #33, #34, #35` closes **only #33**.
  Write `Resolves #33, resolves #34, resolves #35` — or close the stragglers
  by hand in Phase 6.
- PR body: per-issue summary, what testing/live-verification was done, and what
  the review skills caught. End with the Claude Code generation line.

## Phase 6 — Land it, then sync docs + release

After the user merges the PRs:

1. **Close any issues that didn't auto-close** (`gh issue close <n> -c "Resolved
   by #<pr> ..."`), and confirm `gh issue list --state open` is empty.
2. `git checkout main && git pull` and re-run the full non-integration suite on
   the merged result.
3. **Documentation/skill sync** (these lag behind a feature merge):
   - Bump the bundled skill version in `src/mondo/skill/SKILL.md`
     (`version:` frontmatter, minor bump) so `_skill_freshness.py` nudges users
     to re-pull the updated `references/`. Convention: bump on any CLI surface
     change.
   - Update `README.md` command blocks for the new commands/flags; fix any
     claim the change made stale.
   - Regenerate `docs/output-contract-matrix`:
     `uv run python scripts/generate_output_contract_matrix.py`. **Heads-up:**
     its generator only discovers `@app.command(...)` **decorators** — commands
     registered via the call form `app.command("x")(fn)` (one handler, two
     names) must be added to `MANUAL_ROWS` in the generator by hand.
   - Ship these doc/skill changes as their own PR for review.
4. **Release** (only after the doc/skill PR is merged): the package version is
   independent of the skill version. **Always confirm the exact new version
   with the user** (state current + proposed bump; pre-1.0 feature work is
   usually a minor bump). Then:
   `bash scripts/release.sh <version>` (runs `uv sync --all-extras` + the test
   suite, commits, tags, pushes — triggering the release workflow). Watch it:
   `gh run watch <id> --exit-status` and confirm the GitHub Release + assets.

## Scope discipline

- Touch only what each issue asks for; mention adjacent problems, don't fix them
  (e.g. `column rename` shares `group rename`'s `--title`-only pattern — note it,
  leave it).
- Prefer the issue's own suggested fix when it's the simplest correct one.
- When you can't verify something (no live token, an API you can't introspect),
  say so explicitly in the PR rather than shipping an unverified claim.
