"""Storage + retrieval against a live Qdrant server (spec v2 §7.2, §7.3, §8, §12).

Unlike the ``:memory:`` unit tests (which no-op payload indexes), this exercises the real Qdrant
server: it creates the collection *with* payload indexes, upserts with real embedders, and confirms
hybrid retrieval returns cross-document candidates with correct ``doc_id != self`` filtering and
that the server-side payload-index filters actually work.

Marked ``integration`` (deselected by default). **Self-skips** if no Qdrant is reachable at
``qdrant_url`` — bring one up with ``docker compose up -d qdrant``. It uses an isolated throwaway
collection (``crosscheck_itest``) and deletes it afterward, so it never touches a real ``claims``
collection. Point the ``CROSSCHECK_*`` model settings at small models to run it cheaply.
"""

from typing import Literal

import pytest

from crosscheck.config import get_settings
from crosscheck.models import Claim
from crosscheck.retrieval.candidate_gen import build_candidate_strategy
from crosscheck.storage.claim_repo import ClaimRepo
from crosscheck.storage.embeddings import build_dense_embedder, build_sparse_embedder
from crosscheck.storage.qdrant_client import INDEXED_FIELDS, build_client, ensure_collection

pytestmark = pytest.mark.integration

_TEST_COLLECTION = "crosscheck_itest"


def _claim(
    claim_id: str,
    doc_id: str,
    text: str,
    subject: str,
    polarity: Literal["positive", "negative"] = "positive",
) -> Claim:
    return Claim(
        claim_id=claim_id,
        doc_id=doc_id,
        section_id=f"{doc_id}-s0",
        text=text,
        evidence_quote=text,
        evidence_offset=(0, len(text)),
        subject=subject,
        predicate="",
        polarity=polarity,
    )


def test_live_qdrant_storage_and_retrieval() -> None:
    settings = get_settings().model_copy(update={"qdrant_collection": _TEST_COLLECTION})
    client = build_client(settings)
    try:
        client.get_collections()
    except Exception:  # any connection failure means "no server reachable" -> skip
        pytest.skip("no Qdrant reachable at qdrant_url; run `docker compose up -d qdrant`")

    dense = build_dense_embedder(settings)
    sparse = build_sparse_embedder(settings)
    ensure_collection(client, settings, recreate=True)
    try:
        # Payload indexes really exist on the server (the :memory: tests cannot verify this).
        schema = client.get_collection(_TEST_COLLECTION).payload_schema
        assert set(INDEXED_FIELDS) <= set(schema), f"missing payload indexes: {set(schema)}"

        repo = ClaimRepo(client, settings, dense_embedder=dense, sparse_embedder=sparse)
        claims = [
            _claim("ins_a", "doc_a", "Vendors must carry liability insurance.", "insurance"),
            _claim("pto_a", "doc_a", "Employees receive 20 paid time off days.", "pto"),
            _claim(
                "ins_b",
                "doc_b",
                "Vendors are not required to carry insurance.",
                "insurance",
                "negative",
            ),
            _claim("ref_b", "doc_b", "Refunds are issued within 30 days.", "refund"),
        ]
        assert repo.upsert(claims) == len(claims)
        assert repo.count() == len(claims)

        # get round-trips a full claim from the server payload; a missing id is None.
        assert repo.get("ins_b") == claims[2]
        assert repo.get("does-not-exist") is None

        # Hybrid retrieval applies the cross-document filter: a doc_a query returns only doc_b
        # claims, and the true insurance partner (ins_b) is among them.
        strategy = build_candidate_strategy(
            repo, settings, dense_embedder=dense, sparse_embedder=sparse
        )
        insurance_a = claims[0]
        hits = strategy.neighbors(insurance_a, top_k=settings.retrieval_top_k)
        assert hits, "expected cross-document candidates"
        assert all(hit.claim.doc_id != insurance_a.doc_id for hit in hits)
        assert "ins_b" in {hit.claim.claim_id for hit in hits}

        # Server-side payload-index filter: constraining subject returns only that subject.
        filtered = repo.search(
            dense=dense.embed_query(insurance_a.text),
            subject="insurance",
            exclude_doc_id="doc_a",
            top_k=10,
        )
        assert {hit.claim.claim_id for hit in filtered} == {"ins_b"}
        assert all(hit.claim.subject == "insurance" for hit in filtered)
    finally:
        client.delete_collection(_TEST_COLLECTION)
