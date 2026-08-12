"""View decisions for the Streamlit demo, kept free of Streamlit (spec §7.7).

Everything the demo needs to *decide* lives here: which mode it is running in, which bundled
reports it can offer, how a passage splits around the judge's quote, how findings group on screen,
and what a confidence score should be presented as. ``ui/streamlit_app.py`` then does nothing but
call widgets with the answers.

The split is not ceremony. Streamlit's execution model — re-run the script top to bottom on every
interaction — makes logic embedded in a page genuinely hard to test, and this is the demo the
whole project is judged on. Pulling the decisions out means they are checked by ``mypy --strict``
and covered by unit tests that need no browser and no server.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from crosscheck.aggregation.report import ContradictionReport, Finding, FindingSide, load_report
from crosscheck.detection.taxonomy import ContradictionType

#: Confidence at or above which the judge has been measured as well calibrated.
TRUSTWORTHY_CONFIDENCE = 0.90

#: Confidence at or above which a verdict is shown, but flagged as overconfident. The band is not
#: a guess: the calibration study measured the 0.8-0.9 bin overconfident by +.181 on the synthetic
#: benchmark and +.252 on the hand-written one, and — the part that makes it worth surfacing — the
#: effect replicated across both, so it is a property of the judge rather than of one benchmark.
DISCOUNT_CONFIDENCE = 0.80

#: Reports shipped in the repo, offered when no service is reachable. Ordered deliberately: the
#: real-corpus run leads, because a conflict found in a published NIST standard is the most
#: honest thing this project can show, and §7.7 asks for the demo to be captured against it.
BUNDLED_REPORTS: tuple[tuple[str, str, str], ...] = (
    (
        "NIST SP 800-63B — Rev 3 vs Rev 4",
        "benchmarks/realcorpus/nist_63b/report.json",
        "Real corpus, no gold labels. Two genuine requirement changes, reported as four of "
        "fifteen findings — including the password minimum rising from 8 to 15 characters.",
    ),
    (
        "Hand-written validation set",
        "benchmarks/handwritten/report.json",
        "28 contradictions written by hand in realistic phrasing. F1 .578 — lower than the "
        "synthetic set, which is the point of having it.",
    ),
    (
        "Synthetic benchmark v1",
        "benchmarks/synthetic/v1/report.json",
        "139 contradictions injected into GDPR texts by GPT-4.1, a different model family from "
        "the judge. F1 .745.",
    ),
)

#: What the demo is doing right now. ``live`` drives a real audit through the API; ``explorer``
#: reads reports committed to the repo. Explorer is a supported configuration, not a degraded
#: one: the pipeline needs 4.2 GB of models and a vector store, which no free host will run,
#: so the deployed demo explores real results instead of pretending to compute them (D51).
Mode = Literal["live", "explorer"]

#: How a confidence score should be presented, per the calibration bands above.
ConfidenceBand = Literal["trustworthy", "discounted", "low"]


@dataclass(frozen=True)
class Segment:
    """One run of passage text, either inside the judge's evidence quote or outside it."""

    text: str
    highlighted: bool


@dataclass(frozen=True)
class BundledReport:
    """A report committed to the repo, offered in explorer mode."""

    label: str
    path: Path
    description: str


def highlight_segments(side: FindingSide) -> list[Segment]:
    """Split a passage into highlighted and plain runs around the judge's quote.

    The span is sliced before any escaping or markup, which is what keeps the offsets valid; the
    renderer escapes each segment itself. Mirrors ``html_renderer._highlight`` deliberately —
    same rule, different output format — because a demo that highlighted a different span than
    the HTML export would be a bug that only ever showed up on screen.

    Args:
        side: One half of a finding.

    Returns:
        Segments in order. Empty runs are dropped, so a quote at the very start or end of a
        passage does not produce a leading or trailing blank.
    """
    quote = side.evidence_quote
    if side.highlight_span is None:
        return [Segment(text=quote, highlighted=False)] if quote else []
    start, end = side.highlight_span
    candidates = (
        Segment(text=quote[:start], highlighted=False),
        Segment(text=quote[start:end], highlighted=True),
        Segment(text=quote[end:], highlighted=False),
    )
    return [segment for segment in candidates if segment.text]


