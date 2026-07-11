"""Shared GraphQL fragments interpolated into multiple query modules."""

from __future__ import annotations

# Canonical `column_values` field selection. The polymorphic inline
# fragments make the computed-column types (mirror, formula, board_relation,
# dependency) return their computed `display_value` (monday returns a null
# `text` for these types), so typed reads no longer need to escape to raw
# GraphQL. Kept as a single-line string so callers can interpolate it into an
# f-string query template (`column_values {{ {COLUMN_VALUES_SELECTION} }}`)
# without doubling the fragment's own braces.
COLUMN_VALUES_SELECTION = (
    "id type text value "
    "... on MirrorValue { display_value } "
    "... on BoardRelationValue { display_value linked_item_ids } "
    "... on FormulaValue { display_value } "
    "... on DependencyValue { display_value linked_item_ids }"
)
