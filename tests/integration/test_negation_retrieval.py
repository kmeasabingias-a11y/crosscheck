"""Negation-sensitivity of retrieval (spec v2 §7.3, §9.2, §12).

Real-model integration test: for each known cross-document negation pair, the true negation
partner must be the top-ranked candidate after **hybrid retrieval + rerank**. This is the
empirical check that the default hybrid (BM25 + dense) stack surfaces "X required" vs "X not
required" pairs that pure dense retrieval can place far apart — BM25 catches their near-identical
wording, and the cross-encoder confirms it.

Marked ``integration`` (deselected by default; run with ``uv run pytest -m integration``). On first
run it downloads the real embedder + reranker (bge-large + bge-reranker-v2-m3, ~3.5 GB). To run it
cheaply against smaller models, point the model settings at them, e.g.::

    CROSSCHECK_DENSE_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 \
    CROSSCHECK_DENSE_VECTOR_SIZE=384 \
    CROSSCHECK_RERANK_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2 \
    uv run pytest -m integration tests/integration/test_negation_retrieval.py

Uses qdrant-client's in-process ``:memory:`` mode, so no Qdrant service is needed.
"""

from pathlib import Path

import pytest
from loguru import logger
from qdrant_client import QdrantClient

from crosscheck.config import get_settings
from crosscheck.evaluation.negation import load_negation_pairs, to_claim_pairs, to_claims
from crosscheck.retrieval.candidate_gen import build_candidate_strategy
from crosscheck.retrieval.reranker import build_reranker
from crosscheck.storage.claim_repo import ClaimRepo
from crosscheck.storage.embeddings import build_dense_embedder, build_sparse_embedder
from crosscheck.storage.qdrant_client import ensure_collection

pytestmark = [
    pytest.mark.integration,
    # Local (:memory:) Qdrant warns that payload indexes are server-only (see the repo tests).
    pytest.mark.filterwarnings(
        "ignore:Payload indexes have no effect in the local Qdrant:UserWarning"
    ),
]

_FIXTURE = Path(__file__).parents[2] / "benchmarks" / "negation" / "negation_pairs.json"
# The clean fixture has one distinct subject per pair, so top-K would be trivial; the meaningful
# signal is recall@1 — the true negation must be the single best match among all candidates.
_RECALL_AT_1_MIN = 0.75


def test_negation_pairs_survive_retrieval_and_rerank() -> None:
    settings = get_settings()
    pairs = load_negation_pairs(_FIXTURE)
    claim_pairs = to_claim_pairs(pairs)

    # Share one dense + one sparse embedder across the repo (indexing) and strategy (querying).
    dense = build_dense_embedder(settings)
    sparse = build_sparse_embedder(settings)
    client = QdrantClient(":memory:")
    ensure_collection(client, settings)
    repo = ClaimRepo(client, settings, dense_embedder=dense, sparse_embedder=sparse)
    repo.upsert(to_claims(pairs))

    strategy = build_candidate_strategy(
        repo, settings, dense_embedder=dense, sparse_embedder=sparse
    )
    reranker = build_reranker(settings)

    hits = 0
    for positive, negative in claim_pairs:
        neighbors = strategy.neighbors(positive, top_k=settings.retrieval_top_k)
        assert neighbors, f"no cross-document candidates retrieved for {positive.text!r}"
        scores = reranker.score_pairs([(positive.text, sc.claim.text) for sc in neighbors])
        best = max(zip(neighbors, scores, strict=True), key=lambda item: item[1])[0]
        if best.claim.claim_id == negative.claim_id:
            hits += 1

    recall = hits / len(claim_pairs)
    logger.info(
        "negation-pair recall@1 after retrieval+rerank: {:.2f} ({}/{})",
        recall,
        hits,
        len(claim_pairs),
    )
    assert recall >= _RECALL_AT_1_MIN, (
        f"negation-pair recall@1 {recall:.2f} < {_RECALL_AT_1_MIN} "
        f"({hits}/{len(claim_pairs)} partners ranked first)"
    )
