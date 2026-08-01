"""Turn an :class:`~crosscheck.orchestrator.AuditResult` into a reportable structure (§7.5).

The orchestrator returns raw material: verdicts that name their pair by id, the claims those
pairs point at, and one :class:`~crosscheck.models.DocumentRef` per ingested document. This
module joins them into :class:`Finding` objects that carry everything a renderer needs —
citation, both passages, the span to highlight, the rationale — so neither the JSON export nor
the HTML renderer has to walk the audit result or resolve an id.

Two shaping decisions are recorded in ``DECISIONS.md``:

* **D34** — findings are grouped by the *pair of documents* they span, not by ``Claim.subject``.
  Subject is the grammatical subject of an assertion, not a topic: on the acceptance corpus,
  342 claims produced 173 distinct subjects of which 62% were singletons, so subject grouping
  fragments rather than groups. Every finding is inherently cross-document, so the document
  pair is a total, deterministic key.
* **Near-duplicate roll-up** — within a document pair, findings that span the *same pair of
  sections* are collapsed under the highest-confidence one. The Phase 3 smoke run reported one
  semantic conflict twice because the judge paired a general rule from one document with a
  scoped exception in the other, and then the reverse; both came from the same two sections.
  The roll-up is presentation only — the exported JSON keeps every finding, because the
  evaluation harness scores them individually (§9.2).

Ordering is fully deterministic — groups by filename, findings by descending confidence then
pair id — so the frozen-fixture regression snapshot in §12 is stable.
"""

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from crosscheck.detection.taxonomy import ContradictionType
from crosscheck.models import Claim, CrossCheckModel, DocumentRef, Pair, Verdict
from crosscheck.orchestrator import AuditResult, AuditStats, CostSummary


def locate_quote(haystack: str, quote: str) -> tuple[int, int] | None:
    """Return the ``[start, end)`` span of ``quote`` within ``haystack``, or None.

    Mirrors the verbatim rule the extractor and judge already apply (D20): an exact match
    first, then a whitespace-flexible match, because a model routinely normalizes a source's
    line-wrap newlines to spaces while copying a span otherwise verbatim. The judge validated
    that its quotes are present at all; this locates them so the renderer can mark the span.

    Args:
        haystack: The passage the quote should appear in.
        quote: The verbatim span to find.

    Returns:
        The half-open character span, or None when the quote is not present.
    """
    if not quote.strip():
        return None
    index = haystack.find(quote)
    if index >= 0:
        return (index, index + len(quote))
    pattern = re.compile(r"\s+".join(re.escape(word) for word in quote.split()))
    match = pattern.search(haystack)
    return match.span() if match else None


class FindingSide(CrossCheckModel):
    """One half of a contradiction: a claim, where it came from, and what to highlight.

    Flattened on purpose. A renderer should be able to emit a citation and a highlighted
    passage from this object alone, without reaching back into the audit result.
    """

    claim_id: str
    doc_id: str
    filename: str = Field(description="Source file name — the citation label.")
    doc_title: str | None = None
    section_id: str
    section_heading: str | None = None
    page_span: tuple[int, int] | None = None
    claim_text: str = Field(description="The decontextualized claim, as actually compared.")
    evidence_quote: str = Field(description="The verbatim source span the claim came from.")
    highlight: str = Field(description="The judge's verbatim quote for this side.")
    highlight_span: tuple[int, int] | None = Field(
        default=None,
        description="Span of `highlight` within `evidence_quote`, or None if it was quoted "
        "from the claim text instead.",
    )
    polarity: Literal["positive", "negative"]


class Finding(CrossCheckModel):
    """One reported contradiction, joined and ready to render."""

    pair_id: str
    contradiction_type: ContradictionType
    confidence: float = Field(ge=0.0, le=1.0)
    subject: str = Field(description="Subject of claim A — shown on the card, not grouped on.")
    rationale: str
    resolution_hint: str | None = None
    a: FindingSide
    b: FindingSide
    retrieval_score: float | None = None
    rerank_score: float | None = None
    nli_contradiction_prob: float | None = None
    near_duplicates: list["Finding"] = Field(
        default_factory=list,
        description="Same-section findings rolled up under this one (presentation only).",
    )

    @property
    def section_key(self) -> tuple[str, str]:
        """The ordered pair of section ids this finding spans — the roll-up key."""
        first, second = sorted((self.a.section_id, self.b.section_id))
        return (first, second)


