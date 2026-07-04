# Mondo — Technical-Debt Reduction Plan

Derived from a deep code review (Codex gpt-5.5, high effort, read-only) with
every High finding independently verified against the code.

**Principle:** every stage is independently mergeable, keeps the CLI surface +
output contract identical (except Stage 7, which is an intentional reliability
improvement), and lands with its own tests. No stage depends on a later one.

## Verified findings (source of the stages)

| # | Sev | Finding | Evidence |
|---|-----|---------|----------|
| 1 | High | Lower layers import CLI code (cache + services reach up into `mondo.cli.*`) | `cache/directory.py:40`; `services/items.py:19-21`, `boards.py:91`, `docs.py:36` |
| 2 | High | `api/queries.py` is a god module (2217 lines) | `api/queries.py:3` |
| 3 | High | `cli/doc.py` does too much (1661 lines) | `cli/doc.py:591`, branches 784–849 |
| 4 | Medium | `GlobalOpts` is a service locator | `cli/context.py:49,56,119,168` |
| 5 | Medium | Live vs. cache list paths duplicate filter/decorate logic | `cli/board.py:287 & 427`, `cli/doc.py:437 & 554`, `cli/workspace.py:141 & 216` |
| 6 | Medium | Cache entity metadata duplicated 3× | `cache/store.py:32`, `cache/config.py:52`, `cli/cache.py:39` |
| 7 | Medium | Decoration hides errors + opens extra clients | `cli/_list_decorate.py:19 & 40` |
| 8 | Medium | File upload bypasses the client reliability path (no retry/network-error handling) | `api/client.py:145` vs `216-220` |
| 9 | Low | Broad `except Exception` masks defects in doc object-id hints | `services/docs.py:201,216` |
| 10 | Low | argv test/comment drift — `--version` *is* reordered but comment says it isn't and never asserts it | `cli/argv.py:35`, `tests/unit/test_argv_reorder.py:93` |
| 11 | Low | Stale skill docs — `doc duplicate`/`rename` tests claimed `xfail` but carry no xfail marks | `src/mondo/skill/references/docs.md:185` |

Tooling notes: `ruff check src tests` passes clean. No coverage tooling exists
(`pyproject.toml` has pytest config but no `pytest-cov`/threshold). Core service
logic is tested only through the CLI surface; `services.{boards,items,docs}`
have no direct unit tests.

---

## Stage 0 — Guardrails (do first, tiny PR)

**Goal:** make the debt measurable so it can't silently regrow.

- Add `pytest-cov` to dev deps in `pyproject.toml`; wire `--cov=mondo` into the pytest config.
- Set a **baseline** threshold at today's number (don't aim high yet — just fail-on-regression).
- Add an import-layering guard (`flake8-tidy-imports` banned-imports or a tiny `tests/unit/test_import_layering.py`) asserting `mondo.cache.*`, `mondo.services.*`, and `mondo.api.*` do **not** import `mondo.cli.*`. It will fail now — mark `xfail`/skip with a reference to Stage 1, then flip it on when Stage 1 lands.

**Verify:** `uv run pytest` green; coverage number recorded in PR description.
**Risk:** none.

---

## Stage 1 — Break upward CLI imports (the keystone) — Finding #1

**Goal:** lower layers stop importing `mondo.cli.*`; services become directly unit-testable.

- Create `mondo/domain/` package.
- Move `cli/_normalize.py` → `domain/normalize.py`. Repoint `cache/directory.py:40`.
- Move the resolvers `services/items.py` reaches up for — `fetch_board_columns` (`_column_cache`), `parse_settings`/`resolve_tag_names_to_ids` (`_columns`), `resolve_by_filters` (`_resolve`) — into `domain/` modules. Leave thin re-export shims in the old `cli/_*` paths if any CLI code still imports them, to keep the diff surgical.
- The `GlobalOpts` type-only imports in services (`boards.py:17`, `docs.py:36`) are `TYPE_CHECKING` hints — replace with a narrow `Protocol` in `domain/` so services no longer name a CLI type even in annotations.
- Flip on the Stage 0 layering test.

**Verify:** layering test green; existing suite green; new direct unit tests for at least one moved resolver.
**Risk:** low (moves + shims). This is the highest-value PR.

---

## Stage 2 — Split `api/queries.py` into a package — Finding #2

**Goal:** kill the 2217-line god module with zero behaviour change.

- `api/queries.py` → `api/queries/` with `items.py`, `boards.py`, `docs.py`, `updates.py`, `workspaces.py`, `me.py`, etc.
- `api/queries/__init__.py` re-exports every existing constant name → **all import sites keep working unchanged** (`from mondo.api.queries import ITEMS_QUERY` still resolves).
- Delete the "the query set is small" comment.

