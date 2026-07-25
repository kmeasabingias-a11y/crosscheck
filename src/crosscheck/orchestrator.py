"""Audit orchestrator — the eight-stage pipeline, end to end (spec v2 §4).

This module is the seam where every stage built so far meets: parse → chunk → extract →
embed/store → candidate-gen → rerank → NLI filter → judge. Stages run in strict sequence;
fan-out and batching stay *inside* the stages, so this file reads as the pipeline it is.

Three cross-cutting concerns live here rather than in any single stage, because only the
orchestrator sees the whole audit:

1. **One LLM client per audit.** Extraction and judging share a single
    :class:`~crosscheck.llm.LLMClient`, so they share one :class:`~crosscheck.llm.CostTracker`
    and therefore one cost ceiling. Spend is a property of the audit, not of a stage.
2. **The cost ceiling, at both levels** (§4). The audit-wide ceiling is enforced by the shared
    client. The per-document cap is enforced here, by tightening that client's budget around
    each document's extraction: a single pathological document is abandoned and the audit
    carries on, whereas hitting the audit ceiling stops dispatch and finalizes a ``partial``
    result. An audit never runs unbounded.
3. **Resume / idempotency** (§4). An audit that dies at document 90 of 100 must not restart
    from zero *in tokens*. Both LLM stages are pointed at on-disk caches keyed by content hash
    (``DiskClaimCache`` for extraction, ``DiskVerdictCache`` for judging), and the Qdrant upsert
    is idempotent by ``claim_id``. A resumed run therefore re-parses, re-chunks and re-embeds —
    all local, no spend — but re-pays for nothing that was already bought from an LLM. A small
    :class:`AuditState` file next to those caches records how far the last run got.

The result is an :class:`AuditResult`: verdicts plus the claims and pairs needed to render
them, the stage counters the eval harness reports on (§9.2), and the running cost. Turning
that into JSON/HTML artifacts is aggregation's job (Phase 4, §7.5) — including the
"no contradictions found" path, which this module treats as an ordinary successful audit.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from loguru import logger
from pydantic import Field

from crosscheck.config import Settings
from crosscheck.detection.llm_judge import DiskVerdictCache, LLMJudge
from crosscheck.detection.nli_filter import NLIScorer, build_nli_scorer, filter_pairs
from crosscheck.ids import content_hash
from crosscheck.ingestion.chunking import chunk_document
from crosscheck.ingestion.claim_extractor import ClaimExtractor, DiskClaimCache
from crosscheck.ingestion.parsers import UnsupportedFormatError, parse
from crosscheck.llm import CostCeilingError, CostTracker, LLMClient
from crosscheck.models import Claim, CrossCheckModel, Pair, Verdict
from crosscheck.retrieval.candidate_gen import (
    CandidateStrategy,
    build_candidate_strategy,
    generate_candidate_pairs,
)
from crosscheck.retrieval.reranker import Reranker, build_reranker, rerank_pairs
from crosscheck.storage.claim_repo import ClaimRepo
from crosscheck.storage.embeddings import build_dense_embedder, build_sparse_embedder
from crosscheck.storage.qdrant_client import build_client, ensure_collection

_STATE_FILENAME = "audit_state.json"
_CLAIM_CACHE_DIRNAME = "claims"
_VERDICT_CACHE_DIRNAME = "verdicts"


class AuditStats(CrossCheckModel):
    """Per-stage counters for one audit — the observability surface of §9.2.

    Kept flat and separate from the payload (claims, pairs, verdicts) so a report can show
    the funnel — how many candidates became survivors became verdicts — without walking it.
    """

    document_count: int = 0
    chunk_count: int = 0
    claim_count: int = 0
    candidate_pair_count: int = 0
    reranked_pair_count: int = 0
    nli_kept_count: int = 0
    extraction_cache_hits: int = 0
    extraction_llm_calls: int = 0
    rejected_evidence_count: int = Field(
        default=0, description="Claims dropped because their quote was not verbatim in the chunk."
    )
    decontextualization_flags: int = Field(
        default=0, description="Claims that opened with a dangling reference (§7.1)."
    )
    judge_cache_hits: int = 0
    judge_llm_calls: int = 0
    hallucination_count: int = Field(
        default=0, description="Contradiction verdicts dropped for un-quotable evidence (§7.4)."
    )

    @property
    def decontextualization_failure_rate(self) -> float:
        """Fraction of extracted claims flagged as not standing alone (0.0 if none)."""
        return self.decontextualization_flags / self.claim_count if self.claim_count else 0.0


class CostSummary(CrossCheckModel):
    """A serializable snapshot of one audit's LLM spend."""

    total_usd: float = 0.0
    call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @classmethod
    def from_tracker(cls, tracker: CostTracker) -> Self:
        """Snapshot a live :class:`~crosscheck.llm.CostTracker`."""
        return cls(
            total_usd=tracker.total_usd,
            call_count=tracker.call_count,
            input_tokens=tracker.input_tokens,
            output_tokens=tracker.output_tokens,
        )


