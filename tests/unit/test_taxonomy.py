"""Unit tests for the contradiction taxonomy."""

from crosscheck.detection.taxonomy import V1_TYPES, ContradictionType


def test_v1_types_has_five_members() -> None:
    assert len(V1_TYPES) == 5


def test_v1_types_excludes_fallback_and_reserved() -> None:
    assert ContradictionType.UNCLEAR not in V1_TYPES
    assert ContradictionType.CONDITIONAL_TRIPLET not in V1_TYPES


def test_strenum_value_is_snake_case() -> None:
    assert ContradictionType.DIRECT_NEGATION.value == "direct_negation"
