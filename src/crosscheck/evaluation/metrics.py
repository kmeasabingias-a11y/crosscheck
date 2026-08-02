"""Detection metrics for the labelled benchmarks (spec v2 §9.2).

This is the module the README's headline numbers come from, so its definitions matter more than
its code. Three of them are worth stating up front, because each one is a place where a plausible
alternative would quietly report a different number for the same run.

**1. What counts as one prediction.** The report rolls same-section near-duplicates up under a
single finding (D34): the extractor may split one section into several claims, so one underlying
disagreement can surface as several verdicts. Gold labels match at *section* level (D36). Those two
facts agree — the rolled-up finding and the gold pair are the same unit — so the default
granularity, ``"grouped"``, scores the findings **as displayed**, one card per section pair. On the
v1 GDPR benchmark this is exactly one-to-one: 108 findings, zero of them duplicating another's
gold pair. ``"per_verdict"`` scores every verdict including rolled-up duplicates; it answers a
different question (how often was the *judge* right) and is reported alongside as a diagnostic,
never as the headline.

**2. Precision and recall must not mix units.** The obvious implementation counts true positives as
*gold pairs matched* and false positives as *findings that matched nothing* — numerator and
denominator then describe different kinds of object, and the resulting "precision" is not a
proportion of anything. Here both are counted in findings, recall is counted in gold pairs, and a
gold pair can be claimed by at most one finding; any further finding landing on an already-claimed
gold pair is a duplicate, counted and reported separately rather than silently folded into either
column.

**3. Strata are defined by the text being compared, on whichever side is available.** §9.2 wants
metrics split by lexical overlap, to expose a system that only catches near-duplicate phrasing. A
missed gold pair has no prediction to measure, and a false positive has no gold, so neither side
alone can stratify everything. Gold pairs (matched and missed) are stratified by their own two
texts, which keeps a pair in the same stratum across runs; unmatched findings are stratified by
their two claim texts. The asymmetry is deliberate and is why a stratum's precision and recall
have slightly different provenance.

Claim-extraction precision/recall is **not** here — it lives in ``extraction_gold.py``, scored
against its own gold set, because §9.2 wants extraction quality attributable separately from
end-to-end detection.
"""

import re
from collections.abc import Iterable, Sequence
from typing import Literal

from pydantic import Field

from crosscheck.aggregation.report import ContradictionReport, Finding
from crosscheck.detection.taxonomy import ContradictionType
from crosscheck.evaluation.gold import GoldPair, GoldSet, matches
from crosscheck.models import CrossCheckModel

#: Granularity of a detection score. ``grouped`` scores findings as displayed (near-duplicates
#: rolled up, the default and the headline); ``per_verdict`` scores every verdict separately.
Granularity = Literal["grouped", "per_verdict"]

#: Default lexical-overlap cut separating the high- and low-overlap strata. Chosen as a round
#: number next to the v1 benchmark's median (0.310), where it splits 139 gold pairs 71/68. A
#: fitted value (the exact median) would rebalance on every benchmark and stop runs comparing.
DEFAULT_OVERLAP_THRESHOLD = 0.30

#: Number of equal-width bins in the reliability diagram.
DEFAULT_CALIBRATION_BINS = 10

_WORD = re.compile(r"[a-z0-9]+")


class Counts(CrossCheckModel):
    """Confusion counts and the three rates derived from them."""

    true_positives: int = Field(default=0, ge=0)
    false_positives: int = Field(default=0, ge=0)
    false_negatives: int = Field(default=0, ge=0)

    @property
    def precision(self) -> float:
        """Fraction of predictions that were right (0.0 when nothing was predicted)."""
        predicted = self.true_positives + self.false_positives
        return self.true_positives / predicted if predicted else 0.0

    @property
    def recall(self) -> float:
        """Fraction of gold pairs that were found (0.0 when there are none)."""
        actual = self.true_positives + self.false_negatives
        return self.true_positives / actual if actual else 0.0

    @property
    def f1(self) -> float:
        """Harmonic mean of precision and recall (0.0 if both are zero)."""
        precision, recall = self.precision, self.recall
        return 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0


class Stratum(CrossCheckModel):
    """Detection counts restricted to one lexical-overlap band (§9.2)."""

    name: Literal["high_overlap", "low_overlap"]
    threshold: float = Field(description="Overlap at or above which a pair is 'high'.")
    counts: Counts = Field(default_factory=Counts)


