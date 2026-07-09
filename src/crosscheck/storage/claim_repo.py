"""Claim repository: CRUD and hybrid retrieval over the Qdrant ``claims`` collection.

This is the storage layer above :mod:`crosscheck.storage.qdrant_client` (spec v2 §7.2). It
turns :class:`~crosscheck.models.Claim` objects into Qdrant points — dense + sparse vectors
plus the full claim as payload — on the way in, and reconstructs claims on the way out.
``search`` runs the hybrid BM25+dense retrieval that §7.3 makes the default *entirely
in-engine*, via Qdrant's Query API RRF fusion; no client-side score merging.

The repository holds the two embedders only for the *indexing* side (``upsert``). The read
side takes pre-computed query vectors, so the retrieval *strategy* (which embedders, dense-only
vs hybrid) lives one layer up in :mod:`crosscheck.retrieval` and this class stays a thin,
testable adapter over the vector store. The only payload fields exposed as typed filter
arguments are the ones the collection indexes (``doc_id`` via ``exclude_doc_id``, ``subject``,
``polarity``); above all the cross-document ``doc_id != self`` filter that runs on every
retrieval (§7.3). Qdrant's ``Filter`` type is built internally and never crosses the API
boundary.
"""

from collections.abc import Sequence

from loguru import logger
from qdrant_client import QdrantClient, models

from crosscheck.config import Settings
from crosscheck.models import Claim, ScoredClaim
from crosscheck.storage.embeddings import (
    DenseEmbedder,
    SparseEmbedder,
    SparseVector,
    build_dense_embedder,
    build_sparse_embedder,
)
from crosscheck.storage.qdrant_client import DENSE_VECTOR, SPARSE_VECTOR, to_point_id

#: Default number of points sent to Qdrant per upsert request.
_DEFAULT_UPSERT_BATCH = 128


class StorageError(RuntimeError):
    """Raised when a stored Qdrant point cannot be turned back into a claim."""


