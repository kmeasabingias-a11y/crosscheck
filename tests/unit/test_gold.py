"""Unit tests for the gold-label schema and matching primitive (§9.1, §9.2, decision D36)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from crosscheck.aggregation.report import Finding, build_report
from crosscheck.detection.taxonomy import ContradictionType
from crosscheck.evaluation.gold import (
    GoldPair,
    GoldSet,
    GoldSide,
    duplicate_section_keys,
    first_match,
    gold_id,
    load_gold_set,
    matches,
    write_gold_set,
)
from crosscheck.models import Claim, DocumentRef, Pair, SectionRef, Verdict
from crosscheck.orchestrator import AuditResult, AuditStats

_TEXT_A = "Unused paid time off does not carry over into the following calendar year."
_TEXT_B = "Employees may carry over up to 5 unused paid time off days."


def _side(document: str, section_id: str | None, text: str) -> GoldSide:
    return GoldSide(
        document=document,
        section_id=section_id,
        section_heading="2. Paid Time Off",
        text=text,
        evidence_quote=text,
        char_span=(0, len(text)),
    )


def _pair(
    *,
    section_a: str | None = "s1",
    section_b: str | None = "s2",
    doc_a: str = "01_handbook.md",
    doc_b: str = "02_pto.md",
    contradiction_type: ContradictionType = ContradictionType.DIRECT_NEGATION,
    review_verdict: str | None = None,
) -> GoldPair:
    a = _side(doc_a, section_a, _TEXT_A)
    b = _side(doc_b, section_b, _TEXT_B)
    return GoldPair(
        pair_id=gold_id(a, b),
        contradiction_type=contradiction_type,
        a=a,
        b=b,
        origin="injected",
        generator_model="gpt-4o",
        review_verdict=review_verdict,  # type: ignore[arg-type]
    )


def _finding(
    *, section_a: str = "s1", section_b: str = "s2", doc_a: str = "01_handbook.md"
) -> Finding:
    """Build a real Finding by running a tiny audit result through the report builder."""
    docs = [
        DocumentRef(
            doc_id="d1",
            source_path=Path(f"/corpus/{doc_a}"),
            sections=[SectionRef(section_id=section_a, heading="2. Paid Time Off")],
        ),
        DocumentRef(
            doc_id="d2",
            source_path=Path("/corpus/02_pto.md"),
            sections=[SectionRef(section_id=section_b, heading="3. Carry-Over")],
        ),
    ]

    def claim(cid: str, did: str, sid: str, text: str, polarity: str) -> Claim:
        return Claim(
            claim_id=cid,
            doc_id=did,
            section_id=sid,
            text=text,
            evidence_quote=text,
            evidence_offset=(0, len(text)),
            subject="paid time off",
            predicate="carries over",
            polarity="negative" if polarity == "negative" else "positive",
        )

    result = AuditResult(
        audit_id="aid",
        corpus_path=Path("/corpus"),
        documents=docs,
        claims=[
            claim("c1", "d1", section_a, _TEXT_A, "negative"),
            claim("c2", "d2", section_b, _TEXT_B, "positive"),
        ],
        judged_pairs=[Pair(pair_id="p1", claim_a_id="c1", claim_b_id="c2")],
        verdicts=[
            Verdict(
                pair_id="p1",
                is_contradiction=True,
                contradiction_type=ContradictionType.DIRECT_NEGATION,
                confidence=0.9,
                rationale="r",
                evidence_a=_TEXT_A,
                evidence_b=_TEXT_B,
            )
        ],
        stats=AuditStats(document_count=2, claim_count=2, nli_kept_count=1),
    )
    return build_report(result).findings[0]


# --- schema ------------------------------------------------------------------------------


def test_gold_id_is_order_independent_and_deterministic() -> None:
    a, b = _side("a.md", "s1", _TEXT_A), _side("b.md", "s2", _TEXT_B)
    assert gold_id(a, b) == gold_id(b, a)
    assert gold_id(a, b) == gold_id(a, b)


def test_gold_id_changes_with_content() -> None:
    a, b = _side("a.md", "s1", _TEXT_A), _side("b.md", "s2", _TEXT_B)
    assert gold_id(a, b) != gold_id(a, _side("b.md", "s2", "something else"))


def test_reserved_triplet_type_is_rejected_as_a_gold_label() -> None:
    """v1 detects five types; a gold label outside them would score against nothing (§6)."""
    with pytest.raises(ValidationError):
        _pair(contradiction_type=ContradictionType.CONDITIONAL_TRIPLET)


def test_unclear_is_rejected_as_a_gold_label() -> None:
    with pytest.raises(ValidationError):
        _pair(contradiction_type=ContradictionType.UNCLEAR)


def test_review_verdicts_drop_a_pair_from_the_usable_set() -> None:
    gold = GoldSet(
        name="s",
        corpus_dir="corpus",
        pairs=[
            _pair(),
            _pair(section_a="s3", review_verdict="implausible"),
            _pair(section_a="s4", review_verdict="mislabelled"),
            _pair(section_a="s5", review_verdict="plausible"),
        ],
    )
    assert len(gold.pairs) == 4
    assert len(gold.usable_pairs) == 2
    assert gold.type_counts == {"direct_negation": 2}


# --- the §9.1 cross-model guard ----------------------------------------------------------


def test_cross_model_is_true_for_different_families() -> None:
    gold = GoldSet(
        name="s",
        corpus_dir="c",
        generator_model="gpt-4o",
        judge_model_at_authoring="claude-sonnet-4-6",
    )
    assert gold.cross_model is True


def test_cross_model_is_false_for_the_same_family() -> None:
    gold = GoldSet(
        name="s",
        corpus_dir="c",
        generator_model="claude-opus-4-8",
        judge_model_at_authoring="claude-sonnet-4-6",
    )
    assert gold.cross_model is False


def test_cross_model_is_unknown_when_a_model_is_unrecorded() -> None:
    """'Unknown' and 'fine' are different answers — never conflate them."""
    assert GoldSet(name="s", corpus_dir="c", generator_model="gpt-4o").cross_model is None


# --- matching ----------------------------------------------------------------------------


def test_a_finding_matches_the_gold_pair_it_reports() -> None:
    assert matches(_finding(), _pair())


def test_matching_is_order_independent() -> None:
    """The finding's sides are filename-ordered; gold may be authored either way round."""
    reversed_gold = _pair(doc_a="02_pto.md", doc_b="01_handbook.md", section_a="s2", section_b="s1")
    assert matches(_finding(), reversed_gold)