def confidence_band(confidence: float) -> ConfidenceBand:
    """Classify a confidence score against the measured calibration bands.

    Args:
        confidence: The judge's confidence, 0.0-1.0.

    Returns:
        ``trustworthy`` at or above 0.90, ``discounted`` in 0.80-0.90 (where the judge is
        measurably overconfident on both benchmarks), ``low`` below that.
    """
    if confidence >= TRUSTWORTHY_CONFIDENCE:
        return "trustworthy"
    if confidence >= DISCOUNT_CONFIDENCE:
        return "discounted"
    return "low"


def group_by_type(
    findings: Iterable[Finding],
) -> list[tuple[ContradictionType, list[Finding]]]:
    """Group findings by contradiction type for display (§7.7).

    Types come out in taxonomy order rather than by count, so the same corpus always renders in
    the same order and two runs can be compared on screen. Types with no findings are omitted.

    Args:
        findings: Findings to group.

    Returns:
        ``(type, findings)`` pairs, each list ordered by descending confidence then pair id.
    """
    buckets: dict[ContradictionType, list[Finding]] = {}
    for finding in findings:
        buckets.setdefault(finding.contradiction_type, []).append(finding)
    ordered: list[tuple[ContradictionType, list[Finding]]] = []
    for contradiction_type in ContradictionType:
        bucket = buckets.get(contradiction_type)
        if bucket:
            bucket.sort(key=lambda f: (-f.confidence, f.pair_id))
            ordered.append((contradiction_type, bucket))
    return ordered


def empty_state_message(report: ContradictionReport) -> str:
    """The wording for a clean corpus (§7.5).

    A corpus with no contradictions is a result, not a failure, and it gets a sentence that says
    what was actually checked — the same wording the CLI prints, so the two agree.

    Args:
        report: A report with no findings.

    Returns:
        A sentence naming how much was examined to reach that conclusion.
    """
    stats = report.stats
    return (
        f"No contradictions detected across {stats.document_count} document(s) / "
        f"{stats.nli_kept_count} claim pair(s) evaluated."
    )


def bundled_reports(root: Path) -> list[BundledReport]:
    """The repo-committed reports that exist under ``root``.

    Filtered by what is actually on disk rather than assumed, so a checkout missing a benchmark
    renders a shorter list instead of erroring when the user picks it.

    Args:
        root: Repository root.

    Returns:
        The available reports, in the order declared by :data:`BUNDLED_REPORTS`.
    """
    available: list[BundledReport] = []
    for label, relative, description in BUNDLED_REPORTS:
        path = root / relative
        if path.is_file():
            available.append(BundledReport(label=label, path=path, description=description))
    return available


def load_bundled(report: BundledReport) -> ContradictionReport:
    """Read one bundled report from disk.

    Args:
        report: The report to load.

    Returns:
        The parsed report.
    """
    return load_report(report.path)


def summarize(report: ContradictionReport) -> Sequence[tuple[str, str]]:
    """Headline figures for the results screen, as ``(label, value)`` pairs.

    Returns findings, documents, pairs evaluated and cost — the four numbers that say what a run
    actually did. Cost is included because §7.7 wants spend visible to the caller, and a demo
    that hides what it spent is exactly the habit this project argues against.

    Args:
        report: The report being displayed.

    Returns:
        Label/value pairs, ready to render as metrics.
    """
    stats = report.stats
    return (
        ("Contradictions", str(report.contradiction_count)),
        ("Documents", str(stats.document_count)),
        ("Pairs evaluated", str(stats.nli_kept_count)),
        ("Cost", f"${report.cost.total_usd:.4f}"),
    )
