"""Synthetic contradiction benchmark generator (spec v2 §7.6, §9.1).

Takes a seed corpus of documents, injects contradictions of each v1 type into paired documents,
and writes both the modified corpus and a :class:`~crosscheck.evaluation.gold.GoldSet` describing
exactly what was injected and where.

**Cross-model by construction.** Generation runs through whatever :class:`StructuredLLM` it is
given, and the model id is recorded on every gold pair and on the set. §9.1 requires the generator
to be a different family from the judge, and recording it in the artifact means a same-family run
is visible in the data rather than resting on a claim in a README (D37).

**Deterministic from a seed.** Which documents pair with which, which sections are chosen, and in
what order, are all decided by a seeded RNG *before* any LLM call. The model's wording is not
reproducible in the strict sense — `temperature=0` and `seed` are best-effort at the API — which
is exactly why the generated corpus and its gold labels are committed to the repo rather than
regenerated on demand.

**Why the output corpus is Markdown regardless of input format.** Injection means rewriting a
document, and rewriting a PDF or DOCX faithfully is a large amount of machinery for no measurement
value: the synthetic benchmark exists to measure *detection*, and format handling is already
covered by the parser tests and the acceptance corpus. Parsing on the way in is format-agnostic,
so a PDF seed corpus works fine — it simply comes out the other side as Markdown.

**Sections are paired by topic, not at random.** The first version of this module drew source
and target sections uniformly, and the dry run showed why that fails: asked to contradict two
unrelated sections, an instruction-following model complies rather than refusing. It produced
topically absurd placements — a data-retention rule injected into a Remote Work section — and,
worse, gold labels that were not contradictions at all ("employees return property on their last
day" vs "contractors return property within 14 days" is two rules for two populations). A wrong
gold label corrupts metrics in *both* directions: the system correctly declining to flag a
non-contradiction is scored as a miss, depressing recall for being right.

So targets are now chosen from a section's nearest neighbours in embedding space, using the same
dense embedder the pipeline retrieves with. The generator is only ever asked to contradict
something the target section actually discusses. See D38.

**Section ids are resolved after writing, not before.** A ``section_id`` derives from a ``doc_id``,
which is a content hash of the whole document — so injecting text *changes every section id in
that document*. Gold labels are therefore filled in by re-parsing the written corpus and locating
each claim in it, which guarantees the ids in the benchmark are the ones the pipeline will compute
when it audits the same files. See D38.
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

from crosscheck.aggregation.report import locate_quote
from crosscheck.config import Settings
from crosscheck.detection.taxonomy import V1_TYPES, ContradictionType
from crosscheck.evaluation.gold import (
    GoldPair,
    GoldSet,
    GoldSide,
    duplicate_section_keys,
    gold_id,
)
from crosscheck.ingestion.parsers import UnsupportedFormatError, parse
from crosscheck.llm import LLMError, StructuredLLM
from crosscheck.models import Document, Section
from crosscheck.prompts import load_prompt
from crosscheck.storage.embeddings import DenseEmbedder

#: A section's position in the corpus: (document index, section index).
SectionKey = tuple[int, int]

#: Sections shorter than this carry too little to contradict; skipped when choosing a source.
_MIN_SOURCE_CHARS = 240

#: Cap on how much section text is shown to the generator, to bound cost per call.
_MAX_EXCERPT_CHARS = 1800

#: Output cap per injection. The claim is a sentence or two; this is ample.
_INJECTION_MAX_TOKENS = 700

#: How many related sections in other documents each source may draw a target from.
_DEFAULT_TOP_K = 5

#: Cosine floor for calling two sections related. Below this the generator would be asked to
#: invent a link, which is exactly the failure the dry run surfaced.
_DEFAULT_MIN_SIMILARITY = 0.55

_TYPE_DEFINITIONS: dict[ContradictionType, str] = {
    ContradictionType.DIRECT_NEGATION: (
        "The target must assert the logical opposite of the source claim: one says X holds, the "
        "other says X does not."
    ),
    ContradictionType.NUMERICAL_MISMATCH: (
        "The target must give the same subject an incompatible quantity, threshold, duration or "
        "date — a number that cannot also be correct."
    ),
    ContradictionType.TEMPORAL_CONFLICT: (
        "The target must supersede, deprecate or postdate the source claim while both documents "
        "remain current. A supersession marker is appropriate here."
    ),
    ContradictionType.OBLIGATION_REVERSAL: (
        "The source mandates an action and the target prohibits or exempts from it, or the "
        "reverse. The conflict is about duty, not about fact."
    ),
    ContradictionType.SCOPE_JURISDICTION: (
        "The two must agree in the general case but diverge for a named scope, population or "
        "jurisdiction, with no stated carve-out reconciling them."
    ),
}


class GeneratedInjection(BaseModel):
    """What the generator model returns for one injection."""

    source_claim: str = Field(
        description="Verbatim sentence from the source excerpt that is being contradicted; "
        "empty when the excerpt holds nothing concrete enough to contradict."
    )
    injected_claim: str = Field(description="The contradicting statement for the target document.")
    rationale: str = Field(description="One sentence on why the two cannot both hold.")


@dataclass(frozen=True)
class InjectionPlan:
    """One planned injection, decided before any LLM call so planning stays deterministic."""

    contradiction_type: ContradictionType
    source_index: int
    source_section_index: int
    target_index: int
    target_section_index: int


@dataclass
class GenerationResult:
    """What a generation run produced, including what it could not produce."""

    gold: GoldSet
    corpus_dir: Path
    gold_path: Path
    planned: int = 0
    skipped: list[str] = field(default_factory=list)
    cost_usd: float = 0.0

    @property
    def generated(self) -> int:
        """Injections that survived generation and validation."""
        return len(self.gold.pairs)


def section_candidates(documents: Sequence[Document]) -> list[SectionKey]:
    """Sections long enough to carry a contradictable assertion, in corpus order."""
    return [
        (doc_index, section_index)
        for doc_index, document in enumerate(documents)
        for section_index, section in enumerate(document.sections)
        if len(section.text.strip()) >= _MIN_SOURCE_CHARS
    ]


def related_sections(
    documents: Sequence[Document],
    embedder: DenseEmbedder,
    *,
    top_k: int = _DEFAULT_TOP_K,
    min_similarity: float = _DEFAULT_MIN_SIMILARITY,
) -> dict[SectionKey, list[SectionKey]]:
    """Map each candidate section to its nearest sections in *other* documents.

    Uses the pipeline's own dense embedder, so "related" here means the same thing it means at
    retrieval time. Neighbours below ``min_similarity`` are dropped rather than padded: a source
    section with no topical partner should produce no injection at all, because asking a model to
    contradict an unrelated section produces a fake contradiction, not a hard one (D38).

    Args:
        documents: Parsed seed documents.
        embedder: Dense embedder; the same model the pipeline retrieves with.
        top_k: How many neighbours to keep per section.
        min_similarity: Cosine floor for calling two sections related.

    Returns:
        Neighbours per section, best first. Sections with none are omitted.
    """
    candidates = section_candidates(documents)
    if not candidates:
        return {}
    vectors = embedder.embed_passages(
        [documents[d].sections[s].text.strip() for d, s in candidates]
    )
    normalised = [_normalise(vector) for vector in vectors]

    neighbours: dict[SectionKey, list[SectionKey]] = {}
    for index, key in enumerate(candidates):
        scored = [
            (_dot(normalised[index], normalised[other]), candidates[other])
            for other in range(len(candidates))
            if candidates[other][0] != key[0]  # a contradiction must span two documents
        ]
        # Sort by score, then by key, so ties never depend on iteration order.
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        kept = [other for score, other in scored[:top_k] if score >= min_similarity]
        if kept:
            neighbours[key] = kept
    return neighbours


def plan_injections(
    documents: Sequence[Document],
    neighbours: dict[SectionKey, list[SectionKey]],
    *,
    seed: int,
    per_type: int,
) -> list[InjectionPlan]:
    """Decide every injection up front, deterministically.

    Pure and hermetic: all the embedding work happens in :func:`related_sections`, so planning
    can be tested without loading a model. Each unordered section pair is used at most once,
    because section-level gold matching cannot tell two contradictions apart when they span the
    same two sections (D36).

    Args:
        documents: Parsed seed documents, in a stable order.
        neighbours: Topically related sections per source, from :func:`related_sections`.
        seed: RNG seed; the same seed and neighbours produce the same plan.
        per_type: How many injections to plan for each of the five v1 types.

    Returns:
        The planned injections, ordered by type then by draw.
    """
    rng = random.Random(seed)
    sources = sorted(neighbours)
    if len(documents) < 2 or not sources:
        return []

    plans: list[InjectionPlan] = []
    used: set[frozenset[SectionKey]] = set()
    for contradiction_type in sorted(V1_TYPES, key=lambda t: t.value):
        drawn = 0
        for _ in range(per_type * 40):
            if drawn >= per_type:
                break
            source = rng.choice(sources)
            target = rng.choice(neighbours[source])
            key = frozenset({source, target})
            if key in used:
                continue
            used.add(key)
            plans.append(
                InjectionPlan(
                    contradiction_type=contradiction_type,
                    source_index=source[0],
                    source_section_index=source[1],
                    target_index=target[0],
                    target_section_index=target[1],
                )
            )
            drawn += 1
        if drawn < per_type:
            logger.warning(
                "only planned {}/{} injections for {} — the corpus ran out of distinct "
                "related section pairs",
                drawn,
                per_type,
                contradiction_type.value,
            )
    return plans


def _normalise(vector: Sequence[float]) -> list[float]:
    """Unit-normalise a vector so a dot product is cosine similarity."""
    norm = sum(value * value for value in vector) ** 0.5
    return [value / norm for value in vector] if norm else list(vector)


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    """Dot product of two equal-length vectors."""
    return sum(x * y for x, y in zip(a, b, strict=True))


def generate_benchmark(
    seed_corpus: Path,
    out_dir: Path,
    llm: StructuredLLM,
    settings: Settings,
    embedder: DenseEmbedder,
    *,
    seed: int,
    per_type: int,
    name: str = "synthetic",
    version: str = "v1",
) -> GenerationResult:
    """Generate a labelled contradiction benchmark from a seed corpus.

    Args:
        seed_corpus: Directory of seed documents (any supported format).
        out_dir: Where the modified corpus and ``gold.json`` are written.
        llm: The generator client — must be a different model family from the judge (§9.1).
        settings: Runtime configuration; ``generator_model`` selects the model.
        embedder: Dense embedder used to pair sections by topic (D38).
        seed: RNG seed for planning.
        per_type: Injections to attempt per contradiction type.
        name: Benchmark name recorded in the gold set.
        version: Benchmark version recorded in the gold set.

    Returns:
        The result, including the gold set and anything that had to be skipped.

    Raises:
        FileNotFoundError: If ``seed_corpus`` does not exist.
    """
    documents = _load_seed_documents(seed_corpus)
    neighbours = related_sections(documents, embedder)
    plans = plan_injections(documents, neighbours, seed=seed, per_type=per_type)
    logger.info(
        "planned {} injection(s) from {} seed document(s); {} of {} section(s) had a "
        "topically related partner in another document",
        len(plans),
        len(documents),
        len(neighbours),
        len(section_candidates(documents)),
    )

    system_prompt = load_prompt("benchmark_injection_system")
    user_prompt = load_prompt("benchmark_injection_user")

    # Mutable copy of every section's text, so injections accumulate before anything is written.
    bodies: list[list[str]] = [[s.text for s in document.sections] for document in documents]
    accepted: list[tuple[InjectionPlan, GeneratedInjection]] = []
    skipped: list[str] = []
    spent_before = llm.cost.total_usd

    for plan in plans:
        source_doc, target_doc = documents[plan.source_index], documents[plan.target_index]
        source_section = source_doc.sections[plan.source_section_index]
        target_section = target_doc.sections[plan.target_section_index]
        excerpt = _excerpt(source_section.text)
        rendered = user_prompt.render(
            contradiction_type=plan.contradiction_type.value,
            type_definition=_TYPE_DEFINITIONS[plan.contradiction_type],
            source_document=_output_name(source_doc),
            source_heading=source_section.heading or "(untitled)",
            source_excerpt=excerpt,
            target_document=_output_name(target_doc),
            target_heading=target_section.heading or "(untitled)",
            target_excerpt=_excerpt(target_section.text),
        )
        try:
            injection = llm.structured(
                model=settings.generator_model,
                system=system_prompt.text,
                user=rendered,
                schema=GeneratedInjection,
                max_tokens=_INJECTION_MAX_TOKENS,
            )
        except LLMError as exc:
            skipped.append(f"{plan.contradiction_type.value}: generation failed — {exc}")
            continue

        reason = _reject_reason(injection, excerpt)
        if reason is not None:
            skipped.append(f"{plan.contradiction_type.value}: {reason}")
            continue

        bodies[plan.target_index][plan.target_section_index] = (
            bodies[plan.target_index][plan.target_section_index].rstrip()
            + "\n\n"
            + injection.injected_claim.strip()
        )
        accepted.append((plan, injection))

    corpus_dir = out_dir / "corpus"
    _write_corpus(documents, bodies, corpus_dir)
    gold = _build_gold_set(
        documents,
        accepted,
        corpus_dir,
        settings=settings,
        seed=seed,
        name=name,
        version=version,
        skipped=skipped,
    )
    gold_path = out_dir / "gold.json"
    gold_path.parent.mkdir(parents=True, exist_ok=True)
    gold_path.write_text(gold.model_dump_json(indent=2), encoding="utf-8")

    result = GenerationResult(
        gold=gold,
        corpus_dir=corpus_dir,
        gold_path=gold_path,
        planned=len(plans),
        skipped=skipped,
        cost_usd=llm.cost.total_usd - spent_before,
    )
    logger.info(
        "generated {}/{} injection(s) into {} document(s) for ${:.4f}; {} skipped",
        result.generated,
        result.planned,
        len(documents),
        result.cost_usd,
        len(skipped),
    )
    collisions = duplicate_section_keys(gold.pairs)
    if collisions:
        logger.warning(
            "{} section-pair collision(s) in the gold set — those pairs cannot be told apart "
            "by section-level matching (D36)",
            len(collisions),
        )
    return result


def _load_seed_documents(seed_corpus: Path) -> list[Document]:
    """Parse every supported file in the seed corpus, in filename order."""
    if not seed_corpus.exists():
        raise FileNotFoundError(seed_corpus)
    documents: list[Document] = []
    for path in sorted(p for p in seed_corpus.rglob("*") if p.is_file()):
        try:
            documents.append(parse(path))
        except UnsupportedFormatError:
            logger.debug("skipping unsupported seed file {}", path.name)
    return documents


def _excerpt(text: str) -> str:
    """Trim section text to a cost-bounded excerpt, on a whitespace boundary."""
    stripped = text.strip()
    if len(stripped) <= _MAX_EXCERPT_CHARS:
        return stripped
    cut = stripped[:_MAX_EXCERPT_CHARS]
    return cut[: cut.rfind(" ")] if " " in cut else cut


def _reject_reason(injection: GeneratedInjection, excerpt: str) -> str | None:
    """Return why this injection is unusable, or None if it is fine.

    The verbatim check is the load-bearing one. A gold label whose ``source_claim`` is a
    paraphrase points at text that does not exist in the corpus, so the span recorded for it
    would be wrong and any span-level metric computed later would be measuring nothing.
    """
    if not injection.source_claim.strip():
        return "generator found nothing concrete to contradict"
    if not injection.injected_claim.strip():
        return "empty injected claim"
    if locate_quote(excerpt, injection.source_claim) is None:
        return "source_claim is not verbatim in the excerpt"
    return None


def _output_name(document: Document) -> str:
    """The generated corpus writes Markdown regardless of the seed document's format."""
    return f"{document.source_path.stem}.md"