class AuditResult(CrossCheckModel):
    """Everything one audit produced: verdicts, the material to render them, and the counters.

    Carries the corpus ``claims`` and the ``judged_pairs`` alongside the verdicts because a
    :class:`~crosscheck.models.Verdict` identifies its pair by id only — aggregation needs the
    claim text to render a side-by-side view (§7.5), and the eval harness needs the negatives
    as well as the positives (§9.2).
    """

    audit_id: str
    corpus_path: Path
    document_ids: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    judged_pairs: list[Pair] = Field(default_factory=list)
    verdicts: list[Verdict] = Field(default_factory=list)
    stats: AuditStats = Field(default_factory=AuditStats)
    cost: CostSummary = Field(default_factory=CostSummary)
    partial: bool = Field(
        default=False, description="True if a cost ceiling stopped the audit early (§4)."
    )
    partial_reason: str | None = None

    @property
    def contradictions(self) -> list[Verdict]:
        """The subset of verdicts that assert a contradiction, highest confidence first."""
        found = [verdict for verdict in self.verdicts if verdict.is_contradiction]
        found.sort(key=lambda verdict: (-verdict.confidence, verdict.pair_id))
        return found


class AuditState(CrossCheckModel):
    """The small on-disk breadcrumb that makes an audit resumable (§4).

    Deliberately tiny: the expensive state lives in the content-hashed caches beside it. This
    records only how far the last run got, so a resumed run can say so and a crashed one leaves
    a diagnosable trace.
    """

    audit_id: str
    corpus_path: Path
    stage: str = Field(description="The last pipeline stage that completed.")
    stats: AuditStats = Field(default_factory=AuditStats)
    cost_usd: float = 0.0
    partial: bool = False
    partial_reason: str | None = None


@dataclass
class AuditComponents:
    """The pipeline's stage implementations, bundled so they can be swapped wholesale.

    Built by :func:`build_components` for a real run; assembled by hand in tests and by the
    eval harness's ablations (§9.3), which vary one stage at a time.
    """

    extractor: ClaimExtractor
    repo: ClaimRepo
    strategy: CandidateStrategy
    reranker: Reranker
    nli_scorer: NLIScorer
    judge: LLMJudge


def audit_id(corpus: Path) -> str:
    """Return the deterministic id for auditing ``corpus``.

    Derived from the resolved corpus path, so re-running the same corpus lands on the same
    state directory and caches — which is what makes a resume automatic rather than something
    the user has to opt into with a run id.
    """
    return content_hash(str(corpus.resolve()))


