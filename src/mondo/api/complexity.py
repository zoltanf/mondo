"""Client-side complexity accounting (plan §8.2 / §8.6).

monday bills each query/mutation a complexity score and exposes a
per-minute budget (~10M for Core, more for higher tiers). A GraphQL
query can request the current cost back via:

    complexity {
      query before after reset_in_x_seconds
    }

We auto-inject that field into every query sent by `MondayClient` so
we can keep a running tally of the remaining budget across the
session — useful for `--debug` diagnostics and for bulk operations
(export/import) that could otherwise drain the account silently.

Idempotent: if the query already asks for `complexity.reset_in_x_seconds`,
we leave it alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

COMPLEXITY_FIELD = "complexity { query before after reset_in_x_seconds }"


def inject_complexity_field(query: str) -> str:
    """Append `complexity { ... }` before the closing `}` of the outermost
    operation block. Returns the original query if already injected or if
    we can't confidently locate the root brace pair.
    """
    if "reset_in_x_seconds" in query:
        return query

    depth = 0
    root_close = -1
    root_open = -1
    for idx, ch in enumerate(query):
        if ch == "{":
            if depth == 0:
                root_open = idx
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                root_close = idx
                break

    if root_open < 0 or root_close < 0:
        return query
    return query[:root_close] + f"  {COMPLEXITY_FIELD}\n" + query[root_close:]


@dataclass
class ComplexitySample:
    """A single reading from a monday response's `complexity` field."""

    query_cost: int
    budget_before: int
    budget_after: int
    reset_in_seconds: int


@dataclass
class ComplexityMeter:
    """Session-wide running tally of monday complexity drain.

    Updated each time a response carries a `complexity` block. Safe to
    mutate without locking — the client is single-threaded per Phase 1+2.
    """

    samples: int = 0
    last_query_cost: int | None = None
    budget_before: int | None = None
    budget_after: int | None = None
    reset_in_seconds: int | None = None
    total_cost: int = 0
    history: list[ComplexitySample] = field(default_factory=list)

    def record(self, response_data: dict[str, Any] | None) -> ComplexitySample | None:
        """Pull a complexity block out of a GraphQL response `data` payload
        and update in-memory state. Returns the sample on success, None if
        the response doesn't carry one."""
        if not response_data:
            return None
        block = response_data.get("complexity")
        if not isinstance(block, dict):
            return None
        values: dict[str, int] = {}
        for key in ("query", "before", "after", "reset_in_x_seconds"):
            raw = block.get(key)
            if not isinstance(raw, (int, str)):
                return None
            try:
                values[key] = int(raw)
            except ValueError:
                return None
        sample = ComplexitySample(
            query_cost=values["query"],
            budget_before=values["before"],
            budget_after=values["after"],
            reset_in_seconds=values["reset_in_x_seconds"],
        )
        self.samples += 1
        self.total_cost += sample.query_cost
        self.last_query_cost = sample.query_cost
        self.budget_before = sample.budget_before
        self.budget_after = sample.budget_after
        self.reset_in_seconds = sample.reset_in_seconds
        self.history.append(sample)
        return sample

    def to_dict(self) -> dict[str, Any]:
        return {
            "samples": self.samples,
            "last_query_cost": self.last_query_cost,
            "budget_before": self.budget_before,
            "budget_after": self.budget_after,
            "reset_in_seconds": self.reset_in_seconds,
            "total_cost": self.total_cost,
        }