def _render_markdown(document: Document, bodies: Sequence[str]) -> str:
    """Rebuild a document as Markdown from its sections' (possibly injected) bodies."""
    parts: list[str] = []
    if document.title:
        parts.append(f"# {document.title}\n")
    for section, body in zip(document.sections, bodies, strict=True):
        if section.heading:
            parts.append(f"## {section.heading}\n")
        parts.append(f"{body.strip()}\n")
    return "\n".join(parts).rstrip() + "\n"


def _write_corpus(
    documents: Sequence[Document],
    bodies: Sequence[Sequence[str]],
    corpus_dir: Path,
) -> None:
    """Write every document, injected or not, as Markdown into ``corpus_dir``."""
    corpus_dir.mkdir(parents=True, exist_ok=True)
    for document, document_bodies in zip(documents, bodies, strict=True):
        path = corpus_dir / _output_name(document)
        path.write_text(_render_markdown(document, document_bodies), encoding="utf-8")


def _build_gold_set(
    documents: Sequence[Document],
    accepted: Sequence[tuple[InjectionPlan, GeneratedInjection]],
    corpus_dir: Path,
    *,
    settings: Settings,
    seed: int,
    name: str,
    version: str,
    skipped: Sequence[str],
) -> GoldSet:
    """Re-parse the written corpus and label each injection against the ids it will really have.

    Section ids derive from a document's content hash, so injecting text changes every id in
    that document. Resolving them here — against the files as written — is what makes the gold
    labels match what the pipeline computes when it audits the same corpus (D38).
    """
    written = {path.name: parse(path) for path in sorted(corpus_dir.glob("*.md"))}
    pairs: list[GoldPair] = []
    for plan, injection in accepted:
        source_name = _output_name(documents[plan.source_index])
        target_name = _output_name(documents[plan.target_index])
        source_side = _resolve_side(written.get(source_name), source_name, injection.source_claim)
        target_side = _resolve_side(written.get(target_name), target_name, injection.injected_claim)
        if source_side is None or target_side is None:
            logger.warning(
                "dropping a {} pair: could not locate its text in the written corpus",
                plan.contradiction_type.value,
            )
            continue
        pairs.append(
            GoldPair(
                pair_id=gold_id(source_side, target_side),
                contradiction_type=plan.contradiction_type,
                a=source_side,
                b=target_side,
                origin="injected",
                generator_model=settings.generator_model,
                notes=injection.rationale.strip() or None,
            )
        )
    return GoldSet(
        name=name,
        version=version,
        corpus_dir=corpus_dir.name,
        origin="injected",
        seed=seed,
        generator_model=settings.generator_model,
        judge_model_at_authoring=settings.judge_model,
        pairs=pairs,
    )


def _resolve_side(document: Document | None, filename: str, claim: str) -> GoldSide | None:
    """Find ``claim`` in the written document and build the gold side that cites it."""
    if document is None:
        return None
    for section in document.sections:
        span = locate_quote(section.text, claim)
        if span is not None:
            return _side(filename, section, claim, span)
    return None


def _side(filename: str, section: Section, claim: str, span: tuple[int, int]) -> GoldSide:
    """Build one gold side from a located claim."""
    return GoldSide(
        document=filename,
        section_id=section.section_id,
        section_heading=section.heading,
        text=claim.strip(),
        evidence_quote=section.text[span[0] : span[1]],
        char_span=span,
    )