def build_components(
    settings: Settings,
    llm: LLMClient,
    *,
    state_dir: Path,
    reset_store: bool = False,
) -> AuditComponents:
    """Construct the real pipeline stages for an audit.

    The dense and sparse embedders are built once and shared between the repository (which
    embeds on the indexing side) and the retrieval strategy (which embeds queries), so the
    ~1.3 GB bge model loads a single time. The Qdrant collection is ensured here because a
    working store is part of what this returns.

    Args:
        settings: Runtime configuration (models, collection, retrieval strategy).
        llm: The audit's shared cost-tracked LLM client.
        state_dir: Directory holding this audit's caches and state file.
        reset_store: If True, drop and rebuild the claims collection first. Destructive —
            it discards claims from previous audits (and so any resume against them).

    Returns:
        The bundled stage implementations.
    """
    dense = build_dense_embedder(settings)
    sparse = build_sparse_embedder(settings)
    client = build_client(settings)
    ensure_collection(client, settings, recreate=reset_store)
    repo = ClaimRepo(client, settings, dense_embedder=dense, sparse_embedder=sparse)
    return AuditComponents(
        extractor=ClaimExtractor(
            llm, settings, cache=DiskClaimCache(state_dir / _CLAIM_CACHE_DIRNAME)
        ),
        repo=repo,
        strategy=build_candidate_strategy(
            repo, settings, dense_embedder=dense, sparse_embedder=sparse
        ),
        reranker=build_reranker(settings),
        nli_scorer=build_nli_scorer(settings),
        judge=LLMJudge(llm, settings, cache=DiskVerdictCache(state_dir / _VERDICT_CACHE_DIRNAME)),
    )


def audit(
    corpus: Path,
    settings: Settings,
    *,
    llm: LLMClient | None = None,
    components: AuditComponents | None = None,
    reset_store: bool = False,
) -> AuditResult:
    """Run the full contradiction audit over a corpus directory (or a single file).

    Args:
        corpus: Directory to audit (recursively), or a single document file. Files whose
            format is unsupported are skipped with a debug log, not an error.
        settings: Runtime configuration for every stage.
        llm: The shared cost-tracked LLM client; one is built from settings if omitted.
        components: Pre-built stage implementations; built from settings if omitted.
        reset_store: If True, drop and rebuild the claims collection before ingesting.
            Ignored when ``components`` is supplied (the caller owns the store then).

    Returns:
        The audit result. An empty corpus, a corpus that yields no claims, and a corpus with
        no contradictions are all ordinary successful results, not errors (§7.5).

    Raises:
        LLMError: If no LLM client is given and no Anthropic API key is configured.
    """
    corpus = corpus.resolve()
    aid = audit_id(corpus)
    state_dir = settings.audit_state_dir / aid
    files = _discover_documents(corpus)
    logger.info("audit {} starting: {} candidate file(s) under {}", aid, len(files), corpus)

    resumed = _load_state(state_dir)
    if resumed is not None:
        logger.info(
            "audit {} has previous state (reached stage {!r}, spent ${:.4f}); cached "
            "extractions and verdicts will be reused",
            aid,
            resumed.stage,
            resumed.cost_usd,
        )

    if not files:
        logger.warning("no files found under {}; nothing to audit", corpus)
        return _finish(aid, corpus, AuditStats(), state_dir, stage="discover")

    if llm is None:
        llm = LLMClient(settings)
    if components is None:
        components = build_components(settings, llm, state_dir=state_dir, reset_store=reset_store)

    stats = AuditStats()
    ingestion = _ingest(files, settings, components.extractor, llm, stats)
    _write_state(state_dir, aid, corpus, stats, llm, stage="ingest", partial=ingestion.partial)
    if ingestion.partial or not ingestion.claims:
        if not ingestion.claims:
            logger.warning(
                "no claims extracted from {} document(s); nothing to compare",
                stats.document_count,
            )
        return _finish(
            aid,
            corpus,
            stats,
            state_dir,
            stage="ingest",
            claims=ingestion.claims,
            document_ids=ingestion.document_ids,
            llm=llm,
            partial=ingestion.partial,
            partial_reason=ingestion.reason,
        )

    claims = ingestion.claims
    stored = components.repo.upsert(claims)
    logger.info("stored {} claim(s) in the claim collection", stored)
    _warn_on_foreign_claims(components.repo, len(claims))
    _write_state(state_dir, aid, corpus, stats, llm, stage="store")

    candidates = generate_candidate_pairs(
        claims, components.strategy, top_k=settings.retrieval_top_k
    )
    stats.candidate_pair_count = len(candidates)

    # The reranker keeps a *corpus-wide* top-K (D25), so scale the per-claim budget of §7.3
    # ("keep top-10") by the corpus size: the audit keeps rerank_top_k pairs per claim on
    # average, but spends them where the cross-encoder found the strongest signal.
    reranked = rerank_pairs(
        candidates,
        claims,
        components.reranker,
        top_k=settings.rerank_top_k * max(1, len(claims)),
    )
    stats.reranked_pair_count = len(reranked)
    _write_state(state_dir, aid, corpus, stats, llm, stage="rerank")

    survivors = filter_pairs(
        reranked,
        claims,
        components.nli_scorer,
        thresholds=settings.nli_thresholds,
        default_threshold=settings.nli_default_threshold,
    )
    stats.nli_kept_count = len(survivors)
    _write_state(state_dir, aid, corpus, stats, llm, stage="nli")

    judged = components.judge.judge(survivors, claims)
    stats.judge_cache_hits = judged.cache_hits
    stats.judge_llm_calls = judged.llm_call_count
    stats.hallucination_count = judged.hallucination_count
    reason = "audit cost ceiling reached while judging" if judged.partial else None

    return _finish(
        aid,
        corpus,
        stats,
        state_dir,
        stage="judge",
        claims=claims,
        document_ids=ingestion.document_ids,
        judged_pairs=list(survivors),
        verdicts=judged.verdicts,
        llm=llm,
        partial=judged.partial,
        partial_reason=reason,
    )


