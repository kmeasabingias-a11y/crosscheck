"""Unit tests for report assembly (spec v2 §7.5, decisions D33/D34)."""

from datetime import UTC, datetime
from pathlib import Path

from crosscheck.aggregation.report import (
    ContradictionReport,
    build_report,
    load_report,
    locate_quote,
    write_json,
)
from crosscheck.detection.taxonomy import ContradictionType
from crosscheck.models import Claim, DocumentRef, Pair, SectionRef, Verdict
from crosscheck.orchestrator import AuditResult, AuditStats

# --- fixtures ----------------------------------------------------------------------------

_QUOTE_A = "Unused paid time off does not carry over into the following calendar year."
_QUOTE_B = "Employees may carry over up to 5 unused paid time off days."


def _doc(doc_id: str, name: str, *sections: tuple[str, str]) -> DocumentRef:
    return DocumentRef(
        doc_id=doc_id,
        source_path=Path(f"/corpus/{name}"),
        title=name.replace("_", " "),
        sections=[SectionRef(section_id=sid, heading=heading) for sid, heading in sections],
    )


def _claim(
    claim_id: str,
    doc_id: str,
    section_id: str,
    text: str,
    *,
    subject: str = "paid time off",
    polarity: str = "positive",
) -> Claim:
    return Claim(
        claim_id=claim_id,
        doc_id=doc_id,
        section_id=section_id,
        text=text,
        evidence_quote=text,
        evidence_offset=(0, len(text)),
        subject=subject,
        predicate="carries over",
        polarity="positive" if polarity == "positive" else "negative",
    )


def _verdict(
    pair_id: str,
    *,
    confidence: float = 0.9,
    evidence_a: str = _QUOTE_A,
    evidence_b: str = _QUOTE_B,
    contradiction_type: ContradictionType | None = ContradictionType.DIRECT_NEGATION,
    is_contradiction: bool = True,
) -> Verdict:
    return Verdict(
        pair_id=pair_id,
        is_contradiction=is_contradiction,
        contradiction_type=contradiction_type,
        confidence=confidence,
        rationale="They cannot both hold.",
        evidence_a=evidence_a,
        evidence_b=evidence_b,
        resolution_hint="v2 controls.",
    )


def _result(
    *,
    claims: list[Claim],
    pairs: list[Pair],
    verdicts: list[Verdict],
    documents: list[DocumentRef],
    stats: AuditStats | None = None,
    partial: bool = False,
) -> AuditResult:
    return AuditResult(
        audit_id="aid",
        corpus_path=Path("/corpus"),
        documents=documents,
        claims=claims,
        judged_pairs=pairs,
        verdicts=verdicts,
        stats=stats or AuditStats(document_count=2, claim_count=len(claims), nli_kept_count=1),
        partial=partial,
    )


def _simple_result() -> AuditResult:
    docs = [
        _doc("d1", "01_employee_handbook.md", ("s1", "2. Paid Time Off")),
        _doc("d2", "02_pto_policy_v2.md", ("s2", "3. Carry-Over")),
    ]
    claims = [
        _claim("c1", "d1", "s1", _QUOTE_A, polarity="negative"),
        _claim("c2", "d2", "s2", _QUOTE_B),
    ]
    pairs = [
        Pair(
            pair_id="p1",
            claim_a_id="c1",
            claim_b_id="c2",
            retrieval_score=0.03,
            rerank_score=0.88,
            nli_contradiction_prob=0.97,
        )
    ]
    return _result(claims=claims, pairs=pairs, verdicts=[_verdict("p1")], documents=docs)


# --- locate_quote ------------------------------------------------------------------------


def test_locate_quote_finds_an_exact_span() -> None:
    assert locate_quote("alpha beta gamma", "beta") == (6, 10)


def test_locate_quote_tolerates_rewrapped_whitespace() -> None:
    # The judge normalizes a source's line wrap to spaces (D20); the span must still resolve.
    span = locate_quote("alpha beta\ngamma delta", "beta gamma")
    assert span is not None and "alpha beta\ngamma delta"[span[0] : span[1]] == "beta\ngamma"


def test_locate_quote_rejects_a_fabricated_quote() -> None:
    assert locate_quote("alpha beta gamma", "beta epsilon") is None
    assert locate_quote("alpha", "   ") is None


# --- assembly ----------------------------------------------------------------------------


def test_build_report_joins_verdict_claims_and_citations() -> None:
    report = build_report(_simple_result())

    assert report.contradiction_count == 1
    assert not report.is_empty
    finding = report.findings[0]
    assert finding.a.filename == "01_employee_handbook.md"
    assert finding.a.section_heading == "2. Paid Time Off"
    assert finding.b.filename == "02_pto_policy_v2.md"
    assert finding.b.section_heading == "3. Carry-Over"
    assert finding.a.polarity == "negative"
    assert finding.subject == "paid time off"
    assert finding.rerank_score == 0.88
    assert finding.nli_contradiction_prob == 0.97