class CalibrationBin(CrossCheckModel):
    """One bucket of a reliability diagram: how confident, versus how often right."""

    lower: float = Field(ge=0.0, le=1.0)
    upper: float = Field(ge=0.0, le=1.0)
    count: int = Field(default=0, ge=0)
    mean_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    accuracy: float = Field(default=0.0, ge=0.0, le=1.0)

    @property
    def gap(self) -> float:
        """Signed confidence minus accuracy: positive means overconfident."""
        return self.mean_confidence - self.accuracy


class Calibration(CrossCheckModel):
    """Reliability diagram plus its scalar summaries (§9.2).

    Empty bins are kept in ``bins`` so a plot has a stable x-axis across runs, but they
    contribute nothing to the error terms.
    """

    bins: list[CalibrationBin] = Field(default_factory=list)
    expected_error: float = Field(
        default=0.0, description="ECE: bin-count-weighted mean |accuracy - confidence|."
    )
    max_error: float = Field(
        default=0.0, description="MCE: the worst single non-empty bin's |accuracy - confidence|."
    )
    brier: float = Field(
        default=0.0, description="Mean squared error of confidence against correctness."
    )
    sample_count: int = Field(default=0, ge=0)


class DetectionMetrics(CrossCheckModel):
    """Everything scored from one report against one gold set, at one granularity."""

    granularity: Granularity
    overall: Counts = Field(default_factory=Counts)
    by_type: dict[str, Counts] = Field(
        default_factory=dict,
        description="Per contradiction type. TP/FN are counted on the gold type; FP on the "
        "type the judge predicted, so a mislabelled hit is not also a false positive.",
    )
    strata: list[Stratum] = Field(default_factory=list)
    calibration: Calibration = Field(default_factory=Calibration)
    duplicate_count: int = Field(
        default=0,
        description="Findings landing on a gold pair already claimed by another finding. "
        "Expected to be 0 at 'grouped' granularity — a non-zero value means the report's "
        "near-duplicate roll-up and the gold set's section matching have diverged.",
    )
    matched_count: int = Field(default=0, ge=0)
    type_agreement: float = Field(
        default=0.0,
        description="Of the gold pairs found, the fraction labelled with the gold's own type.",
    )
    type_confusion: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description="gold type -> predicted type -> count, over matched pairs only. The "
        "taxonomy overlaps (an obligation reversal is usually also a direct negation), so "
        "read this before treating a low `type_agreement` as an error rate.",
    )


class BenchmarkMetrics(CrossCheckModel):
    """A full §9.2 scorecard for one benchmark run."""

    gold_pair_count: int = 0
    finding_count: int = Field(default=0, description="Findings as displayed (grouped).")
    verdict_count: int = Field(default=0, description="Findings including rolled-up duplicates.")
    grouped: DetectionMetrics
    per_verdict: DetectionMetrics
    hallucination_rate: float = Field(
        default=0.0, description="Judge verdicts whose evidence failed the verbatim check."
    )
    decontextualization_rate: float = Field(
        default=0.0, description="Claims flagged with an unresolved reference (§7.1)."
    )
    cost_usd: float = 0.0
    cost_per_100_documents: float = 0.0
    partial: bool = False
    partial_reason: str | None = None


def lexical_overlap(a: str, b: str) -> float:
    """Return the Jaccard overlap of the two texts' lowercased alphanumeric tokens.

    Deliberately crude. This exists to separate "the two claims say nearly the same words" from
    "the two claims share almost no surface form", which is all §9.2's stratification needs; an
    embedding similarity would be a better similarity and a worse stratifier, because it would
    fold in exactly the semantic signal the strata are meant to hold constant.

    Args:
        a: One text.
        b: The other text.

    Returns:
        Overlap in ``[0.0, 1.0]``; 0.0 when both texts have no tokens.
    """
    tokens_a = set(_WORD.findall(a.lower()))
    tokens_b = set(_WORD.findall(b.lower()))
    union = tokens_a | tokens_b
    return len(tokens_a & tokens_b) / len(union) if union else 0.0


def _finding_overlap(finding: Finding) -> float:
    return lexical_overlap(finding.a.claim_text, finding.b.claim_text)


def _gold_overlap(gold: GoldPair) -> float:
    return lexical_overlap(gold.a.text, gold.b.text)


def expand(findings: Iterable[Finding]) -> list[Finding]:
    """Return every finding including near-duplicates rolled up under it (D34)."""
    out: list[Finding] = []
    for finding in findings:
        out.append(finding)
        out.extend(finding.near_duplicates)
    return out


