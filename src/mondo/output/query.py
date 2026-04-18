"""JMESPath projection helper.

Applied *before* formatting so `--query` reshapes the data before the table /
csv / json renderer sees it (matches az CLI's `--query` semantics).
"""

from __future__ import annotations

from typing import Any

import jmespath  # type: ignore[import-untyped]
from jmespath.exceptions import JMESPathError  # type: ignore[import-untyped]


def apply_query(data: Any, expression: str | None) -> Any:
    """Project `data` through a JMESPath expression, or return it unchanged.

    Raises ValueError on invalid JMESPath so the caller can surface a usage
    error with the correct exit code.
    """
    if not expression:
        return data
    try:
        return jmespath.search(expression, data)
    except JMESPathError as e:
        raise ValueError(f"invalid JMESPath expression: {e}") from e