class ClaimRepo:
    """CRUD and hybrid retrieval for extracted claims, backed by Qdrant.

    Exposes the ``upsert`` / ``search`` / ``get`` / ``count`` surface from spec §7.2. The
    caller is responsible for having created the collection first
    (:func:`crosscheck.storage.qdrant_client.ensure_collection`).
    """

    def __init__(
        self,
        client: QdrantClient,
        settings: Settings,
        *,
        dense_embedder: DenseEmbedder | None = None,
        sparse_embedder: SparseEmbedder | None = None,
    ) -> None:
        """Build a repository over an existing client and collection.

        Args:
            client: A configured Qdrant client (see ``build_client``).
            settings: Runtime configuration (collection name, embedding models).
            dense_embedder: Dense encoder for the indexing side; the default bge embedder is
                built from settings if omitted. Inject a shared instance to avoid loading the
                model twice, or a fake for tests.
            sparse_embedder: Sparse BM25 encoder for the indexing side; the default fastembed
                embedder is built from settings if omitted.
        """
        self._client = client
        self._collection = settings.qdrant_collection
        self._dense = (
            dense_embedder if dense_embedder is not None else build_dense_embedder(settings)
        )
        self._sparse = (
            sparse_embedder if sparse_embedder is not None else build_sparse_embedder(settings)
        )

    def upsert(self, claims: Sequence[Claim], *, batch_size: int = _DEFAULT_UPSERT_BATCH) -> int:
        """Embed and store claims, returning the number written.

        Idempotent by ``claim_id``: the point id derives deterministically from it
        (:func:`to_point_id`), so re-upserting a claim overwrites its point rather than
        creating a duplicate — a prerequisite for the §4 resume story.

        Args:
            claims: The claims to store.
            batch_size: Points per Qdrant upsert request (bounds embedding memory on large
                corpora).

        Returns:
            The number of claims upserted.
        """
        claims = list(claims)
        if not claims:
            return 0
        total = 0
        for start in range(0, len(claims), batch_size):
            batch = claims[start : start + batch_size]
            texts = [claim.text for claim in batch]
            dense_vectors = self._dense.embed_passages(texts)
            sparse_vectors = self._sparse.embed_passages(texts)
            points = [
                models.PointStruct(
                    id=to_point_id(claim.claim_id),
                    vector={
                        DENSE_VECTOR: dense,
                        SPARSE_VECTOR: _to_qdrant_sparse(sparse),
                    },
                    payload=claim.model_dump(mode="json"),
                )
                for claim, dense, sparse in zip(batch, dense_vectors, sparse_vectors, strict=True)
            ]
            self._client.upsert(collection_name=self._collection, points=points)
            total += len(points)
        logger.info("upserted {} claim(s) into collection {!r}", total, self._collection)
        return total

    def search(
        self,
        *,
        dense: list[float],
        sparse: SparseVector | None = None,
        exclude_doc_id: str | None = None,
        subject: str | None = None,
        polarity: str | None = None,
        top_k: int,
    ) -> list[ScoredClaim]:
        """Retrieve the top-``k`` most similar stored claims.

        Hybrid (dense + sparse BM25, fused with RRF) when ``sparse`` is provided — the §7.3
        default — otherwise dense-only, which is the ablation baseline. The query vectors are
        supplied by the caller (the retrieval layer embeds the query claim), keeping strategy
        out of the store.

        Args:
            dense: The query's dense vector.
            sparse: The query's sparse vector; when omitted, search is dense-only.
            exclude_doc_id: Drop claims from this document — the cross-document filter.
            subject: If set, keep only claims with this subject.
            polarity: If set, keep only claims with this polarity.
            top_k: Maximum number of results to return.

        Returns:
            Scored claims, most similar first.
        """
        query_filter = self._build_filter(exclude_doc_id, subject, polarity)
        if sparse is not None:
            sparse_query = _to_qdrant_sparse(sparse)
            response = self._client.query_points(
                collection_name=self._collection,
                prefetch=[
                    models.Prefetch(
                        query=dense, using=DENSE_VECTOR, filter=query_filter, limit=top_k
                    ),
                    models.Prefetch(
                        query=sparse_query, using=SPARSE_VECTOR, filter=query_filter, limit=top_k
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=top_k,
                with_payload=True,
            )
        else:
            response = self._client.query_points(
                collection_name=self._collection,
                query=dense,
                using=DENSE_VECTOR,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
        return [
            ScoredClaim(claim=self._payload_to_claim(point.payload), score=point.score)
            for point in response.points
        ]

    def get(self, claim_id: str) -> Claim | None:
        """Fetch one claim by its CrossCheck ``claim_id``.

        Args:
            claim_id: The claim's deterministic CrossCheck id.

        Returns:
            The stored claim, or None if no point maps to that id.
        """
        records = self._client.retrieve(
            collection_name=self._collection,
            ids=[to_point_id(claim_id)],
            with_payload=True,
        )
        if not records:
            return None
        return self._payload_to_claim(records[0].payload)

    def count(self) -> int:
        """Return the number of claims stored in the collection."""
        return self._client.count(collection_name=self._collection).count

    @staticmethod
    def _build_filter(
        exclude_doc_id: str | None, subject: str | None, polarity: str | None
    ) -> models.Filter | None:
        """Build a Qdrant filter from the typed arguments (None if no constraints)."""
        must: list[models.Condition] = []
        must_not: list[models.Condition] = []
        if subject is not None:
            must.append(
                models.FieldCondition(key="subject", match=models.MatchValue(value=subject))
            )
        if polarity is not None:
            must.append(
                models.FieldCondition(key="polarity", match=models.MatchValue(value=polarity))
            )
        if exclude_doc_id is not None:
            must_not.append(
                models.FieldCondition(key="doc_id", match=models.MatchValue(value=exclude_doc_id))
            )
        if not must and not must_not:
            return None
        return models.Filter(must=must or None, must_not=must_not or None)

    @staticmethod
    def _payload_to_claim(payload: dict[str, object] | None) -> Claim:
        """Reconstruct a Claim from a point's payload, failing loudly if it is missing."""
        if payload is None:
            raise StorageError("Qdrant point has no payload; cannot reconstruct claim")
        return Claim.model_validate(payload)


def _to_qdrant_sparse(sparse: SparseVector) -> models.SparseVector:
    """Convert the neutral :class:`SparseVector` to Qdrant's ``SparseVector`` at the boundary."""
    return models.SparseVector(indices=sparse.indices, values=sparse.values)
