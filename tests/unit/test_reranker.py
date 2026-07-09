"""Unit tests for the cross-encoder reranker (hermetic — fake models, no downloads).

``CrossEncoderReranker`` accepts an injected model, so its wiring (call shape, float conversion)
is tested with a fake CrossEncoder. ``rerank_pairs`` is tested with a fake ``Reranker`` returning
canned scores, so the resolve-text / attach-score / sort / truncate logic is exact and offline.
"""

from typing import Any, cast

import numpy as np

from crosscheck.config import Settings
from crosscheck.ids import pair_id
from crosscheck.models import Claim, Pair
from crosscheck.retrieval.reranker import (
    CrossEncoderReranker,
    RerankError,
    build_reranker,
    rerank_pairs,
)


def _claim(claim_id: str, text: str) -> Claim:
    return Claim(
        claim_id=claim_id,
        doc_id=claim_id[0].upper(),
        section_id=f"{claim_id}-s0",
        text=text,
        evidence_quote=text,
        evidence_offset=(0, len(text)),
        subject="pto",
        predicate="entitlement",
        polarity="positive",
    )


def _pair(a_id: str, b_id: str, retrieval_score: float = 0.5) -> Pair:
    first, second = sorted((a_id, b_id))
    return Pair(
        pair_id=pair_id(first, second),
        claim_a_id=first,
        claim_b_id=second,
        retrieval_score=retrieval_score,
    )


class _FakeCrossEncoder:
    """Stand-in for a sentence-transformers CrossEncoder."""

    def __init__(self, seen: list[tuple[str, str]]) -> None:
        self._seen = seen

    def predict(self, inputs: list[tuple[str, str]]) -> Any:
        self._seen.extend((a, b) for a, b in inputs)
        # Score = length of the first text, as a deterministic numpy array (like the real model).
        return np.array([float(len(a)) for a, _ in inputs], dtype="float32")


class _FakeReranker:
    """Scores by the resolved text pair, recording the pairs it was given."""

    def __init__(self, seen: list[tuple[str, str]]) -> None:
        self._seen = seen

    def score_pairs(self, pairs: list[tuple[str, str]]) -> list[float]:
        self._seen.extend(pairs)
        table = {("a-text", "b-text"): 0.9, ("b-text", "c-text"): 0.2}
        return [table.get((a, b), 0.0) for a, b in pairs]


def test_cross_encoder_reranker_wraps_model_and_returns_floats() -> None:
    seen: list[tuple[str, str]] = []
    reranker = CrossEncoderReranker(Settings(), model=cast(Any, _FakeCrossEncoder(seen)))
    scores = reranker.score_pairs([("hello", "x"), ("hi", "y")])
    assert scores == [5.0, 2.0]
    assert all(isinstance(s, float) for s in scores)
    assert seen == [("hello", "x"), ("hi", "y")]


def test_cross_encoder_reranker_empty_is_noop() -> None:
    # No model needed: empty input short-circuits before loading.
    reranker = CrossEncoderReranker(Settings())
    assert reranker.score_pairs([]) == []


def test_rerank_pairs_scores_sorts_and_truncates() -> None:
    claims = [_claim("a1", "a-text"), _claim("b1", "b-text"), _claim("c1", "c-text")]
    pairs = [_pair("a1", "b1"), _pair("b1", "c1")]
    seen: list[tuple[str, str]] = []
    reranker = _FakeReranker(seen)
    kept = rerank_pairs(pairs, claims, cast(Any, reranker), top_k=1)
    # a1/b1 scores 0.9 vs b1/c1 0.2 → only the top pair survives top_k=1.
    assert len(kept) == 1
    assert kept[0].pair_id == pair_id("a1", "b1")
    assert kept[0].rerank_score == 0.9
    # The reranker saw the resolved claim texts, in canonical (a<b) order.
    assert ("a-text", "b-text") in seen


def test_rerank_pairs_empty_returns_empty() -> None:
    reranker = _FakeReranker([])
    assert rerank_pairs([], [_claim("a1", "a-text")], cast(Any, reranker), top_k=10) == []


def test_rerank_pairs_unknown_claim_raises() -> None:
    pairs = [_pair("a1", "z9")]  # z9 not in claims
    reranker = _FakeReranker([])
    try:
        rerank_pairs(pairs, [_claim("a1", "a-text")], cast(Any, reranker), top_k=10)
    except RerankError as exc:
        assert "z9" in str(exc)
    else:
        raise AssertionError("expected RerankError for an unknown claim id")


def test_build_reranker_constructs_without_loading_model() -> None:
    # Building a reranker must not trigger a model download; it only wires config.
    assert isinstance(build_reranker(Settings()), CrossEncoderReranker)
