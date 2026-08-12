"""Tests for the §9.4 scope filter (D55).

The cases here are the real ones: every "fires" test is a false positive the system actually
produced against NIST SP 800-63B, and every "does not fire" test is a true positive from the same
run or from a labelled benchmark. A rule that passes invented examples but drops a real finding
is the failure mode this file exists to prevent.
"""

from __future__ import annotations

from pathlib import Path

from crosscheck.aggregation.report import ContradictionReport, build_report
from crosscheck.detection.scope_filter import spurious_reason
from crosscheck.detection.taxonomy import ContradictionType
from crosscheck.models import Claim, DocumentRef, Pair, SectionRef, Verdict
from crosscheck.orchestrator import AuditResult, AuditStats

# --- cross-reference renumbering ----------------------------------------------------------

_REV3_XREF = (
    "Changing the pre-registered telephone number SHALL only occur as described in Section 6.1.2."
)
_REV4_XREF = (
    "Setting or changing the pre-registered telephone number SHALL only occur as described "
    "in Sec. 4.1.2."
)


def test_renumbered_cross_reference_is_suppressed() -> None:
    assert (
        spurious_reason(ContradictionType.NUMERICAL_MISMATCH, _REV3_XREF, _REV4_XREF)
        == "cross_reference_renumbering"
    )


def test_a_real_numeric_difference_survives() -> None:
    """The 8 -> 15 character minimum: the run's most valuable finding."""
    a = (
        "Verifiers SHALL require subscriber-chosen memorized secrets to be at least "
        "8 characters in length."
    )
    b = (
        "Verifiers and CSPs shall require passwords that are used as a single-factor "
        "authentication mechanism to be a minimum of 15 characters in length."
    )
    assert spurious_reason(ContradictionType.NUMERICAL_MISMATCH, a, b) is None


def test_cross_reference_rule_ignores_other_types() -> None:
    """Numbers are incidental outside a numerical mismatch, so the rule must not vote."""
    assert spurious_reason(ContradictionType.OBLIGATION_REVERSAL, _REV3_XREF, _REV4_XREF) is None


def test_identical_numbers_do_not_trigger_the_rule() -> None:
    a = "The salt SHALL be at least 32 bits in length as described in Section 5.1."
    b = "The salt shall be at least 32 bits in length as described in Section 5.1."
    assert spurious_reason(ContradictionType.NUMERICAL_MISMATCH, a, b) is None


# --- complementary thresholds -------------------------------------------------------------


def test_complementary_thresholds_are_suppressed() -> None:
    a = (
        "Look-up secrets having at least 112 bits of entropy SHALL be hashed with an "
        "approved one-way function."
    )
    b = (
        "Look-up secrets that are shorter than 112 bits shall be stored in a salted and hashed "
        "form using a suitable password hashing scheme."
    )
    assert (
        spurious_reason(ContradictionType.OBLIGATION_REVERSAL, a, b) == "complementary_thresholds"
    )


def test_two_floors_are_not_complementary() -> None:
    """Both claims bound from below at different values — a genuine mismatch, not a partition."""
    a = "Memorized secrets chosen randomly by the CSP SHALL be at least 6 characters in length."
    b = "Passwords shall be a minimum of 15 characters in length."
    assert spurious_reason(ContradictionType.NUMERICAL_MISMATCH, a, b) is None


def test_opposite_bounds_on_different_values_are_not_complementary() -> None:
    a = "Secrets SHALL be at least 112 bits in length."
    b = "Secrets shorter than 64 bits shall be rejected."
    assert spurious_reason(ContradictionType.NUMERICAL_MISMATCH, a, b) is None


# --- wiring into the report ---------------------------------------------------------------


def _report_from(
    text_a: str, text_b: str, kind: ContradictionType, *, scope_filter: bool
) -> ContradictionReport:
    docs = [
        DocumentRef(
            doc_id="d1",
            source_path=Path("/corpus/rev3.md"),
            title="Rev 3",
            sections=[SectionRef(section_id="s1", heading="5.1.3.3")],
        ),
        DocumentRef(
            doc_id="d2",
            source_path=Path("/corpus/rev4.md"),
            title="Rev 4",
            sections=[SectionRef(section_id="s2", heading="PSTN")],
        ),
    ]
    claims = [
        Claim(
            claim_id="c1",
            doc_id="d1",
            section_id="s1",
            text=text_a,
            evidence_quote=text_a,
            evidence_offset=(0, len(text_a)),
            subject="telephone number",
            predicate="changes",
            polarity="positive",
        ),
        Claim(
            claim_id="c2",
            doc_id="d2",
            section_id="s2",
            text=text_b,
            evidence_quote=text_b,
            evidence_offset=(0, len(text_b)),
            subject="telephone number",
            predicate="changes",
            polarity="positive",
        ),
    ]
    pairs = [
        Pair(
            pair_id="p1",
            claim_a_id="c1",
            claim_b_id="c2",
            retrieval_score=0.5,
            rerank_score=0.9,
            nli_contradiction_prob=0.9,
        )
    ]
    verdicts = [
        Verdict(
            pair_id="p1",
            is_contradiction=True,
            contradiction_type=kind,
            confidence=0.92,
            rationale="Two different section numbers.",
            evidence_a=text_a,
            evidence_b=text_b,
            resolution_hint=None,
        )
    ]
    result = AuditResult(
        audit_id="aid",
        corpus_path=Path("/corpus"),
        documents=docs,
        claims=claims,
        judged_pairs=pairs,
        verdicts=verdicts,
        stats=AuditStats(document_count=2, claim_count=2, nli_kept_count=1),
    )
    return build_report(result, scope_filter=scope_filter)


def test_build_report_suppresses_a_renumbered_cross_reference() -> None:
    report = _report_from(
        _REV3_XREF, _REV4_XREF, ContradictionType.NUMERICAL_MISMATCH, scope_filter=True
    )
    assert report.contradiction_count == 0
    assert report.is_empty


def test_build_report_keeps_it_when_the_filter_is_off() -> None:
    """The escape hatch has to work, or the filter cannot be audited against the judge."""
    report = _report_from(
        _REV3_XREF, _REV4_XREF, ContradictionType.NUMERICAL_MISMATCH, scope_filter=False
    )
    assert report.contradiction_count == 1
