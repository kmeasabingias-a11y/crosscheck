"""Evaluation runner: turn scored benchmarks into a reproducible report (spec v2 §7.6, §13).

`metrics.py` computes the numbers; this file is what makes them *citable*. It loads one or more
labelled benchmarks with the reports produced for them, scores each, and writes a timestamped
directory under ``benchmarks/results/`` holding both the machine-readable metrics and the markdown
that becomes ``docs/eval-report.md``.

**Provenance is the point, not a nicety.** A precision figure with no record of which judge produced
it is not a result, it is a rumour — and this project has already paid for that: a benchmark run
silently used a different judge model than the baseline it was being compared against, missed every
cached verdict, and cost real money before anyone noticed. Every report this module writes therefore
carries the configuration it was produced under.

One honest limitation, stated in the output rather than hidden: a `ContradictionReport` does not
record which model judged it (`CostSummary` tracks spend, not models), so the configuration block
describes the settings **at evaluation time**. If you score an old report under new settings, the
block will describe the new ones. The rendered markdown says so explicitly; stamping the judge model
onto the report itself is the real fix and is noted as follow-up work.

The runner deliberately does **not** run the pipeline. Auditing is expensive and slow; scoring is
free and instant, and welding them together would mean re-running a 25-minute audit to fix a typo in
a table. ``crosscheck audit`` produces the report, ``crosscheck eval`` scores it.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger
from pydantic import Field

from crosscheck import __version__
from crosscheck.aggregation.report import load_report
from crosscheck.config import Settings
from crosscheck.evaluation.gold import GoldSet, load_gold_set
from crosscheck.evaluation.metrics import (
    DEFAULT_CALIBRATION_BINS,
    DEFAULT_OVERLAP_THRESHOLD,
    BenchmarkMetrics,
    DetectionMetrics,
    score_benchmark,
)
from crosscheck.models import CrossCheckModel

_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_METRICS_FILENAME = "eval.json"
_MARKDOWN_FILENAME = "report.md"


class BenchmarkSpec(CrossCheckModel):
    """One benchmark to score: a gold set and the report produced against its corpus."""

    name: str = Field(description="Short label used as the section heading, e.g. 'synthetic-v1'.")
    gold_path: Path
    report_path: Path


class BenchmarkSuite(CrossCheckModel):
    """Several benchmarks to score into a single report.

    The point of a suite is that the synthetic and hand-written sets belong in *one* document,
    next to each other: the gap between them is the result, and a reader who has to open two
    files to find it will not (§9.1, §14). Committing the manifest also makes the published
    report reproducible with one command rather than a remembered pair of paths.
    """

    benchmarks: list[BenchmarkSpec] = Field(default_factory=list)


def load_suite(path: Path) -> list[BenchmarkSpec]:
    """Load a suite manifest, resolving its paths relative to the manifest's own directory.

    Relative resolution is what makes a committed manifest portable: the paths inside it are
    written relative to the file, so it works from any working directory and on any checkout.

    Args:
        path: The manifest JSON file.

    Returns:
        The benchmark specs, with absolute paths.

    Raises:
        ValueError: If the manifest does not validate, or lists no benchmarks.
    """
    suite = BenchmarkSuite.model_validate_json(path.read_text(encoding="utf-8"))
    if not suite.benchmarks:
        raise ValueError(f"{path} lists no benchmarks")
    root = path.resolve().parent
    return [
        spec.model_copy(
            update={
                "gold_path": (root / spec.gold_path).resolve(),
                "report_path": (root / spec.report_path).resolve(),
            }
        )
        for spec in suite.benchmarks
    ]


class RunConfig(CrossCheckModel):
    """The pipeline configuration a set of numbers should be read against.

    Captured from :class:`~crosscheck.config.Settings` at evaluation time — see the module
    docstring for why that is not the same as the configuration the audit ran under.
    """

    crosscheck_version: str
    judge_model: str
    extraction_model: str
    retrieval_strategy: str
    retrieval_top_k: int
    rerank_model: str
    rerank_top_k: int
    nli_model: str
    nli_default_threshold: float
    nli_thresholds: dict[str, float] = Field(default_factory=dict)
    overlap_threshold: float = DEFAULT_OVERLAP_THRESHOLD
    calibration_bins: int = DEFAULT_CALIBRATION_BINS

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        overlap_threshold: float = DEFAULT_OVERLAP_THRESHOLD,
        calibration_bins: int = DEFAULT_CALIBRATION_BINS,
    ) -> "RunConfig":
        """Snapshot the settings that matter to a detection number.

        Args:
            settings: Runtime configuration.
            overlap_threshold: Lexical-overlap cut used for the strata.
            calibration_bins: Reliability-diagram bin count.

        Returns:
            The snapshot, ready to embed in the report.
        """
        return cls(
            crosscheck_version=__version__,
            judge_model=settings.judge_model,
            extraction_model=settings.extraction_model,
            retrieval_strategy=settings.retrieval_strategy,
            retrieval_top_k=settings.retrieval_top_k,
            rerank_model=settings.rerank_model,
            rerank_top_k=settings.rerank_top_k,
            nli_model=settings.nli_model,
            nli_default_threshold=settings.nli_default_threshold,
            nli_thresholds={k.value: v for k, v in settings.nli_thresholds.items()},
            overlap_threshold=overlap_threshold,
            calibration_bins=calibration_bins,
        )


class GoldSummary(CrossCheckModel):
    """What a benchmark is, so its numbers can be read in context (§9.1)."""

    name: str
    version: str
    origin: str
    seed: int | None = None
    generator_model: str | None = None
    judge_model_at_authoring: str | None = None
    cross_model: bool | None = Field(
        default=None,
        description="True when generation and judging used different families. None means one "
        "of the two models was not recorded — unknown is not the same as fine (§9.1).",
    )
    pair_count: int = 0
    usable_pair_count: int = 0
    type_counts: dict[str, int] = Field(default_factory=dict)

    @classmethod
    def of(cls, gold: GoldSet) -> "GoldSummary":
        """Summarize a loaded gold set."""
        return cls(
            name=gold.name,
            version=gold.version,
            origin=gold.origin,
            seed=gold.seed,
            generator_model=gold.generator_model,
            judge_model_at_authoring=gold.judge_model_at_authoring,
            cross_model=gold.cross_model,
            pair_count=len(gold.pairs),
            usable_pair_count=len(gold.usable_pairs),
            type_counts=gold.type_counts,
        )


class BenchmarkResult(CrossCheckModel):
    """One benchmark, scored."""

    name: str
    gold_path: Path
    report_path: Path
    gold: GoldSummary
    metrics: BenchmarkMetrics

    @property
    def warnings(self) -> list[str]:
        """Conditions that make these numbers unsafe to quote as-is.

        Rendered into the markdown so a caveat travels with the table rather than living in
        someone's memory of the run.
        """
        found: list[str] = []
        if self.metrics.partial:
            found.append(
                f"The audit was **partial** ({self.metrics.partial_reason}). Recall is "
                "understated: pairs that were never judged are counted as misses."
            )
        if self.metrics.grouped.duplicate_count:
            found.append(
                f"{self.metrics.grouped.duplicate_count} finding(s) landed on a gold pair already "
                "claimed by another at grouped granularity. Expected 0 — the report's "
                "near-duplicate roll-up and the gold set's section matching have diverged."
            )
        # Only an *injected* benchmark can be inflated by self-recognition, because only an
        # injected benchmark was written by a model. A hand-written set has no generator to
        # compare against, so raising "cross-model status unknown" there would be noise
        # attached to the one benchmark whose provenance is least in doubt (D44).
        if self.gold.origin == "injected":
            if self.gold.cross_model is False:
                found.append(
                    "Generator and judge are the **same model family**. §9.1 requires different "
                    "families; these numbers partly measure self-recognition."
                )
            if self.gold.cross_model is None:
                found.append(
                    "Cross-model status is **unknown** — the gold set does not record both the "
                    "generator and the judge it was authored against."
                )
        if self.gold.usable_pair_count < self.gold.pair_count:
            found.append(
                f"{self.gold.pair_count - self.gold.usable_pair_count} gold pair(s) were excluded "
                "by manual review and are not scored."
            )
        return found


class EvalRun(CrossCheckModel):
    """A full evaluation: every benchmark scored under one configuration."""

    generated_at: datetime | None = Field(
        default=None,
        description="Left None by default so a fixture-driven test stays byte-stable.",
    )
    config: RunConfig
    benchmarks: list[BenchmarkResult] = Field(default_factory=list)


def evaluate(
    specs: Sequence[BenchmarkSpec],
    settings: Settings,
    *,
    overlap_threshold: float = DEFAULT_OVERLAP_THRESHOLD,
    calibration_bins: int = DEFAULT_CALIBRATION_BINS,
    generated_at: datetime | None = None,
) -> EvalRun:
    """Load and score every benchmark in ``specs``.

    Args:
        specs: The benchmarks to score.
        settings: Runtime configuration, captured into the report for provenance.
        overlap_threshold: Lexical overlap at or above which a pair is "high overlap".
        calibration_bins: Number of reliability-diagram bins.
        generated_at: Timestamp to stamp on the run; None leaves it unstamped.

    Returns:
        The scored run, ready to write.
    """
    results: list[BenchmarkResult] = []
    for spec in specs:
        gold = load_gold_set(spec.gold_path)
        report = load_report(spec.report_path)
        metrics = score_benchmark(
            report,
            gold,
            overlap_threshold=overlap_threshold,
            calibration_bins=calibration_bins,
        )
        logger.info(
            "scored {!r}: P {:.3f} R {:.3f} F1 {:.3f} over {} gold pair(s)",
            spec.name,
            metrics.grouped.overall.precision,
            metrics.grouped.overall.recall,
            metrics.grouped.overall.f1,
            metrics.gold_pair_count,
        )
        results.append(
            BenchmarkResult(
                name=spec.name,
                gold_path=spec.gold_path,
                report_path=spec.report_path,
                gold=GoldSummary.of(gold),
                metrics=metrics,
            )
        )
    return EvalRun(
        generated_at=generated_at,
        config=RunConfig.from_settings(
            settings, overlap_threshold=overlap_threshold, calibration_bins=calibration_bins
        ),
        benchmarks=results,
    )


def _row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    return [
        _row(headers),
        _row(["---"] * len(headers)),
        *(_row(row) for row in rows),
    ]


def _detection_tables(detection: DetectionMetrics) -> list[str]:
    counts = detection.overall
    lines = [
        *_table(
            ["metric", "value"],
            [
                ["Precision", f"{counts.precision:.3f}"],
                ["Recall", f"{counts.recall:.3f}"],
                ["F1", f"{counts.f1:.3f}"],
                [
                    "TP / FP / FN",
                    f"{counts.true_positives} / "
                    f"{counts.false_positives} / {counts.false_negatives}",
                ],
                ["Duplicates", str(detection.duplicate_count)],
            ],
        ),
        "",
        "**By contradiction type**",
        "",
        *_table(
            ["type", "TP", "FP", "FN", "P", "R", "F1"],
            [
                [
                    name,
                    str(c.true_positives),
                    str(c.false_positives),
                    str(c.false_negatives),
                    f"{c.precision:.3f}",
                    f"{c.recall:.3f}",
                    f"{c.f1:.3f}",
                ]
                for name, c in detection.by_type.items()
            ],
        ),
        "",
        "**By lexical overlap** — the stratum that shows whether the system only catches "
        "near-duplicate phrasing (§9.2).",
        "",
        *_table(
            ["stratum", "cut", "TP", "FP", "FN", "P", "R", "F1"],
            [
                [
                    s.name,
                    f"{s.threshold:.2f}",
                    str(s.counts.true_positives),
                    str(s.counts.false_positives),
                    str(s.counts.false_negatives),
                    f"{s.counts.precision:.3f}",
                    f"{s.counts.recall:.3f}",
                    f"{s.counts.f1:.3f}",
                ]
                for s in detection.strata
            ],
        ),
    ]
    return lines


def _calibration_section(detection: DetectionMetrics) -> list[str]:
    calibration = detection.calibration
    populated = [b for b in calibration.bins if b.count]
    return [
        "**Confidence calibration** — predicted confidence against observed correctness (§9.2).",
        "",
        f"ECE {calibration.expected_error:.4f} · MCE {calibration.max_error:.4f} · "
        f"Brier {calibration.brier:.4f} · n={calibration.sample_count}",
        "",
        *_table(
            ["confidence bin", "n", "mean confidence", "accuracy", "gap"],
            [
                [
                    f"{b.lower:.1f} to {b.upper:.1f}",
                    str(b.count),
                    f"{b.mean_confidence:.3f}",
                    f"{b.accuracy:.3f}",
                    f"{b.gap:+.3f}",
                ]
                for b in populated
            ],
        ),
        "",
        "A positive gap means overconfident. Empty bins are omitted here but kept in `eval.json` "
        "so a plotted diagram has a stable axis.",
    ]


def _stratum_f1(result: BenchmarkResult, name: str) -> float | None:
    """The grouped F1 for one lexical-overlap stratum, or None if that stratum is empty."""
    for stratum in result.metrics.grouped.strata:
        if stratum.name == name:
            counts = stratum.counts
            total = counts.true_positives + counts.false_positives + counts.false_negatives
            return counts.f1 if total else None
    return None


def _comparison_section(run: EvalRun) -> list[str]:
    """Render the head-to-head table and the gap statement §13 requires.

    Only meaningful when a run scores more than one benchmark, which is the case the suite
    manifest exists to create. The gap between an injected benchmark and a hand-authored one is
    the project's central honesty claim, and a reader should not have to compute it by scrolling
    between two tables.

    Args:
        run: The scored run.

    Returns:
        Markdown lines, or an empty list when there is nothing to compare.
    """
    if len(run.benchmarks) < 2:
        return []

    def cell(value: float | None) -> str:
        return "—" if value is None else f"{value:.3f}"

    lines = [
        "",
        "## Benchmarks side by side",
        "",
        "The gap between these rows is the result. A number from an injected benchmark is a "
        "ceiling; a number from a hand-authored one is closer to what a real corpus would give "
        "(§9.1, §14).",
        "",
        *_table(
            [
                "benchmark",
                "origin",
                "gold pairs",
                "median overlap",
                "P",
                "R",
                "F1",
                "low-overlap F1",
            ],
            [
                [
                    result.name,
                    result.gold.origin,
                    str(result.gold.usable_pair_count),
                    cell(result.metrics.median_gold_overlap),
                    f"{result.metrics.grouped.overall.precision:.3f}",
                    f"{result.metrics.grouped.overall.recall:.3f}",
                    f"{result.metrics.grouped.overall.f1:.3f}",
                    cell(_stratum_f1(result, "low_overlap")),
                ]
                for result in run.benchmarks
            ],
        ),
    ]

    injected = [r for r in run.benchmarks if r.gold.origin == "injected"]
    authored = [r for r in run.benchmarks if r.gold.origin != "injected"]
    if len(injected) == 1 and len(authored) == 1:
        high, low = injected[0], authored[0]
        delta = high.metrics.grouped.overall.f1 - low.metrics.grouped.overall.f1
        direction = "below" if delta > 0 else "above"
        lines += [
            "",
            f"**The gap.** `{low.name}` ({low.gold.origin}) scores F1 "
            f"{low.metrics.grouped.overall.f1:.3f}, {abs(delta):.3f} {direction} the "
            f"{high.metrics.grouped.overall.f1:.3f} of the injected `{high.name}`. The two runs "
            "share every pipeline setting in the configuration block above, so the difference is "
            "attributable to the benchmarks rather than to the system.",
            "",
            "Injected pairs are lexically closer to each other than hand-authored ones — a "
            "generator asked to negate a sentence answers in that sentence's vocabulary — and the "
            "median-overlap column quantifies it. Quote the lower number, or quote both.",
        ]
    return lines


def render_markdown(run: EvalRun) -> str:
    """Render an evaluation run as the markdown of ``docs/eval-report.md``.

    Args:
        run: The scored run.

    Returns:
        The complete markdown document.
    """
    stamp = run.generated_at.strftime("%Y-%m-%d %H:%M UTC") if run.generated_at else "unstamped"
    config = run.config
    lines: list[str] = [
        "# CrossCheck evaluation report",
        "",
        f"Generated {stamp} · crosscheck {config.crosscheck_version}",
        "",
        "## Configuration",
        "",
        "These are the settings **at evaluation time**. A contradiction report does not record "
        "which model judged it, so scoring an old report under new settings will describe the new "
        "ones — check this block against the run you meant to score.",
        "",
        *_table(
            ["setting", "value"],
            [
                ["judge model", config.judge_model],
                ["extraction model", config.extraction_model],
                ["retrieval", f"{config.retrieval_strategy}, top-{config.retrieval_top_k}"],
                ["reranker", f"{config.rerank_model}, top-{config.rerank_top_k}"],
                ["NLI model", config.nli_model],
                ["NLI threshold", f"{config.nli_default_threshold}"],
                ["NLI per-type thresholds", str(config.nli_thresholds or "none")],
                ["overlap cut", f"{config.overlap_threshold:.2f}"],
            ],
        ),
    ]

    for result in run.benchmarks:
        metrics = result.metrics
        gold = result.gold
        lines += [
            "",
            f"## {result.name}",
            "",
            f"`{result.gold_path}` scored against `{result.report_path}`.",
            "",
        ]
        if result.warnings:
            lines += ["> **Read these numbers with care.**", ""]
            lines += [f"> - {warning}" for warning in result.warnings]
            lines += [""]
        lines += [
            *_table(
                ["benchmark", "value"],
                [
                    ["origin", gold.origin],
                    ["generator", gold.generator_model or "—"],
                    ["judge at authoring", gold.judge_model_at_authoring or "—"],
                    [
                        "cross-model (§9.1)",
                        # "unknown" is the right answer only for an injected set. A hand-authored
                        # one has no generator to compare against, so the question does not apply
                        # and saying "unknown" would imply a gap in the provenance record (D44).
                        "n/a (hand-authored)"
                        if gold.origin != "injected"
                        else {True: "yes", False: "NO", None: "unknown"}[gold.cross_model],
                    ],
                    ["seed", str(gold.seed) if gold.seed is not None else "—"],
                    ["gold pairs scored", str(gold.usable_pair_count)],
                    ["findings (grouped)", str(metrics.finding_count)],
                    ["verdicts (expanded)", str(metrics.verdict_count)],
                ],
            ),
            "",
            "### Detection — grouped (headline)",
            "",
            "One row per contradiction as displayed, near-duplicates rolled up. This is the "
            "granularity the README quotes; see D42.",
            "",
            *_detection_tables(metrics.grouped),
            "",
            "### Detection — per verdict (diagnostic)",
            "",
            "Every judge verdict scored separately. Answers how often the *judge* was right, "
            "not how often what a user is shown is right.",
            "",
            *_table(
                ["metric", "value"],
                [
                    ["Precision", f"{metrics.per_verdict.overall.precision:.3f}"],
                    ["Recall", f"{metrics.per_verdict.overall.recall:.3f}"],
                    ["F1", f"{metrics.per_verdict.overall.f1:.3f}"],
                    ["Duplicates (not scored)", str(metrics.per_verdict.duplicate_count)],
                ],
            ),
            "",
            "### Calibration",
            "",
            *_calibration_section(metrics.grouped),
            "",
            "### Type agreement",
            "",
            f"{metrics.grouped.type_agreement:.3f} of found contradictions carry the gold's own "
            "type. Matching deliberately ignores type (D36), so a mislabelled hit is still a hit. "
            "The taxonomy overlaps — an obligation reversal is usually also a direct negation — so "
            "read the confusion matrix in `eval.json` before treating this as an error rate.",
            "",
            "### Observability and cost",
            "",
            *_table(
                ["metric", "value"],
                [
                    ["judge hallucination rate", f"{metrics.hallucination_rate:.4f}"],
                    ["decontextualization failure rate", f"{metrics.decontextualization_rate:.4f}"],
                    ["cost (this run)", f"${metrics.cost_usd:.4f}"],
                    ["cost per 100 documents", f"${metrics.cost_per_100_documents:.2f}"],
                ],
            ),
            "",
            "Cost reflects cache hits and so understates a cold run; it is spend, not price.",
        ]

    lines += [
        "",
        "## How to read these numbers",
        "",
        "- **Matching is at section level** (D36): a finding counts when both sides land in the "
        "gold pair's two sections. That is deliberately coarse — extraction quality is measured "
        "separately against its own gold set — and it is generous to the system.",
        "- **False positives are an upper bound on error** on an injected benchmark. Only what was "
        "injected is labelled, so a finding that flags a real but unlabelled contradiction counts "
        "against us.",
        "- **Injected contradictions are cleaner than real drift.** Synthetic numbers are the "
        "ceiling, not the expectation; the hand-written set and the real-corpus check are what "
        "test transfer (§9.1, §9.4).",
    ]
    lines += _comparison_section(run)
    lines += [""]
    return "\n".join(lines) + "\n"


def write_run(run: EvalRun, root: Path, *, directory_name: str | None = None) -> Path:
    """Write ``eval.json`` and ``report.md`` into a timestamped directory under ``root``.

    Args:
        run: The scored run.
        root: Results root, e.g. ``benchmarks/results``.
        directory_name: Override the timestamped directory name (used by tests).

    Returns:
        The directory written to.
    """
    if directory_name is None:
        stamp = run.generated_at or datetime.now(UTC)
        directory_name = stamp.strftime(_TIMESTAMP_FORMAT)
    destination = root / directory_name
    destination.mkdir(parents=True, exist_ok=True)
    (destination / _METRICS_FILENAME).write_text(run.model_dump_json(indent=2), encoding="utf-8")
    (destination / _MARKDOWN_FILENAME).write_text(render_markdown(run), encoding="utf-8")
    logger.info("wrote evaluation report to {}", destination)
    return destination
