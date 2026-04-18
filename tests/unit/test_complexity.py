"""Unit tests for the complexity injector + meter + CLI status command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from mondo.api.client import MondayClient
from mondo.api.complexity import ComplexityMeter, inject_complexity_field
from mondo.cli.main import app

ENDPOINT = "https://api.monday.com/v2"
runner = CliRunner()


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


# --- inject_complexity_field ---


class TestInjector:
    def test_injects_into_simple_query(self) -> None:
        q = "query { me { id } }"
        out = inject_complexity_field(q)
        assert "reset_in_x_seconds" in out
        # Original selection is still present.
        assert "me { id }" in out

    def test_injects_into_mutation(self) -> None:
        q = 'mutation { create_item(board_id: 1, item_name: "x") { id } }'
        out = inject_complexity_field(q)
        assert "reset_in_x_seconds" in out

    def test_idempotent(self) -> None:
        q = "query { me { id } complexity { query before after reset_in_x_seconds } }"
        assert inject_complexity_field(q) == q

    def test_missing_braces_returns_input(self) -> None:
        q = "not-a-query"
        assert inject_complexity_field(q) == q


# --- ComplexityMeter ---


class TestMeter:
    def test_record_updates_fields(self) -> None:
        meter = ComplexityMeter()
        sample = meter.record(
            {
                "complexity": {
                    "query": 100,
                    "before": 9_900_000,
                    "after": 9_899_900,
                    "reset_in_x_seconds": 30,
                },
                "me": {"id": "1"},
            }
        )
        assert sample is not None
        assert sample.query_cost == 100
        assert meter.samples == 1
        assert meter.total_cost == 100
        assert meter.budget_after == 9_899_900

    def test_record_without_complexity_returns_none(self) -> None:
        meter = ComplexityMeter()
        assert meter.record({"me": {"id": "1"}}) is None
        assert meter.samples == 0

    def test_record_with_malformed_block_returns_none(self) -> None:
        meter = ComplexityMeter()
        assert meter.record({"complexity": "nope"}) is None
        assert (
            meter.record({"complexity": {"query": "not-an-int", "before": 1, "after": 1}}) is None
        )
        assert meter.samples == 0

    def test_history_accumulates(self) -> None:
        meter = ComplexityMeter()
        for i in range(3):
            meter.record(
                {
                    "complexity": {
                        "query": 10 + i,
                        "before": 100,
                        "after": 90 - i,
                        "reset_in_x_seconds": 60,
                    }
                }
            )
        assert meter.samples == 3
        assert meter.total_cost == 10 + 11 + 12
        assert [s.query_cost for s in meter.history] == [10, 11, 12]


# --- MondayClient integration ---


class TestClientInjection:
    def test_injects_by_default(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({}))
        client = MondayClient(token="t", api_version="2026-01")
        client.execute("query { me { id } }")
        body = json.loads(httpx_mock.get_request().content)
        assert "reset_in_x_seconds" in body["query"]

    def test_raw_skips_injection(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({}))
        client = MondayClient(token="t", api_version="2026-01")
        client.execute("query { me { id } }", raw=True)
        body = json.loads(httpx_mock.get_request().content)
        assert "reset_in_x_seconds" not in body["query"]

    def test_inject_complexity_false_overrides(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({}))
        client = MondayClient(token="t", api_version="2026-01", inject_complexity=False)
        client.execute("query { me { id } }")
        body = json.loads(httpx_mock.get_request().content)
        assert "reset_in_x_seconds" not in body["query"]

    def test_meter_records_from_response(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "me": {"id": "1"},
                    "complexity": {
                        "query": 50,
                        "before": 1000,
                        "after": 950,
                        "reset_in_x_seconds": 42,
                    },
                }
            ),
        )
        client = MondayClient(token="t", api_version="2026-01")
        client.execute("query { me { id } }")
        assert client.meter.samples == 1
        assert client.meter.last_query_cost == 50
        assert client.meter.budget_after == 950
        assert client.meter.reset_in_seconds == 42


# --- CLI ---


@pytest.fixture
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")


class TestComplexityStatusCmd:
    def test_prints_meter(self, _clean_env: None, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "me": {"id": "1"},
                    "complexity": {
                        "query": 10,
                        "before": 5_000_000,
                        "after": 4_999_990,
                        "reset_in_x_seconds": 55,
                    },
                }
            ),
        )
        result = runner.invoke(app, ["complexity", "status"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["samples"] == 1
        assert parsed["last_query_cost"] == 10
        assert parsed["budget_after"] == 4_999_990
        assert parsed["reset_in_seconds"] == 55

    def test_handles_no_complexity_block(self, _clean_env: None, httpx_mock: HTTPXMock) -> None:
        # Older API responses could omit the field — CLI should still succeed.
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"me": {"id": "1"}}))
        result = runner.invoke(app, ["complexity", "status"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["samples"] == 0
