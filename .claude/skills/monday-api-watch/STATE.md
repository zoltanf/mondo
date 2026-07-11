# monday API watch — state

**Last checked:** 2026-07-11
**mondo pinned version:** `2026-01` (`DEFAULT_API_VERSION` in `src/mondo/config/loader.py`) — **in maintenance since 2026-07-01**

## Version lifecycle (from live `versions` query, 2026-07-11)

| Version | Status |
|---------|--------|
| 2026-10, 2027-01 | release candidate |
| **2026-07** | **current** |
| 2026-04, 2026-01, 2025-10, 2025-07, 2025-04 | maintenance |
| 2025-01, 2024-10 | deprecated/removed 2026-02-15 |

Rotation: Jan 15 / Apr 1 / Jul 1 / Oct 1. A maintenance version survives
roughly 4 more quarters — expect `2026-01` to be removed around mid-2027.

## Known changes that affect mondo (as of 2026-07)

Verified against baseline schema diffs (`baseline/2026-01.txt` vs
`baseline/2026-07.txt`), not just the docs:

- **`Query.users` args removed on 2026-07** (not merely deprecated):
  `kind`, `newest_first`, `non_active` are gone from the signature.
  Replacements: `user_kind: UserKindFilterInput`, `sort: [UsersSortInput!]`,
  `status: [UserStatus!]`. mondo's `src/mondo/api/queries/users.py` still
  sends `non_active`/`newest_first` → `user list` hard-fails if the pin is
  bumped to 2026-07 without migrating.
- **User fields deprecated on 2026-07, removal targeted 2026-10:**
  `is_admin`/`is_guest`/`is_view_only` → `kind`; `enabled`/`is_pending` →
  `status`; `photo_original`/`photo_thumb`/`photo_thumb_small` →
  `photo_url {...}`; `join_date` → `became_active_at`; `is_verified` →
  `is_email_confirmed`. mondo queries several of these in
  `api/queries/users.py` and `api/queries/me.py`.
- **Scalar changes on 2026-07:** `User.created_at` `Date` → `ISO8601DateTime!`,
  `User.birthday` `Date` → `String`, `User.utc_hours_diff` `Int` → `Float`,
  `users(emails:)` `[String]` → `[String!]`.
- **`Query.users` default limit is now 200** (max 1000) on 2026-07 —
  pagination must be explicit.
- Not mondo-relevant: "Consume AI models through monday" (2026-06-25,
  `run_prompt` + Models API, optional new surface); Platform MCP tool
  additions (2026-06-11, separate transport).

## Canonical sources

- Changelog: <https://developer.monday.com/api-reference/changelog>
  (lazy-loaded, paginated — plain fetch only sees titles/dates; **no RSS feed
  exists**, which is why this skill diffs schema snapshots instead)
- Release notes: <https://developer.monday.com/api-reference/docs/release-notes>
- Versioning schedule: <https://developer.monday.com/api-reference/docs/api-versioning>
- User-entity migration: <https://developer.monday.com/api-reference/docs/migrating-user-entity-to-2026-10>