class MatchResult(CrossCheckModel):
    """Outcome of assigning findings to gold pairs."""

    matched: list[tuple[Finding, GoldPair]] = Field(default_factory=list)
    unmatched_findings: list[Finding] = Field(default_factory=list)
    unmatched_gold: list[GoldPair] = Field(default_factory=list)
    duplicates: list[Finding] = Field(default_factory=list)


def match_findings(findings: Sequence[Finding], gold_pairs: Sequence[GoldPair]) -> MatchResult:
    """Assign findings to gold pairs, at most one finding per gold pair.

    Findings are considered most-confident first, so when two findings could claim the same gold
    pair the stronger one wins and the other is recorded as a duplicate rather than as an error.
    Ties break on ``pair_id`` to keep the assignment deterministic across runs.

    Args:
        findings: Predicted findings.
        gold_pairs: The gold pairs to match against.

    Returns:
        The matched couples, the findings that matched no gold pair, the gold pairs nothing
        matched, and any findings that landed on an already-claimed gold pair.
    """
    ordered = sorted(findings, key=lambda f: (-f.confidence, f.pair_id))
    claimed: dict[str, Finding] = {}
    result = MatchResult()
    for finding in ordered:
        gold = next((g for g in gold_pairs if matches(finding, g)), None)
        if gold is None:
            result.unmatched_findings.append(finding)
        elif gold.pair_id in claimed:
            result.duplicates.append(finding)
        else:
            claimed[gold.pair_id] = finding
            result.matched.append((finding, gold))
    result.unmatched_gold = [g for g in gold_pairs if g.pair_id not in claimed]
    return result


def calibrate(
    samples: Sequence[tuple[float, bool]], *, bins: int = DEFAULT_CALIBRATION_BINS
) -> Calibration:
    """Build a reliability diagram from (confidence, was-correct) samples.

    Args:
        samples: One ``(confidence, correct)`` pair per prediction.
        bins: Number of equal-width bins across ``[0, 1]``.

    Returns:
        The bins (including empty ones) plus ECE, MCE and the Brier score.
    """
    width = 1.0 / bins
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for confidence, correct in samples:
        index = min(int(confidence / width), bins - 1)
        buckets[index].append((confidence, correct))

    total = len(samples)
    built: list[CalibrationBin] = []
    expected, worst = 0.0, 0.0
    for index, bucket in enumerate(buckets):
        lower, upper = index * width, (index + 1) * width
        if not bucket:
            built.append(CalibrationBin(lower=lower, upper=upper))
            continue
        mean_confidence = sum(c for c, _ in bucket) / len(bucket)
        accuracy = sum(1 for _, ok in bucket if ok) / len(bucket)
        built.append(
            CalibrationBin(
                lower=lower,
                upper=upper,
                count=len(bucket),
                mean_confidence=mean_confidence,
                accuracy=accuracy,
            )
        )
        error = abs(accuracy - mean_confidence)
        expected += (len(bucket) / total) * error
        worst = max(worst, error)

    brier = sum((c - (1.0 if ok else 0.0)) ** 2 for c, ok in samples) / total if total else 0.0
    return Calibration(
        bins=built,
        expected_error=expected,
        max_error=worst,
        brier=brier,
        sample_count=total,
    )


