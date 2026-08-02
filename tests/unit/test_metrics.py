"""Unit tests for the benchmark metrics module (§9.2)."""

import pytest

from crosscheck.aggregation.report import ContradictionReport, Finding, FindingSide
from crosscheck.detection.taxonomy import ContradictionType
from crosscheck.evaluation.gold import GoldPair, GoldSet, GoldSide, gold_id
from crosscheck.evaluation.metrics import (
    Counts,
    calibrate,
    expand,
    lexical_overlap,
    match_findings,
    score_benchmark,
    score_detection,
)
from crosscheck.orchestrator import AuditStats

_A = "Vendors must carry liability insurance for the duration of the engagement."
_B = "Vendors are not required to carry liability insurance."
_UNRELATED = "Quarterly board minutes shall be archived offsite."


def _gold_side(document: str, section: str, text: str) -> GoldSide:
    return GoldSide(
        document=document,
        section_id=section,
        section_heading=section,
        text=text,
        evidence_quote=text,
        char_span=(0, len(text)),
    )


def _gold(
    *,
    doc_a: str = "a.md",
    sec_a: str = "s1",
    doc_b: str = "b.md",
    sec_b: str = "s2",
    text_a: str = _A,
    text_b: str = _B,
    contradiction_type: ContradictionType = ContradictionType.OBLIGATION_REVERSAL,
) -> GoldPair:
    a = _gold_side(doc_a, sec_a, text_a)
    b = _gold_side(doc_b, sec_b, text_b)
    return GoldPair(
        pair_id=gold_id(a, b),
        contradiction_type=contradiction_type,
        a=a,
        b=b,
        origin="injected",
        generator_model="gpt-4.1",
    )


def _side(document: str, section: str, text: str) -> FindingSide:
    return FindingSide(
        claim_id=f"{document}:{section}",
        doc_id=document,
        filename=document,
        section_id=section,
        claim_text=text,
        evidence_quote=text,
        highlight=text,
        polarity="positive",
    )


def _finding(
    *,
    pair_id: str = "p1",
    doc_a: str = "a.md",
    sec_a: str = "s1",
    doc_b: str = "b.md",
    sec_b: str = "s2",
    text_a: str = _A,
    text_b: str = _B,
    confidence: float = 0.9,
    contradiction_type: ContradictionType = ContradictionType.OBLIGATION_REVERSAL,
    near_duplicates: list[Finding] | None = None,
) -> Finding:
    return Finding(
        pair_id=pair_id,
        contradiction_type=contradiction_type,
        confidence=confidence,
        subject="liability insurance",
        rationale="one mandates, the other exempts",
        a=_side(doc_a, sec_a, text_a),
        b=_side(doc_b, sec_b, text_b),
        near_duplicates=near_duplicates or [],
    )


class TestCounts:
    def test_rates(self) -> None:
        counts = Counts(true_positives=3, false_positives=1, false_negatives=1)
        assert counts.precision == pytest.approx(0.75)
        assert counts.recall == pytest.approx(0.75)
        assert counts.f1 == pytest.approx(0.75)

    def test_no_predictions_is_zero_not_a_crash(self) -> None:
        counts = Counts(false_negatives=4)
        assert counts.precision == 0.0
        assert counts.recall == 0.0
        assert counts.f1 == 0.0

    def test_perfect(self) -> None:
        counts = Counts(true_positives=5)
        assert counts.precision == 1.0
        assert counts.recall == 1.0
        assert counts.f1 == 1.0


class TestLexicalOverlap:
    def test_identical_text_is_one(self) -> None:
        assert lexical_overlap(_A, _A) == pytest.approx(1.0)

    def test_disjoint_text_is_zero(self) -> None:
        assert lexical_overlap("alpha beta", "gamma delta") == 0.0

    def test_empty_is_zero_not_a_crash(self) -> None:
        assert lexical_overlap("", "") == 0.0
        assert lexical_overlap("", _A) == 0.0

    def test_ignores_case_and_punctuation(self) -> None:
        assert lexical_overlap("Refunds, within 30 days.", "refunds within 30 days") == 1.0

    def test_partial_overlap(self) -> None:
        # {a, b, c} vs {b, c, d} -> 2 shared of 4 distinct
        assert lexical_overlap("a b c", "b c d") == pytest.approx(0.5)


class TestExpand:
    def test_includes_rolled_up_duplicates(self) -> None:
        child = _finding(pair_id="p2")
        parent = _finding(pair_id="p1", near_duplicates=[child])
        assert [f.pair_id for f in expand([parent])] == ["p1", "p2"]

    def test_without_duplicates_is_identity(self) -> None:
        assert len(expand([_finding(), _finding(pair_id="p2")])) == 2


