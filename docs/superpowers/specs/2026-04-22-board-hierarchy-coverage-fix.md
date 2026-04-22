# Board hierarchy coverage fix

Date: 2026-04-22
Status: implementation handoff
Scope: board discovery completeness and board hierarchy metadata visibility

## Problem

`mondo board list` and the board directory cache can miss `multi_level`
boards because `boards(...)` is queried without `hierarchy_types`. In the
2026-04 monday API contract, omitting that argument defaults listings to
`classic` boards unless explicit IDs are provided.

## Chosen fix

- Hardcode `hierarchy_types: [classic, multi_level]` in
  `build_boards_list_query()`.
- Add `hierarchy_type` to the board list selection set.
- Add `hierarchy_type` to `BOARD_GET`.
- Leave `hierarchy_type` as a passthrough output field; no rename or
  normalization.

## Cache note

Bump `SCHEMA_VERSION` in `src/mondo/cache/store.py`. Existing `boards.json`
files may be functionally incomplete because they can be missing
`multi_level` boards entirely, so TTL-only refresh is not sufficient.

## Tests to add

- Query-builder coverage in `tests/unit/test_cli_board.py` for
  `hierarchy_types: [classic, multi_level]`.
- Board list/get output coverage in `tests/unit/test_cli_board.py` for
  `hierarchy_type`.
- Cache priming coverage in `tests/unit/test_cache_directory.py` for both the
  fixed query text and preserved `hierarchy_type`.
- Normalization passthrough coverage in `tests/unit/test_normalize.py`.

## Non-goals

- No new CLI flags or hierarchy-type filters.
- No downstream multi-level/subitem behavior changes.
- No cache migration beyond the existing schema-version invalidation path.
