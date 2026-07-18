"""Filter-expression parsing + relation-codec filter shapes (#109 follow-ups)."""

from __future__ import annotations

import pytest

from mondo.api.errors import UsageError
from mondo.columns import parse_filter_value
from mondo.services.items import split_filter_expr


class TestSplitFilterExpr:
    def test_equality(self) -> None:
        assert split_filter_expr("status=Done") == ("status", "Done", "any_of")

    def test_not_equals(self) -> None:
        assert split_filter_expr("status!=Done") == ("status", "Done", "not_any_of")

    def test_not_equals_inside_value_does_not_shift_split(self) -> None:
        # `item find --column mir0 --value 'a!=b'` round-trips as `mir0=a!=b`;
        # the first separator wins, so the column stays `mir0`.
        assert split_filter_expr("mir0=a!=b") == ("mir0", "a!=b", "any_of")

    def test_equals_inside_negated_value(self) -> None:
        assert split_filter_expr("col!=a=b") == ("col", "a=b", "not_any_of")

    def test_no_separator_raises(self) -> None:
        with pytest.raises(UsageError):
            split_filter_expr("nonsense")


class TestRelationFilterShapes:
    """Filter compare_value for relation types must be INTEGER item ids —
    monday matches nothing on string ids (codex review finding)."""

    @pytest.mark.parametrize("col_type", ["board_relation", "dependency"])
    def test_integer_ids(self, col_type: str) -> None:
        assert parse_filter_value(col_type, "12345", {}) == [12345]
        assert parse_filter_value(col_type, "12345, 678", {}) == [12345, 678]

    @pytest.mark.parametrize("col_type", ["board_relation", "dependency"])
    def test_non_numeric_raises_with_shape_hint(self, col_type: str) -> None:
        with pytest.raises(ValueError, match="integer item IDs"):
            parse_filter_value(col_type, "Alice", {})