class TestMatchFindings:
    def test_matches_on_section_pair(self) -> None:
        gold = _gold()
        result = match_findings([_finding()], [gold])
        assert len(result.matched) == 1
        assert result.matched[0][1].pair_id == gold.pair_id
        assert not result.unmatched_findings
        assert not result.unmatched_gold

    def test_unmatched_finding_and_unmatched_gold(self) -> None:
        result = match_findings([_finding(sec_a="other")], [_gold()])
        assert len(result.unmatched_findings) == 1
        assert len(result.unmatched_gold) == 1
        assert not result.matched

    def test_a_gold_pair_is_claimed_once_and_the_rest_are_duplicates(self) -> None:
        gold = _gold()
        weak = _finding(pair_id="weak", confidence=0.2)
        strong = _finding(pair_id="strong", confidence=0.95)
        result = match_findings([weak, strong], [gold])
        assert len(result.matched) == 1
        # The stronger finding wins the gold pair; the weaker is a duplicate, not an error.
        assert result.matched[0][0].pair_id == "strong"
        assert [f.pair_id for f in result.duplicates] == ["weak"]
        assert not result.unmatched_findings

    def test_ties_break_deterministically(self) -> None:
        gold = _gold()
        first = _finding(pair_id="aaa", confidence=0.5)
        second = _finding(pair_id="bbb", confidence=0.5)
        forward = match_findings([first, second], [gold])
        backward = match_findings([second, first], [gold])
        assert forward.matched[0][0].pair_id == backward.matched[0][0].pair_id == "aaa"

    def test_empty_inputs(self) -> None:
        result = match_findings([], [])
        assert not result.matched and not result.unmatched_findings and not result.unmatched_gold


class TestCalibrate:
    def test_perfectly_calibrated_has_no_error(self) -> None:
        # Confidence 0.95 and always right; confidence 0.05 and always wrong.
        samples = [(0.95, True)] * 10 + [(0.05, False)] * 10
        calibration = calibrate(samples, bins=10)
        assert calibration.expected_error == pytest.approx(0.05, abs=1e-9)
        assert calibration.sample_count == 20

    def test_overconfidence_shows_as_a_positive_gap(self) -> None:
        calibration = calibrate([(0.9, False)] * 4, bins=10)
        hot = [b for b in calibration.bins if b.count]
        assert len(hot) == 1
        assert hot[0].gap == pytest.approx(0.9)
        assert calibration.expected_error == pytest.approx(0.9)
        assert calibration.max_error == pytest.approx(0.9)

    def test_empty_bins_are_kept_for_a_stable_axis(self) -> None:
        calibration = calibrate([(0.55, True)], bins=10)
        assert len(calibration.bins) == 10
        assert sum(1 for b in calibration.bins if b.count) == 1

    def test_confidence_of_one_lands_in_the_last_bin(self) -> None:
        calibration = calibrate([(1.0, True)], bins=10)
        assert calibration.bins[-1].count == 1

    def test_brier_score(self) -> None:
        assert calibrate([(1.0, True), (0.0, False)]).brier == pytest.approx(0.0)
        assert calibrate([(1.0, False)]).brier == pytest.approx(1.0)

    def test_no_samples(self) -> None:
        calibration = calibrate([])
        assert calibration.sample_count == 0
        assert calibration.expected_error == 0.0
        assert calibration.brier == 0.0


