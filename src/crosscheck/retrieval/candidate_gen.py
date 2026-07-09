"""Cross-document candidate pair generation (spec v2 §7.3).

For every stored claim this asks the claim store for its most similar claims *in other
documents* and turns the reciprocal results into deduplicated :class:`~crosscheck.models.Pair`
objects for the detection stages. The retrieval *strategy* is pluggable: hybrid BM25+dense is
the default — §7.3 makes it so, because many contradictions (obligation reversals, scope
conflicts) are lexically close but semantically far, and pure dense retrieval would silently
miss them — with a dense-only strategy kept behind the same interface as the §9.3 ablation
baseline. Further strategies (MMR, …) can be added as implementations of
:class:`CandidateStrategy` without touching pair generation.

The query claim is embedded *here* (the store's read side takes vectors, per D23), so this
layer holds the query-side embedders. Share the same embedder instances the repository uses
for indexing so the dense model loads only once.
"""

from collections.abc import Sequence
from typing import Protocol, assert_never

from loguru import logger

from crosscheck.config import Settings
from crosscheck.ids import pair_id
from crosscheck.models import Claim, Pair, ScoredClaim
from crosscheck.storage.claim_repo import ClaimRepo
from crosscheck.storage.embeddings import (
    DenseEmbedder,
    SparseEmbedder,
    build_dense_embedder,
    build_sparse_embedder,
)


class CandidateStrategy(Protocol):
    """A retrieval strategy: a query claim's most similar candidates from *other* documents."""

    def neighbors(self, claim: Claim, *, top_k: int) -> list[ScoredClaim]:
        """Retrieve up to ``top_k`` cross-document neighbours of ``claim``."""
        ...


class HybridStrategy:
    """Hybrid BM25 + dense retrieval — the §7.3 default.

    Embeds the query claim both ways and lets the store fuse the two result lists in-engine
    (RRF). Catches contradictions that are lexically similar even when semantically distant.
    """

    def __init__(
        self,
        repo: ClaimRepo,
        *,
        dense_embedder: DenseEmbedder,
        sparse_embedder: SparseEmbedder,
    ) -> None:
        self._repo = repo
        self._dense = dense_embedder
        self._sparse = sparse_embedder

    def neighbors(self, claim: Claim, *, top_k: int) -> list[ScoredClaim]:
        """Retrieve up to ``top_k`` cross-document neighbours via hybrid fusion."""
        return self._repo.search(
            dense=self._dense.embed_query(claim.text),
            sparse=self._sparse.embed_query(claim.text),
            exclude_doc_id=claim.doc_id,
            top_k=top_k,
        )


class DenseStrategy:
    """Dense-only retrieval — the §9.3 ablation baseline."""

    def __init__(self, repo: ClaimRepo, *, dense_embedder: DenseEmbedder) -> None:
        self._repo = repo
        self._dense = dense_embedder

    def neighbors(self, claim: Claim, *, top_k: int) -> list[ScoredClaim]:
        """Retrieve up to ``top_k`` cross-document neighbours by dense similarity only."""
        return self._repo.search(
            dense=self._dense.embed_query(claim.text),
            exclude_doc_id=claim.doc_id,
            top_k=top_k,
        )


def build_candidate_strategy(
    repo: ClaimRepo,
    settings: Settings,
    *,
    dense_embedder: DenseEmbedder | None = None,
    sparse_embedder: SparseEmbedder | None = None,
) -> CandidateStrategy:
    """Construct the configured retrieval strategy (``settings.retrieval_strategy``).

    Pass the shared embedder instances the repository uses so the dense model loads once;
    defaults are built from settings when omitted.

    Args:
        repo: The claim store the strategy searches.
        settings: Runtime configuration (selects hybrid vs dense, embedding models).
        dense_embedder: Shared dense encoder; built from settings if omitted.
        sparse_embedder: Shared sparse encoder; built from settings if omitted (hybrid only).

    Returns:
        The strategy named by ``settings.retrieval_strategy``.
    """
    dense = dense_embedder if dense_embedder is not None else build_dense_embedder(settings)
    match settings.retrieval_strategy:
        case "hybrid":
            sparse = (
                sparse_embedder if sparse_embedder is not None else build_sparse_embedder(settings)
            )
            return HybridStrategy(repo, dense_embedder=dense, sparse_embedder=sparse)
        case "dense":
            return DenseStrategy(repo, dense_embedder=dense)
    assert_never(settings.retrieval_strategy)


def generate_candidate_pairs(
    claims: Sequence[Claim], strategy: CandidateStrategy, *, top_k: int
) -> list[Pair]:
    """Build deduplicated cross-document candidate pairs for a corpus of claims.

    Each claim is queried against the store (which must already hold the corpus) for its
    top-``top_k`` neighbours in other documents. Reciprocal hits — B found for A and A found
    for B — collapse to a single :class:`Pair`, keyed by the order-independent
    :func:`~crosscheck.ids.pair_id` and keeping the higher retrieval score (the pair is a
    strong candidate if *either* direction retrieved it well). Pairs are returned sorted by
    descending retrieval score, ties broken by ``pair_id`` for determinism.

    Args:
        claims: The corpus claims to generate candidates for (already upserted into the store).
        strategy: The retrieval strategy to use (hybrid by default).
        top_k: Neighbours to retrieve per claim.

    Returns:
        Deduplicated candidate pairs, highest retrieval score first.
    """
    best: dict[str, tuple[str, str, float]] = {}
    for claim in claims:
        for scored in strategy.neighbors(claim, top_k=top_k):
            neighbor_id = scored.claim.claim_id
            if neighbor_id == claim.claim_id:
                continue  # a claim never pairs with itself (the cross-doc filter prevents it)
            first, second = sorted((claim.claim_id, neighbor_id))
            pid = pair_id(first, second)
            previous = best.get(pid)
            if previous is None or scored.score > previous[2]:
                best[pid] = (first, second, scored.score)
    pairs = [
        Pair(pair_id=pid, claim_a_id=first, claim_b_id=second, retrieval_score=score)
        for pid, (first, second, score) in best.items()
    ]
    pairs.sort(key=lambda pair: (-(pair.retrieval_score or 0.0), pair.pair_id))
    logger.info(
        "generated {} candidate pair(s) from {} claim(s) (top_k={})",
        len(pairs),
        len(claims),
        top_k,
    )
    return pairs
