"""The CrossCheck contradiction taxonomy.

Defines :class:`ContradictionType`, the closed set of labels every detection carries.
v1 ships five detectable types (spec v2 §6); ``UNCLEAR`` is the low-confidence
catch-all for ambiguous cases; ``CONDITIONAL_TRIPLET`` is reserved for the roadmap and
carries no v1 detection or evaluation.
"""

from enum import StrEnum


class ContradictionType(StrEnum):
    """The type label attached to every contradiction verdict.

    The five v1 members are the detectable, evaluated categories. ``UNCLEAR`` is used
    when a pair looks contradictory but fits no v1 type, and is reported with low
    confidence rather than dropped. ``CONDITIONAL_TRIPLET`` is reserved for a future
    release (spec v2 §6 roadmap) and must never be produced by v1 detection.
    """

    DIRECT_NEGATION = "direct_negation"
    NUMERICAL_MISMATCH = "numerical_mismatch"
    TEMPORAL_CONFLICT = "temporal_conflict"
    OBLIGATION_REVERSAL = "obligation_reversal"
    SCOPE_JURISDICTION = "scope_jurisdiction"

    # Low-confidence catch-all for contradictory-looking pairs that fit no v1 type.
    UNCLEAR = "unclear"

    # Reserved roadmap type — no v1 detection or evaluation targets it (spec v2 §6).
    CONDITIONAL_TRIPLET = "conditional_triplet"


#: The types v1 actively detects and evaluates (excludes UNCLEAR and the reserved triplet).
V1_TYPES: frozenset[ContradictionType] = frozenset(
    {
        ContradictionType.DIRECT_NEGATION,
        ContradictionType.NUMERICAL_MISMATCH,
        ContradictionType.TEMPORAL_CONFLICT,
        ContradictionType.OBLIGATION_REVERSAL,
        ContradictionType.SCOPE_JURISDICTION,
    }
)
