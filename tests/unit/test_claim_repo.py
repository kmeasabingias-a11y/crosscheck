"""Unit tests for :class:`ClaimRepo` (hermetic — local in-memory Qdrant, fake embedders).

qdrant-client's ``:memory:`` mode runs a pure-Python Qdrant that supports Query-API RRF
fusion, so the full CRUD + hybrid retrieval path is exercised end-to-end with no service and
no model download. Payload indexes are a no-op in local mode (server-only), which does not
affect filtering correctness. Deterministic 4-d dense vectors and tiny sparse vectors are
injected via fake embedders so the ranking is fully controlled.
"""

from collections.abc import Sequence
from typing import Any, cast

import pytest
from qdrant_client import QdrantClient

from crosscheck.config import Settings
from crosscheck.models import Claim
from crosscheck.storage.claim_repo import ClaimRepo
from crosscheck.storage.embeddings import SparseVector
from crosscheck.storage.qdrant_client import ensure_collection

# Local (:memory:) Qdrant warns that payload indexes are server-only; the index calls are
# correct for the real server, so silence just that one message here.
pytestmark = pytest.mark.filterwarnings(
    "ignore:Payload indexes have no effect in the local Qdrant:UserWarning"
)

# text -> (dense 4-d vector, sparse vector). The store keys everything off claim text.
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


def _repo() -> tuple[ClaimRepo, list[Claim]]:
    settings = Settings(qdrant_collection="claims_test", dense_vector_size=4)
    client = QdrantClient(":memory:")
    ensure_collection(client, settings)
    repo = ClaimRepo(
        client,
        settings,
        dense_embedder=cast(Any, _FakeDense()),
        sparse_embedder=cast(Any, _FakeSparse()),
    )
    claims = [
        _claim("a1", "A", "employees receive 20 pto days"),
        _claim("b1", "B", "employees are not entitled to pto", polarity="negative"),
        _claim("a2", "A", "refunds are issued within 30 days"),
    ]
    repo.upsert(claims)
    return repo, claims


def test_upsert_and_count() -> None:
    repo, claims = _repo()
    assert repo.count() == len(claims)


def test_upsert_is_idempotent() -> None:
    repo, claims = _repo()
    # Re-upserting the same claims overwrites points rather than duplicating them.
    repo.upsert(claims)
    assert repo.count() == len(claims)


def test_upsert_empty_is_noop() -> None:
    repo, _ = _repo()
    assert repo.upsert([]) == 0
    assert repo.count() == 3


def test_get_round_trips_full_claim() -> None:
    repo, claims = _repo()
    fetched = repo.get("b1")
    assert fetched == claims[1]


def test_get_missing_returns_none() -> None:
    repo, _ = _repo()
    assert repo.get("does-not-exist") is None


def test_hybrid_search_excludes_self_doc_and_ranks_partner() -> None:
    repo, _ = _repo()
    dense = _FakeDense().embed_query("employees receive 20 pto days")
    sparse = _FakeSparse().embed_query("employees receive 20 pto days")
    hits = repo.search(dense=dense, sparse=sparse, exclude_doc_id="A", top_k=10)
    # Only the doc-B claim survives the cross-document filter; the other doc-A claim is gone.
    assert [h.claim.claim_id for h in hits] == ["b1"]
    assert hits[0].score > 0


def test_dense_only_search_still_works() -> None:
    repo, _ = _repo()
    dense = _FakeDense().embed_query("employees receive 20 pto days")
    hits = repo.search(dense=dense, exclude_doc_id="A", top_k=10)
    assert [h.claim.claim_id for h in hits] == ["b1"]


def test_polarity_filter_narrows_results() -> None:
    repo, _ = _repo()
    dense = _FakeDense().embed_query("employees receive 20 pto days")
    # The only negative-polarity claim is b1; filtering to positive drops it.
    negatives = repo.search(dense=dense, polarity="negative", top_k=10)
    assert {h.claim.claim_id for h in negatives} == {"b1"}
