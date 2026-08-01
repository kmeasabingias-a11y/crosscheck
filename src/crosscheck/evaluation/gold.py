"""Gold-label schema and matching primitive for the contradiction benchmarks (§9.1, §9.2).

Every labelled benchmark — the injected synthetic set, the hand-written validation set, and any
real-corpus annotations — uses the same :class:`GoldSet` shape, so one metrics module can score
all of them and their numbers can be reported side by side (§9.2).

**How a gold label matches a prediction.** The system extracts its own claims, so a gold label
written at claim level can never match a prediction by id: a claim id is a content hash of text
the extractor chose, and the extractor may split a sentence differently on any given run. The
matching key is therefore the **pair of sections** a contradiction spans — a predicted finding
matches a gold pair when its two sides land in the gold pair's two sections, in either order.

This is deliberately coarse, and the reason is separation of concerns. Extraction quality is
measured on its own against the extraction gold set (§7.1, §9.2); end-to-end detection metrics
should not silently absorb extraction variance too, or a regression in either one becomes
impossible to attribute. Character spans are still recorded on every gold side, so a stricter
span-overlap metric can be computed later without regenerating a benchmark. See D36.

The aggregate scoring — precision, recall, F1, lexical-overlap strata, calibration — lives in the
Phase 6 metrics module. This file owns the schema, the loader, and the single-pair predicate that
scoring is built from.
"""

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Literal

from loguru import logger
from pydantic import Field, field_validator

from crosscheck.aggregation.report import Finding
from crosscheck.detection.taxonomy import V1_TYPES, ContradictionType
from crosscheck.ids import content_hash
from crosscheck.models import CrossCheckModel

#: How a gold pair came to exist. Reported separately because injected contradictions are
#: cleaner and more lexically obvious than real drift, and the gap between them is the point
#: of shipping both (§9.1).
GoldOrigin = Literal["injected", "handwritten", "real"]

#: Outcome of the manual review §9.1 requires on a sample of injected pairs.
ReviewVerdict = Literal["plausible", "implausible", "mislabelled"]


class GoldSide(CrossCheckModel):
    """One side of a labelled contradiction: where it lives and what was written there."""

    document: str = Field(
        description="Source file name, relative to the benchmark corpus. Stable and readable, "
        "unlike a content-hash doc_id."
    )
    section_id: str | None = Field(
        default=None, description="Exact section key when known; the primary matching key."
    )
    section_heading: str | None = Field(
        default=None, description="Human-readable section label, for review and for reporting."
    )
    text: str = Field(description="The claim as authored or injected.")
    evidence_quote: str = Field(default="", description="Verbatim span in the source document.")
    char_span: tuple[int, int] | None = Field(
        default=None, description="[start, end) offsets of the quote within its section."
    )


class GoldPair(CrossCheckModel):
    """One labelled contradiction between two documents."""

    pair_id: str = Field(description="Deterministic id derived from both sides (see gold_id).")
    contradiction_type: ContradictionType
    a: GoldSide
    b: GoldSide
    origin: GoldOrigin = "injected"
    generator_model: str | None = Field(
        default=None,
        description="Model that produced an injected pair — recorded so the cross-model "
        "requirement of §9.1 is auditable from the data rather than taken on trust.",
    )
    notes: str | None = None
    reviewed: bool = False
    review_verdict: ReviewVerdict | None = None

    @field_validator("contradiction_type")
    @classmethod
    def _must_be_a_v1_type(cls, value: ContradictionType) -> ContradictionType:
        """Reject gold labels for types v1 does not detect (§6 cuts CONDITIONAL_TRIPLET)."""
        if value not in V1_TYPES:
            raise ValueError(
                f"{value.value!r} is not a v1 contradiction type; gold labels must be one of "
                f"{sorted(t.value for t in V1_TYPES)}"
            )
        return value

    @property
    def granularity(self) -> Literal["section", "document"]:
        """How precisely this pair can be matched.

        ``section`` when both sides name a section; ``document`` when either does not — a
        hand-written pair authored without parsing the corpus, for instance. Document-level
        pairs match *any* finding spanning the two documents, so they are a weaker label and
        the loader warns about them.
        """
        return "section" if self.a.section_id and self.b.section_id else "document"

    @property
    def section_key(self) -> frozenset[tuple[str, str]]:
        """The unordered pair of ``(document, section)`` keys this contradiction spans.

        Falls back to document-only keys when :attr:`granularity` is ``document``.
        """
        if self.granularity == "document":
            return frozenset({(self.a.document, ""), (self.b.document, "")})
        return frozenset({_side_key(self.a), _side_key(self.b)})

    @property
    def is_usable(self) -> bool:
        """False once review has judged the pair implausible or mislabelled (§9.1)."""
        return self.review_verdict not in {"implausible", "mislabelled"}


class GoldSet(CrossCheckModel):
    """A labelled benchmark: its provenance and its pairs.

    ``corpus_dir`` is stored relative to the benchmark file so a checked-out repo resolves it
    the same way on any machine.
    """

    name: str
    version: str = "v1"
    corpus_dir: str = Field(description="Corpus directory, relative to this file's location.")
    origin: GoldOrigin = "injected"
    seed: int | None = Field(
        default=None, description="Generation seed — §9.1 requires reproducibility from it."
    )
    generator_model: str | None = None
    judge_model_at_authoring: str | None = Field(
        default=None,
        description="The judge this set was authored against, so a same-family generation can "
        "be spotted later rather than silently inflating the numbers (§9.1).",
    )
    pairs: list[GoldPair] = Field(default_factory=list)

    @property
    def usable_pairs(self) -> list[GoldPair]:
        """Pairs that survived manual review."""
        return [pair for pair in self.pairs if pair.is_usable]

    @property
    def type_counts(self) -> dict[str, int]:
        """Usable pair count per contradiction type, in taxonomy order."""
        counts: dict[str, int] = {}
        for contradiction_type in ContradictionType:
            total = sum(
                1 for pair in self.usable_pairs if pair.contradiction_type is contradiction_type
            )
            if total:
                counts[contradiction_type.value] = total
        return counts

    @property
    def cross_model(self) -> bool | None:
        """True when generation and judging used different model families (§9.1).

        None when either model is unrecorded — "unknown" and "fine" are different answers, and
        this is the check that stops a same-family benchmark being reported as if it were not.
        """
        if not self.generator_model or not self.judge_model_at_authoring:
            return None
        return _model_family(self.generator_model) != _model_family(self.judge_model_at_authoring)


