"""Single source of truth for command examples.

Each entry maps a dotted command path (`"item create"`, `"graphql"`) to a list
of `Example` records. The registry is consumed in two places:

- `epilog_for(path)` formats examples for Typer's per-command `--help` epilog.
- `mondo help --dump-spec` emits the raw registry alongside the rest of the
  command tree so agents get a machine-readable contract.

Keep one example per common idiom, not one per flag. Four is usually plenty.
Every example's command string MUST start with `"mondo "` so agents can copy
them verbatim — tests enforce this.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Example:
    description: str
    command: str


EXAMPLES: dict[str, list[Example]] = {
    # --- top-level ---------------------------------------------------------
    "me": [
        Example("Show the authenticated user, team memberships, and account", "mondo me"),
        Example("Extract just the user id", "mondo me -q id -o none"),
    ],
    "account": [
        Example("Show account tier, plan, and active-member count", "mondo account"),
    ],
    "schema": [
        Example(
            "List GraphQL fields each read command selects",
            "mondo schema",
        ),
        Example(
            "Just the board commands",
            "mondo schema board",
        ),
        Example(
            "Project to the `get` field list for an item",
            "mondo schema item -q get",
        ),
    ],
    "graphql": [
        Example(
            "Inline query",
            "mondo graphql 'query { me { id name } }'",
        ),
        Example(
            "Query with variables",
            "mondo graphql 'query ($ids:[ID!]!){items(ids:$ids){id name}}' "
            "--vars '{\"ids\":[1,2]}'",
        ),
        Example("Read a query from file", "mondo graphql @query.graphql"),
        Example(
            "Pipe a mutation through stdin",
            "cat mutation.graphql | mondo graphql -",
        ),
    ],
    # --- auth --------------------------------------------------------------
    "auth whoami": [
        Example("Print just the user + account", "mondo auth whoami"),
    ],
    "auth status": [
        Example(
            "Full identity + where the token was resolved from",
            "mondo auth status",
        ),
    ],
    "auth login": [
        Example(
            "Prompt for token, store in the OS keyring",
            "mondo auth login",
        ),
    ],
    "auth logout": [
        Example("Remove the stored keyring entry", "mondo auth logout"),
    ],
    # --- cache -------------------------------------------------------------
    "cache status": [
        Example("Age and entry counts for every cache file", "mondo cache status"),
        Example("Just the boards cache", "mondo cache status boards"),
        Example("Machine-readable output", "mondo cache status -o json"),
    ],
    "cache refresh": [
        Example("Force-refresh every cached entity type", "mondo cache refresh"),
        Example("Refresh just the users directory", "mondo cache refresh users"),
    ],
    "cache clear": [
        Example("Delete every cache file (idempotent)", "mondo cache clear"),
        Example("Clear the workspaces cache only", "mondo cache clear workspaces"),
    ],
    # --- board -------------------------------------------------------------
    "board list": [
        Example("First page of active boards (served from cache when fresh)", "mondo board list"),
        Example(
            "Filter by name (client-side) and cap the walk",
            "mondo board list --name-contains pager --max-items 500",
        ),
        Example(
            "Archived boards in a specific workspace",
            "mondo board list --state archived --workspace 42",
        ),
        Example(
            "Regex-match names, most-recently-used first",
            "mondo board list --name-matches '^team-\\w+$' --order-by used_at",
        ),
        Example(
            "Fuzzy name search — tolerates typos",
            'mondo board list --name-fuzzy "prodct launc" --fuzzy-score --max-items 5',
        ),
        Example("Bypass local cache for this call", "mondo board list --no-cache"),
        Example("Force-refresh the cache before serving", "mondo board list --refresh-cache"),
        Example(
            "Include a monday URL on every row",
            "mondo board list --with-url --max-items 3",
        ),
        Example(
            "Inspect the shared core shape (matches `doc list`)",
            "mondo board list --max-items 1 -q '.[0] | keys'",
        ),
    ],
    "board get": [
        Example("Fetch by id", "mondo board get --id 1234567890"),
        Example("Positional id", "mondo board get 1234567890"),
        Example(
            "Paste a monday URL (works for boards and workdocs)",
            "mondo board get https://marktguru.monday.com/boards/1234567890",
        ),
        Example(
            "Include the round-trip URL in the payload",
            "mondo board get 1234567890 --with-url -q url -o none",
        ),
        Example(
            "If `type` comes back `document`, switch to `mondo doc get`",
            "mondo board get 1234567890 -q type -o none",
        ),
    ],
    "board create": [
        Example(
            "Minimal create",
            'mondo board create --name "Roadmap" --kind public',
        ),
        Example(
            "Create inside a workspace with owner + subscriber",
            'mondo board create --name "Roadmap" --kind public --workspace 42 '
            "--owner 7 --subscriber 8",
        ),
        Example(
            "Create an empty board (no starter items/groups)",
            'mondo board create --name "Scratch" --kind public --empty',
        ),
        Example(
            "Seed item naming and generation with newer board inputs",
            'mondo board create --name "Launch plan" --kind public '
            '--item-nickname \'{"preset_type":"item"}\' --prompt "Build a launch tracker"',
        ),
    ],
    "board update": [
        Example(
            "Rename",
            'mondo board update --id 1234567890 --attribute name --value "Renamed"',
        ),
        Example(
            "Update the description",
            'mondo board update --id 1234567890 --attribute description --value "Q2 plan"',
        ),
    ],
    "board set-permission": [
        Example(
            "Make the board read-only by default",
            "mondo board set-permission --id 1234567890 --role viewer",
        ),
    ],
    "board move": [
        Example(
            "Move a board into another workspace and folder",
            "mondo board move --id 1234567890 --workspace 42 --folder 7",
        ),
        Example(
            "Reposition a board relative to another overview object",
            'mondo board move --id 1234567890 --position '
            '\'{"object_id":15,"object_type":"Overview","is_after":true}\'',
        ),
    ],
    "board archive": [
        Example(
            "Reversible archive (30-day monday retention)",
            "mondo board archive --id 1234567890 --yes",
        ),
    ],
    "board delete": [
        Example(
            "Permanent delete (both --hard and --yes required)",
            "mondo board delete --id 1234567890 --hard --yes",
        ),
    ],
    "board duplicate": [
        Example(
            "Duplicate a board including its pulses + updates",
            "mondo board duplicate 1234567890 --type duplicate_board_with_pulses_and_updates",
        ),
        Example(
            "Duplicate into a specific workspace, keep subscribers",
            "mondo board duplicate 1234567890 "
            "--type duplicate_board_with_structure "
            '--name "Copy" --workspace 42 --keep-subscribers',
        ),
        Example(
            "Block until the copy is fully populated (5 min timeout)",
            "mondo board duplicate 1234567890 --wait --timeout 300",
        ),
    ],
    # --- item --------------------------------------------------------------
    "item list": [
        Example(
            "List the first page of items on a board",
            "mondo item list --board 1234567890",
        ),
        Example(
            "Paginate through everything, capped at 500",
            "mondo item list --board 1234567890 --max-items 500",
        ),
        Example(
            "Filter server-side by a status column",
            "mondo item list --board 1234567890 --filter status=Done",
        ),
        Example(
            "Filter + sort + project as JSON",
            "mondo item list --board 1234567890 --filter status!=Stuck "
            "--order-by date4,desc -o json -q '[].{id:id,name:name}'",
        ),
    ],
    "item get": [
        Example("Fetch one item", "mondo item get --id 987"),
        Example(
            "Paste a monday /pulses/ URL",
            "mondo item get https://marktguru.monday.com/boards/42/pulses/987",
        ),
        Example(
            "Include the canonical url in the payload",
            "mondo item get 987 --with-url -q url -o none",
        ),
        Example(
            "Include its update thread (comments)",
            "mondo item get --id 987 --include-updates",
        ),
        Example(
            "Include subitems instead",
            "mondo item get --id 987 --include-subitems",
        ),
    ],
    "item create": [
        Example(
            "Minimal create in the default group",
            'mondo item create --board 1234567890 --name "Fix CI"',
        ),
        Example(
            "Codec-parsed columns (status / people / date / tags)",
            'mondo item create --board 1234567890 --name "Fix CI" '
            "--column status=Working --column owner=42 "
            "--column due=2026-04-25 --column tags=urgent,blocked",
        ),
        Example(
            "Raw JSON escape hatch for a single column",
            'mondo item create --board 1234567890 --name "X" '
            "--column status='{\"index\":3}' --raw-columns",
        ),
        Example(
            "Dry-run to preview the GraphQL without sending it",
            'mondo --dry-run item create --board 1234567890 --name "Fix CI"',
        ),
    ],
    "item rename": [
        Example(
            "Rename an item",
            'mondo item rename --id 987 --board 1234567890 --name "New title"',
        ),
    ],
    "item duplicate": [
        Example(
            "Duplicate in place",
            "mondo item duplicate --id 987 --board 1234567890",
        ),
        Example(
            "Duplicate with its update thread",
            "mondo item duplicate --id 987 --board 1234567890 --with-updates",
        ),
    ],
    "item archive": [
        Example(
            "Archive (reversible via monday UI for 30 days)",
            "mondo item archive --id 987 --yes",
        ),
    ],
    "item delete": [
        Example(
            "Permanently delete (both --hard and --yes required)",
            "mondo item delete --id 987 --hard --yes",
        ),
    ],
    "item move": [
        Example(
            "Move to another group on the same board",
            "mondo item move --id 987 --group topics_two",
        ),
    ],
    "item move-to-board": [
        Example(
            "Move to a board whose schema matches the source",
            "mondo item move-to-board --id 987 --to-board 2345 --to-group topics",
        ),
        Example(
            "Remap columns where the schemas differ; drop one with empty target",
            "mondo item move-to-board --id 987 --to-board 2345 --to-group topics "
            "--column-mapping status=state --column-mapping date4=due "
            "--column-mapping notes=",
        ),
    ],
    # --- subitem -----------------------------------------------------------
    "subitem list": [
        Example("List subitems of a parent", "mondo subitem list --parent 1234567890"),
    ],
    "subitem get": [
        Example("Fetch one subitem", "mondo subitem get --id 9876543210"),
        Example(
            "Paste a monday /pulses/ URL",
            "mondo subitem get https://marktguru.monday.com/boards/999/pulses/9876543210",
        ),
        Example(
            "Include the canonical url",
            "mondo subitem get 9876543210 --with-url -q url -o none",
        ),
    ],
    "subitem create": [
        Example(
            "Create a subitem under a parent",
            'mondo subitem create --parent 1234567890 --name "Sub task"',
        ),
        Example(
            "With codec dispatch (pass the subitems-board id)",
            'mondo subitem create --parent 1234567890 --name "Sub task" '
            "--subitems-board 999 --column status9=Done",
        ),
        Example(
            "Auto-create missing status/dropdown labels",
            'mondo subitem create --parent 1234567890 --name "Sub task" '
            "--subitems-board 999 --column status9=NewLabel "
            "--create-labels-if-missing",
        ),
    ],
    "subitem rename": [
        Example(
            "Rename — subitems need both --id and --board (the subitems board)",
            'mondo subitem rename --id 9876 --board 999 --name "New title"',
        ),
    ],
    "subitem move": [
        Example(
            "Move to a different group on the subitems board",
            "mondo subitem move --id 9876 --group subitems_of_1234567890",
        ),
    ],
    "subitem archive": [
        Example("Archive", "mondo subitem archive --id 9876 --yes"),
    ],
    "subitem delete": [
        Example("Permanent delete", "mondo subitem delete --id 9876 --hard --yes"),
    ],
    # --- update (item comments) --------------------------------------------
    "update list": [
        Example("Account-wide, paginated", "mondo update list"),
        Example(
            "Just one item's updates, up to 50",
            "mondo update list --item 1234567890 --max-items 50",
        ),
        Example(
            "Find the most-recently-posted update on an item",
            "mondo update list --item 1234567890 -q 'reverse(sort_by([*],&created_at))[0]'",
        ),
    ],
    "update get": [
        Example("Fetch a single update", "mondo update get --id 555"),
    ],
    "update create": [
        Example(
            "Post a new update (markdown is the default)",
            'mondo update create --item 1234567890 --body "**Done**: audit passed"',
        ),
        Example(
            "Post from a markdown file",
            "mondo update create --item 1234567890 --from-file note.md",
        ),
        Example(
            "Send raw HTML verbatim (e.g. to preserve <mention> tags)",
            'mondo update create --item 1234567890 --body "<p>Hi <mention user=42>Sam</mention></p>" --html',
        ),
    ],
    "update reply": [
        Example(
            "Reply to an existing update (markdown is the default)",
            'mondo update reply --parent 555 --body "thanks, **merged**"',
        ),
        Example(
            "Reply with raw HTML",
            'mondo update reply --parent 555 --body "<p>re</p>" --html',
        ),
    ],
    "update edit": [
        Example(
            "Edit an update's body (markdown is the default)",
            'mondo update edit 555 --body "## Revised\n- fixed typo"',
        ),
        Example(
            "Edit with raw HTML",
            'mondo update edit 555 --body "<p>new body</p>" --html',
        ),
    ],
    "update delete": [
        Example("Delete an update", "mondo update delete --id 555 --yes"),
    ],
    "update like": [
        Example("Like an update", "mondo update like --id 555"),
    ],
    "update unlike": [
        Example("Remove your like", "mondo update unlike --id 555"),
    ],
    "update pin": [
        Example("Pin to the item", "mondo update pin --id 555 --item 1234567890"),
    ],
    "update unpin": [
        Example("Unpin", "mondo update unpin --id 555 --item 1234567890"),
    ],
    "update clear": [
        Example(
            "Nuke every update on an item (destructive)",
            "mondo update clear --item 1234567890 --yes",
        ),
    ],
    # --- workspace docs ----------------------------------------------------
    "doc list": [
        Example("Default workspace", "mondo doc list"),
        Example(
            "In a specific workspace, capped at 500",
            "mondo doc list --workspace 42 --max-items 500",
        ),
        Example(
            "Lookup by the URL-visible object id",
            "mondo doc list --object-id 77",
        ),
        Example(
            "Filter by name (client-side substring)",
            "mondo doc list --name-contains spec",
        ),
        Example(
            "Regex-match names, most-recently-used first",
            "mondo doc list --name-matches '^rfc-\\d+$' --order-by used_at",
        ),
        Example(
            "Fuzzy name search — tolerates typos",
            'mondo doc list --name-fuzzy "prodct launc" --fuzzy-score --max-items 5',
        ),
        Example(
            "Private docs only",
            "mondo doc list --kind private",
        ),
        Example(
            "Include `url` / `relative_url` on every row (opt-in)",
            "mondo doc list --with-url --max-items 3",
        ),
        Example(
            "Inspect the shared core shape (matches `board list`)",
            "mondo doc list --max-items 1 -q '.[0] | keys'",
        ),
    ],
    "doc get": [
        Example("By internal id", "mondo doc get --id 7"),
        Example(
            "By the URL-visible id (what `/boards/<id>` shows)",
            "mondo doc get --object-id 77",
        ),
        Example(
            "Paste the monday URL directly",
            "mondo doc get --object-id https://marktguru.monday.com/boards/77",
        ),
        Example(
            "Render the block tree as markdown",
            "mondo doc get --id 7 --format markdown",
        ),
    ],
    "doc create": [
        Example(
            "Create a public doc in a workspace",
            'mondo doc create --workspace 42 --name "Spec" --kind public',
        ),
    ],
    "doc add-content": [
        Example(
            "Bulk-append a markdown file as blocks",
            "mondo doc add-content --doc 7 --from-file spec.md",
        ),
    ],
    "doc add-markdown": [
        Example(
            "Append markdown using monday's server-side parser",
            'mondo doc add-markdown --doc 7 --markdown "# Title\\n\\nBody"',
        ),
    ],
    "doc import-html": [
        Example(
            "Create a doc from HTML",
            'mondo doc import-html --workspace 42 --html "<h1>Spec</h1><p>Body</p>" --title "Imported"',
        ),
    ],
    "doc add-block": [
        Example(
            "Append one paragraph",
            "mondo doc add-block --doc 7 --type normal_text "
            '--content \'{"deltaFormat":[{"insert":"hi"}]}\'',
        ),
        Example(
            "Insert after a specific block",
            "mondo doc add-block --doc 7 --type normal_text "
            '--content \'{"deltaFormat":[{"insert":"hi"}]}\' '
            "--after <block-id>",
        ),
    ],
    "doc update-block": [
        Example(
            "Replace a block's content",
            "mondo doc update-block --id <block-id> "
            '--content \'{"deltaFormat":[{"insert":"new"}]}\'',
        ),
    ],
    "doc delete-block": [
        Example("Delete one block", "mondo doc delete-block --id <block-id>"),
    ],
    "doc rename": [
        Example("Rename a doc", 'mondo doc rename --doc 7 --name "New name"'),
    ],
    "doc duplicate": [
        Example(
            "Duplicate content and updates",
            "mondo doc duplicate --doc 7 --duplicate-type duplicate_doc_with_content_and_updates",
        ),
    ],
    "doc delete": [
        Example("Delete a doc", "mondo doc delete --doc 7"),
    ],
    "doc export-markdown": [
        Example("Export the whole doc as markdown", "mondo doc export-markdown --doc 7"),
        Example(
            "Export specific blocks only",
            "mondo doc export-markdown --doc 7 --block <block-1> --block <block-2> --raw",
        ),
    ],
    "doc version-history": [
        Example(
            "List restoring points since a date (API 2026-04+)",
            'mondo doc version-history --doc 7 --since "2026-01-01T00:00:00Z"',
        ),
    ],
    "doc version-diff": [
        Example(
            "Diff two restoring points (API 2026-04+)",
            'mondo doc version-diff --doc 7 --date "2026-01-08T10:24:02.469Z" --prev-date "2026-01-08T09:00:00Z"',
        ),
    ],
    # --- webhook -----------------------------------------------------------
    "webhook list": [
        Example(
            "Every webhook on a board",
            "mondo webhook list --board 1234567890",
        ),
        Example(
            "Only webhooks registered by the current app",
            "mondo webhook list --board 1234567890 --app-only",
        ),
    ],
    "webhook create": [
        Example(
            "On create_item (most common)",
            "mondo webhook create --board 1234567890 "
            "--url https://example.com/hook --event create_item",
        ),
        Example(
            "Watch a specific column for status changes",
            "mondo webhook create --board 1234567890 "
            "--url https://example.com/hook "
            "--event change_specific_column_value "
            '--config \'{"columnId":"status"}\'',
        ),
    ],
    "webhook delete": [
        Example("Remove a webhook", "mondo webhook delete --id 123 --yes"),
    ],
    # --- file --------------------------------------------------------------
    "file upload": [
        Example(
            "Attach to a file column on an item",
            "mondo file upload --file report.pdf --item 1234567890 --column files",
        ),
        Example(
            "Attach to an update thread",
            "mondo file upload --file shot.png --target update --update 555",
        ),
    ],
    "file download": [
        Example(
            "Download to ./<asset_name>",
            "mondo file download --asset 42",
        ),
        Example(
            "Download to a specific path",
            "mondo file download --asset 42 --out /tmp/x.pdf",
        ),
    ],
    # --- folder ------------------------------------------------------------
    "folder list": [
        Example("Across every workspace", "mondo folder list"),
        Example("In one workspace", "mondo folder list --workspace 42"),
    ],
    "folder tree": [
        Example("ASCII tree of all folders, grouped by workspace", "mondo folder tree"),
        Example("Restrict to one workspace", "mondo folder tree --workspace 42"),
        Example("Structured JSON tree", "mondo folder tree -o json"),
        Example("Bypass local cache", "mondo folder tree --no-cache"),
    ],
    "folder get": [
        Example("One folder", "mondo folder get --id 7"),
    ],
    "folder create": [
        Example(
            "Top-level folder in a workspace",
            'mondo folder create --workspace 42 --name "Eng"',
        ),
        Example(
            "Nested under a parent folder",
            'mondo folder create --workspace 42 --name "Eng" --color DONE_GREEN --parent 3',
        ),
    ],
    "folder update": [
        Example(
            "Rename",
            'mondo folder update --id 7 --name "Renamed"',
        ),
        Example(
            "Re-order relative to a sibling",
            "mondo folder update --id 7 "
            '--position \'{"object_id":8,"object_type":"Folder","is_after":true}\'',
        ),
    ],
    "folder delete": [
        Example(
            "Delete (archives contained boards)",
            "mondo folder delete --id 7 --hard --yes",
        ),
    ],
    # --- tag ---------------------------------------------------------------
    "tag list": [
        Example("Every account-level tag", "mondo tag list"),
        Example(
            "Specific tag ids",
            "mondo tag list --id 123 --id 456",
        ),
    ],
    "tag get": [
        Example("One tag", "mondo tag get --id 123"),
    ],
    "tag create-or-get": [
        Example(
            "Idempotent — returns existing or creates new",
            "mondo tag create-or-get --name urgent --board 1234567890",
        ),
    ],
    # --- favorite ----------------------------------------------------------
    "favorite list": [
        Example(
            "Boards/dashboards/workspaces/docs the current user favorited",
            "mondo favorite list",
        ),
    ],
    # --- activity ----------------------------------------------------------
    "activity board": [
        Example(
            "Last week of activity (retention is ~7 days on non-Enterprise)",
            "mondo activity board --board 1234567890",
        ),
        Example(
            "Time-bounded + user-filtered",
            "mondo activity board --board 1234567890 "
            "--since 2026-04-01T00:00:00Z --until 2026-04-18T23:59:59Z "
            "--user 42",
        ),
        Example(
            "Narrowed to one item + column",
            "mondo activity board --board 1234567890 --item 100 --column status --max-items 1000",
        ),
    ],
    # --- notify ------------------------------------------------------------
    "notify send": [
        Example(
            "Notify one user about an item or board",
            'mondo notify send --user 42 --target 100 --target-type Project --text "FYI"',
        ),
        Example(
            "Notify about an update/reply (internal = no email)",
            'mondo notify send --user 42 --target 555 --target-type Post --text "reply" --internal',
        ),
    ],
    # --- aggregate ---------------------------------------------------------
    "aggregate board": [
        Example(
            "Total item count on a board",
            "mondo aggregate board --board 1234567890 --select COUNT:*",
        ),
        Example(
            "Count + SUM grouped by status",
            "mondo aggregate board --board 1234567890 --group-by status "
            "--select COUNT:* --select SUM:price",
        ),
        Example(
            "Filter + aggregate",
            "mondo aggregate board --board 1234567890 --group-by owner "
            "--select AVERAGE:duration "
            '--filter \'{"rules":[{"column_id":"status",'
            '"operator":"any_of","compare_value":["Done"]}]}\'',
        ),
    ],
    # --- validation --------------------------------------------------------
    "validation list": [
        Example(
            "Every rule on a board",
            "mondo validation list --board 1234567890",
        ),
    ],
    "validation create": [
        Example(
            "Require a value in a column",
            "mondo validation create --board 1234567890 --column status --rule-type REQUIRED",
        ),
        Example(
            "Constrain a number column to a minimum",
            "mondo validation create --board 1234567890 --column numbers "
            "--rule-type MIN_VALUE --value '{\"min\":10}' "
            '--description "Non-zero price"',
        ),
    ],
    "validation update": [
        Example(
            "Update a rule's description",
            'mondo validation update --id 1 --description "Updated"',
        ),
    ],
    "validation delete": [
        Example("Delete a rule", "mondo validation delete --id 1 --yes"),
    ],
    # --- group -------------------------------------------------------------
    "group list": [
        Example(
            "Every group on a board",
            "mondo group list --board 1234567890",
        ),
    ],
    "group create": [
        Example(
            "Add a group at the top",
            'mondo group create --board 1234567890 --name "Planning"',
        ),
        Example(
            "Insert after an existing group with a specific color",
            'mondo group create --board 1234567890 --name "Planning" '
            '--color "#00c875" --relative-to topics '
            "--position-relative-method after_at",
        ),
    ],
    "group rename": [
        Example(
            "Rename a group",
            'mondo group rename --board 1234567890 --id topics --title "Workstreams"',
        ),
    ],
    "group update": [
        Example(
            "Change a group's color",
            'mondo group update --board 1234567890 --id topics --attribute color --value "#ff007f"',
        ),
    ],
    "group reorder": [
        Example(
            "Move a group after another",
            "mondo group reorder --board 1234567890 --id topics --after g2",
        ),
        Example(
            "Or to an absolute position",
            "mondo group reorder --board 1234567890 --id topics --position 3",
        ),
    ],
    "group duplicate": [
        Example(
            "Duplicate, adding the copy to the top",
            'mondo group duplicate --board 1234567890 --id topics --title "Topics 2" --add-to-top',
        ),
    ],
    "group archive": [
        Example(
            "Archive (last remaining group cannot be archived)",
            "mondo group archive --board 1234567890 --id topics --yes",
        ),
    ],
    "group delete": [
        Example(
            "Delete (cascades to items — last group cannot be deleted)",
            "mondo group delete --board 1234567890 --id topics --hard --yes",
        ),
    ],
    # --- column ------------------------------------------------------------
    "column list": [
        Example(
            "Every column definition on a board",
            "mondo column list 1234567890",
        ),
        Example(
            "Flag form (still works for scripts)",
            "mondo column list --board 1234567890",
        ),
    ],
    "column labels": [
        Example(
            "List status labels with their indices",
            "mondo column labels 1234567890 --column status",
        ),
        Example(
            "List dropdown labels with their ids",
            "mondo column labels 1234567890 --column dropdown_mkrnym4p",
        ),
    ],
    "column get": [
        Example(
            "Codec-rendered display value",
            "mondo column get --item 987 --column status",
        ),
        Example(
            "Raw server payload (id/type/value/text)",
            "mondo column get --item 987 --column status --raw",
        ),
    ],
    "column set": [
        Example(
            "Status by label",
            "mondo column set --item 987 --column status --value Done",
        ),
        Example(
            "Tags by name (auto-resolves via create_or_get_tag)",
            "mondo column set --item 987 --column tags --value urgent,blocked",
        ),
        Example(
            "Raw JSON escape hatch",
            "mondo column set --item 987 --column status --value '{\"index\":3}' --raw",
        ),
    ],
    "column set-many": [
        Example(
            "Write multiple columns in one call",
            "mondo column set-many --item 987 "
            '--values \'{"text":"Hi","due":{"date":"2026-04-25"}}\'',
        ),
    ],
    "column clear": [
        Example(
            "Reset a column to empty",
            "mondo column clear --item 987 --column status",
        ),
    ],
    "column create": [
        Example(
            "Add a status column with initial labels",
            'mondo column create --board 1234567890 --title "Priority" '
            "--type status "
            '--defaults \'{"labels":{"1":"High","2":"Medium"}}\'',
        ),
        Example(
            "Insert after a specific column, pin the id",
            'mondo column create --board 1234567890 --title "Priority" '
            "--type status --id priority --after status "
            '--description "ticket priority"',
        ),
    ],
    "column rename": [
        Example(
            "Rename a column by id",
            'mondo column rename --board 1234567890 --id status --title "Workflow"',
        ),
    ],
    "column change-metadata": [
        Example(
            "Update a column's description",
            "mondo column change-metadata --board 1234567890 --id status "
            '--property description --value "Current workflow state"',
        ),
    ],
    "column delete": [
        Example(
            "Permanently delete a column (and its data)",
            "mondo column delete --board 1234567890 --id status --yes",
        ),
    ],
    # --- column doc --------------------------------------------------------
    "column doc get": [
        Example(
            "Rendered as markdown",
            "mondo column doc get --item 987 --column spec",
        ),
        Example(
            "Raw block JSON",
            "mondo column doc get --item 987 --column spec --format raw-blocks",
        ),
    ],
    "column doc set": [
        Example(
            "Create-or-append a doc column from a markdown file",
            "mondo column doc set --item 987 --column spec --from-file spec.md",
        ),
    ],
    "column doc append": [
        Example(
            "Append an inline markdown fragment",
            'mondo column doc append --item 987 --column spec --markdown "- new bullet"',
        ),
    ],
    "column doc clear": [
        Example(
            "Unlink the doc from the item (keeps the underlying workspace doc)",
            "mondo column doc clear --item 987 --column spec",
        ),
    ],
    # --- workspace ---------------------------------------------------------
    "workspace list": [
        Example("All workspaces (served from cache when fresh)", "mondo workspace list"),
        Example(
            "Only open workspaces, active state",
            "mondo workspace list --kind open --state active",
        ),
        Example(
            "Fuzzy name search",
            'mondo workspace list --name-fuzzy "marketng"',
        ),
        Example("Bypass local cache", "mondo workspace list --no-cache"),
    ],
    "workspace get": [
        Example("One workspace", "mondo workspace get --id 7"),
    ],
    "workspace create": [
        Example(
            "Create an open workspace",
            'mondo workspace create --name "Engineering" --kind open',
        ),
        Example(
            "Closed workspace tied to a product",
            'mondo workspace create --name "Secure" --kind closed '
            '--description "..." --product-id 3',
        ),
    ],
    "workspace update": [
        Example(
            "Rename + convert to closed",
            'mondo workspace update --id 7 --name "Eng" --kind closed',
        ),
    ],
    "workspace delete": [
        Example(
            "Permanently delete a workspace",
            "mondo workspace delete --id 7 --hard --yes",
        ),
    ],
    "workspace add-user": [
        Example(
            "Add users as subscribers",
            "mondo workspace add-user --id 7 --user 42 --user 43",
        ),
        Example(
            "Promote to owner",
            "mondo workspace add-user --id 7 --user 42 --kind owner",
        ),
    ],
    "workspace remove-user": [
        Example(
            "Remove a user from a workspace",
            "mondo workspace remove-user --id 7 --user 42",
        ),
    ],
    "workspace add-team": [
        Example(
            "Add teams as subscribers",
            "mondo workspace add-team --id 7 --team 11 --team 12",
        ),
    ],
    "workspace remove-team": [
        Example(
            "Remove a team",
            "mondo workspace remove-team --id 7 --team 11",
        ),
    ],
    # --- user --------------------------------------------------------------
    "user list": [
        Example("All non-guest users (served from cache when fresh)", "mondo user list --kind non_guests"),
        Example(
            "Search by email (case-sensitive per monday)",
            "mondo user list --email a@example.com",
        ),
        Example(
            "Deactivated users only",
            "mondo user list --include-deactivated --limit 100",
        ),
        Example(
            "Fuzzy name search",
            'mondo user list --name-fuzzy "jon smth" --fuzzy-score --max-items 3',
        ),
        Example("Force-refresh the cache", "mondo user list --refresh-cache"),
    ],
    "user get": [
        Example("One user", "mondo user get --id 42"),
    ],
    "user deactivate": [
        Example(
            "Mass-deactivate (returns successful_users + failed_users)",
            "mondo user deactivate --user 1 --user 2 --yes",
        ),
    ],
    "user activate": [
        Example(
            "Reactivate users",
            "mondo user activate --user 1 --user 2",
        ),
    ],
    "user update-role": [
        Example(
            "Promote to admin",
            "mondo user update-role --user 1 --role admin",
        ),
        Example(
            "Demote to viewer",
            "mondo user update-role --user 1 --role viewer",
        ),
    ],
    "user add-to-team": [
        Example(
            "Add users to a team",
            "mondo user add-to-team --team 7 --user 1 --user 2",
        ),
    ],
    "user remove-from-team": [
        Example(
            "Remove a user from a team",
            "mondo user remove-from-team --team 7 --user 1",
        ),
    ],
    # --- team --------------------------------------------------------------
    "team list": [
        Example("All teams (served from cache when fresh)", "mondo team list"),
        Example("Specific teams (bypasses cache)", "mondo team list --id 1 --id 2"),
        Example(
            "Fuzzy name search",
            'mondo team list --name-fuzzy "platfrm"',
        ),
    ],
    "team get": [
        Example("One team", "mondo team get --id 7"),
    ],
    "team create": [
        Example(
            "Create a team with initial subscribers",
            'mondo team create --name "Platform" --subscriber 1 --subscriber 2',
        ),
        Example(
            "Nested under a parent team",
            'mondo team create --name "Infra" --parent-team 3 --allow-empty',
        ),
    ],
    "team delete": [
        Example(
            "Permanent team delete",
            "mondo team delete --id 7 --hard --yes",
        ),
    ],
    "team add-users": [
        Example(
            "Add members",
            "mondo team add-users --id 7 --user 1 --user 2",
        ),
    ],
    "team remove-users": [
        Example(
            "Remove members",
            "mondo team remove-users --id 7 --user 1",
        ),
    ],
    "team assign-owners": [
        Example(
            "Promote a member to team owner",
            "mondo team assign-owners --id 7 --user 1",
        ),
    ],
    "team remove-owners": [
        Example(
            "Demote an owner",
            "mondo team remove-owners --id 7 --user 1",
        ),
    ],
    # --- export ------------------------------------------------------------
    "export board": [
        Example(
            "CSV to stdout",
            "mondo export board --board 1234567890 --format csv",
        ),
        Example(
            "JSON to file",
            "mondo export board --board 1234567890 --format json --out board.json",
        ),
        Example(
            "XLSX with subitems on a second sheet",
            "mondo export board --board 1234567890 --format xlsx "
            "--out board.xlsx --include-subitems",
        ),
        Example(
            "Markdown table (capped at 1000 rows)",
            "mondo export board --board 1234567890 --format md --max-items 1000",
        ),
    ],
    # --- import ------------------------------------------------------------
    "import board": [
        Example(
            "Round-trip a CSV produced by `export board`",
            "mondo import board --board 1234567890 --from items.csv",
        ),
        Example(
            "Custom header → column_id mapping",
            "mondo import board --board 1234567890 --from items.csv --mapping mapping.yaml",
        ),
        Example(
            "Skip rows whose `name` already exists on the board",
            "mondo import board --board 1234567890 --from items.csv --idempotency-name",
        ),
        Example(
            "Dry-run — print what would be created, send nothing",
            "mondo --dry-run import board --board 1234567890 --from items.csv",
        ),
    ],
    # --- skill -------------------------------------------------------------
    "skill install": [
        Example(
            "Install the skill project-local at ./.claude/skills/mondo/SKILL.md",
            "mondo skill install",
        ),
        Example(
            "Install globally for the current user",
            "mondo skill install --global",
        ),
        Example(
            "Overwrite an existing SKILL.md without prompting",
            "mondo --yes skill install",
        ),
    ],
    # --- complexity --------------------------------------------------------
    "complexity status": [
        Example(
            "Print the live complexity budget",
            "mondo complexity status",
        ),
        Example(
            "Per-call drain logging (mix with any command)",
            "mondo --debug item list --board 42",
        ),
    ],
}


def epilog_for(path: str) -> str | None:
    """Render examples for the given dotted command path as a Typer epilog.

    Returns None when no examples are registered, which Typer treats as
    "no epilog" rather than rendering an empty header.

    Typer with rich_markup_mode="rich" word-wraps text in the epilog panel,
    collapsing single newlines. We emit each line as its own Rich paragraph
    (double-newline separated) to preserve the visual structure.
    """
    exs = EXAMPLES.get(path)
    if not exs:
        return None
    paragraphs: list[str] = ["[bold]Examples[/bold]"]
    for ex in exs:
        # A zero-width-space paragraph forces Rich to emit a visible blank
        # line between example blocks (plain "" gets collapsed).
        if len(paragraphs) > 1:
            paragraphs.append("\u200b")
        paragraphs.append(f"[dim]# {ex.description}[/dim]")
        paragraphs.append(f"  $ {ex.command}")
    return "\n\n".join(paragraphs)
