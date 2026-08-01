"""Unit tests for the standalone HTML export (spec v2 §7.5, decision D35)."""

import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

from crosscheck.aggregation.html_renderer import render_html, write_html
from crosscheck.aggregation.report import build_report
from crosscheck.detection.taxonomy import ContradictionType
from crosscheck.models import Claim, DocumentRef, Pair, SectionRef, Verdict
from crosscheck.orchestrator import AuditResult, AuditStats, CostSummary

_QUOTE_A = "Unused paid time off does not carry over into the following calendar year."
_QUOTE_B = "Employees may carry over up to 5 unused paid time off days."
_VOID = {"meta", "br", "hr", "img", "input", "link", "source"}


class _Balance(HTMLParser):
    """Assert every non-void element is closed, in order."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in _VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack:
            self.errors.append(f"stray </{tag}>")
        elif self.stack[-1] != tag:
            self.errors.append(f"</{tag}> closes <{self.stack[-1]}>")
        else:
            self.stack.pop()


def _assert_well_formed(html: str) -> None:
    parser = _Balance()
    parser.feed(html)
    assert parser.errors == [], parser.errors
    assert parser.stack == [], f"unclosed: {parser.stack}"


def _doc(doc_id: str, name: str, section_id: str, heading: str) -> DocumentRef:
    return DocumentRef(
        doc_id=doc_id,
        source_path=Path(f"/corpus/{name}"),
        title=name,
        sections=[SectionRef(section_id=section_id, heading=heading, page_span=(2, 3))],
    )


def _claim(claim_id: str, doc_id: str, section_id: str, text: str, polarity: str) -> Claim:
    return Claim(
        claim_id=claim_id,
        doc_id=doc_id,
        section_id=section_id,
        text=text,
        evidence_quote=text,
        evidence_offset=(0, len(text)),
        subject="paid time off",
        predicate="carries over",
        polarity="negative" if polarity == "negative" else "positive",
    )


def _result(
    *,
    claim_a_text: str = _QUOTE_A,
    evidence_a: str = _QUOTE_A,
    rationale: str = "They cannot both hold.",
    is_contradiction: bool = True,
    partial: bool = False,
) -> AuditResult:
    docs = [
        _doc("d1", "01_employee_handbook.md", "s1", "2. Paid Time Off"),
        _doc("d2", "02_pto_policy_v2.md", "s2", "3. Carry-Over"),
    ]
    claims = [
        _claim("c1", "d1", "s1", claim_a_text, "negative"),
        _claim("c2", "d2", "s2", _QUOTE_B, "positive"),
    ]
    pairs = [
        Pair(
            pair_id="p1",
            claim_a_id="c1",
            claim_b_id="c2",
            retrieval_score=0.031,
            rerank_score=0.884,
            nli_contradiction_prob=0.972,
        )
    ]
    verdicts = [
        Verdict(
            pair_id="p1",
            is_contradiction=is_contradiction,
            contradiction_type=ContradictionType.DIRECT_NEGATION,
            confidence=0.95,
            rationale=rationale,
            evidence_a=evidence_a,
            evidence_b=_QUOTE_B,
            resolution_hint="The v2 policy controls.",
        )
    ]
    return AuditResult(
        audit_id="d17bc265e092a182",
        corpus_path=Path("/corpus"),
        documents=docs,
        claims=claims,
        judged_pairs=pairs,
        verdicts=verdicts,
        stats=AuditStats(
            document_count=2,
            chunk_count=6,
            claim_count=2,
            candidate_pair_count=9,
            reranked_pair_count=4,
            nli_kept_count=1,
            judge_llm_calls=1,
        ),
        cost=CostSummary(total_usd=0.0123, call_count=1),
        partial=partial,
        partial_reason="audit cost ceiling reached while judging" if partial else None,
    )


# --- structure ---------------------------------------------------------------------------


def test_renders_a_well_formed_standalone_document() -> None:
    html = render_html(build_report(_result()))
    _assert_well_formed(html)
    assert html.startswith("<!DOCTYPE html>")
    assert html.rstrip().endswith("</html>")


def test_export_is_self_contained() -> None:
    """The demo artifact must open from file:// with no network (§7.5)."""
    html = render_html(build_report(_result()))
    assert "<style>" in html and "<script>" in html
    for forbidden in ("http://", "https://", "//cdn", "<link", 'src="'):
        assert forbidden not in html, forbidden