def gold_id(a: GoldSide, b: GoldSide) -> str:
    """Return a deterministic, order-independent id for a gold pair.

    Derived from both sides' document, section and text so regenerating a benchmark from the
    same seed reproduces the same ids (§9.1).

    Args:
        a: One side of the contradiction.
        b: The other side.

    Returns:
        A stable hex id.
    """
    parts = sorted(f"{side.document}|{side.section_id or ''}|{side.text}" for side in (a, b))
    return content_hash("gold\x1f" + "\x1f".join(parts))


def load_gold_set(path: Path) -> GoldSet:
    """Load a gold set from JSON and log what it contains.

    Args:
        path: The benchmark JSON file.

    Returns:
        The parsed gold set.

    Raises:
        ValueError: If the file does not validate against the schema.
    """
    gold = GoldSet.model_validate_json(path.read_text(encoding="utf-8"))
    dropped = len(gold.pairs) - len(gold.usable_pairs)
    logger.info(
        "loaded gold set {!r} ({}): {} pair(s){}, types {}",
        gold.name,
        gold.version,
        len(gold.usable_pairs),
        f" ({dropped} dropped by review)" if dropped else "",
        gold.type_counts,
    )
    coarse = [pair for pair in gold.usable_pairs if pair.granularity == "document"]
    if coarse:
        logger.warning(
            "gold set {!r} has {} document-level pair(s) with no section id; these match any "
            "finding spanning the two documents and will overstate recall",
            gold.name,
            len(coarse),
        )
    if gold.cross_model is False:
        logger.warning(
            "gold set {!r} was generated by {} and judged by {} — same model family, so its "
            "scores are inflated by self-recognition (§9.1)",
            gold.name,
            gold.generator_model,
            gold.judge_model_at_authoring,
        )
    return gold


def write_gold_set(gold: GoldSet, path: Path) -> None:
    """Write a gold set as indented JSON, creating parent directories as needed.

    Args:
        gold: The set to write.
        path: Destination file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(gold.model_dump_json(indent=2), encoding="utf-8")


def finding_section_key(finding: Finding) -> frozenset[tuple[str, str]]:
    """The unordered ``(document, section)`` pair a predicted finding spans."""
    return frozenset(
        {
            (finding.a.filename, finding.a.section_id),
            (finding.b.filename, finding.b.section_id),
        }
    )


def matches(finding: Finding, gold: GoldPair) -> bool:
    """Return True if ``finding`` reports the contradiction ``gold`` describes.

    Matching is on the unordered pair of sections, not on claim ids or text — see the module
    docstring for why. Type agreement is deliberately *not* required here: whether the system
    found the contradiction and whether it labelled the type correctly are two different
    questions, and §9.2 reports them separately.

    Args:
        finding: A finding from a :class:`~crosscheck.aggregation.report.ContradictionReport`.
        gold: The gold pair to test against.

    Returns:
        True when both sides land in the gold pair's two sections.
    """
    if gold.granularity == "document":
        return _document_key(finding) == gold.section_key
    return finding_section_key(finding) == gold.section_key


def first_match(finding: Finding, gold_pairs: Iterable[GoldPair]) -> GoldPair | None:
    """Return the first gold pair a finding matches, or None if it matches none.

    Args:
        finding: The predicted finding.
        gold_pairs: Candidate gold pairs, in the order ties should be broken.

    Returns:
        The matched gold pair, or None.
    """
    return next((gold for gold in gold_pairs if matches(finding, gold)), None)


def duplicate_section_keys(pairs: Sequence[GoldPair]) -> list[frozenset[tuple[str, str]]]:
    """Return section keys shared by more than one gold pair.

    Section-level matching cannot tell two contradictions apart when they span the same two
    sections, so a benchmark containing such a collision will silently score one of them as
    already-found. A generator should call this and either merge or relocate the offenders;
    the loader does not reject them, because a real corpus may legitimately contain two.

    Args:
        pairs: The gold pairs to check.

    Returns:
        Every section key that appears more than once, in first-seen order.
    """
    seen: dict[frozenset[tuple[str, str]], int] = {}
    for pair in pairs:
        seen[pair.section_key] = seen.get(pair.section_key, 0) + 1
    return [key for key, count in seen.items() if count > 1]


def _document_key(finding: Finding) -> frozenset[tuple[str, str]]:
    """The unordered document-only key for a finding, for document-level gold pairs."""
    return frozenset({(finding.a.filename, ""), (finding.b.filename, "")})


def _side_key(side: GoldSide) -> tuple[str, str]:
    """The ``(document, section)`` key for one gold side."""
    return (side.document, side.section_id or "")


def _model_family(model: str) -> str:
    """The vendor family a model id belongs to, for the §9.1 cross-model check."""
    name = model.lower()
    for family in ("claude", "gpt", "gemini", "llama", "mistral", "command"):
        if family in name:
            return family
    return name.split("-", 1)[0]
