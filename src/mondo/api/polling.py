"""Polling helpers for monday's async operations.

monday's `duplicate_board` (and a few other mutations) return a partial payload
immediately while continuing to populate the new resource server-side. There's
no job-id endpoint, so the only completion signal we have is the resource's
own shape — typically `items_count` on a board.

`wait_for_items_count_stable` polls a board until `items_count` stops growing
(or reaches a known target) and returns the final value. Callers that want a
richer progress signal can pass `on_tick` to observe each poll.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from mondo.api.client import MondayClient
from mondo.api.errors import WaitTimeoutError
from mondo.api.queries import BOARD_ITEMS_COUNT


def wait_for_items_count_stable(
    client: MondayClient,
    board_id: int,
    *,
    target: int | None,
    timeout_s: float,
    interval_s: float = 2.0,
    growth_stall: int = 2,
    on_tick: Callable[[int], None] | None = None,
) -> int:
    """Poll `board(ids:)` until `items_count` stabilises; return the final count.

    Stability is defined as either:
    - `items_count == target` (when `target` is supplied), or
    - `items_count` unchanged for `growth_stall` consecutive polls.

    Raises `WaitTimeoutError` when `timeout_s` elapses before either condition
    is satisfied. The elapsed budget is checked before each poll so a single
    slow request can't overshoot by more than `interval_s` plus the request's
    own duration.
    """
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    if interval_s <= 0:
        raise ValueError("interval_s must be positive")
    if growth_stall < 1:
        raise ValueError("growth_stall must be >= 1")

    deadline = time.monotonic() + timeout_s
    last_count: int | None = None
    stall_counter = 0

    while True:
        result = client.execute(BOARD_ITEMS_COUNT, {"ids": [board_id]})
        boards = ((result.get("data") or {}).get("boards")) or []
        if not boards:
            raise WaitTimeoutError(
                f"board {board_id} not found while polling (it may have been deleted)"
            )
        raw_count = boards[0].get("items_count")
        current = int(raw_count) if raw_count is not None else 0
        if on_tick is not None:
            on_tick(current)

        if target is not None and current >= target:
            return current

        if last_count is not None and current == last_count:
            stall_counter += 1
            if stall_counter >= growth_stall:
                return current
        else:
            stall_counter = 0
        last_count = current

        if time.monotonic() >= deadline:
            raise WaitTimeoutError(
                f"timed out after {timeout_s}s waiting for board {board_id} to stabilise "
                f"(last items_count={current}, target={target})"
            )
        time.sleep(interval_s)
