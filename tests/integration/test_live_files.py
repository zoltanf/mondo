"""Live integration test for `mondo file upload` -> `mondo file download` round-trip."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from ._helpers import (
    CleanupPlan,
    invoke,
    invoke_json,
    wait_for,
)
from .conftest import PmBoard


@pytest.mark.integration
def test_live_file_upload_to_column_and_download(
    pm_board_session: PmBoard,
    cleanup_plan: CleanupPlan,
    tmp_path: Path,
) -> None:
    """Upload a small file to a fresh file column; download by asset id; bytes round-trip."""
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]

    # Need a file column on the session board (the fixture didn't add one).
    file_col_id = f"e2e_file_{suffix.lower()}"
    invoke_json(
        [
            "column", "create",
            "--board", str(pm.board_id),
            "--title", f"E2E File {suffix}",
            "--type", "file",
            "--id", file_col_id,
        ]
    )
    cleanup_plan.add(
        f"file column {file_col_id}",
        "column", "delete", "--board", str(pm.board_id), "--column", file_col_id,
    )

    # Scratch item to attach the file to.
    item = invoke_json(
        [
            "item", "create",
            "--board", str(pm.board_id),
            "--group", pm.group_ids["backlog"],
            "--name", f"E2E File Item {suffix}",
        ]
    )
    item_id = int(item["id"])
    cleanup_plan.add(
        f"file item {item_id}",
        "item", "delete", "--id", str(item_id), "--hard",
    )

    # Deterministic content + filename.
    src_file = tmp_path / f"e2e-upload-{suffix}.txt"
    payload = f"hello-monday-{suffix}\n".encode("utf-8")
    src_file.write_bytes(payload)

    upload_result = invoke_json(
        [
            "file", "upload",
            "--file", str(src_file),
            "--target", "item",
            "--item", str(item_id),
            "--column", file_col_id,
        ]
    )

    asset_id = _extract_asset_id(upload_result)
    assert asset_id, f"could not extract asset id from upload payload: {upload_result}"

    download_path = tmp_path / "downloaded.bin"
    invoke(
        [
            "file", "download",
            "--asset", str(asset_id),
            "--out", str(download_path),
        ],
        expect_exit=0,
    )
    assert download_path.exists(), "download did not produce output file"
    assert download_path.read_bytes() == payload, "uploaded vs downloaded bytes diverge"


def _extract_asset_id(payload: Any) -> int | None:
    """Pull an asset id out of the upload response, tolerant of nested shapes."""
    if isinstance(payload, dict):
        for key in ("asset_id", "id"):
            if key in payload and payload[key]:
                try:
                    return int(payload[key])
                except (TypeError, ValueError):
                    pass
        for key in ("asset", "data", "result"):
            inner = payload.get(key)
            if isinstance(inner, dict):
                got = _extract_asset_id(inner)
                if got:
                    return got
        # Walk the payload's `assets` list (file-column upload path).
        assets = payload.get("assets")
        if isinstance(assets, list) and assets:
            return _extract_asset_id(assets[0])
        # update path: change_column_value returns nested asset.
        cv = payload.get("change_column_value") or payload.get("add_file_to_update")
        if isinstance(cv, dict):
            return _extract_asset_id(cv)
    return None
