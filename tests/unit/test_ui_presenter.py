"""Unit tests for the demo's view logic (§7.7).

No Streamlit anywhere. `crosscheck.ui.presenter` holds the decisions the page makes precisely so
they can be tested without a browser, a server, or a rerun loop; `ui/streamlit_app.py` is left
with widget calls only.
"""

from pathlib import Path

import pytest

from crosscheck.aggregation.report import (
    ContradictionReport,
    DocumentPairGroup,
    Finding,
    FindingSide,
)
from crosscheck.detection.taxonomy import ContradictionType
from crosscheck.orchestrator import AuditStats, CostSummary
from crosscheck.ui.presenter import (
    Segment,
    bundled_reports,
    confidence_band,
    empty_state_message,
    group_by_type,
    highlight_segments,
    summarize,
)

_QUOTE = "Vendors must carry liability insurance for the duration of the engagement."


def _side(*, quote: str = _QUOTE, span: tuple[int, int] | None = None) -> FindingSide:
    return FindingSide(
        claim_id="c1",
        doc_id="d1",
        filename="msa.docx",
        section_id="s1",
        claim_text=quote,
        evidence_quote=quote,
        highlight=quote if span is None else quote[span[0] : span[1]],
        highlight_span=span,
        polarity="positive",
    )


def _finding(
    *,
    pair_id: str = "p1",
    confidence: float = 0.9,
    contradiction_type: ContradictionType = ContradictionType.DIRECT_NEGATION,
) -> Finding:
    return Finding(
        pair_id=pair_id,
        contradiction_type=contradiction_type,
        confidence=confidence,
        subject="liability insurance",
        rationale="one mandates, the other exempts",
        a=_side(),
        b=_side(),
    )


def _report(findings: list[Finding], *, documents: int = 2, pairs: int = 10) -> ContradictionReport:
    return ContradictionReport(
        audit_id="aid",
        corpus_path=Path("/corpus"),
        document_count=documents,
        claim_count=40,
        candidate_pair_count=100,
        pairs_evaluated=pairs,
        contradiction_count=len(findings),
        groups=[
            DocumentPairGroup(
                doc_a_id="d1", doc_b_id="d2", doc_a="a.md", doc_b="b.md", findings=findings
            )
        ]
        if findings
        else [],
        stats=AuditStats(document_count=documents, nli_kept_count=pairs),
        cost=CostSummary(total_usd=1.2345),
    )


class TestHighlightSegments:
    def test_splits_around_the_quote(self) -> None:
        segments = highlight_segments(_side(span=(8, 13)))

        assert segments == [
            Segment(text="Vendors ", highlighted=False),
            Segment(text="must ", highlighted=True),
            Segment(
                text="carry liability insurance for the duration of the engagement.",
                highlighted=False,
            ),
        ]

    def test_no_span_is_one_plain_segment(self) -> None:
        segments = highlight_segments(_side(span=None))

        assert segments == [Segment(text=_QUOTE, highlighted=False)]

    def test_quote_at_the_start_produces_no_leading_blank(self) -> None:
        segments = highlight_segments(_side(span=(0, 7)))

        assert [s.highlighted for s in segments] == [True, False]
        assert segments[0].text == "Vendors"

    def test_quote_at_the_end_produces_no_trailing_blank(self) -> None:
        segments = highlight_segments(_side(span=(0, len(_QUOTE))))

        assert segments == [Segment(text=_QUOTE, highlighted=True)]

    def test_reassembling_segments_reproduces_the_passage(self) -> None:
        """The property that matters: highlighting must never alter the text it marks up."""
        for span in [(0, 7), (8, 13), (14, 19), (0, len(_QUOTE)), None]:
            segments = highlight_segments(_side(span=span))
            assert "".join(s.text for s in segments) == _QUOTE

    def test_empty_passage_is_no_segments(self) -> None:
        assert highlight_segments(_side(quote="", span=None)) == []


class TestConfidenceBand:
    @pytest.mark.parametrize(
        ("confidence", "expected"),
        [
            (1.0, "trustworthy"),
            (0.90, "trustworthy"),
            (0.899, "discounted"),
            (0.80, "discounted"),
            (0.799, "low"),
            (0.0, "low"),
        ],
    )
    def test_bands(self, confidence: float, expected: str) -> None:
        assert confidence_band(confidence) == expected

    def test_the_discounted_band_is_the_measured_overconfident_one(self) -> None:
        """0.8-0.9 is where calibration showed +.181 (synthetic) and +.252 (hand-written)."""
        assert confidence_band(0.85) == "discounted"


class TestGroupByType:
    def test_groups_in_taxonomy_order_not_by_count(self) -> None:
        findings = [
            _finding(pair_id="p1", contradiction_type=ContradictionType.OBLIGATION_REVERSAL),
            _finding(pair_id="p2", contradiction_type=ContradictionType.DIRECT_NEGATION),
            _finding(pair_id="p3", contradiction_type=ContradictionType.OBLIGATION_REVERSAL),
        ]

        grouped = group_by_type(findings)

        # DIRECT_NEGATION precedes OBLIGATION_REVERSAL in the taxonomy despite having fewer.
        assert [t for t, _ in grouped] == [
            ContradictionType.DIRECT_NEGATION,
            ContradictionType.OBLIGATION_REVERSAL,
        ]

    def test_within_a_type_the_most_confident_comes_first(self) -> None:
        findings = [
            _finding(pair_id="p_low", confidence=0.5),
            _finding(pair_id="p_high", confidence=0.95),
        ]

        assert [f.pair_id for _, fs in group_by_type(findings) for f in fs] == ["p_high", "p_low"]

    def test_empty_types_are_omitted(self) -> None:
        assert len(group_by_type([_finding()])) == 1

    def test_no_findings_is_no_groups(self) -> None:
        assert group_by_type([]) == []


class TestEmptyState:
    def test_names_what_was_actually_checked(self) -> None:
        message = empty_state_message(_report([], documents=7, pairs=413))

        assert "7 document(s)" in message
        assert "413 claim pair(s)" in message
        assert message.startswith("No contradictions detected")

    def test_matches_the_cli_wording(self) -> None:
        """The two surfaces must agree; a demo that words it differently reads as a bug."""
        assert empty_state_message(_report([])) == (
            "No contradictions detected across 2 document(s) / 10 claim pair(s) evaluated."
        )


class TestSummarize:
    def test_reports_the_four_headline_numbers_including_cost(self) -> None:
        pairs = dict(summarize(_report([_finding()])))

        assert pairs["Contradictions"] == "1"
        assert pairs["Documents"] == "2"
        assert pairs["Pairs evaluated"] == "10"
        assert pairs["Cost"] == "$1.2345"


class TestBundledReports:
    def test_only_offers_reports_that_exist(self, tmp_path: Path) -> None:
        target = tmp_path / "benchmarks/realcorpus/nist_63b/report.json"
        target.parent.mkdir(parents=True)
        target.write_text("{}", encoding="utf-8")

        available = bundled_reports(tmp_path)

        assert [item.path for item in available] == [target]

    def test_a_checkout_with_no_reports_yields_none(self, tmp_path: Path) -> None:
        assert bundled_reports(tmp_path) == []

    def test_the_real_corpus_report_leads(self) -> None:
        """§7.7 wants the demo captured against the real-corpus run, so it is offered first."""
        repo_root = Path(__file__).resolve().parents[2]
        available = bundled_reports(repo_root)

        assert available, "expected the committed benchmark reports to be present"
        assert "800-63B" in available[0].label
