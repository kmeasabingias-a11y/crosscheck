"""Cross-encoder reranking of candidate pairs (spec v2 §7.3, §5).

Candidate generation is recall-oriented — it casts a wide net (top-25 per claim via hybrid
retrieval) to avoid missing a contradiction. The reranker is precision-oriented: a cross-encoder
reads *both* claims of a pair together (not as two independent vectors) and scores how strongly
they relate, so the most promising pairs rise to the top and only the top-K reach the expensive
NLI + LLM-judge stages. This is the standard retrieve-then-rerank pattern; keeping it a separate,
optional stage also makes the "reranker on vs off" ablation (§9.3) a one-line change upstream.

The model is sentence-transformers' ``CrossEncoder`` with the spec-prescribed
``BAAI/bge-reranker-v2-m3`` (§5). ``torch`` and ``sentence-transformers`` are already present for
the dense embedder (D22), so this adds **no new dependency** and reuses the same runtime. The
model loads lazily on first use and accepts an injected model for hermetic tests, mirroring the
embedders.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

from loguru import logger

from crosscheck.config import Settings
from crosscheck.models import Claim, Pair

if TYPE_CHECKING:  # imported lazily at runtime (see _get_model) to keep construction cheap
    from sentence_transformers import CrossEncoder


class RerankError(RuntimeError):
    """Raised when a pair references a claim id absent from the provided claims."""


class Reranker(Protocol):
    """Scores ``(text_a, text_b)`` claim pairs by how strongly they relate."""

    def score_pairs(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        """Return one relatedness score per input text pair (higher = more related)."""
        ...


class CrossEncoderReranker:
    """Reranker backed by a sentence-transformers ``CrossEncoder`` (default bge-reranker-v2-m3).

    The model is loaded on first ``score_pairs`` call; pass ``model=`` to inject a pre-built or
    fake model for tests.
    """

    def __init__(self, settings: Settings, *, model: "CrossEncoder | None" = None) -> None:
        """Build from settings, optionally wrapping a pre-built model (for tests).

        Args:
            settings: Runtime configuration (reranker model name).
            model: A pre-loaded CrossEncoder; loaded lazily from the model name if omitted.
        """
        self._model_name = settings.rerank_model
        self._model: CrossEncoder | None = model

    def score_pairs(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        """Score each ``(text_a, text_b)`` pair with the cross-encoder.

        Args:
            pairs: The text pairs to score.

        Returns:
            One float score per pair, in the same order.
        """
        if not pairs:
            return []
        model = self._get_model()
        scores = model.predict([(a, b) for a, b in pairs])
        return [float(score) for score in scores]

    def _get_model(self) -> "CrossEncoder":
        if self._model is None:
            from sentence_transformers import CrossEncoder

            logger.info("loading reranker model {!r} (first use)", self._model_name)
            self._model = CrossEncoder(self._model_name)
        return self._model


def build_reranker(settings: Settings) -> Reranker:
    """Construct the default cross-encoder reranker (returns the :class:`Reranker` interface)."""
    return CrossEncoderReranker(settings)


def rerank_pairs(
    pairs: Sequence[Pair],
    claims: Sequence[Claim],
    reranker: Reranker,
    *,
    top_k: int,
) -> list[Pair]:
    """Rescore candidate pairs with the cross-encoder and keep the top-``top_k``.

    Each pair's two claims are resolved to their text, scored together by the reranker, and the
    resulting ``rerank_score`` is attached to a copy of the pair. Pairs are returned sorted by
    descending rerank score (ties broken by ``pair_id`` for determinism), truncated to ``top_k``.

    Args:
        pairs: Candidate pairs from candidate generation
            (:func:`~crosscheck.retrieval.candidate_gen.generate_candidate_pairs`).
        claims: The corpus claims (used to resolve each pair's claim ids to text).
        reranker: The reranker to score with.
        top_k: Number of top-scoring pairs to keep.

    Returns:
        The top-``top_k`` pairs, highest rerank score first, each carrying its ``rerank_score``.

    Raises:
        RerankError: If a pair references a claim id not present in ``claims``.
    """
    if not pairs:
        return []
    claims_by_id = {claim.claim_id: claim for claim in claims}
    try:
        text_pairs = [
            (claims_by_id[pair.claim_a_id].text, claims_by_id[pair.claim_b_id].text)
            for pair in pairs
        ]
    except KeyError as exc:  # a pair references a claim we were not given
        raise RerankError(f"pair references unknown claim id {exc.args[0]!r}") from exc
    scores = reranker.score_pairs(text_pairs)
    reranked = [
        pair.model_copy(update={"rerank_score": score})
        for pair, score in zip(pairs, scores, strict=True)
    ]
    reranked.sort(key=lambda pair: (-(pair.rerank_score or 0.0), pair.pair_id))
    kept = reranked[:top_k]
    logger.info("reranked {} candidate pair(s), kept top {}", len(pairs), len(kept))
    return kept