def test_citations_and_passages_reach_the_page() -> None:
    html = render_html(build_report(_result()))
    assert "01_employee_handbook.md" in html
    assert "2. Paid Time Off" in html
    assert "pp. 2&ndash;3" in html
    assert "NEGATIVE" in html
    assert "The v2 policy controls." in html


def test_evidence_span_is_marked_in_the_passage() -> None:
    html = render_html(build_report(_result()))
    marked = re.findall(r"<mark>(.*?)</mark>", html, flags=re.S)
    assert _QUOTE_A in marked
    assert _QUOTE_B in marked


def test_scores_and_funnel_are_rendered() -> None:
    html = render_html(build_report(_result()))
    assert "0.972" in html  # NLI probability
    assert "0.884" in html  # rerank score
    assert "NLI survivors" in html
    assert "$0.01" in html


def test_grouping_heading_names_both_documents() -> None:
    html = render_html(build_report(_result()))
    assert "<code>01_employee_handbook.md</code>" in html
    assert "<code>02_pto_policy_v2.md</code>" in html


# --- escaping ----------------------------------------------------------------------------


def test_markup_in_source_text_is_escaped_not_executed() -> None:
    """Claim text comes from documents CrossCheck did not author — treat it as untrusted."""
    hostile = '<script>alert("xss")</script> & <img src=x onerror=1>'
    html = render_html(build_report(_result(claim_a_text=hostile, evidence_a=hostile)))

    assert "<script>alert" not in html
    assert "<img src=x" not in html
    assert "&lt;script&gt;alert" in html
    assert "&amp;" in html
    _assert_well_formed(html)


def test_rationale_markup_is_escaped() -> None:
    html = render_html(build_report(_result(rationale="a < b && c > d")))
    assert "a &lt; b &amp;&amp; c &gt; d" in html


# --- states ------------------------------------------------------------------------------


def test_empty_report_renders_the_designed_empty_state() -> None:
    result = _result(is_contradiction=False)
    html = render_html(build_report(result))

    assert "No contradictions detected" in html
    assert 'class="empty"' in html
    # The empty state must carry real numbers, not just say "nothing found".
    assert "2 claims" in html and "2 documents" in html
    assert 'class="finding"' not in html
    _assert_well_formed(html)


def test_partial_audit_shows_the_ceiling_banner() -> None:
    html = render_html(build_report(_result(partial=True)))
    assert 'class="partial"' in html
    assert "audit cost ceiling reached while judging" in html


def test_completed_audit_has_no_partial_banner() -> None:
    assert 'class="partial"' not in render_html(build_report(_result()))


def test_filter_row_is_omitted_for_a_single_type() -> None:
    """One type means the chips would filter nothing — don't render dead controls."""
    assert 'class="filters"' not in render_html(build_report(_result()))


# --- determinism and IO ------------------------------------------------------------------


def test_render_is_deterministic() -> None:
    assert render_html(build_report(_result())) == render_html(build_report(_result()))


def test_timestamp_is_rendered_only_when_the_report_carries_one() -> None:
    without = render_html(build_report(_result()))
    with_stamp = render_html(
        build_report(_result(), generated_at=datetime(2026, 8, 1, 19, 7, tzinfo=UTC))
    )
    assert "2026-08-01" not in without
    assert "2026-08-01 19:07" in with_stamp


def test_write_html_creates_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "report.html"
    write_html(build_report(_result()), path)
    assert path.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