def test_highlight_span_indexes_into_the_evidence_quote() -> None:
    report = build_report(_simple_result())
    side = report.findings[0].a
    assert side.highlight_span is not None
    start, end = side.highlight_span
    assert side.evidence_quote[start:end] == side.highlight


def test_highlight_span_is_none_when_the_judge_quoted_the_claim_text() -> None:
    result = _simple_result()
    result.verdicts = [_verdict("p1", evidence_a="something else entirely")]
    side = build_report(result).findings[0].a
    assert side.highlight_span is None
    assert side.highlight == "something else entirely"


def test_untyped_contradiction_is_reported_as_unclear() -> None:
    result = _simple_result()
    result.verdicts = [_verdict("p1", contradiction_type=None)]
    assert build_report(result).findings[0].contradiction_type is ContradictionType.UNCLEAR


def test_non_contradiction_verdicts_are_not_reported() -> None:
    result = _simple_result()
    result.verdicts = [_verdict("p1", is_contradiction=False)]
    report = build_report(result)
    assert report.is_empty
    assert report.groups == []


def test_missing_claims_are_skipped_rather_than_raising() -> None:
    # A partial audit can leave a verdict whose claims never made it into the result.
    result = _simple_result()
    result.claims = [result.claims[0]]
    assert build_report(result).is_empty


# --- D34: grouping -----------------------------------------------------------------------


def test_findings_are_grouped_by_document_pair_and_sorted_by_filename() -> None:
    docs = [
        _doc("d1", "01_handbook.md", ("s1", "A")),
        _doc("d2", "02_pto.md", ("s2", "B")),
        _doc("d3", "03_remote.txt", ("s3", "C")),
    ]
    claims = [
        _claim("c1", "d1", "s1", _QUOTE_A),
        _claim("c2", "d2", "s2", _QUOTE_B),
        _claim("c3", "d3", "s3", _QUOTE_B),
    ]
    pairs = [
        Pair(pair_id="p1", claim_a_id="c1", claim_b_id="c3"),
        Pair(pair_id="p2", claim_a_id="c1", claim_b_id="c2"),
    ]
    verdicts = [_verdict("p1", confidence=0.5), _verdict("p2", confidence=0.9)]
    report = build_report(_result(claims=claims, pairs=pairs, verdicts=verdicts, documents=docs))

    assert [(group.doc_a, group.doc_b) for group in report.groups] == [
        ("01_handbook.md", "02_pto.md"),
        ("01_handbook.md", "03_remote.txt"),
    ]
    assert all(group.finding_count == 1 for group in report.groups)


def test_sides_are_ordered_by_filename_not_by_claim_hash() -> None:
    """Pair order comes from content hashes; the report must not expose that ordering."""
    docs = [_doc("d1", "01_handbook.md", ("s1", "A")), _doc("d2", "02_pto.md", ("s2", "B"))]
    claims = [_claim("c1", "d1", "s1", _QUOTE_A), _claim("c2", "d2", "s2", _QUOTE_B)]
    # Pair built "backwards": claim A is the second document.
    pairs = [Pair(pair_id="p1", claim_a_id="c2", claim_b_id="c1")]
    report = build_report(
        _result(claims=claims, pairs=pairs, verdicts=[_verdict("p1")], documents=docs)
    )

    finding = report.findings[0]
    assert (finding.a.filename, finding.b.filename) == ("01_handbook.md", "02_pto.md")
    group = report.groups[0]
    assert (group.doc_a, group.doc_b) == ("01_handbook.md", "02_pto.md")


def test_reversed_pairs_land_in_the_same_group() -> None:
    """A→B and B→A must not produce two groups for one document pair."""
    docs = [
        _doc("d1", "01_handbook.md", ("s1", "A"), ("s3", "C")),
        _doc("d2", "02_pto.md", ("s2", "B"), ("s4", "D")),
    ]
    claims = [
        _claim("c1", "d1", "s1", _QUOTE_A),
        _claim("c2", "d2", "s2", _QUOTE_B),
        _claim("c3", "d1", "s3", _QUOTE_A),
        _claim("c4", "d2", "s4", _QUOTE_B),
    ]
    pairs = [
        Pair(pair_id="p1", claim_a_id="c1", claim_b_id="c2"),
        Pair(pair_id="p2", claim_a_id="c4", claim_b_id="c3"),  # reversed
    ]
    verdicts = [_verdict("p1"), _verdict("p2", confidence=0.7)]
    report = build_report(_result(claims=claims, pairs=pairs, verdicts=verdicts, documents=docs))

    assert len(report.groups) == 1
    assert report.groups[0].finding_count == 2