def score_detection(
    findings: Sequence[Finding],
    gold_pairs: Sequence[GoldPair],
    *,
    granularity: Granularity,
    overlap_threshold: float = DEFAULT_OVERLAP_THRESHOLD,
    calibration_bins: int = DEFAULT_CALIBRATION_BINS,
) -> DetectionMetrics:
    """Score one set of findings against the gold pairs.

    Args:
        findings: Predicted findings, already at the requested granularity.
        gold_pairs: Gold pairs to score against (use ``GoldSet.usable_pairs``).
        granularity: Which granularity these findings represent — recorded on the result.
        overlap_threshold: Lexical overlap at or above which a pair is "high overlap".
        calibration_bins: Number of reliability-diagram bins.

    Returns:
        Counts overall, per type, per stratum, plus calibration and type agreement.
    """
    result = match_findings(findings, gold_pairs)
    matched_gold = {gold.pair_id for _, gold in result.matched}

    # Duplicates are not errors — section-level matching cannot tell them apart from their
    # parent — so they are counted and reported, never folded into false positives.
    overall = Counts(
        true_positives=len(result.matched),
        false_positives=len(result.unmatched_findings),
        false_negatives=len(result.unmatched_gold),
    )

    by_type: dict[str, Counts] = {}
    for gold in gold_pairs:
        counts = by_type.setdefault(gold.contradiction_type.value, Counts())
        if gold.pair_id in matched_gold:
            counts.true_positives += 1
        else:
            counts.false_negatives += 1
    for finding in result.unmatched_findings:
        counts = by_type.setdefault(finding.contradiction_type.value, Counts())
        counts.false_positives += 1

    def _stratum(name: Literal["high_overlap", "low_overlap"], *, high: bool) -> Stratum:
        def keep(value: float) -> bool:
            return (value >= overlap_threshold) if high else (value < overlap_threshold)

        return Stratum(
            name=name,
            threshold=overlap_threshold,
            counts=Counts(
                true_positives=sum(1 for _, gold in result.matched if keep(_gold_overlap(gold))),
                false_positives=sum(
                    1 for finding in result.unmatched_findings if keep(_finding_overlap(finding))
                ),
                false_negatives=sum(
                    1 for gold in result.unmatched_gold if keep(_gold_overlap(gold))
                ),
            ),
        )

    strata = [_stratum("high_overlap", high=True), _stratum("low_overlap", high=False)]

    agreed = 0
    confusion: dict[str, dict[str, int]] = {}
    for finding, gold in result.matched:
        row = confusion.setdefault(gold.contradiction_type.value, {})
        row[finding.contradiction_type.value] = row.get(finding.contradiction_type.value, 0) + 1
        if finding.contradiction_type is gold.contradiction_type:
            agreed += 1

    samples = [(finding.confidence, True) for finding, _ in result.matched]
    samples += [(finding.confidence, False) for finding in result.unmatched_findings]

    return DetectionMetrics(
        granularity=granularity,
        overall=overall,
        by_type=dict(sorted(by_type.items())),
        strata=strata,
        calibration=calibrate(samples, bins=calibration_bins),
        duplicate_count=len(result.duplicates),
        matched_count=len(result.matched),
        type_agreement=agreed / len(result.matched) if result.matched else 0.0,
        type_confusion={key: dict(sorted(row.items())) for key, row in sorted(confusion.items())},
    )


def score_benchmark(
    report: ContradictionReport,
    gold: GoldSet,
    *,
    overlap_threshold: float = DEFAULT_OVERLAP_THRESHOLD,
    calibration_bins: int = DEFAULT_CALIBRATION_BINS,
) -> BenchmarkMetrics:
    """Score a full report against a gold set at both granularities (§9.2).

    Args:
        report: The audit's contradiction report.
        gold: The labelled benchmark; only ``usable_pairs`` are scored.
        overlap_threshold: Lexical overlap at or above which a pair is "high overlap".
        calibration_bins: Number of reliability-diagram bins.

    Returns:
        The scorecard: detection at both granularities, plus the observability rates §9.2
        requires alongside them.
    """
    usable = gold.usable_pairs
    grouped_findings = report.findings
    verdict_findings = expand(grouped_findings)

    judged = report.stats.judge_llm_calls + report.stats.judge_cache_hits
    documents = report.document_count

    return BenchmarkMetrics(
        gold_pair_count=len(usable),
        finding_count=len(grouped_findings),
        verdict_count=len(verdict_findings),
        grouped=score_detection(
            grouped_findings,
            usable,
            granularity="grouped",
            overlap_threshold=overlap_threshold,
            calibration_bins=calibration_bins,
        ),
        per_verdict=score_detection(
            verdict_findings,
            usable,
            granularity="per_verdict",
            overlap_threshold=overlap_threshold,
            calibration_bins=calibration_bins,
        ),
        hallucination_rate=report.stats.hallucination_count / judged if judged else 0.0,
        decontextualization_rate=(
            report.stats.decontextualization_flags / report.claim_count
            if report.claim_count
            else 0.0
        ),
        cost_usd=report.cost.total_usd,
        cost_per_100_documents=(report.cost.total_usd / documents * 100) if documents else 0.0,
        partial=report.partial,
        partial_reason=report.partial_reason,
    )


def v1_type_order() -> list[ContradictionType]:
    """Return the five v1 contradiction types in a stable reporting order."""
    return [
        ContradictionType.DIRECT_NEGATION,
        ContradictionType.NUMERICAL_MISMATCH,
        ContradictionType.TEMPORAL_CONFLICT,
        ContradictionType.OBLIGATION_REVERSAL,
        ContradictionType.SCOPE_JURISDICTION,
    ]
