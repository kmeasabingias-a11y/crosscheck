"""Unit tests for the dense/sparse embedders (hermetic — fake models, no downloads).

The concrete embedders accept an injected model, so these tests exercise the wiring — batch
shapes, the query instruction, the dimension check, and the numpy->neutral sparse conversion —
without loading a real model. The real models are exercised by the Phase-2 storage integration
test.
"""

from typing import Any, cast

import numpy as np
import pytest

from crosscheck.config import Settings
from crosscheck.storage.embeddings import (
    BgeDenseEmbedder,
    Bm25SparseEmbedder,
    EmbeddingError,
    SparseVector,
    build_dense_embedder,
    build_sparse_embedder,
)


class _FakeSTModel:
    """Stand-in for a sentence-transformers model."""

    def __init__(self, dim: int, seen: list[str]) -> None:
        self._dim = dim
        self._seen = seen

    def get_sentence_embedding_dimension(self) -> int:
        return self._dim

    def encode(
        self, texts: list[str], normalize_embeddings: bool = False, convert_to_numpy: bool = False
    ) -> Any:
        self._seen.extend(texts)
        return np.zeros((len(texts), self._dim), dtype="float32")


class _FakeSparseEmbedding:
    def __init__(self, indices: list[int], values: list[float]) -> None:
        self.indices = np.array(indices, dtype="int64")
        self.values = np.array(values, dtype="float64")


class _FakeBM25:
    """Stand-in for a fastembed SparseTextEmbedding model."""

    def __init__(self, seen: list[tuple[str, str]]) -> None:
        self._seen = seen

    def embed(self, texts: list[str]) -> Any:
        for text in texts:
            self._seen.append(("embed", text))
            yield _FakeSparseEmbedding([1, 2], [0.5, 0.5])

    def query_embed(self, text: str) -> Any:
        self._seen.append(("query", text))
        yield _FakeSparseEmbedding([2], [1.0])


def test_dense_passages_verbatim_query_gets_instruction() -> None:
    seen: list[str] = []
    emb = BgeDenseEmbedder(
        Settings(dense_vector_size=8, dense_query_instruction="Q: "),
        model=cast(Any, _FakeSTModel(8, seen)),
    )
    assert emb.dim == 8
    passages = emb.embed_passages(["a", "b"])
    assert len(passages) == 2 and all(len(v) == 8 for v in passages)
    query = emb.embed_query("hello")
    assert len(query) == 8
    # Passages embedded as-is; the query is prefixed with the instruction.
    assert seen == ["a", "b", "Q: hello"]


def test_dense_no_instruction_when_blank() -> None:
    seen: list[str] = []
    emb = BgeDenseEmbedder(
        Settings(dense_vector_size=4, dense_query_instruction=""),
        model=cast(Any, _FakeSTModel(4, seen)),
    )
    emb.embed_query("hello")
    assert seen == ["hello"]


def test_dense_dimension_mismatch_raises() -> None:
    emb = BgeDenseEmbedder(Settings(dense_vector_size=1024), model=cast(Any, _FakeSTModel(8, [])))
    with pytest.raises(EmbeddingError):
        emb.embed_passages(["x"])


def test_sparse_conversion_to_neutral_vectors() -> None:
    seen: list[tuple[str, str]] = []
    emb = Bm25SparseEmbedder(Settings(), model=cast(Any, _FakeBM25(seen)))
    passages = emb.embed_passages(["a", "b"])
    assert passages[0] == SparseVector(indices=[1, 2], values=[0.5, 0.5])
    # Indices come back as plain Python ints (not numpy int64).
    assert type(passages[0].indices[0]) is int
    query = emb.embed_query("hi")
    assert query == SparseVector(indices=[2], values=[1.0])
    assert seen == [("embed", "a"), ("embed", "b"), ("query", "hi")]


def test_factories_construct_without_loading_models() -> None:
    # Building an embedder must not trigger a model download; it only wires config.
    assert build_dense_embedder(Settings()).dim == Settings().dense_vector_size
    build_sparse_embedder(Settings())
