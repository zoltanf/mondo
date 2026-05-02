---
name: mondo
description: Use when the user wants to do anything against monday.com via the `mondo` CLI — reading or writing workspaces, folders, boards, groups, items, subitems, columns, updates, docs, files, users, teams, webhooks, or when they paste a monday.com URL.
---

# mondo

`mondo` is a power-user CLI for the monday.com GraphQL API (az/gh/gam style).
Invoke via the `mondo` binary on PATH. Authenticate once with `mondo auth login`.

## monday.com object model

- **workspace** holds **folders** and **boards**.
- **board** contains **groups** (sections) and **columns** (typed fields); groups contain **items** (rows).
- **item** has **subitems** and **column values**; column types include `status`, `date`, `people`, `numbers`, `dropdown`, `doc`, `board_relation`, …
- **update** = comment on an item. **doc** = workspace-level rich document (distinct from the `doc` column).
- **user**, **team**, **tag**, **webhook**, **favorite**, **activity**, **validation** — each has its own `mondo <group>`.

URL hint: `/boards/<id>` may be a board **or** a workdoc — `mondo board get` warns when the id is a document and points at `mondo doc get --object-id <id>`.

## Discover, don't guess

- `mondo --help`, `mondo <group> --help`, `mondo <group> <cmd> --help` — flags, args, examples per command.
- `mondo help` lists prose topics; `mondo help <topic>` reads one (e.g. `codecs`, `filters`, `boards-vs-docs`, `batch-operations`, `complexity`).
- `mondo help --dump-spec -o json` — full machine-readable command tree. Prefer this over scraping `--help`.

## Drill-down references

Consult these *before* improvising. Each is a Goal / Command / Output / Gotcha sheet, sourced from the live integration tests so behaviour matches reality.

- `references/boards.md` — create / get / list / duplicate / move / archive / delete.
- `references/groups.md` — create / rename / reorder / archive / delete; selectors with `--name-contains`, `--name-fuzzy`.
- `references/columns.md` — typed columns + read/write column values (status, date, people, numbers, dropdown, …).
- `references/items-and-subitems.md` — items + subitems CRUD, multi-column writes on create, archive vs hard-delete.
- `references/updates.md` — post / reply / edit / like / pin / delete (item comments).
- `references/docs.md` — workspace docs **and** doc-column ops; markdown round-trip; create/append/clear.
- `references/files.md` — upload to file columns, attach to updates, download assets.
- `references/workspaces-and-folders.md` — workspace lookup, folder tree, create / move / delete folders.
- `references/bulk.md` — `--batch` envelopes, `mondo export` / `mondo import` for CSV/XLSX/JSON/Markdown round-trips.
- `references/admin.md` — users, teams, webhooks, tags, activity logs, favorites, notify, validation, complexity.

## Operating norms (every command obeys these)

- **Output format:** auto-JSON when stdout isn't a TTY. Don't set `-o json` in scripts; mondo detects it. Force with `-o json|yaml|tsv|csv`.
- **Project before format** with `-q JMESPATH` (applied before the formatter). Server-side `--filter col=val` (repeatable, AND'ed) beats client-side filtering on large boards.
- **JSON error envelope** on stderr (non-TTY): `{"error": "...", "code": "...", "exit_code": N, "request_id": "...", "retry_in_seconds": N, "suggestion": "..."}`. Branch on `exit_code`, never parse stderr text.
- **Stable exit codes:** 0 ok · 2 usage · 3 auth · 4 rate/complexity (retry after 60s) · 5 validation · 6 not-found · 7 network.
- **Dry-run writes first:** every mutating command takes `--dry-run` (prints GraphQL + variables, sends nothing). Use it when the task is unfamiliar.
- **Batch:** `--batch <file.json>` on bulk operations (`item create`, `column set`, `import board`). Returns a per-row envelope; partial failure → exit 1, full success → exit 0.
- **URLs:** pass `--with-url` on get commands so you can return a clickable monday.com link to the user.
- **Cleanup:** delete commands soft-archive by default; pass `--hard` for true delete.
- **Escape hatch:** `mondo graphql '<query>'` for anything no subcommand wraps.
- **Cache notice:** read commands may emit `cache: hit (entity=…, age=…)` to stderr. Suppress with `MONDO_NO_CACHE_NOTICE=1`. Force refresh with `--no-cache` or `--refresh-cache`.

## When references aren't enough

Fall back to `mondo help <topic>` for prose deep-dives (the bundled topics cover codecs, exit codes, filters, batch operations, complexity, boards-vs-docs, output, auth, profiles, graphql, agent tips, agent workflow, duplicate-and-customize). For the long tail, `mondo help --dump-spec -o json` is the full contract.