@dataclass
class _Ingestion:
    """What the ingest loop produced, plus whether the audit ceiling cut it short."""

    claims: list[Claim]
    document_ids: list[str]
    partial: bool = False
    reason: str | None = None


def _ingest(
    files: Sequence[Path],
    settings: Settings,
    extractor: ClaimExtractor,
    llm: LLMClient,
    stats: AuditStats,
) -> _Ingestion:
    """Parse, chunk and extract each document, enforcing the per-document cost cap (§4).

    Each document's extraction runs inside a tightened LLM budget, so a document that blows
    the per-document cap is abandoned (its completed batches stay cached) and the audit moves
    on. Hitting the *audit* ceiling is different in kind — it stops ingestion entirely and the
    result is marked partial.

    The counters advance only once a document's extraction succeeds, so ``document_count`` and
    ``chunk_count`` describe what actually entered the audit rather than what was merely read.
    """
    audit_ceiling = llm.cost_ceiling_usd
    doc_cap = settings.max_document_cost_usd
    claims: list[Claim] = []
    document_ids: list[str] = []
    for path in files:
        try:
            document = parse(path)
        except UnsupportedFormatError:
            logger.debug("skipping unsupported file {}", path.name)
            continue
        chunks = chunk_document(document, settings=settings)
        try:
            with llm.budget(doc_cap):
                extraction = extractor.extract(chunks)
        except CostCeilingError as exc:
            if llm.cost.total_usd >= audit_ceiling:
                logger.warning("ingestion stopped at the audit cost ceiling: {}", exc)
                return _Ingestion(
                    claims=claims,
                    document_ids=document_ids,
                    partial=True,
                    reason="audit cost ceiling reached while extracting claims",
                )
            logger.warning(
                "document {} hit the per-document cost cap of ${:.2f} and was abandoned; "
                "its completed batches are cached for a resumed run",
                path.name,
                doc_cap,
            )
            continue
        document_ids.append(document.doc_id)
        stats.document_count += 1
        stats.chunk_count += len(chunks)
        claims.extend(extraction.claims)
        stats.claim_count += len(extraction.claims)
        stats.extraction_cache_hits += extraction.cache_hits
        stats.extraction_llm_calls += extraction.llm_call_count
        stats.rejected_evidence_count += extraction.rejected_evidence_count
        stats.decontextualization_flags += extraction.decontextualization_flags
    logger.info(
        "ingested {} document(s) into {} chunk(s) and {} claim(s)",
        stats.document_count,
        stats.chunk_count,
        stats.claim_count,
    )
    return _Ingestion(claims=claims, document_ids=document_ids)


