---
name: mondo
description: Use when the user wants to do anything against monday.com via the `mondo` CLI — reading or writing workspaces, folders, boards, groups, items, subitems, columns, updates, docs, files, users, teams, webhooks, or when they paste a monday.com URL.
version: "1.2.0"
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

## Before you run any commands

Read the relevant reference file(s) first — before attempting any command. This is not optional: the references contain the exact flag names, argument order, and gotchas that can't be reliably inferred from `--help` alone (as experience shows, guessing leads to wasted calls and wrong syntax).

Map your task to files:

| Task involves… | Read first |
|---|---|
| boards (list, get, create, archive) | `references/boards.md` |
| items or subitems | `references/items-and-subitems.md` |
| groups | `references/groups.md` |
| column values (read or write) | `references/columns.md` |
| workspace docs or doc columns | `references/docs.md` |
| file uploads / attachments | `references/files.md` |
| workspaces or folders | `references/workspaces-and-folders.md` |
| bulk export / import | `references/bulk.md` |
| users, teams, webhooks, activity | `references/admin.md` |
| item comments / updates | `references/updates.md` |

If a task spans multiple areas (e.g. listing items and reading column values), read both files. Only after reading should you construct and run commands.

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
- **Project before format** with `-q JMESPATH` (applied before the formatter). For the "give me id, name, status" case, `--fields KEY1,KEY2,...` (CSV of keys; dotted paths walk nested dicts) is shorter than the equivalent `-q` projection. Both are global flags surfaced in the "Output / Query" help panel.
- **Filter server-side** with `--filter col=val` (repeatable, AND'ed) instead of paging then JMESPath-filtering. On `item list` specifically, `--group <id>` and `--parent <item-id>` are first-class shortcuts (no need to reach for `--filter group=…` or switch to `subitem list`).
- **JSON error envelope** on stderr (non-TTY): `{"error": "...", "code": "...", "exit_code": N, "request_id": "...", "retry_in_seconds": N, "suggestion": "..."}`. Branch on `exit_code`, never parse stderr text.
- **Stable exit codes:** 0 ok · 2 usage · 3 auth · 4 rate/complexity (retry after 60s) · 5 validation · 6 not-found · 7 network.
- **Dry-run writes first:** every typed mutating command takes `--dry-run` (prints GraphQL + variables, sends nothing). Use it when the task is unfamiliar. Not supported on `mondo graphql` — the raw passthrough refuses `--dry-run` with exit 2 because mondo can't safely preview a query it doesn't parse.
- **Batch:** `--batch <file.json>` on bulk operations (`item create`, `column set`, `import board`). Returns a per-row envelope; partial failure → exit 1, full success → exit 0.
- **URLs:** pass `--with-url` on `board get`, `board list`, `board create`, `item get`, `item create`, `subitem get`, `doc get`, `doc list`, `doc create` to return a clickable monday.com link to the user. On the create commands this is single-call create + URL retrieval (no extra request).
- **Wait for async state changes** with `--poll-until '<jmespath>'` + `--poll-interval` + `--poll-timeout` on `item list`, `item get`, `board get` — replaces hand-rolled bash `until/sleep` loops.
- **Find items by column value** with `mondo item find --board X --column COL --value VAL` (sugar over `item list --filter`, with the same codec dispatch).
- **Inspect a single column's metadata** with `mondo column get-meta --board X --column COL` (returns one column with `settings_str` preserved; `column list` strips it).
- **Cleanup:** delete commands soft-archive by default; pass `--hard` for true delete.
- **Escape hatch:** `mondo graphql '<query>'` for anything no subcommand wraps. **Pass the query as a positional** — `-q/--query` is the global JMESPath projection, not the GraphQL query. If a GraphQL document lands in `--query` anyway, mondo runs it as the query (stderr note) but disables the projection for that call; pass it positionally to combine with `-q`.
- **Cache notice:** read commands may emit `cache: hit (entity=…, age=…)` to stderr. Suppress with `MONDO_NO_CACHE_NOTICE=1`. Force refresh with `--no-cache` or `--refresh-cache` on any cached read (`<entity> list/get` directories plus per-board / per-item / per-doc caches — `item get`, `item list` bare board scope (60s TTL), `subitem list/get`, `update list --item`, `doc get`, `board get`, `webhook list`, `tag list/get`). Filtered `item list` variants, account-wide `update list`, and `mondo graphql` stay live. See `docs/caching.md` for the per-entity TTL table.

## When references aren't enough

Fall back to `mondo help <topic>` for prose deep-dives (the bundled topics cover codecs, exit codes, filters, batch operations, complexity, boards-vs-docs, output, auth, profiles, graphql, agent tips, agent workflow, duplicate-and-customize). For the long tail, `mondo help --dump-spec -o json` is the full contract.
