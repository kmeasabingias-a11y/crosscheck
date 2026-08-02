"""NLI filter: a cheap contradiction pre-screen before the LLM judge (spec v2 §7.4).

The LLM judge is expensive (~$0.003-0.015/pair); NLI is roughly 1000x cheaper. A 500-claim corpus
yields on the order of 10k candidate pairs after retrieval — far too many to judge directly. This
stage runs a 3-way NLI cross-encoder (contradiction / entailment / neutral) on each reranked pair
and keeps only the likely-contradiction ones, so the judge reasons carefully over a few hundred
rather than thousands.

**Recall is the priority here** (precision is recovered by the judge): a pair is kept if
contradiction is the NLI model's top label **or** its contradiction probability clears a threshold.
Note that the OR makes the threshold meaningful only *below* 0.5: with three labels a
contradiction probability of 0.5 or more is necessarily the argmax, so any higher threshold
reduces to the argmax arm alone and filters nothing extra (D41).
Thresholds are **per contradiction type** (§7.4) — numerical mismatch and direct negation calibrate
very differently from scope/jurisdiction. The type is usually unknown before the judge, so the
filter then uses the **most permissive** (lowest) threshold; a caller that has a type hint (e.g. the
Phase-6 calibration harness, which knows the gold type) can pass one to use that type's threshold.
Both NLI orderings of a pair are scored and combined, because NLI is directional and contradiction
detection should not depend on which claim is treated as the premise.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from loguru import logger

from crosscheck.config import Settings
from crosscheck.detection.taxonomy import ContradictionType
from crosscheck.models import Claim, Pair

if TYPE_CHECKING:  # imported lazily at runtime (see _get_model) to keep construction cheap
    from sentence_transformers import CrossEncoder


class NLIError(RuntimeError):
    """Raised when a pair references a claim id absent from the provided claims."""


@dataclass(frozen=True)
class NLIResult:
    """One NLI scoring of an ordered ``(premise, hypothesis)`` text pair."""

    contradiction_prob: float
    is_contradiction: bool  # contradiction is the argmax of the three labels


class NLIScorer(Protocol):
    """Scores ordered ``(premise, hypothesis)`` text pairs for contradiction."""

    def score(self, pairs: Sequence[tuple[str, str]]) -> list[NLIResult]:
        """Return one :class:`NLIResult` per input text pair, in order."""
        ...


class DebertaNLIScorer:
    """NLI scorer backed by a sentence-transformers ``CrossEncoder`` (default nli-deberta-v3-base).

    The model's three logits are softmaxed to probabilities; the contradiction label's index is
    read from the model's ``id2label`` (not hardcoded), so a differently-ordered model still works.
    Loads lazily on first ``score`` call and accepts an injected model for tests.
    """

    def __init__(self, settings: Settings, *, model: "CrossEncoder | None" = None) -> None:
        """Build from settings, optionally wrapping a pre-built model (for tests).

        Args:
            settings: Runtime configuration (NLI model name).
            model: A pre-loaded CrossEncoder; loaded lazily from the model name if omitted.
        """
        self._model_name = settings.nli_model
        self._model: CrossEncoder | None = model
        self._contradiction_index: int | None = None

    def score(self, pairs: Sequence[tuple[str, str]]) -> list[NLIResult]:
        """Score each ordered ``(premise, hypothesis)`` pair.

        Args:
            pairs: The ordered text pairs to score.

        Returns:
            One result per pair (contradiction probability + whether it is the top label).
        """
        if not pairs:
            return []
        model = self._get_model()
        index = self._get_contradiction_index()
        raw = model.predict([(premise, hypothesis) for premise, hypothesis in pairs])
        results: list[NLIResult] = []
        for row in raw:
            probs = _softmax([float(value) for value in row])
            top = max(range(len(probs)), key=probs.__getitem__)
            results.append(
                NLIResult(contradiction_prob=probs[index], is_contradiction=(top == index))
            )
        return results

    def _get_model(self) -> "CrossEncoder":
        if self._model is None:
            from sentence_transformers import CrossEncoder

            logger.info("loading NLI model {!r} (first use)", self._model_name)
            self._model = CrossEncoder(self._model_name)
        return self._model

    def _get_contradiction_index(self) -> int:
        if self._contradiction_index is None:
            hf_model = self._get_model().model
            if hf_model is None:
                raise NLIError(f"NLI model {self._model_name!r} is not loaded")
            id2label = hf_model.config.id2label
            if id2label is None:
                raise NLIError(f"NLI model {self._model_name!r} exposes no id2label mapping")
            for index, label in id2label.items():
                if str(label).lower() == "contradiction":
                    self._contradiction_index = int(index)
                    break
            else:
                raise NLIError(
                    f"NLI model {self._model_name!r} exposes no 'contradiction' label: {id2label}"
                )
        return self._contradiction_index


def build_nli_scorer(settings: Settings) -> NLIScorer:
    """Construct the default NLI scorer (returns the :class:`NLIScorer` interface)."""
    return DebertaNLIScorer(settings)


def filter_pairs(
    pairs: Sequence[Pair],
    claims: Sequence[Claim],
    scorer: NLIScorer,
    *,
    thresholds: Mapping[ContradictionType, float],
    default_threshold: float,
    type_hints: Mapping[str, ContradictionType] | None = None,
) -> list[Pair]:
    """Keep the likely-contradiction pairs, scoring each with NLI in both orderings.

    A pair survives if contradiction is the top NLI label in either ordering, or if its (max over
    the two orderings) contradiction probability clears the applicable threshold. The surviving
    pairs carry that probability in ``nli_contradiction_prob``.

    Args:
        pairs: Reranked candidate pairs.
        claims: The corpus claims (used to resolve each pair's claim ids to text).
        scorer: The NLI scorer.
        thresholds: Per-type contradiction-probability thresholds (§7.4).
        default_threshold: Threshold for a type absent from ``thresholds``.
        type_hints: Optional pair_id -> likely type. When a pair has no hint, the most permissive
            (lowest) applicable threshold is used, since the type is unknown before the judge.

    Returns:
        The surviving pairs, each with ``nli_contradiction_prob`` set, in input order.

    Raises:
        NLIError: If a pair references a claim id not present in ``claims``.
    """
    if not pairs:
        return []
    claims_by_id = {claim.claim_id: claim for claim in claims}
    try:
        ordered: list[tuple[str, str]] = []
        for pair in pairs:
            a_text = claims_by_id[pair.claim_a_id].text
            b_text = claims_by_id[pair.claim_b_id].text
            ordered.append((a_text, b_text))
            ordered.append((b_text, a_text))
    except KeyError as exc:  # a pair references a claim we were not given
        raise NLIError(f"pair references unknown claim id {exc.args[0]!r}") from exc

    results = scorer.score(ordered)
    permissive = min([default_threshold, *thresholds.values()])
    kept: list[Pair] = []
    for i, pair in enumerate(pairs):
        forward, reverse = results[2 * i], results[2 * i + 1]
        prob = max(forward.contradiction_prob, reverse.contradiction_prob)
        is_contradiction = forward.is_contradiction or reverse.is_contradiction
        hint = type_hints.get(pair.pair_id) if type_hints else None
        threshold = thresholds.get(hint, default_threshold) if hint is not None else permissive
        if is_contradiction or prob >= threshold:
            kept.append(pair.model_copy(update={"nli_contradiction_prob": prob}))
    logger.info("NLI filter kept {}/{} candidate pair(s)", len(kept), len(pairs))
    return kept


def _softmax(values: list[float]) -> list[float]:
    """Numerically stable softmax over a small list of logits."""
    peak = max(values)
    exps = [math.exp(value - peak) for value in values]
    total = sum(exps)
    return [exp / total for exp in exps]
