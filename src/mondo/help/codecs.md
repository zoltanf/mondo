# Column-value codecs

`mondo item create`, `mondo item update`, `mondo column set`, `mondo subitem
create`, and `mondo import board` all accept `--column COL=VAL` pairs. `VAL`
is parsed through a codec registry keyed on the target column's type — so
you rarely need to hand-write monday's column-value JSON.

Pass `--raw-columns` (or `--raw` on `column set`) to skip the codec and send
`VAL` verbatim.

## Writable types

| Column type     | Shorthand VAL                   | Expands to                                       |
|-----------------|---------------------------------|--------------------------------------------------|
| `text`          | `Hello`                         | `"Hello"`                                        |
| `long_text`     | `Hello`                         | `{"text":"Hello"}`                               |
| `numbers`       | `42.5`                          | `"42.5"`                                         |
| `status`        | `Done` or `#1`                  | `{"label":"Done"}` / `{"index":1}`               |
| `date`          | `2026-04-25`                    | `{"date":"2026-04-25"}`                          |
| `date`          | `2026-04-25T10:00`              | `{"date":"…","time":"10:00:00"}`                 |
| `timeline`      | `2026-04-01..2026-04-15`        | `{"from":"…","to":"…"}`                          |
| `week`          | `2026-W16`                      | `{"week":{"startDate":"…","endDate":"…"}}`       |
| `hour`          | `14:30`                         | `{"hour":14,"minute":30}`                        |
| `people`        | `42,51,team:7`                  | `{"personsAndTeams":[…]}`                        |
| `dropdown`      | `Cookie,Cupcake`                | `{"labels":[…]}`                                 |
| `email`         | `a@b.com,"Display"`             | `{"email":"…","text":"…"}`                       |
| `phone`         | `+19175998722,US`               | `{"phone":"…","countryShortName":"US"}`          |
| `link`          | `https://x.com,"click me"`      | `{"url":"…","text":"…"}`                         |
| `location`      | `40.68,-74.04,"NYC"`            | `{"lat":"…","lng":"…","address":"…"}`            |
| `country`       | `US`                            | `{"countryCode":"US","countryName":"…"}`         |
| `checkbox`      | `true` / `false` / `clear`      | `{"checked":"true"}` / `null`                    |
| `rating`        | `4`                             | `{"rating":4}`                                   |
| `tags`          | `urgent,blocked`                | `{"tag_ids":[…]}` (names resolved via `create_or_get_tag`) |
| `board_relation`| `12345,23456`                   | `{"item_ids":[…]}`                               |
| `dependency`    | `12345,23456`                   | `{"item_ids":[…]}`                               |
| `world_clock`   | `Europe/London`                 | `{"timezone":"Europe/London"}`                   |

## Escape hatches

Force raw JSON for one value:

    mondo column set --item 1 --column status --value '{"index":3}' --raw

Skip all codec dispatch on a create:

    mondo item create --board 42 --name "X" \
        --column status='{"index":3}' --raw-columns

When you do `--raw-columns`, the preflight board-columns query is skipped
too — `--dry-run --raw-columns` is fully offline, ideal for reproducing
GraphQL payloads from a CI log.

## Read-only column types

Some types (e.g. `formula`, `mirror`, `auto_number`, `creation_log`,
`last_updated`, `item_id`) cannot be written. Attempting to set one exits
with code 5 (validation error) and a message naming the column.

See also: `mondo help exit-codes`, `mondo help output`.
