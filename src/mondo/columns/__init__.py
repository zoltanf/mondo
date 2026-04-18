"""Column codecs.

Importing this package registers every built-in codec as a side effect, so
`get_codec("status")` etc. work immediately.
"""

from __future__ import annotations

# Side-effect imports: each module calls `register(...)` at the bottom.
# Ordered alphabetically; inter-module dependencies are nil.
from mondo.columns import contact as _contact  # noqa: F401
from mondo.columns import datelike as _datelike  # noqa: F401
from mondo.columns import dropdown as _dropdown  # noqa: F401
from mondo.columns import location as _location  # noqa: F401
from mondo.columns import people as _people  # noqa: F401
from mondo.columns import readonly as _readonly  # noqa: F401
from mondo.columns import relation as _relation  # noqa: F401
from mondo.columns import simple as _simple  # noqa: F401
from mondo.columns import status as _status  # noqa: F401
from mondo.columns import tags as _tags  # noqa: F401
from mondo.columns.base import (
    ColumnCodec,
    UnknownColumnTypeError,
    clear_payload_for,
    get_codec,
    parse_value,
    register,
    registered_types,
    render_value,
)

__all__ = [
    "ColumnCodec",
    "UnknownColumnTypeError",
    "clear_payload_for",
    "get_codec",
    "parse_value",
    "register",
    "registered_types",
    "render_value",
]