**Verify:** `grep` confirms no remaining import references the old module path directly; suite green.
**Risk:** none (re-exports preserve the public surface).

---

## Stage 3 — `cache/registry.py` single source of truth — Finding #6

**Goal:** entity metadata defined once, not three times.

- New `cache/registry.py`: one record per entity — display name, scope kind, TTL env key, refresh handler.
- Drive `EntityType` (`store.py:32`), the TTL match arms (`config.py:52`), and the CLI enum/grouping/fetcher tables (`cache.py:39`) from the registry.
- Add a drift test: assert the registry, `EntityType`, and CLI table stay in sync.

**Verify:** `cache status`/`clear`/`refresh` output byte-identical before/after; drift test green.
**Risk:** low-medium (touches three files, but each now reads from one table).

---

## Stage 4 — Extract pure list filter/decorate functions — Finding #5

**Goal:** remove the live-vs-cache duplication and make filtering cheaply unit-testable.

- Extract pure functions (no I/O): `filter_boards`, `decorate_boards`, and the doc/workspace equivalents — inputs are plain lists, outputs are plain lists.
- Repoint both the live paths (`board.py:287`, `doc.py:437`, `workspace.py:141`) and cache paths (`board.py:427`, `doc.py:554`, `workspace.py:216`) at them.
- Add parity unit tests: same input → identical output regardless of source.

**Verify:** parity tests green; integration list tests still pass.
**Risk:** low.

---

## Stage 5 — Split `cli/doc.py` — Finding #3

**Goal:** decompose the 1661-line command module.

- `services/docs_fetch.py` (resolve IDs, cache, page fetch), `services/docs_render.py` (MD/MDX/HTML/PDF + image embed/download/write), `cli/doc.py` stays as the thin arg-parse/dispatch layer.
- Keep the `mondo doc *` command surface and output identical.

**Verify:** live doc suite (`test_live_doc_*`) green; markdown golden round-trip unchanged.
**Risk:** medium — largest move; do it *after* Stage 1 so the render/fetch code has a clean domain layer to sit in.

---

## Stage 6 — Decompose `GlobalOpts` — Finding #4

**Goal:** stop the service-locator pattern.

- Separate three concerns currently fused in `cli/context.py`: config loading, output rendering, and client/cache factories.
- Pass explicit `client`/`cache` factory dependencies into services instead of handing them the whole `GlobalOpts`.

**Verify:** suite green; no service references `GlobalOpts` directly (extend the Stage 1 layering test).
**Risk:** medium (broad but mechanical). Sequenced late because Stages 1/4/5 already peel responsibilities away from it.

---

## Stage 7 — Route uploads through shared reliability plumbing — Finding #8 *(only functional change)*

**Goal:** `upload_file()` gets the same retry + network-error classification as `execute()`.

- Factor the retry/backoff/`_classify_response` loop from `client.py:145` into a shared helper; have `upload_file()` (`client.py:216`) use it so `httpx.TimeoutException`/`TransportError` become retryable `NetworkError`s instead of raw exceptions.
- Add unit tests: timeout → retried; transport error → `NetworkError`; success after retry.

**Verify:** new tests green; `test_live_files.py` upload round-trip still passes.
**Risk:** medium — real behaviour change (uploads now retry). Ship alone so it's easy to bisect.

---

## Stage 8 — Cleanups (single small PR) — Findings #7, #9, #10, #11

- #7: make decoration error policy explicit (`_list_decorate.py:19,40`) and reuse the command's existing client instead of opening a new one.
- #9: narrow `except Exception` → `(MondoError, TypeError, ValueError)` in `services/docs.py:201,216`.
- #10: fix the misleading comment and add the missing `--version` reorder assertion in `tests/unit/test_argv_reorder.py:93`.
- #11: update the stale `xfail` note in `src/mondo/skill/references/docs.md:185`.

**Verify:** suite green.
**Risk:** low.

---

## Sequencing summary

```
Stage 0 (guardrails) ─┐
Stage 1 (imports) ────┼─► unlocks direct service tests + layering guard
Stage 2 (queries) ────┤   (independent, can parallel Stage 1)
Stage 3 (registry) ───┤   (independent)
Stage 4 (filters) ────┘
Stage 5 (doc.py split)   ← after Stage 1
Stage 6 (GlobalOpts)     ← after 1/4/5
Stage 7 (upload retry)   ← standalone, functional
Stage 8 (cleanups)       ← anytime
```

**Fastest debt reduction for least risk:** Stages 0 → 1 → 2 in that order.
Stage 1 is the one structural change that pays off everywhere else.