class TestScoreDetection:
    def test_counts_and_rates(self) -> None:
        gold = [_gold(), _gold(doc_a="c.md", sec_a="s3", doc_b="d.md", sec_b="s4")]
        findings = [_finding(), _finding(pair_id="spurious", doc_a="x.md", sec_a="s9")]
        metrics = score_detection(findings, gold, granularity="grouped")
        assert metrics.overall.true_positives == 1
        assert metrics.overall.false_positives == 1
        assert metrics.overall.false_negatives == 1
        assert metrics.matched_count == 1
        assert metrics.duplicate_count == 0

    def test_duplicates_are_not_false_positives(self) -> None:
        gold = [_gold()]
        findings = [_finding(pair_id="p1"), _finding(pair_id="p2", confidence=0.1)]
        metrics = score_detection(findings, gold, granularity="per_verdict")
        assert metrics.overall.true_positives == 1
        assert metrics.overall.false_positives == 0
        assert metrics.duplicate_count == 1

    def test_type_agreement_and_confusion(self) -> None:
        gold = [_gold(contradiction_type=ContradictionType.OBLIGATION_REVERSAL)]
        findings = [_finding(contradiction_type=ContradictionType.DIRECT_NEGATION)]
        metrics = score_detection(findings, gold, granularity="grouped")
        assert metrics.type_agreement == 0.0
        assert metrics.type_confusion == {"obligation_reversal": {"direct_negation": 1}}

    def test_a_mislabelled_hit_is_still_a_true_positive(self) -> None:
        # Matching deliberately ignores type (D36): finding it and labelling it are separate.
        gold = [_gold(contradiction_type=ContradictionType.OBLIGATION_REVERSAL)]
        findings = [_finding(contradiction_type=ContradictionType.NUMERICAL_MISMATCH)]
        metrics = score_detection(findings, gold, granularity="grouped")
        assert metrics.overall.true_positives == 1
        assert metrics.overall.false_positives == 0

    def test_by_type_attributes_misses_to_the_gold_type(self) -> None:
        gold = [
            _gold(contradiction_type=ContradictionType.TEMPORAL_CONFLICT),
            _gold(
                doc_a="c.md",
                sec_a="s3",
                doc_b="d.md",
                sec_b="s4",
                contradiction_type=ContradictionType.TEMPORAL_CONFLICT,
            ),
        ]
        metrics = score_detection([_finding()], gold, granularity="grouped")
        temporal = metrics.by_type["temporal_conflict"]
        assert temporal.true_positives == 1
        assert temporal.false_negatives == 1

    def test_strata_split_on_overlap(self) -> None:
        # Identical texts -> overlap 1.0 (high); disjoint texts -> 0.0 (low).
        high = _gold(text_a=_A, text_b=_A)
        low = _gold(
            doc_a="c.md", sec_a="s3", doc_b="d.md", sec_b="s4", text_a="alpha", text_b="beta"
        )
        metrics = score_detection([], [high, low], granularity="grouped")
        by_name = {s.name: s for s in metrics.strata}
        assert by_name["high_overlap"].counts.false_negatives == 1
        assert by_name["low_overlap"].counts.false_negatives == 1

    def test_empty_report_against_empty_gold(self) -> None:
        metrics = score_detection([], [], granularity="grouped")
        assert metrics.overall.f1 == 0.0
        assert metrics.type_agreement == 0.0
        assert metrics.calibration.sample_count == 0


class TestScoreBenchmark:
    def _report(self, findings: list[Finding]) -> ContradictionReport:
        from crosscheck.aggregation.report import DocumentPairGroup

        return ContradictionReport(
            audit_id="aid",
            corpus_path="/corpus",  # type: ignore[arg-type]
            document_count=2,
            claim_count=10,
            contradiction_count=len(expand(findings)),
            groups=[
                DocumentPairGroup(
                    doc_a_id="d1", doc_b_id="d2", doc_a="a.md", doc_b="b.md", findings=findings
                )
            ],
            stats=AuditStats(
                claim_count=10,
                decontextualization_flags=1,
                judge_llm_calls=8,
                judge_cache_hits=2,
                hallucination_count=1,
            ),
        )

    def _gold_set(self, pairs: list[GoldPair]) -> GoldSet:
        return GoldSet(name="t", corpus_dir="corpus", pairs=pairs)

    def test_grouped_and_per_verdict_differ_on_duplicates(self) -> None:
        child = _finding(pair_id="child", confidence=0.3)
        parent = _finding(pair_id="parent", confidence=0.9, near_duplicates=[child])
        metrics = score_benchmark(self._report([parent]), self._gold_set([_gold()]))
        assert metrics.finding_count == 1
        assert metrics.verdict_count == 2
        assert metrics.grouped.duplicate_count == 0
        assert metrics.per_verdict.duplicate_count == 1
        # Both agree on what was actually found.
        assert metrics.grouped.overall.true_positives == 1
        assert metrics.per_verdict.overall.true_positives == 1

    def test_observability_rates(self) -> None:
        metrics = score_benchmark(self._report([_finding()]), self._gold_set([_gold()]))
        assert metrics.hallucination_rate == pytest.approx(0.1)  # 1 of 10 judged
        assert metrics.decontextualization_rate == pytest.approx(0.1)  # 1 of 10 claims
        assert metrics.gold_pair_count == 1

    def test_empty_report_is_scored_not_rejected(self) -> None:
        metrics = score_benchmark(self._report([]), self._gold_set([_gold()]))
        assert metrics.finding_count == 0
        assert metrics.grouped.overall.false_negatives == 1
        assert metrics.grouped.overall.precision == 0.0
