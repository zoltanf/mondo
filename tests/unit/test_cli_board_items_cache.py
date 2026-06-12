"""Short-TTL board-scope `item list` cache (#21).

Contract: only the bare `--board` (and `--board --group`, served by
client-side filtering off the same file) variants touch the
`board_items/<board_id>.json` cache. Filtered / ordered / column-narrowed
variants stay live; partial results (group slice, max-items prefix,
slimmed selection) are never written back.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from mondo.cli.main import app

ENDPOINT = "https://api.monday.com/v2"
runner = CliRunner()

BOARD = "4242"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")
    monkeypatch.setenv("MONDO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MONDO_CACHE_ENABLED", "true")
    # The cache notice is gated on a human watching stderr (#25); force it
    # on so the provenance assertions hold under captured streams.
    monkeypatch.setenv("MONDO_VERBOSE", "1")


@pytest.fixture
def cache_file(tmp_path: Path) -> Path:
    return tmp_path / "cache" / "default" / "board_items" / f"{BOARD}.json"


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


ITEMS = [
    {
        "id": "1",
        "name": "A",
        "state": "active",
        "group": {"id": "g1", "title": "G1"},
        "column_values": [{"id": "status", "type": "status", "text": "Done", "value": "{}"}],
    },
    {
        "id": "2",
        "name": "B",
        "state": "active",
        "group": {"id": "g2", "title": "G2"},
        "column_values": [],
    },
]


def _items_page(items: list[dict], cursor: str | None = None) -> dict:
    return {"boards": [{"items_page": {"cursor": cursor, "items": items}}]}


def _warm(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok(_items_page(ITEMS)))
    result = runner.invoke(app, ["item", "list", "--board", BOARD])
    assert result.exit_code == 0, result.output


class TestBareListCache:
    def test_cold_list_writes_cache(
        self, httpx_mock: HTTPXMock, cache_file: Path
    ) -> None:
        _warm(httpx_mock)
        assert cache_file.exists()
        envelope = json.loads(cache_file.read_text())
        assert [e["id"] for e in envelope["entries"]] == ["1", "2"]
        assert envelope["ttl_seconds"] == 60

    def test_second_list_serves_from_cache(
        self, httpx_mock: HTTPXMock, cache_file: Path
    ) -> None:
        _warm(httpx_mock)
        result = runner.invoke(app, ["item", "list", "--board", BOARD])
        assert result.exit_code == 0, result.output
        assert [r["id"] for r in json.loads(result.stdout)] == ["1", "2"]
        assert "cache: hit" in result.stderr
        assert "entity=board_items" in result.stderr
        # Only the warm-up call hit the API.
        assert len(httpx_mock.get_requests()) == 1

    def test_group_variant_served_from_cached_full_list(
        self, httpx_mock: HTTPXMock
    ) -> None:
        _warm(httpx_mock)
        result = runner.invoke(app, ["item", "list", "--board", BOARD, "--group", "g2"])
        assert result.exit_code == 0, result.output
        assert [r["id"] for r in json.loads(result.stdout)] == ["2"]
        assert len(httpx_mock.get_requests()) == 1

    def test_max_items_served_truncated_from_cache(
        self, httpx_mock: HTTPXMock
    ) -> None:
        _warm(httpx_mock)
        result = runner.invoke(
            app, ["item", "list", "--board", BOARD, "--max-items", "1"]
        )
        assert result.exit_code == 0, result.output
        assert [r["id"] for r in json.loads(result.stdout)] == ["1"]
        assert len(httpx_mock.get_requests()) == 1

    def test_fields_projection_served_from_cache(
        self, httpx_mock: HTTPXMock
    ) -> None:
        _warm(httpx_mock)
        result = runner.invoke(
            app, ["--fields", "id,name", "item", "list", "--board", BOARD]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout) == [
            {"id": "1", "name": "A"},
            {"id": "2", "name": "B"},
        ]
        assert len(httpx_mock.get_requests()) == 1


class TestNonBareVariantsStayLive:
    def test_group_only_cold_does_not_write(
        self, httpx_mock: HTTPXMock, cache_file: Path
    ) -> None:
        # Cold group listing goes live: column-defs preflight + items fetch.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": BOARD, "name": "B", "columns": []}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok(_items_page([ITEMS[1]]))
        )
        result = runner.invoke(app, ["item", "list", "--board", BOARD, "--group", "g2"])
        assert result.exit_code == 0, result.output
        assert not cache_file.exists()

    def test_max_items_cold_does_not_write(
        self, httpx_mock: HTTPXMock, cache_file: Path
    ) -> None:
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok(_items_page(ITEMS))
        )
        result = runner.invoke(
            app, ["item", "list", "--board", BOARD, "--max-items", "1"]
        )
        assert result.exit_code == 0, result.output
        assert not cache_file.exists()

    def test_slim_fields_cold_does_not_write(
        self, httpx_mock: HTTPXMock, cache_file: Path
    ) -> None:
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok(_items_page(ITEMS))
        )
        result = runner.invoke(
            app, ["--fields", "id,name", "item", "list", "--board", BOARD]
        )
        assert result.exit_code == 0, result.output
        assert not cache_file.exists()

    def test_filtered_list_bypasses_cache(
        self, httpx_mock: HTTPXMock, cache_file: Path
    ) -> None:
        _warm(httpx_mock)
        # --filter needs the column-defs preflight (its own cache) plus the
        # live items fetch — neither touches board_items.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "id": BOARD,
                            "name": "B",
                            "columns": [{"id": "text7", "title": "T", "type": "text"}],
                        }
                    ]
                }
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok(_items_page([ITEMS[0]]))
        )
        result = runner.invoke(
            app, ["item", "list", "--board", BOARD, "--filter", "text7=x"]
        )
        assert result.exit_code == 0, result.output
        assert len(httpx_mock.get_requests()) == 3

    def test_group_with_comma_bypasses_cache(
        self, httpx_mock: HTTPXMock
    ) -> None:
        # `--group "g1,g2"` comma-splits to multiple ids on the live path
        # (raw-filter fallback); the cached path matches the id exactly, so
        # multi-id group filters must not be served from the cache.
        _warm(httpx_mock)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": BOARD, "name": "B", "columns": []}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok(_items_page(ITEMS))
        )
        result = runner.invoke(
            app, ["item", "list", "--board", BOARD, "--group", "g1,g2"]
        )
        assert result.exit_code == 0, result.output
        assert [r["id"] for r in json.loads(result.stdout)] == ["1", "2"]
        assert len(httpx_mock.get_requests()) == 3

    def test_columns_selection_bypasses_cache(
        self, httpx_mock: HTTPXMock
    ) -> None:
        _warm(httpx_mock)
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok(_items_page(ITEMS))
        )
        result = runner.invoke(
            app, ["item", "list", "--board", BOARD, "--columns", "status"]
        )
        assert result.exit_code == 0, result.output
        assert len(httpx_mock.get_requests()) == 2


class TestCacheFlags:
    def test_no_cache_and_refresh_cache_are_mutually_exclusive(self) -> None:
        result = runner.invoke(
            app,
            ["item", "list", "--board", BOARD, "--no-cache", "--refresh-cache"],
        )
        assert result.exit_code == 2
        assert "mutually exclusive" in result.stderr

    def test_no_cache_fetches_live(self, httpx_mock: HTTPXMock) -> None:
        _warm(httpx_mock)
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok(_items_page(ITEMS))
        )
        result = runner.invoke(app, ["item", "list", "--board", BOARD, "--no-cache"])
        assert result.exit_code == 0, result.output
        assert len(httpx_mock.get_requests()) == 2

    def test_refresh_cache_rewrites(
        self, httpx_mock: HTTPXMock, cache_file: Path
    ) -> None:
        _warm(httpx_mock)
        fresh = [dict(ITEMS[0], name="A-renamed"), ITEMS[1]]
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok(_items_page(fresh))
        )
        result = runner.invoke(
            app, ["item", "list", "--board", BOARD, "--refresh-cache"]
        )
        assert result.exit_code == 0, result.output
        assert len(httpx_mock.get_requests()) == 2
        envelope = json.loads(cache_file.read_text())
        assert envelope["entries"][0]["name"] == "A-renamed"

    def test_expired_envelope_fetches_live(
        self, httpx_mock: HTTPXMock, cache_file: Path
    ) -> None:
        _warm(httpx_mock)
        envelope = json.loads(cache_file.read_text())
        envelope["fetched_at"] = "2020-01-01T00:00:00Z"
        cache_file.write_text(json.dumps(envelope))
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_ok(_items_page(ITEMS))
        )
        result = runner.invoke(app, ["item", "list", "--board", BOARD])
        assert result.exit_code == 0, result.output
        assert len(httpx_mock.get_requests()) == 2


class TestWritePathInvalidation:
    def test_item_create_drops_board_cache(
        self, httpx_mock: HTTPXMock, cache_file: Path
    ) -> None:
        _warm(httpx_mock)
        assert cache_file.exists()
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "9", "name": "New"}}),
        )
        result = runner.invoke(
            app, ["item", "create", "--board", BOARD, "--name", "New"]
        )
        assert result.exit_code == 0, result.output
        assert not cache_file.exists()

    def test_item_rename_drops_board_cache(
        self, httpx_mock: HTTPXMock, cache_file: Path
    ) -> None:
        _warm(httpx_mock)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_simple_column_value": {"id": "1", "name": "Z"}}),
        )
        result = runner.invoke(
            app, ["item", "rename", "1", "--board", BOARD, "--name", "Z"]
        )
        assert result.exit_code == 0, result.output
        assert not cache_file.exists()

    def test_column_set_drops_board_cache(
        self, httpx_mock: HTTPXMock, cache_file: Path
    ) -> None:
        _warm(httpx_mock)
        # COLUMN_CONTEXT preflight (carries the board id) + the mutation.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "items": [
                        {
                            "id": "1",
                            "name": "A",
                            "board": {
                                "id": BOARD,
                                "columns": [
                                    {
                                        "id": "text7",
                                        "title": "T",
                                        "type": "text",
                                        "settings_str": "{}",
                                    }
                                ],
                            },
                            "column_values": [],
                        }
                    ]
                }
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_value": {"id": "1", "name": "A"}}),
        )
        result = runner.invoke(
            app,
            ["column", "set", "--item", "1", "--column", "text7", "--value", "x"],
        )
        assert result.exit_code == 0, result.output
        assert not cache_file.exists()

    def test_group_delete_drops_board_cache(
        self, httpx_mock: HTTPXMock, cache_file: Path
    ) -> None:
        _warm(httpx_mock)
        assert cache_file.exists()
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_group": {"id": "g2", "deleted": True}}),
        )
        result = runner.invoke(
            app,
            ["--yes", "group", "delete", "--board", BOARD, "--id", "g2", "--hard"],
        )
        assert result.exit_code == 0, result.output
        assert not cache_file.exists()

    def test_column_delete_drops_board_cache(
        self, httpx_mock: HTTPXMock, cache_file: Path
    ) -> None:
        _warm(httpx_mock)
        assert cache_file.exists()
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_column": {"id": "status"}}),
        )
        result = runner.invoke(
            app,
            ["--yes", "column", "delete", "--board", BOARD, "--id", "status"],
        )
        assert result.exit_code == 0, result.output
        assert not cache_file.exists()