def test_a_finding_in_other_sections_does_not_match() -> None:
    assert not matches(_finding(section_a="s9"), _pair())


def test_a_finding_in_other_documents_does_not_match() -> None:
    assert not matches(_finding(doc_a="99_other.md"), _pair())


def test_type_disagreement_still_counts_as_a_match() -> None:
    """Finding it and labelling it are separate questions, reported separately (§9.2)."""
    assert matches(_finding(), _pair(contradiction_type=ContradictionType.NUMERICAL_MISMATCH))


def test_first_match_returns_none_when_nothing_matches() -> None:
    assert first_match(_finding(), [_pair(section_a="s9")]) is None
    assert first_match(_finding(), []) is None


def test_first_match_returns_the_matching_pair() -> None:
    wanted = _pair()
    assert first_match(_finding(), [_pair(section_a="s9"), wanted]) is wanted


# --- granularity -------------------------------------------------------------------------


def test_a_pair_without_section_ids_is_document_level() -> None:
    pair = _pair(section_a=None, section_b=None)
    assert pair.granularity == "document"


def test_document_level_gold_matches_any_finding_between_those_documents() -> None:
    pair = _pair(section_a=None, section_b=None)
    assert matches(_finding(section_a="s1"), pair)
    assert matches(_finding(section_a="whatever"), pair)
    # Still bounded by the documents.
    assert not matches(_finding(doc_a="99_other.md"), pair)


def test_a_half_specified_pair_degrades_to_document_level() -> None:
    """One missing section id must not silently produce a key that matches nothing."""
    pair = _pair(section_b=None)
    assert pair.granularity == "document"
    assert matches(_finding(), pair)


# --- collision detection -----------------------------------------------------------------


def test_duplicate_section_keys_are_reported() -> None:
    """Two gold pairs in the same section pair are indistinguishable to section matching."""
    collisions = duplicate_section_keys([_pair(), _pair(), _pair(section_a="s7")])
    assert len(collisions) == 1


def test_no_duplicates_reported_when_keys_are_distinct() -> None:
    assert duplicate_section_keys([_pair(), _pair(section_a="s7")]) == []


# --- IO ----------------------------------------------------------------------------------


def test_gold_set_round_trips_through_json(tmp_path: Path) -> None:
    gold = GoldSet(
        name="synthetic-v1",
        corpus_dir="corpus",
        seed=42,
        generator_model="gpt-4o",
        judge_model_at_authoring="claude-sonnet-4-6",
        pairs=[_pair(), _pair(section_a="s7")],
    )
    path = tmp_path / "nested" / "gold.json"
    write_gold_set(gold, path)

    reloaded = load_gold_set(path)
    assert reloaded.model_dump_json() == gold.model_dump_json()
    assert reloaded.seed == 42
    assert reloaded.cross_model is True
