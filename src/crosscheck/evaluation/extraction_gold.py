"""Extraction gold set: schema, loader, and scorer.

Measures claim extraction on its own, separate from end-to-end contradiction metrics
(spec v2 §7.1, §9.2). A gold chunk stores its text verbatim plus the atomic claims a
human says it should yield; the scorer matches the extractor's claims to those gold
claims by evidence-span overlap and reports precision, recall, F1, and polarity
accuracy. The scorer takes already-extracted claims — it makes no LLM calls — so it is
deterministic, unit-testable, and reused unchanged by the Phase 6 metrics module.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from loguru import logger
from pydantic import Field

from crosscheck.ids import chunk_id, content_hash
from crosscheck.models import Chunk, Claim, CrossCheckModel

Span = tuple[int, int]


class GoldClaim(CrossCheckModel):
    """One hand-labeled atomic claim a chunk is expected to yield."""

    evidence_quote: str
    polarity: Literal["positive", "negative"]
    subject: str | None = None
    note: str | None = None


class GoldChunk(CrossCheckModel):
    """A hand-labeled chunk: its verbatim text and the claims it should yield.

    An empty ``claims`` list is meaningful: it asserts the chunk is all non-claims
    (opinion, question, definition) and the extractor should return nothing for it.
    """

    gold_id: str
    source: str
    text: str
    claims: list[GoldClaim] = Field(default_factory=list)


class ExtractionScore(CrossCheckModel):
    """Precision/recall of claim extraction against the gold set."""

    gold_chunks: int = 0
    gold_claims: int = 0
    extracted_claims: int = 0
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    polarity_correct: int = 0
    unresolved_gold: int = 0

    @property
    def precision(self) -> float:
        """Fraction of extracted claims that matched a gold claim (0.0 if none)."""
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom else 0.0

    @property
    def recall(self) -> float:
        """Fraction of gold claims that were extracted (0.0 if none)."""
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom else 0.0

    @property
    def f1(self) -> float:
        """Harmonic mean of precision and recall (0.0 if both are zero)."""
        precision, recall = self.precision, self.recall
        return 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    @property
    def polarity_accuracy(self) -> float:
        """Fraction of matched claims whose polarity agrees with gold (0.0 if none)."""
        return self.polarity_correct / self.true_positives if self.true_positives else 0.0


def load_gold_set(directory: Path) -> list[GoldChunk]:
    """Load every ``*.json`` gold chunk in ``directory``, sorted by filename."""
    gold = [
        GoldChunk.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    ]
    logger.info("loaded {} gold chunk(s) from {}", len(gold), directory)
    return gold


def to_chunk(gold: GoldChunk) -> Chunk:
    """Build a :class:`Chunk` from a gold chunk so the extractor can run on it.

    Uses synthetic but deterministic ids namespaced under ``gold:`` so gold chunks
    never collide with real corpus chunks.
    """
    doc = f"gold:{gold.gold_id}"
    section = content_hash(gold.gold_id)
    span = (0, len(gold.text))
    return Chunk(
        chunk_id=chunk_id(doc, section, span),
        doc_id=doc,
        section_id=section,
        text=gold.text,
        char_span=span,
        token_count=None,
    )


def _overlap_ratio(a: Span, b: Span) -> float:
    """Overlap of two spans as a fraction of the shorter span (0.0 if disjoint).

    Fraction-of-shorter rather than IoU so a short extracted quote that sits inside a
    longer gold quote (or vice versa) still counts as referring to the same claim.
    """
    intersection = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    if intersection == 0:
        return 0.0
    shorter = min(a[1] - a[0], b[1] - b[0])
    return intersection / shorter if shorter else 0.0


def _match(
    gold_spans: Sequence[Span],
    ext_spans: Sequence[Span],
    threshold: float,
) -> list[tuple[int, int]]:
    """Greedily pair gold and extracted spans one-to-one by descending overlap."""
    candidates = [
        (_overlap_ratio(gold_span, ext_span), gi, ei)
        for gi, gold_span in enumerate(gold_spans)
        for ei, ext_span in enumerate(ext_spans)
        if _overlap_ratio(gold_span, ext_span) >= threshold
    ]
    candidates.sort(key=lambda item: item[0], reverse=True)
    used_gold: set[int] = set()
    used_ext: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for _score, gi, ei in candidates:
        if gi in used_gold or ei in used_ext:
            continue
        used_gold.add(gi)
        used_ext.add(ei)
        pairs.append((gi, ei))
    return pairs


def score_extraction(
    gold: Sequence[GoldChunk],
    extracted: Mapping[str, Sequence[Claim]],
    *,
    overlap_threshold: float = 0.5,
) -> ExtractionScore:
    """Score extracted claims against the gold set (spec v2 §7.1, §9.2).

    Each extracted claim is matched to at most one gold claim in the same chunk by
    evidence-span overlap; matched pairs are true positives, unmatched extractions are
    false positives, unmatched gold claims are false negatives. Polarity agreement is
    tallied among matches. Gold quotes that are not verbatim substrings of their chunk
    are counted as ``unresolved_gold`` (labeling errors) and excluded.

    Args:
        gold: The hand-labeled gold chunks.
        extracted: Extractor output per chunk, keyed by ``GoldChunk.gold_id``.
        overlap_threshold: Minimum fraction-of-shorter-span overlap to count a match.

    Returns:
        The aggregated :class:`ExtractionScore`.
    """
    gold_claims = extracted_claims = 0
    true_positives = false_positives = false_negatives = 0
    polarity_correct = unresolved_gold = 0

    for gold_chunk in gold:
        gold_spans: list[Span] = []
        resolved: list[GoldClaim] = []
        for claim in gold_chunk.claims:
            quote = claim.evidence_quote
            start = gold_chunk.text.find(quote) if quote.strip() else -1
            if start < 0:
                unresolved_gold += 1
                logger.warning(
                    "gold {}: quote not found verbatim, skipping: {!r}",
                    gold_chunk.gold_id,
                    quote,
                )
                continue
            gold_spans.append((start, start + len(quote)))
            resolved.append(claim)

        chunk_extracted = list(extracted.get(gold_chunk.gold_id, []))
        ext_spans = [claim.evidence_offset for claim in chunk_extracted]

        gold_claims += len(resolved)
        extracted_claims += len(chunk_extracted)

        pairs = _match(gold_spans, ext_spans, overlap_threshold)
        true_positives += len(pairs)
        false_negatives += len(resolved) - len(pairs)
        false_positives += len(chunk_extracted) - len(pairs)
        for gi, ei in pairs:
            if resolved[gi].polarity == chunk_extracted[ei].polarity:
                polarity_correct += 1

    score = ExtractionScore(
        gold_chunks=len(gold),
        gold_claims=gold_claims,
        extracted_claims=extracted_claims,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        polarity_correct=polarity_correct,
        unresolved_gold=unresolved_gold,
    )
    logger.info(
        "extraction score: P={:.2f} R={:.2f} F1={:.2f} polarity={:.2f} "
        "(TP={} FP={} FN={} unresolved_gold={})",
        score.precision,
        score.recall,
        score.f1,
        score.polarity_accuracy,
        true_positives,
        false_positives,
        false_negatives,
        unresolved_gold,
    )
    return score