def _discover_documents(corpus: Path) -> list[Path]:
    """List the files to attempt to parse, sorted so an audit is deterministic.

    Everything is offered to the parser; unsupported extensions are filtered by the parser's
    own dispatch rather than by a second copy of the format list here.
    """
    if corpus.is_file():
        return [corpus]
    if not corpus.exists():
        raise FileNotFoundError(corpus)
    return sorted(path for path in corpus.rglob("*") if path.is_file())


def _warn_on_foreign_claims(repo: ClaimRepo, expected: int) -> None:
    """Warn when the collection holds claims this audit did not put there.

    The claims collection is shared across audits and upsert is deliberately non-destructive
    (that is what makes a resume cheap), so a previous corpus's claims can still be present and
    will be retrieved as cross-document candidates. Surfacing it beats silently mixing corpora.
    """
    total = repo.count()
    if total > expected:
        logger.warning(
            "claim collection holds {} claim(s) but this corpus produced {}; results may "
            "include claims from earlier audits — re-run with reset_store=True for a clean store",
            total,
            expected,
        )


def _write_state(
    state_dir: Path,
    aid: str,
    corpus: Path,
    stats: AuditStats,
    llm: LLMClient | None,
    *,
    stage: str,
    partial: bool = False,
    partial_reason: str | None = None,
) -> None:
    """Persist the audit breadcrumb after a stage completes (§4)."""
    state = AuditState(
        audit_id=aid,
        corpus_path=corpus,
        stage=stage,
        stats=stats,
        cost_usd=llm.cost.total_usd if llm is not None else 0.0,
        partial=partial,
        partial_reason=partial_reason,
    )
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / _STATE_FILENAME).write_text(state.model_dump_json(indent=2), encoding="utf-8")
    logger.debug("audit {} state written after stage {!r}", aid, stage)


def _load_state(state_dir: Path) -> AuditState | None:
    """Load a previous run's breadcrumb, or None if there isn't a readable one."""
    path = state_dir / _STATE_FILENAME
    if not path.exists():
        return None
    try:
        return AuditState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # corrupt or truncated by a hard crash
        logger.warning("ignoring unreadable audit state at {}: {}", path, exc)
        return None


def _finish(
    aid: str,
    corpus: Path,
    stats: AuditStats,
    state_dir: Path,
    *,
    stage: str,
    claims: list[Claim] | None = None,
    document_ids: list[str] | None = None,
    judged_pairs: list[Pair] | None = None,
    verdicts: list[Verdict] | None = None,
    llm: LLMClient | None = None,
    partial: bool = False,
    partial_reason: str | None = None,
) -> AuditResult:
    """Assemble the final result, write the closing state file, and log the summary."""
    result = AuditResult(
        audit_id=aid,
        corpus_path=corpus,
        document_ids=document_ids or [],
        claims=claims or [],
        judged_pairs=judged_pairs or [],
        verdicts=verdicts or [],
        stats=stats,
        cost=CostSummary.from_tracker(llm.cost) if llm is not None else CostSummary(),
        partial=partial,
        partial_reason=partial_reason,
    )
    _write_state(
        state_dir,
        aid,
        corpus,
        stats,
        llm,
        stage=stage,
        partial=partial,
        partial_reason=partial_reason,
    )
    logger.info(
        "audit {} complete: {} contradiction(s) from {} claim(s) across {} document(s); "
        "cost ${:.4f} over {} LLM call(s){}",
        aid,
        len(result.contradictions),
        stats.claim_count,
        stats.document_count,
        result.cost.total_usd,
        result.cost.call_count,
        f" [partial: {partial_reason}]" if partial else "",
    )
    return result


def load_audit_state(settings: Settings, corpus: Path) -> AuditState | None:
    """Read the persisted state for a corpus's audit, if any (for CLI/API status reporting)."""
    return _load_state(settings.audit_state_dir / audit_id(corpus))