Finding.model_rebuild()


class DocumentPairGroup(CrossCheckModel):
    """Every contradiction found between one pair of documents (D34)."""

    doc_a_id: str
    doc_b_id: str
    doc_a: str = Field(description="Filename of the first document.")
    doc_b: str = Field(description="Filename of the second document.")
    findings: list[Finding] = Field(default_factory=list)

    @property
    def finding_count(self) -> int:
        """Findings shown in this group, excluding rolled-up near-duplicates."""
        return len(self.findings)


class ContradictionReport(CrossCheckModel):
    """The audit's findings, grouped and counted — the JSON and HTML export payload.

    A corpus with no contradictions is an ordinary, successful report with an empty
    ``groups`` list, not an error (§7.5). ``is_empty`` distinguishes it so a renderer can
    choose the designed empty state.
    """

    audit_id: str
    corpus_path: Path
    generated_at: datetime | None = Field(
        default=None,
        description="Left None by default so a frozen-fixture snapshot stays byte-stable.",
    )
    document_count: int = 0
    claim_count: int = 0
    candidate_pair_count: int = 0
    pairs_evaluated: int = Field(
        default=0, description="Pairs that survived NLI and reached the judge."
    )
    contradiction_count: int = Field(
        default=0, description="Every contradiction, including rolled-up near-duplicates."
    )
    groups: list[DocumentPairGroup] = Field(default_factory=list)
    type_counts: dict[str, int] = Field(default_factory=dict)
    stats: AuditStats = Field(default_factory=AuditStats)
    cost: CostSummary = Field(default_factory=CostSummary)
    partial: bool = False
    partial_reason: str | None = None

    @property
    def is_empty(self) -> bool:
        """True when the audit ran and found nothing — the §7.5 empty-report path."""
        return self.contradiction_count == 0

    @property
    def findings(self) -> list[Finding]:
        """Every displayed finding across all groups, in report order."""
        return [finding for group in self.groups for finding in group.findings]


def build_report(
    result: AuditResult,
    *,
    generated_at: datetime | None = None,
) -> ContradictionReport:
    """Assemble a :class:`ContradictionReport` from a finished audit.

    Joins each contradiction verdict to its pair, both claims, and their documents; groups the
    result by document pair (D34); rolls up same-section near-duplicates; and orders everything
    deterministically.

    Verdicts whose pair or claims are missing from the result are skipped rather than raising —
    a partial audit is a normal outcome, and a report should render what survived.

    Args:
        result: The audit to report on.
        generated_at: Timestamp to stamp on the report. Left None by default so that a
            regression snapshot over a frozen fixture stays byte-stable.

    Returns:
        The report, ready to export as JSON or render as HTML.
    """
    claims = {claim.claim_id: claim for claim in result.claims}
    pairs = {pair.pair_id: pair for pair in result.judged_pairs}
    documents = result.document_index

    findings: list[Finding] = []
    for verdict in result.contradictions:
        pair = pairs.get(verdict.pair_id)
        if pair is None:
            continue
        claim_a = claims.get(pair.claim_a_id)
        claim_b = claims.get(pair.claim_b_id)
        if claim_a is None or claim_b is None:
            continue
        findings.append(_build_finding(verdict, pair, claim_a, claim_b, documents))

    grouped = _group_by_document_pair(findings, documents)
    return ContradictionReport(
        audit_id=result.audit_id,
        corpus_path=result.corpus_path,
        generated_at=generated_at,
        document_count=result.stats.document_count,
        claim_count=result.stats.claim_count,
        candidate_pair_count=result.stats.candidate_pair_count,
        pairs_evaluated=result.stats.nli_kept_count,
        contradiction_count=len(findings),
        groups=grouped,
        type_counts=_count_types(findings),
        stats=result.stats,
        cost=result.cost,
        partial=result.partial,
        partial_reason=result.partial_reason,
    )


