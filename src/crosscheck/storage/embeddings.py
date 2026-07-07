"""Dense and sparse embedders for the claim store (spec §5, §7.2, §7.3).

Two encoders turn a claim's text into the two vectors the ``claims`` collection holds:

- **dense** — ``bge-large-en-v1.5`` (1024-d, cosine) via sentence-transformers, for *semantic*
similarity ("these claims are about the same thing").
- **sparse** — BM25 via fastembed (``Qdrant/bm25``), for *lexical* overlap ("these claims use the
same words"), stored as Qdrant sparse vectors so hybrid retrieval runs in-engine (§7.3).

Both expose ``embed_passages`` (the indexing side, used when claims are upserted) and
``embed_query`` (the retrieval side). The dense embedder prepends a query instruction on the
query side only, following bge's recommended asymmetric retrieval setup.

Models load **lazily** on first use, so importing this module and constructing an embedder cost
nothing until an embedding is actually needed — unit tests, ``--help``, and config validation stay
fast and offline. The concrete embedders also accept an injected model so tests need no download.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from loguru import logger

from crosscheck.config import Settings

if TYPE_CHECKING:  # imported lazily at runtime (see _get_model) to keep construction cheap
    from fastembed import SparseTextEmbedding
    from sentence_transformers import SentenceTransformer


class EmbeddingError(RuntimeError):
    """Raised when an embedder is misconfigured (e.g. model/collection dimension mismatch)."""


@dataclass(frozen=True)
class SparseVector:
    """A sparse embedding as parallel index/value lists.

    Provider-neutral (no numpy, no Qdrant types) so the repository converts it to Qdrant's
    ``SparseVector`` at the boundary and tests can construct one directly.
    """

    indices: list[int]
    values: list[float]


class DenseEmbedder(Protocol):
    """Turns claim text into dense vectors for semantic similarity search."""

    @property
    def dim(self) -> int:
        """The dense vector dimension (must match the collection's dense vector size)."""
        ...

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed claims for indexing (no query instruction)."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a single claim for retrieval (query instruction applied)."""
        ...


class SparseEmbedder(Protocol):
    """Turns claim text into sparse BM25 vectors for lexical search."""

    def embed_passages(self, texts: Sequence[str]) -> list[SparseVector]:
        """Embed claims for indexing (document-side BM25 term weights)."""
        ...

    def embed_query(self, text: str) -> SparseVector:
        """Embed a single claim for retrieval (query-side BM25 terms)."""
        ...


class BgeDenseEmbedder:
    """Dense embedder backed by a sentence-transformers model (default bge-large-en-v1.5).

    The model is loaded on first embed call and its true dimension is checked against the
    configured ``dense_vector_size`` — a mismatch would silently corrupt the collection, so it
    fails loudly instead.
    """

    def __init__(self, settings: Settings, *, model: "SentenceTransformer | None" = None) -> None:
        """Build from settings, optionally wrapping a pre-built model (for tests).

        Args:
            settings: Runtime configuration (model name, vector size, query instruction).
            model: A pre-loaded sentence-transformers model; loaded lazily from the model name
                if omitted.
        """
        self._model_name = settings.dense_embedding_model
        self._configured_dim = settings.dense_vector_size
        self._query_instruction = settings.dense_query_instruction
        self._model: SentenceTransformer | None = model
        self._dim_checked = False

    @property
    def dim(self) -> int:
        """The configured dense vector dimension."""
        return self._configured_dim

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed claims for indexing, without the query instruction.

        Args:
            texts: Claim texts to embed.

        Returns:
            One unit-normalized dense vector per input text.
        """
        return self._encode(list(texts))

    def embed_query(self, text: str) -> list[float]:
        """Embed one claim for retrieval, prepending the query instruction.

        Args:
            text: The claim text to search with.

        Returns:
            A single unit-normalized dense vector.
        """
        query = f"{self._query_instruction}{text}" if self._query_instruction else text
        return self._encode([query])[0]

    def _get_model(self) -> "SentenceTransformer":
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info("loading dense embedding model {!r} (first use)", self._model_name)
            self._model = SentenceTransformer(self._model_name)
        if not self._dim_checked:
            actual = self._model.get_sentence_embedding_dimension()
            if actual != self._configured_dim:
                raise EmbeddingError(
                    f"dense model {self._model_name!r} produces dimension {actual}, but "
                    f"dense_vector_size is {self._configured_dim}; they must match the "
                    f"'claims' collection's dense vector."
                )
            self._dim_checked = True
        return self._model

    def _encode(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return [row.tolist() for row in vectors]


class Bm25SparseEmbedder:
    """Sparse BM25 embedder backed by fastembed (default ``Qdrant/bm25``).

    Emits document-side term weights for indexing and query-side terms for retrieval; the corpus
    IDF weighting is applied by Qdrant at query time (the collection's sparse vector uses the IDF
    modifier), so nothing here tracks global document frequencies.
    """

    def __init__(self, settings: Settings, *, model: "SparseTextEmbedding | None" = None) -> None:
        """Build from settings, optionally wrapping a pre-built model (for tests).

        Args:
            settings: Runtime configuration (sparse model name).
            model: A pre-loaded fastembed model; loaded lazily from the model name if omitted.
        """
        self._model_name = settings.sparse_model
        self._model: SparseTextEmbedding | None = model

    def embed_passages(self, texts: Sequence[str]) -> list[SparseVector]:
        """Embed claims for indexing (document-side BM25 term weights).

        Args:
            texts: Claim texts to embed.

        Returns:
            One sparse vector per input text.
        """
        model = self._get_model()
        return [_to_sparse(embedding) for embedding in model.embed(list(texts))]

    def embed_query(self, text: str) -> SparseVector:
        """Embed one claim for retrieval (query-side BM25 terms).

        Args:
            text: The claim text to search with.

        Returns:
            A single sparse vector.
        """
        model = self._get_model()
        return _to_sparse(next(iter(model.query_embed(text))))

    def _get_model(self) -> "SparseTextEmbedding":
        if self._model is None:
            from fastembed import SparseTextEmbedding

            logger.info("loading sparse BM25 model {!r} (first use)", self._model_name)
            self._model = SparseTextEmbedding(model_name=self._model_name)
        return self._model


def _to_sparse(embedding: Any) -> SparseVector:
    """Convert a fastembed ``SparseEmbedding`` (numpy arrays) to a neutral :class:`SparseVector`."""
    return SparseVector(
        indices=[int(i) for i in embedding.indices.tolist()],
        values=[float(v) for v in embedding.values.tolist()],
    )


def build_dense_embedder(settings: Settings) -> DenseEmbedder:
    """Construct the default dense embedder (returns the :class:`DenseEmbedder` interface)."""
    return BgeDenseEmbedder(settings)


def build_sparse_embedder(settings: Settings) -> SparseEmbedder:
    """Construct the default sparse embedder (returns the :class:`SparseEmbedder` interface)."""
    return Bm25SparseEmbedder(settings)
