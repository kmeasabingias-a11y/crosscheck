"""Qdrant connection and collection lifecycle for the CrossCheck claim store.

Qdrant is the system of record for extracted claims (spec v2 §7.2). This module owns the
low-level concerns: building a configured client and creating the single ``claims``
collection with the right vector layout. Everything above it — upsert, search, get, count —
lives in :mod:`crosscheck.storage.claim_repo`, which builds on the primitives here.

The collection carries two vectors per claim so hybrid retrieval (spec §7.3) runs entirely
inside Qdrant: a dense vector (``bge-large-en-v1.5``, cosine) for semantic similarity and a
sparse BM25 vector (IDF-weighted server-side) for lexical overlap. Payload indexes on
``doc_id``, ``subject``, and ``polarity`` keep filtered search fast — the cross-document
filter (``doc_id != self``) runs on every retrieval.
"""

import uuid

from loguru import logger
from qdrant_client import QdrantClient, models

from crosscheck.config import Settings

#: Name of the dense (semantic) named vector within the collection.
DENSE_VECTOR = "dense"
#: Name of the sparse (BM25 / lexical) named vector within the collection.
SPARSE_VECTOR = "sparse"
#: Payload fields indexed for fast filtered search (spec §7.2).
INDEXED_FIELDS: tuple[str, ...] = ("doc_id", "subject", "polarity")

# Fixed UUID namespace so a claim_id always maps to the same Qdrant point id, on any
# machine and across reruns — a prerequisite for idempotent upserts and resume (spec §4).
_POINT_ID_NAMESPACE = uuid.UUID("1b4db8a2-3f5c-4e21-9a7d-0c6e2f8b5d34")


def to_point_id(claim_id: str) -> str:
    """Map a CrossCheck ``claim_id`` to a deterministic Qdrant point id.

    Qdrant point ids must be an unsigned integer or a UUID; our claim ids are short hex
    digests. A UUIDv5 over a fixed namespace yields a stable, collision-free point id, while
    the original ``claim_id`` is preserved in the payload for lookups by our own id.

    Args:
        claim_id: The claim's deterministic CrossCheck id.

    Returns:
        A UUID string usable as a Qdrant point id.
    """
    return str(uuid.uuid5(_POINT_ID_NAMESPACE, claim_id))


def build_client(settings: Settings) -> QdrantClient:
    """Construct a Qdrant client from settings.

    Args:
        settings: Runtime configuration (URL, optional API key, timeout).

    Returns:
        A configured :class:`~qdrant_client.QdrantClient`.
    """
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        timeout=int(settings.qdrant_timeout_seconds),
    )


def ensure_collection(
    client: QdrantClient,
    settings: Settings,
    *,
    recreate: bool = False,
) -> None:
    """Ensure the ``claims`` collection exists with the dense+sparse layout.

    Idempotent: if the collection already exists it is left untouched, so an interrupted
    audit resumes against the same store (spec §4). Pass ``recreate=True`` to drop and
    rebuild it — destructive, for a clean re-ingest or a dense-vector-size change only.

    Args:
        client: The Qdrant client to use.
        settings: Runtime configuration (collection name, dense vector size).
        recreate: If True, drop any existing collection first. Destroys stored claims.
    """
    name = settings.qdrant_collection
    if recreate and client.collection_exists(name):
        client.delete_collection(name)
        logger.warning("dropped existing Qdrant collection {!r} (recreate=True)", name)
    if client.collection_exists(name):
        logger.debug("Qdrant collection {!r} already exists; leaving it in place", name)
        return
    client.create_collection(
        collection_name=name,
        vectors_config={
            DENSE_VECTOR: models.VectorParams(
                size=settings.dense_vector_size,
                distance=models.Distance.COSINE,
            )
        },
        sparse_vectors_config={
            SPARSE_VECTOR: models.SparseVectorParams(modifier=models.Modifier.IDF)
        },
    )
    for field in INDEXED_FIELDS:
        client.create_payload_index(
            name, field_name=field, field_schema=models.PayloadSchemaType.KEYWORD
        )
    logger.info(
        "created Qdrant collection {!r} (dense size={}, cosine; sparse BM25/IDF; "
        "payload indexes on {})",
        name,
        settings.dense_vector_size,
        ", ".join(INDEXED_FIELDS),
    )