def test_findings_within_a_group_are_ordered_by_confidence() -> None:
    docs = [_doc("d1", "a.md", ("s1", "A"), ("s3", "C")), _doc("d2", "b.md", ("s2", "B"))]
    claims = [
        _claim("c1", "d1", "s1", _QUOTE_A),
        _claim("c2", "d2", "s2", _QUOTE_B),
        _claim("c3", "d1", "s3", _QUOTE_A),
    ]
    pairs = [
        Pair(pair_id="p_low", claim_a_id="c1", claim_b_id="c2"),
        Pair(pair_id="p_high", claim_a_id="c3", claim_b_id="c2"),
    ]
    verdicts = [_verdict("p_low", confidence=0.4), _verdict("p_high", confidence=0.95)]
    report = build_report(_result(claims=claims, pairs=pairs, verdicts=verdicts, documents=docs))

    assert [finding.pair_id for finding in report.groups[0].findings] == ["p_high", "p_low"]


def test_same_section_findings_roll_up_under_the_most_confident_one() -> None:
    """The Phase 3 smoke run reported one semantic conflict twice from the same two sections."""
    docs = [
        _doc("d1", "08_security.pdf", ("s1", "4. Patching")),
        _doc("d2", "09_it.pdf", ("s2", "4. Patching")),
    ]
    claims = [
        _claim("c1", "d1", "s1", _QUOTE_A),
        _claim("c2", "d2", "s2", _QUOTE_B),
        _claim("c3", "d1", "s1", _QUOTE_A),
        _claim("c4", "d2", "s2", _QUOTE_B),
    ]
    pairs = [
        Pair(pair_id="p1", claim_a_id="c1", claim_b_id="c2"),
        Pair(pair_id="p2", claim_a_id="c3", claim_b_id="c4"),
    ]
    verdicts = [_verdict("p1", confidence=0.6), _verdict("p2", confidence=0.85)]
    report = build_report(_result(claims=claims, pairs=pairs, verdicts=verdicts, documents=docs))

    group = report.groups[0]
    assert group.finding_count == 1
    primary = group.findings[0]
    assert primary.pair_id == "p2"
    assert [dupe.pair_id for dupe in primary.near_duplicates] == ["p1"]
    # Rolled up for display, still counted and still exported (§9.2 needs every verdict).
    assert report.contradiction_count == 2


def test_different_sections_in_the_same_document_pair_are_not_rolled_up() -> None:
    docs = [
        _doc("d1", "06_msa.docx", ("s1", "4. Subcontracting"), ("s3", "7. Governing Law")),
        _doc("d2", "07_eu.docx", ("s2", "4. Subcontracting"), ("s4", "6. Governing Law")),
    ]
    claims = [
        _claim("c1", "d1", "s1", _QUOTE_A),
        _claim("c2", "d2", "s2", _QUOTE_B),
        _claim("c3", "d1", "s3", _QUOTE_A),
        _claim("c4", "d2", "s4", _QUOTE_B),
    ]
    pairs = [
        Pair(pair_id="p1", claim_a_id="c1", claim_b_id="c2"),
        Pair(pair_id="p2", claim_a_id="c3", claim_b_id="c4"),
    ]
    verdicts = [_verdict("p1"), _verdict("p2", confidence=0.7)]
    report = build_report(_result(claims=claims, pairs=pairs, verdicts=verdicts, documents=docs))

    assert report.groups[0].finding_count == 2


# --- empty path and export ---------------------------------------------------------------


def test_empty_report_is_well_formed_not_an_error() -> None:
    stats = AuditStats(document_count=10, claim_count=342, nli_kept_count=906)
    report = build_report(_result(claims=[], pairs=[], verdicts=[], documents=[], stats=stats))

    assert report.is_empty
    assert report.groups == []
    assert report.type_counts == {}
    # The empty state needs real numbers to say "we looked and found nothing".
    assert (report.document_count, report.claim_count, report.pairs_evaluated) == (10, 342, 906)


def test_type_counts_follow_the_taxonomy_order() -> None:
    report = build_report(_simple_result())
    assert report.type_counts == {"direct_negation": 1}


def test_partial_state_survives_into_the_report() -> None:
    result = _simple_result()
    result.partial = True
    result.partial_reason = "audit cost ceiling reached while judging"
    report = build_report(result)
    assert report.partial and report.partial_reason is not None


def test_report_round_trips_through_json(tmp_path: Path) -> None:
    report = build_report(_simple_result(), generated_at=datetime(2026, 8, 1, 19, 7, tzinfo=UTC))
    path = tmp_path / "nested" / "report.json"
    write_json(report, path)

    reloaded = load_report(path)
    assert isinstance(reloaded, ContradictionReport)
    assert reloaded.model_dump_json() == report.model_dump_json()
    assert reloaded.findings[0].a.filename == "01_employee_handbook.md"


def test_report_is_deterministic_without_a_timestamp() -> None:
    first = build_report(_simple_result())
    second = build_report(_simple_result())
    assert first.model_dump_json() == second.model_dump_json()
