"""End-to-end CLI tests for Phase 3i: notify / me / account / aggregate / validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from mondo.cli.main import app

ENDPOINT = "https://api.monday.com/v2"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


def _last_body(httpx_mock: HTTPXMock) -> dict:
    return json.loads(httpx_mock.get_requests()[-1].content)


# --- notify ---


class TestNotify:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_notification": {"id": "-1", "text": "hi"}}),
        )
        result = runner.invoke(
            app,
            [
                "notify",
                "send",
                "--user",
                "42",
                "--target",
                "100",
                "--target-type",
                "Project",
                "--text",
                "hi",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {
            "user": 42,
            "target": 100,
            "targetType": "Project",
            "text": "hi",
            "internal": None,
        }

    def test_internal_flag(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_notification": {"id": "-1"}}),
        )
        result = runner.invoke(
            app,
            [
                "notify",
                "send",
                "--user",
                "42",
                "--target",
                "100",
                "--target-type",
                "Post",
                "--text",
                "fyi",
                "--internal",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["targetType"] == "Post"
        assert v["internal"] is True

    def test_invalid_target_type(self, httpx_mock: HTTPXMock) -> None:
        # NotificationTargetType is case-sensitive; lowercase should fail.
        result = runner.invoke(
            app,
            [
                "notify",
                "send",
                "--user",
                "42",
                "--target",
                "100",
                "--target-type",
                "project",
                "--text",
                "hi",
            ],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []


# --- me / account ---


class TestMe:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "me": {
                        "id": "42",
                        "name": "Alice",
                        "email": "a@x.com",
                        "account": {"id": "1", "name": "Acme"},
                    }
                }
            ),
        )
        result = runner.invoke(app, ["me"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["name"] == "Alice"
        assert parsed["account"]["name"] == "Acme"


class TestAccount:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "me": {
                        "account": {
                            "id": "1",
                            "name": "Acme",
                            "tier": "pro",
                            "slug": "acme",
                        }
                    }
                }
            ),
        )
        result = runner.invoke(app, ["account"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["tier"] == "pro"
        assert parsed["slug"] == "acme"


# --- aggregate ---


class TestAggregate:
    def test_ungrouped_count_flattens_response(self, httpx_mock: HTTPXMock) -> None:
        """Simplest shape: COUNT:* with no grouping. Result is flattened into
        a single {alias: value} dict."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "aggregate": {
                        "results": [
                            {
                                "entries": [
                                    {
                                        "alias": "count",
                                        "value": {
                                            "__typename": "AggregateBasicAggregationResult",
                                            "result": 5,
                                        },
                                    }
                                ]
                            }
                        ]
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            [
                "aggregate",
                "board",
                "--board",
                "42",
                "--select",
                "COUNT:*",
            ],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed == [{"count": 5}]

        body = _last_body(httpx_mock)
        q = body["variables"]["q"]
        assert q["from"] == {"type": "TABLE", "id": "42"}
        assert q["select"] == [
            {"type": "FUNCTION", "function": {"function": "COUNT_ITEMS", "params": []}, "as": "count"}
        ]
        assert "group_by" not in q

    def test_group_by_auto_adds_column_select(self, httpx_mock: HTTPXMock) -> None:
        """Monday rejects the query unless every `group_by` column also
        appears in `select` — we add the COLUMN select automatically."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "aggregate": {
                        "results": [
                            {
                                "entries": [
                                    {
                                        "alias": "status",
                                        "value": {
                                            "__typename": "AggregateGroupByResult",
                                            "value_string": "Done",
                                            "value_int": None,
                                            "value_float": None,
                                            "value_boolean": None,
                                            "value": "Done",
                                        },
                                    },
                                    {
                                        "alias": "count",
                                        "value": {
                                            "__typename": "AggregateBasicAggregationResult",
                                            "result": 3,
                                        },
                                    },
                                ]
                            }
                        ]
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            [
                "aggregate",
                "board",
                "--board",
                "42",
                "--group-by",
                "status",
                "--select",
                "COUNT:*",
            ],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed == [{"status": "Done", "count": 3}]

        q = _last_body(httpx_mock)["variables"]["q"]
        assert q["group_by"] == [{"column_id": "status"}]
        assert q["select"] == [
            {"type": "COLUMN", "column": {"column_id": "status"}, "as": "status"},
            {"type": "FUNCTION", "function": {"function": "COUNT_ITEMS", "params": []}, "as": "count"},
        ]

    def test_sum_and_average_wrap_column_as_function_param(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"aggregate": {"results": []}}),
        )
        result = runner.invoke(
            app,
            [
                "aggregate",
                "board",
                "--board",
                "42",
                "--select",
                "SUM:price",
                "--select",
                "AVERAGE:price",
            ],
        )
        assert result.exit_code == 0, result.stdout
        q = _last_body(httpx_mock)["variables"]["q"]
        assert q["select"] == [
            {
                "type": "FUNCTION",
                "function": {
                    "function": "SUM",
                    "params": [
                        {"type": "COLUMN", "column": {"column_id": "price"}, "as": "_price"}
                    ],
                },
                "as": "sum_price",
            },
            {
                "type": "FUNCTION",
                "function": {
                    "function": "AVERAGE",
                    "params": [
                        {"type": "COLUMN", "column": {"column_id": "price"}, "as": "_price"}
                    ],
                },
                "as": "average_price",
            },
        ]

    def test_wildcard_rejected_for_non_count(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["aggregate", "board", "--board", "42", "--select", "SUM:*"],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_invalid_function(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            [
                "aggregate",
                "board",
                "--board",
                "42",
                "--select",
                "BOGUS:x",
            ],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_missing_colon(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["aggregate", "board", "--board", "42", "--select", "COUNT"],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_filter_json_passthrough(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"aggregate": {"results": []}}),
        )
        result = runner.invoke(
            app,
            [
                "aggregate",
                "board",
                "--board",
                "42",
                "--select",
                "COUNT:*",
                "--filter",
                '{"rules":[{"column_id":"status","operator":"any_of","compare_value":["Done"]}]}',
            ],
        )
        assert result.exit_code == 0, result.stdout
        q = _last_body(httpx_mock)["variables"]["q"]
        assert q["query"]["rules"][0]["column_id"] == "status"


# --- validation ---


class TestValidationList:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "id": "42",
                            "validations": [
                                {
                                    "id": "1",
                                    "column_id": "status",
                                    "rule_type": "REQUIRED",
                                }
                            ],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["validation", "list", "--board", "42"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [r["id"] for r in parsed] == ["1"]

    def test_board_not_found(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": []}))
        result = runner.invoke(app, ["validation", "list", "--board", "999"])
        assert result.exit_code == 6


class TestValidationCreate:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "create_validation_rule": {
                        "id": "1",
                        "column_id": "status",
                        "rule_type": "REQUIRED",
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            [
                "validation",
                "create",
                "--board",
                "42",
                "--column",
                "status",
                "--rule-type",
                "REQUIRED",
            ],
        )
        assert result.exit_code == 0, result.stdout

    def test_with_value_json(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_validation_rule": {"id": "1"}}),
        )
        result = runner.invoke(
            app,
            [
                "validation",
                "create",
                "--board",
                "42",
                "--column",
                "numbers",
                "--rule-type",
                "MIN_VALUE",
                "--value",
                '{"min":10}',
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["value"] == {"min": 10}

    def test_invalid_value_json_exit_2(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            [
                "validation",
                "create",
                "--board",
                "42",
                "--column",
                "x",
                "--rule-type",
                "T",
                "--value",
                "{not json",
            ],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []


class TestValidationUpdate:
    def test_requires_one_attr(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["validation", "update", "--id", "1"])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_update_description(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_validation_rule": {"id": "1"}}),
        )
        result = runner.invoke(
            app,
            [
                "validation",
                "update",
                "--id",
                "1",
                "--description",
                "new desc",
            ],
        )
        assert result.exit_code == 0, result.stdout


class TestValidationDelete:
    def test_requires_confirmation(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["validation", "delete", "--id", "1"], input="n\n")
        assert result.exit_code == 1
        assert httpx_mock.get_requests() == []

    def test_yes(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_validation_rule": {"id": "1"}}),
        )
        result = runner.invoke(app, ["--yes", "validation", "delete", "--id", "1"])
        assert result.exit_code == 0, result.stdout
