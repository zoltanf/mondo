"""Live Monday integration test covering real write operations.

This test is intentionally env-gated and marked `integration` because it
creates and deletes real resources in a playground workspace.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from mondo.cli.main import app

MONDAY_TEST_TOKEN_ENV = "MONDAY_TEST_TOKEN"
MONDAY_TEST_WORKSPACE_ID_ENV = "MONDAY_TEST_WORKSPACE_ID"
MONDO_TEST_BOARD_ID_ENV = "MONDO_TEST_BOARD_ID"
MONDO_TEST_DOC_ID_ENV = "MONDO_TEST_DOC_ID"
DEFAULT_PLAYGROUND_WORKSPACE_ID = 592446
API_VERSION = "2026-01"

runner = CliRunner()


def _require_live_token() -> str:
    token = os.environ.get(MONDAY_TEST_TOKEN_ENV)
    if not token:
        pytest.skip(f"set {MONDAY_TEST_TOKEN_ENV} to run live Monday integration tests")
    return token


def _format_failure(args: list[str], result: Any) -> str:
    return (
        f"mondo {' '.join(args)}\n"
        f"exit_code={result.exit_code}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def _invoke(args: list[str], *, expect_exit: int | None = 0) -> Any:
    result = runner.invoke(app, ["--yes", "--output", "json", *args])
    if expect_exit is not None:
        assert result.exit_code == expect_exit, _format_failure(args, result)
    return result


def _json_output(result: Any) -> Any:
    text = result.stdout.strip()
    assert text, "command produced no JSON output"
    return json.loads(text)


def _invoke_json(args: list[str], *, expect_exit: int | None = 0) -> Any:
    return _json_output(_invoke(args, expect_exit=expect_exit))


def _wait_for(
    description: str,
    probe: Any,
    *,
    timeout_seconds: float = 45.0,
    interval_seconds: float = 1.0,
) -> Any:
    deadline = time.monotonic() + timeout_seconds
    last_error: AssertionError | None = None
    while time.monotonic() < deadline:
        try:
            return probe()
        except AssertionError as exc:
            last_error = exc
            time.sleep(interval_seconds)
    detail = f": {last_error}" if last_error else ""
    raise AssertionError(f"timed out waiting for {description}{detail}")


@dataclass
class CleanupAction:
    label: str
    args: list[str]


@dataclass
class CleanupPlan:
    actions: list[CleanupAction] = field(default_factory=list)

    def add(self, label: str, *args: str) -> None:
        self.actions.append(CleanupAction(label=label, args=list(args)))


@pytest.fixture
def live_workspace_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> int:
    token = _require_live_token()
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", token)
    monkeypatch.setenv("MONDAY_API_VERSION", API_VERSION)
    monkeypatch.setenv("MONDO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MONDO_CACHE_ENABLED", "false")
    return int(os.environ.get(MONDAY_TEST_WORKSPACE_ID_ENV, DEFAULT_PLAYGROUND_WORKSPACE_ID))


@pytest.fixture
def cleanup_plan(live_workspace_id: int) -> CleanupPlan:
    plan = CleanupPlan()
    yield plan

    failures: list[str] = []
    for action in reversed(plan.actions):
        deadline = time.monotonic() + 45.0
        while True:
            result = _invoke(action.args, expect_exit=None)
            if result.exit_code in {0, 6}:
                break
            if time.monotonic() >= deadline:
                failures.append(f"{action.label} cleanup failed\n{_format_failure(action.args, result)}")
                break
            time.sleep(1.0)
    if failures:
        pytest.fail("\n\n".join(failures))


def _probe_board(board_id: int, *, workspace_id: int, folder_id: int, board_name: str) -> dict[str, Any]:
    result = _invoke(["board", "get", "--id", str(board_id)], expect_exit=None)
    assert result.exit_code == 0, _format_failure(["board", "get", "--id", str(board_id)], result)
    board = _json_output(result)
    assert board["name"] == board_name
    assert str(board["workspace_id"]) == str(workspace_id)
    assert str(board["folder_id"]) == str(folder_id)
    return board


def _probe_group(board_id: int, group_id: str, group_name: str) -> list[dict[str, Any]]:
    result = _invoke(["group", "list", "--board", str(board_id)], expect_exit=None)
    assert result.exit_code == 0, _format_failure(["group", "list", "--board", str(board_id)], result)
    groups = _json_output(result)
    match = next((group for group in groups if group["id"] == group_id), None)
    assert match is not None, f"group {group_id} not visible on board {board_id}"
    assert match["title"] == group_name
    return groups


def _probe_columns(board_id: int, expected: dict[str, str]) -> list[dict[str, Any]]:
    result = _invoke(["column", "list", "--board", str(board_id)], expect_exit=None)
    assert result.exit_code == 0, _format_failure(["column", "list", "--board", str(board_id)], result)
    columns = _json_output(result)
    by_id = {column["id"]: column for column in columns}
    for column_id, column_type in expected.items():
        assert column_id in by_id, f"column {column_id!r} not visible on board {board_id}"
        assert by_id[column_id]["type"] == column_type
    return columns


def _probe_item(
    item_id: int,
    *,
    board_id: int,
    group_id: str,
    item_name: str,
    expected_texts: dict[str, str] | None = None,
) -> dict[str, Any]:
    result = _invoke(["item", "get", "--id", str(item_id)], expect_exit=None)
    assert result.exit_code == 0, _format_failure(["item", "get", "--id", str(item_id)], result)
    item = _json_output(result)
    assert item["name"] == item_name
    assert str(item["board"]["id"]) == str(board_id)
    assert item["group"]["id"] == group_id
    if expected_texts:
        values = {value["id"]: value for value in item.get("column_values") or []}
        for column_id, expected_text in expected_texts.items():
            assert values[column_id]["text"] == expected_text
    return item


@pytest.mark.integration
def test_live_cli_writes_folder_board_group_columns_and_item(
    live_workspace_id: int, cleanup_plan: CleanupPlan
) -> None:
    suffix = uuid.uuid4().hex[:8]
    folder_name = f"e2e mondo test {suffix}"
    board_name = f"E2E Mondo Board {suffix}"
    group_name = f"E2E Group {suffix}"
    item_name = f"E2E Item {suffix}"
    text_value = f"text value {suffix}"
    note_value = f"note value {suffix}"

    folder = _invoke_json(
        [
            "folder",
            "create",
            "--workspace",
            str(live_workspace_id),
            "--name",
            folder_name,
        ]
    )
    folder_id = int(folder["id"])
    cleanup_plan.add("folder", "folder", "delete", "--id", str(folder_id), "--hard")

    board = _invoke_json(
        [
            "board",
            "create",
            "--workspace",
            str(live_workspace_id),
            "--folder",
            str(folder_id),
            "--name",
            board_name,
            "--kind",
            "private",
            "--empty",
        ]
    )
    board_id = int(board["id"])
    cleanup_plan.add("board", "board", "delete", "--id", str(board_id), "--hard")

    _wait_for(
        "board creation",
        lambda: _probe_board(
            board_id,
            workspace_id=live_workspace_id,
            folder_id=folder_id,
            board_name=board_name,
        ),
    )

    group = _invoke_json(
        [
            "group",
            "create",
            "--board",
            str(board_id),
            "--name",
            group_name,
        ]
    )
    group_id = group["id"]
    _wait_for("group creation", lambda: _probe_group(board_id, group_id, group_name))

    text_column = _invoke_json(
        [
            "column",
            "create",
            "--board",
            str(board_id),
            "--title",
            "E2E Text",
            "--type",
            "text",
            "--id",
            "e2e_text",
        ]
    )
    assert text_column["id"] == "e2e_text"
    assert text_column["type"] == "text"

    note_column = _invoke_json(
        [
            "column",
            "create",
            "--board",
            str(board_id),
            "--title",
            "E2E Note",
            "--type",
            "long_text",
            "--id",
            "e2e_note",
        ]
    )
    assert note_column["id"] == "e2e_note"
    assert note_column["type"] == "long_text"

    _wait_for(
        "column creation",
        lambda: _probe_columns(board_id, {"e2e_text": "text", "e2e_note": "long_text"}),
    )

    item = _invoke_json(
        [
            "item",
            "create",
            "--board",
            str(board_id),
            "--group",
            group_id,
            "--name",
            item_name,
        ]
    )
    item_id = int(item["id"])
    cleanup_plan.add("item", "item", "delete", "--id", str(item_id), "--hard")

    _wait_for(
        "item creation",
        lambda: _probe_item(item_id, board_id=board_id, group_id=group_id, item_name=item_name),
    )

    _invoke_json(
        [
            "column",
            "set",
            "--item",
            str(item_id),
            "--column",
            "e2e_text",
            "--value",
            text_value,
        ]
    )
    _invoke_json(
        [
            "column",
            "set",
            "--item",
            str(item_id),
            "--column",
            "e2e_note",
            "--value",
            note_value,
        ]
    )

    _wait_for(
        "column value writes",
        lambda: _probe_item(
            item_id,
            board_id=board_id,
            group_id=group_id,
            item_name=item_name,
            expected_texts={"e2e_text": text_value, "e2e_note": note_value},
        ),
    )

    rendered_text = _invoke_json(
        ["column", "get", "--item", str(item_id), "--column", "e2e_text"]
    )
    assert rendered_text == text_value

    rendered_note = _invoke_json(
        ["column", "get", "--item", str(item_id), "--column", "e2e_note"]
    )
    assert rendered_note == note_value


# ---------------------------------------------------------------------------
# Per-feature live coverage (Phase 3.1, 3.2, 5.1 + docs)
#
# These tests reuse the long-lived playground board (MONDO_TEST_BOARD_ID) and
# the prepared doc (MONDO_TEST_DOC_ID) instead of paying for folder/board
# create on every run. Each test cleans up the artefacts it creates.
# ---------------------------------------------------------------------------


@pytest.fixture
def live_test_board_id(live_workspace_id: int) -> int:
    """Existing playground board id, gated by MONDO_TEST_BOARD_ID."""
    raw = os.environ.get(MONDO_TEST_BOARD_ID_ENV)
    if not raw:
        pytest.skip(f"set {MONDO_TEST_BOARD_ID_ENV} to run feature-coverage live tests")
    del live_workspace_id  # consumed only for token gate + monkeypatch setup
    return int(raw)


@pytest.fixture
def live_test_doc_id(live_workspace_id: int) -> int:
    """Pre-prepared doc id (the one with notice boxes), gated by MONDO_TEST_DOC_ID."""
    raw = os.environ.get(MONDO_TEST_DOC_ID_ENV)
    if not raw:
        pytest.skip(f"set {MONDO_TEST_DOC_ID_ENV} to run doc read tests")
    del live_workspace_id
    return int(raw)


@pytest.mark.integration
def test_live_name_selectors_and_first(
    live_test_board_id: int, cleanup_plan: CleanupPlan
) -> None:
    """Phase 3.1 — --name-contains / --name-fuzzy / --first on group rename + update."""
    suffix = uuid.uuid4().hex[:8]
    # Two titles that share the suffix-prefix `<suffix>-Alpha` — `Alphabet`
    # is `Alpha` + `bet`, so a substring search for `<suffix>-Alpha` matches
    # both. The shared suffix isolates this run from any leftover groups.
    alpha_title = f"{suffix}-Alpha"
    alphabet_title = f"{suffix}-Alphabet"
    renamed_title = f"{suffix}-Renamed"
    fuzzy_renamed_title = f"{suffix}-FuzzyRenamed"
    common_needle = f"{suffix}-Alpha"

    alpha = _invoke_json(
        ["group", "create", "--board", str(live_test_board_id), "--name", alpha_title]
    )
    alpha_id = alpha["id"]
    cleanup_plan.add(
        f"group {alpha_title}", "group", "delete", "--board",
        str(live_test_board_id), "--id", alpha_id, "--hard",
    )

    alphabet = _invoke_json(
        ["group", "create", "--board", str(live_test_board_id), "--name", alphabet_title]
    )
    alphabet_id = alphabet["id"]
    cleanup_plan.add(
        f"group {alphabet_title}", "group", "delete", "--board",
        str(live_test_board_id), "--id", alphabet_id, "--hard",
    )

    def _both_groups_visible() -> list[dict[str, Any]]:
        groups = _invoke_json(["group", "list", "--board", str(live_test_board_id)])
        ids = {g["id"] for g in groups}
        assert alpha_id in ids and alphabet_id in ids, "groups not yet propagated"
        return groups

    _wait_for("both groups visible", _both_groups_visible)

    # Ambiguous filter without --first should exit 2 (UsageError).
    ambiguous = _invoke(
        [
            "group", "rename",
            "--board", str(live_test_board_id),
            "--name-contains", common_needle,
            "--title", renamed_title,
        ],
        expect_exit=None,
    )
    assert ambiguous.exit_code == 2, _format_failure(["group rename ambiguous"], ambiguous)

    # Same filter + --first picks one of them deterministically (lowest position).
    _invoke_json(
        [
            "group", "rename",
            "--board", str(live_test_board_id),
            "--name-contains", common_needle,
            "--first",
            "--title", renamed_title,
        ]
    )

    def _exactly_one_renamed() -> dict[str, str]:
        groups = _invoke_json(["group", "list", "--board", str(live_test_board_id)])
        by_title = {g["title"]: g["id"] for g in groups if g["id"] in {alpha_id, alphabet_id}}
        assert renamed_title in by_title, f"no group renamed to {renamed_title!r}: {by_title}"
        remaining_titles = [t for t in by_title if t != renamed_title]
        assert len(remaining_titles) == 1, f"unexpected group set: {by_title}"
        assert remaining_titles[0] in {alpha_title, alphabet_title}
        return by_title

    by_title = _wait_for("exactly one group renamed", _exactly_one_renamed)
    untouched_title = next(t for t in by_title if t != renamed_title)

    # `group update --name-fuzzy` against the *untouched* group. Pass a clear
    # typo so fuzzy match clears the default threshold (70). The other group
    # is now named `renamed_title`, which is unrelated, so the match is unique.
    needle = "Allphabet" if untouched_title == alphabet_title else "Allpha"
    _invoke_json(
        [
            "group", "update",
            "--board", str(live_test_board_id),
            "--name-fuzzy", f"{suffix}-{needle}",
            "--attribute", "title",
            "--value", fuzzy_renamed_title,
        ]
    )

    def _fuzzy_renamed() -> None:
        groups = _invoke_json(["group", "list", "--board", str(live_test_board_id)])
        titles = {g["title"] for g in groups}
        assert fuzzy_renamed_title in titles, (
            f"group not fuzzy-renamed to {fuzzy_renamed_title!r}: {titles}"
        )

    _wait_for("group fuzzy-renamed", _fuzzy_renamed)


@pytest.mark.integration
def test_live_item_create_batch_success(
    live_test_board_id: int, cleanup_plan: CleanupPlan, tmp_path: Path
) -> None:
    """Phase 3.2 — `mondo item create --batch` happy path, single-chunk."""
    suffix = uuid.uuid4().hex[:8]

    groups = _invoke_json(["group", "list", "--board", str(live_test_board_id)])
    assert groups, "test board has no groups"
    target_group_id = groups[0]["id"]

    rows = [
        {"name": f"E2E Batch {suffix} #{i}", "group_id": target_group_id}
        for i in range(3)
    ]
    batch_path = tmp_path / "batch_ok.json"
    batch_path.write_text(json.dumps(rows), encoding="utf-8")

    envelope = _invoke_json(
        [
            "item", "create",
            "--board", str(live_test_board_id),
            "--batch", str(batch_path),
        ]
    )

    assert envelope["summary"]["requested"] == 3
    assert envelope["summary"]["created"] == 3
    assert envelope["summary"]["failed"] == 0
    assert len(envelope["results"]) == 3
    for i, result in enumerate(envelope["results"]):
        assert result["ok"] is True, result
        assert result["row_index"] == i
        assert result["id"], f"row {i} missing id: {result}"
        item_id_str = str(result["id"])
        cleanup_plan.add(
            f"batch item {result['name']}",
            "item", "delete", "--id", item_id_str, "--hard",
        )

    sample_id = int(envelope["results"][0]["id"])
    _wait_for(
        "first batch item visible",
        lambda: _probe_item(
            sample_id,
            board_id=live_test_board_id,
            group_id=target_group_id,
            item_name=envelope["results"][0]["name"],
        ),
    )


@pytest.mark.integration
def test_live_item_create_batch_partial_failure(
    live_test_board_id: int, cleanup_plan: CleanupPlan, tmp_path: Path
) -> None:
    """Phase 3.2 — partial-failure surface via the per-row error envelope.

    Row 1 targets a deliberately invalid group_id so monday rejects only that
    mutation; row 0 lands in a real group and succeeds.
    """
    suffix = uuid.uuid4().hex[:8]

    groups = _invoke_json(["group", "list", "--board", str(live_test_board_id)])
    assert groups
    valid_group_id = groups[0]["id"]
    bogus_group_id = f"definitely_not_a_real_group_{suffix}"

    rows = [
        {"name": f"E2E BatchOK {suffix}", "group_id": valid_group_id},
        {"name": f"E2E BatchBAD {suffix}", "group_id": bogus_group_id},
    ]
    batch_path = tmp_path / "batch_partial.json"
    batch_path.write_text(json.dumps(rows), encoding="utf-8")

    result = _invoke(
        [
            "item", "create",
            "--board", str(live_test_board_id),
            "--batch", str(batch_path),
        ],
        expect_exit=None,
    )
    assert result.exit_code == 1, _format_failure(["item create --batch partial"], result)
    envelope = _json_output(result)

    assert envelope["summary"]["requested"] == 2
    assert envelope["summary"]["created"] == 1
    assert envelope["summary"]["failed"] == 1
    assert len(envelope["results"]) == 2

    ok_results = [r for r in envelope["results"] if r["ok"]]
    failed_results = [r for r in envelope["results"] if not r["ok"]]
    assert len(ok_results) == 1
    assert len(failed_results) == 1
    assert ok_results[0]["row_index"] == 0
    assert failed_results[0]["row_index"] == 1
    assert failed_results[0]["error"], "failed row missing error message"

    # Clean up the row that did land.
    cleanup_plan.add(
        f"batch ok item {ok_results[0]['name']}",
        "item", "delete", "--id", str(ok_results[0]["id"]), "--hard",
    )


@pytest.mark.integration
def test_live_json_error_envelope_for_server_errors(live_test_board_id: int) -> None:
    """Phase 5.1 — server-side MondoError emits a structured stderr envelope.

    `mondo item delete --id 1 --hard` runs the ITEM_DELETE mutation through
    `execute()` (which routes MondoError through `handle_mondo_error_or_exit`
    → `_emit_error`) — so the structured stderr envelope fires when the API
    rejects the request. Read commands like `item get` use a hand-rolled
    `secho` for not-found and intentionally bypass the envelope; they're
    not the right probe for this contract.
    """
    del live_test_board_id  # consumed only for the token gate in the fixture chain

    result = runner.invoke(
        app,
        ["--yes", "--output", "json", "item", "delete", "--id", "1", "--hard"],
    )
    assert result.exit_code != 0, _format_failure(["item delete --id 1 --hard"], result)

    stderr_text = result.stderr.strip()
    assert stderr_text, "expected JSON envelope on stderr"

    parsed_envelopes: list[dict[str, Any]] = []
    for line in stderr_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            parsed_envelopes.append(parsed)

    envelope = next(
        (e for e in parsed_envelopes if "exit_code" in e and "error" in e),
        None,
    )
    assert envelope is not None, (
        f"no Phase 5.1 envelope on stderr; got: {stderr_text!r}"
    )

    allowed_keys = {"error", "code", "exit_code", "request_id", "retry_in_seconds", "suggestion"}
    assert set(envelope.keys()) <= allowed_keys, f"unexpected keys: {envelope}"
    assert envelope["exit_code"] == result.exit_code
    assert isinstance(envelope["error"], str) and envelope["error"]
    assert isinstance(envelope.get("code"), str) and envelope["code"]

    assert result.stdout.strip() == "", f"stdout should be empty on error: {result.stdout!r}"


@pytest.mark.integration
def test_live_doc_read_with_notice_box(live_test_doc_id: int) -> None:
    """Read-only verification against the user-prepared doc.

    Confirms `doc get` returns blocks (one of which is a notice-box-style
    block), `doc export-markdown` renders to non-empty markdown, and
    `doc list --no-cache` finds the doc by name.
    """
    doc = _invoke_json(
        [
            "doc", "get",
            "--object-id", str(live_test_doc_id),
            "--format", "json",
        ]
    )
    assert "id" in doc and "object_id" in doc, doc
    assert int(doc["object_id"]) == live_test_doc_id
    assert doc.get("name"), "doc has no name"
    blocks = doc.get("blocks") or []
    assert blocks, "doc has no blocks"

    # Notice-box blocks: monday's API uses a type containing "notice"; tolerate
    # legacy/case variants by lower-casing and substring-matching.
    notice_types = [b.get("type", "") for b in blocks if "notice" in str(b.get("type", "")).lower()]
    assert notice_types, (
        f"expected at least one notice-box-style block; got types: "
        f"{sorted({b.get('type') for b in blocks})}"
    )

    md_result = _invoke(
        [
            "doc", "export-markdown",
            "--doc", str(int(doc["id"])),
        ]
    )
    assert md_result.stdout.strip(), "export-markdown produced no output"

    workspace_id = int(os.environ.get(MONDAY_TEST_WORKSPACE_ID_ENV, DEFAULT_PLAYGROUND_WORKSPACE_ID))
    needle = doc["name"].split()[0] if doc["name"] else ""
    assert needle, "doc name is too short to derive a search needle"
    listing = _invoke_json(
        [
            "doc", "list",
            "--no-cache",
            "--workspace", str(workspace_id),
            "--name-contains", needle,
        ]
    )
    matched = [
        entry for entry in listing
        if int(entry.get("object_id", 0)) == live_test_doc_id
    ]
    assert matched, f"prepared doc not found by name-contains {needle!r}: {listing}"


@pytest.mark.integration
def test_live_doc_create_add_blocks_delete(
    live_workspace_id: int, cleanup_plan: CleanupPlan
) -> None:
    """Mutation coverage: create a throwaway doc, push blocks, delete it."""
    suffix = uuid.uuid4().hex[:8]
    doc_name = f"E2E Doc {suffix}"

    created = _invoke_json(
        [
            "doc", "create",
            "--workspace", str(live_workspace_id),
            "--name", doc_name,
        ]
    )
    assert created.get("id"), created
    doc_id = int(created["id"])
    cleanup_plan.add(
        f"doc {doc_name}",
        "doc", "delete", "--doc", str(doc_id),
    )

    block_content = json.dumps({"deltaFormat": [{"insert": "hello from e2e"}]})
    _invoke_json(
        [
            "doc", "add-block",
            "--doc", str(doc_id),
            "--type", "normal_text",
            "--content", block_content,
        ]
    )

    _invoke(
        [
            "doc", "add-content",
            "--doc", str(doc_id),
            "--markdown", "## E2E Heading\n\n- e2e bullet 1\n- e2e bullet 2\n",
        ]
    )

    def _blocks_landed() -> list[dict[str, Any]]:
        fetched = _invoke_json(
            ["doc", "get", "--id", str(doc_id), "--format", "json"]
        )
        blocks = fetched.get("blocks") or []
        # Monday's read API normalises types to space-separated form
        # (`normal text`) even though the create mutation accepts both
        # `normal_text` and the spaced form. Match against either.
        normalised = {str(b.get("type", "")).replace(" ", "_") for b in blocks}
        assert "normal_text" in normalised, f"normal_text missing: {normalised}"
        assert "medium_title" in normalised, f"medium_title missing: {normalised}"
        assert "bulleted_list" in normalised, f"bulleted_list missing: {normalised}"
        return blocks

    _wait_for("doc blocks landed", _blocks_landed)
