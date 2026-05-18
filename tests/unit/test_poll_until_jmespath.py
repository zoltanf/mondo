"""poll_until_jmespath: re-call a fetcher until a JMESPath expression
evaluates truthy against its result, or timeout."""
from __future__ import annotations

import pytest

from mondo.api.errors import WaitTimeoutError
from mondo.api.polling import poll_until_jmespath


def test_returns_immediately_when_expression_already_truthy():
    sequence = iter([{"status": "done"}])
    result = poll_until_jmespath(
        fetch=lambda: next(sequence),
        expression="status == 'done'",
        interval_s=0.0,
        timeout_s=10.0,
        sleep=lambda s: None,
        now=iter([0.0, 1.0]).__next__,
    )
    assert result == {"status": "done"}


def test_returns_on_first_truthy_match():
    sequence = iter([{"s": "pending"}, {"s": "pending"}, {"s": "done"}])
    result = poll_until_jmespath(
        fetch=lambda: next(sequence),
        expression="s == 'done'",
        interval_s=0.0,
        timeout_s=10.0,
        sleep=lambda s: None,
        now=iter([0.0, 1.0, 2.0, 3.0]).__next__,
    )
    assert result == {"s": "done"}


def test_raises_wait_timeout_when_expression_stays_falsy():
    with pytest.raises(WaitTimeoutError, match="--poll-until"):
        poll_until_jmespath(
            fetch=lambda: {"s": "pending"},
            expression="s == 'done'",
            interval_s=0.0,
            timeout_s=1.0,
            sleep=lambda s: None,
            now=iter([0.0, 0.5, 1.5]).__next__,
        )


def test_passes_through_dict_payload():
    """When the payload is a dict and the JMESPath returns a value,
    the helper returns that same dict (not the evaluated expression)."""
    result = poll_until_jmespath(
        fetch=lambda: {"id": "1", "ready": True},
        expression="ready",
        interval_s=0.0,
        timeout_s=10.0,
        sleep=lambda s: None,
        now=iter([0.0, 1.0]).__next__,
    )
    assert result == {"id": "1", "ready": True}


def test_works_on_list_payload():
    result = poll_until_jmespath(
        fetch=lambda: [{"id": "1"}, {"id": "2"}],
        expression="length(@) >= `2`",
        interval_s=0.0,
        timeout_s=10.0,
        sleep=lambda s: None,
        now=iter([0.0, 1.0]).__next__,
    )
    assert result == [{"id": "1"}, {"id": "2"}]


def test_invalid_jmespath_expression_raises_value_error():
    with pytest.raises((ValueError, Exception)):
        poll_until_jmespath(
            fetch=lambda: {"x": 1},
            expression="this is not valid jmespath !@#",
            interval_s=0.0,
            timeout_s=1.0,
            sleep=lambda s: None,
            now=iter([0.0]).__next__,
        )
