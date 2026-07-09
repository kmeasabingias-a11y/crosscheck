"""Unit tests for cross-document candidate pair generation (hermetic).

Two layers are covered. The dedup / sort / self-skip logic of ``generate_candidate_pairs`` is
tested against a *fake* strategy with canned neighbours, so the pairing behaviour is exact and
fast. The strategies themselves and the ``build_candidate_strategy`` factory are tested against
a real in-process Qdrant (``:memory:``) with the same fake embedders used for the repo tests,
so the end-to-end retrieve→pair path runs with no service and no downloads.
"""

from collections.abc import Sequence
from typing import Any, cast

import pytest
from qdrant_client import QdrantClient

from crosscheck.config import Settings
from crosscheck.ids import pair_id
from crosscheck.models import Claim, ScoredClaim
from crosscheck.retrieval.candidate_gen import (
    DenseStrategy,
    HybridStrategy,
    build_candidate_strategy,
    generate_candidate_pairs,
)
from crosscheck.storage.claim_repo import ClaimRepo
from crosscheck.storage.embeddings import SparseVector
from crosscheck.storage.qdrant_client import ensure_collection

pytestmark = pytest.mark.filterwarnings(
    "ignore:Payload indexes have no effect in the local Qdrant:UserWarning"
)


def _claim(claim_id: str, doc_id: str, text: str, polarity: str = "positive") -> Claim:
    return Claim(
        claim_id=claim_id,
        doc_id=doc_id,
        section_id=f"{doc_id}-s0",
        text=text,
        evidence_quote=text,
        evidence_offset=(0, len(text)),
        subject="pto",
        predicate="entitlement",
        polarity=cast(Any, polarity),
    )


# --- generate_candidate_pairs against a fake strategy -----------------------------------------


class _FakeStrategy:
    """Returns canned neighbours per claim id, honouring top_k."""

    def __init__(self, neighbors: dict[str, list[ScoredClaim]]) -> None:
        self._neighbors = neighbors

    def neighbors(self, claim: Claim, *, top_k: int) -> list[ScoredClaim]:
        return self._neighbors.get(claim.claim_id, [])[:top_k]


def test_reciprocal_hits_dedup_to_one_pair_keeping_max_score() -> None:
    a = _claim("a1", "A", "employees receive 20 pto days")
    b = _claim("b1", "B", "employees are not entitled to pto")
    strategy = _FakeStrategy(
        {
            "a1": [ScoredClaim(claim=b, score=0.80)],  # A finds B at 0.80
            "b1": [ScoredClaim(claim=a, score=0.90)],  # B finds A at 0.90
        }
    )
    pairs = generate_candidate_pairs([a, b], cast(Any, strategy), top_k=10)
    assert len(pairs) == 1
    (pair,) = pairs
    assert pair.pair_id == pair_id("a1", "b1")
    assert {pair.claim_a_id, pair.claim_b_id} == {"a1", "b1"}
    assert pair.retrieval_score == 0.90  # the higher of the two directions


def test_self_hits_are_skipped() -> None:
    a = _claim("a1", "A", "employees receive 20 pto days")
    strategy = _FakeStrategy({"a1": [ScoredClaim(claim=a, score=1.0)]})
    assert generate_candidate_pairs([a], cast(Any, strategy), top_k=10) == []


def test_pairs_sorted_by_descending_score() -> None:
    a = _claim("a1", "A", "a")
    b = _claim("b1", "B", "b")
    c = _claim("c1", "C", "c")
    strategy = _FakeStrategy(
        {
            "a1": [ScoredClaim(claim=b, score=0.3), ScoredClaim(claim=c, score=0.9)],
        }
    )
    pairs = generate_candidate_pairs([a, b, c], cast(Any, strategy), top_k=10)
    assert [p.retrieval_score for p in pairs] == [0.9, 0.3]


# --- the real strategies + factory over a local in-memory Qdrant ------------------------------

_VECTORS: dict[str, tuple[list[float], SparseVector]] = {
    "employees receive 20 pto days": ([1.0, 0.0, 0.0, 0.0], SparseVector([1, 2], [1.0, 1.0])),
    "employees are not entitled to pto": ([0.96, 0.2, 0.0, 0.0], SparseVector([1, 2], [1.0, 1.0])),
    "refunds are issued within 30 days": ([0.0, 0.0, 1.0, 0.0], SparseVector([9], [1.0])),
}


class _FakeDense:
    dim = 4

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [_VECTORS[t][0] for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return _VECTORS[text][0]


class _FakeSparse:
    def embed_passages(self, texts: Sequence[str]) -> list[SparseVector]:
        return [_VECTORS[t][1] for t in texts]

    def embed_query(self, text: str) -> SparseVector:
        return _VECTORS[text][1]


def _repo_with_claims() -> tuple[ClaimRepo, list[Claim], _FakeDense, _FakeSparse]:
    settings = Settings(qdrant_collection="claims_test", dense_vector_size=4)
    client = QdrantClient(":memory:")
    ensure_collection(client, settings)
    dense, sparse = _FakeDense(), _FakeSparse()
    repo = ClaimRepo(
        client, settings, dense_embedder=cast(Any, dense), sparse_embedder=cast(Any, sparse)
    )
    claims = [
        _claim("a1", "A", "employees receive 20 pto days"),
        _claim("b1", "B", "employees are not entitled to pto", polarity="negative"),
        _claim("a2", "A", "refunds are issued within 30 days"),
    ]
    repo.upsert(claims)
    return repo, claims, dense, sparse


def test_hybrid_strategy_generates_cross_doc_pair() -> None:
    repo, claims, dense, sparse = _repo_with_claims()
    strategy = HybridStrategy(
        repo, dense_embedder=cast(Any, dense), sparse_embedder=cast(Any, sparse)
    )
    pairs = generate_candidate_pairs(claims, strategy, top_k=10)
    # The PTO claims contradict across docs A/B; the refund claim (doc A) has no cross-doc match.
    assert pair_id("a1", "b1") in {p.pair_id for p in pairs}
    for pair in pairs:
        assert {pair.claim_a_id, pair.claim_b_id} != {"a1", "a2"}  # never same-doc


def test_dense_strategy_generates_cross_doc_pair() -> None:
    repo, claims, dense, _ = _repo_with_claims()
    strategy = DenseStrategy(repo, dense_embedder=cast(Any, dense))
    pairs = generate_candidate_pairs(claims, strategy, top_k=10)
    assert pair_id("a1", "b1") in {p.pair_id for p in pairs}


def test_factory_selects_strategy_from_settings() -> None:
    repo, _, dense, sparse = _repo_with_claims()
    hybrid = build_candidate_strategy(
        repo,
        Settings(retrieval_strategy="hybrid", dense_vector_size=4),
        dense_embedder=cast(Any, dense),
        sparse_embedder=cast(Any, sparse),
    )
    dense_only = build_candidate_strategy(
        repo,
        Settings(retrieval_strategy="dense", dense_vector_size=4),
        dense_embedder=cast(Any, dense),
    )
    assert isinstance(hybrid, HybridStrategy)
    assert isinstance(dense_only, DenseStrategy)