def write_json(report: ContradictionReport, path: Path) -> None:
    """Write the report as indented JSON, creating parent directories as needed.

    Args:
        report: The report to export.
        path: Destination file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")


def _build_finding(
    verdict: Verdict,
    pair: Pair,
    claim_a: Claim,
    claim_b: Claim,
    documents: dict[str, DocumentRef],
) -> Finding:
    """Join one verdict with its pair, claims and document refs."""
    return Finding(
        pair_id=verdict.pair_id,
        # The judge coerces an untyped contradiction to UNCLEAR (D29); belt and braces here.
        contradiction_type=verdict.contradiction_type or ContradictionType.UNCLEAR,
        confidence=verdict.confidence,
        subject=claim_a.subject,
        rationale=verdict.rationale,
        resolution_hint=verdict.resolution_hint,
        a=_build_side(claim_a, verdict.evidence_a, documents),
        b=_build_side(claim_b, verdict.evidence_b, documents),
        retrieval_score=pair.retrieval_score,
        rerank_score=pair.rerank_score,
        nli_contradiction_prob=pair.nli_contradiction_prob,
    )


def _build_side(claim: Claim, highlight: str, documents: dict[str, DocumentRef]) -> FindingSide:
    """Flatten one claim plus its citation and highlight span into a renderable side."""
    document = documents.get(claim.doc_id)
    section = document.section(claim.section_id) if document is not None else None
    return FindingSide(
        claim_id=claim.claim_id,
        doc_id=claim.doc_id,
        # A doc_id with no ref means the audit was assembled by hand (tests, eval ablations);
        # fall back to the hash so the report still cites something traceable.
        filename=document.filename if document is not None else claim.doc_id,
        doc_title=document.title if document is not None else None,
        section_id=claim.section_id,
        section_heading=section.heading if section is not None else None,
        page_span=section.page_span if section is not None else None,
        claim_text=claim.text,
        evidence_quote=claim.evidence_quote,
        highlight=highlight,
        highlight_span=locate_quote(claim.evidence_quote, highlight),
        polarity=claim.polarity,
    )


def _group_by_document_pair(
    findings: list[Finding],
    documents: dict[str, DocumentRef],
) -> list[DocumentPairGroup]:
    """Bucket findings by the document pair they span, roll up near-duplicates, and sort."""
    buckets: dict[tuple[str, str], list[Finding]] = defaultdict(list)
    for finding in findings:
        key = (finding.a.doc_id, finding.b.doc_id)
        buckets[key if key[0] <= key[1] else (key[1], key[0])].append(finding)

    groups: list[DocumentPairGroup] = []
    for (doc_a_id, doc_b_id), bucket in buckets.items():
        groups.append(
            DocumentPairGroup(
                doc_a_id=doc_a_id,
                doc_b_id=doc_b_id,
                doc_a=_filename(doc_a_id, documents),
                doc_b=_filename(doc_b_id, documents),
                findings=_roll_up_near_duplicates(bucket),
            )
        )
    groups.sort(key=lambda group: (group.doc_a, group.doc_b, group.doc_a_id))
    return groups


def _roll_up_near_duplicates(findings: list[Finding]) -> list[Finding]:
    """Collapse findings spanning the same section pair under the most confident one.

    The rolled-up findings are attached as ``near_duplicates`` rather than discarded: the JSON
    export stays complete, and the HTML renderer can show them behind a disclosure.
    """
    ordered = sorted(findings, key=_finding_order)
    by_section: dict[tuple[str, str], Finding] = {}
    primaries: list[Finding] = []
    for finding in ordered:
        primary = by_section.get(finding.section_key)
        if primary is None:
            by_section[finding.section_key] = finding
            primaries.append(finding)
        else:
            primary.near_duplicates.append(finding)
    return primaries


def _finding_order(finding: Finding) -> tuple[float, str]:
    """Sort key: highest confidence first, then pair id so ties are deterministic."""
    return (-finding.confidence, finding.pair_id)


def _filename(doc_id: str, documents: dict[str, DocumentRef]) -> str:
    """The citation label for a document id, falling back to the id itself."""
    document = documents.get(doc_id)
    return document.filename if document is not None else doc_id


def _count_types(findings: list[Finding]) -> dict[str, int]:
    """Count findings per contradiction type, ordered by the taxonomy for stable output."""
    counts: dict[str, int] = {}
    for contradiction_type in ContradictionType:
        total = sum(1 for finding in findings if finding.contradiction_type is contradiction_type)
        if total:
            counts[contradiction_type.value] = total
    return counts


def load_report(path: Path) -> ContradictionReport:
    """Read a previously exported report back from JSON.

    Args:
        path: A file written by :func:`write_json`.

    Returns:
        The parsed report.

    Raises:
        ValueError: If the file is not a valid report document.
    """
    return ContradictionReport.model_validate(json.loads(path.read_text(encoding="utf-8")))
