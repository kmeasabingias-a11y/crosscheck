"""Unit tests for the NLI filter (hermetic — fake scorer / fake CrossEncoder, no models).

``filter_pairs`` is tested with a fake ``NLIScorer`` returning canned results, so the keep/drop,
bidirectional-combine, and per-type-threshold logic is exact and offline. ``DebertaNLIScorer`` is
tested with a fake CrossEncoder to confirm it reads the contradiction label index dynamically and
softmaxes correctly.
"""

from types import SimpleNamespace
from typing import Any, cast

import numpy as np

from crosscheck.config import Settings
from crosscheck.detection.nli_filter import (
    DebertaNLIScorer,
    NLIError,
    NLIResult,
    build_nli_scorer,
    filter_pairs,
)
from crosscheck.detection.taxonomy import ContradictionType
from crosscheck.ids import pair_id
from crosscheck.models import Claim, Pair


def _claim(claim_id: str, text: str) -> Claim:
    return Claim(
        claim_id=claim_id,
        doc_id=claim_id[0].upper(),
        section_id=f"{claim_id}-s0",
        text=text,
        evidence_quote=text,
        evidence_offset=(0, len(text)),
        subject="s",
        predicate="",
        polarity="positive",
    )


def _pair(a_id: str, b_id: str) -> Pair:
    first, second = sorted((a_id, b_id))
    return Pair(pair_id=pair_id(first, second), claim_a_id=first, claim_b_id=second)


class _FakeScorer:
    """Returns canned NLI results keyed by the ordered (premise, hypothesis) text pair."""

    def __init__(self, table: dict[tuple[str, str], NLIResult]) -> None:
        self._table = table

    def score(self, pairs: list[tuple[str, str]]) -> list[NLIResult]:
        default = NLIResult(contradiction_prob=0.1, is_contradiction=False)
        return [self._table.get((premise, hypothesis), default) for premise, hypothesis in pairs]


_A, _B = _claim("a1", "a-text"), _claim("b1", "b-text")
_CLAIMS = [_A, _B]
_PAIR = _pair("a1", "b1")


def _run(table: dict[tuple[str, str], NLIResult], **kw: Any) -> list[Pair]:
    kw.setdefault("thresholds", {})
    kw.setdefault("default_threshold", 0.5)
    return filter_pairs([_PAIR], _CLAIMS, cast(Any, _FakeScorer(table)), **kw)


def test_argmax_keeps_pair_even_below_threshold() -> None:
    # Contradiction is the top label (is_contradiction) though prob 0.2 < threshold 0.5.
    kept = _run({("a-text", "b-text"): NLIResult(0.2, True)})
    assert len(kept) == 1
    assert kept[0].nli_contradiction_prob == 0.2


def test_threshold_keeps_pair_when_prob_high() -> None:
    # Not the top label, but prob 0.6 >= threshold 0.5.
    kept = _run({("a-text", "b-text"): NLIResult(0.6, False)})
    assert len(kept) == 1 and kept[0].nli_contradiction_prob == 0.6


def test_drops_pair_when_low_prob_and_not_argmax() -> None:
    assert _run({("a-text", "b-text"): NLIResult(0.3, False)}) == []


def test_bidirectional_reverse_ordering_can_keep_and_sets_max_prob() -> None:
    # Forward is weak; the reverse ordering (b, a) is a strong contradiction.
    kept = _run(
        {
            ("a-text", "b-text"): NLIResult(0.1, False),
            ("b-text", "a-text"): NLIResult(0.7, True),
        }
    )
    assert len(kept) == 1
    assert kept[0].nli_contradiction_prob == 0.7  # max over the two orderings


def test_type_hint_applies_that_types_threshold() -> None:
    table = {("a-text", "b-text"): NLIResult(0.6, False)}
    thresholds = {ContradictionType.SCOPE_JURISDICTION: 0.9}
    # No hint: most-permissive threshold is min(0.5, 0.9) = 0.5, so 0.6 keeps it.
    assert len(_run(table, thresholds=thresholds)) == 1
    # With the SCOPE hint (threshold 0.9), 0.6 is below it and not argmax -> dropped.
    hints = {_PAIR.pair_id: ContradictionType.SCOPE_JURISDICTION}
    assert _run(table, thresholds=thresholds, type_hints=hints) == []


def test_empty_returns_empty() -> None:
    assert (
        filter_pairs([], _CLAIMS, cast(Any, _FakeScorer({})), thresholds={}, default_threshold=0.5)
        == []
    )


def test_unknown_claim_raises() -> None:
    bad = _pair("a1", "z9")
    try:
        filter_pairs(
            [bad], _CLAIMS, cast(Any, _FakeScorer({})), thresholds={}, default_threshold=0.5
        )
    except NLIError as exc:
        assert "z9" in str(exc)
    else:
        raise AssertionError("expected NLIError for an unknown claim id")


# --- DebertaNLIScorer over a fake CrossEncoder --------------------------------------------------


class _FakeCrossEncoder:
    """Stand-in for a sentence-transformers NLI CrossEncoder: raw logits + id2label."""

    def __init__(self, rows: list[list[float]], id2label: dict[int, str]) -> None:
        self._rows = rows
        self.model = SimpleNamespace(config=SimpleNamespace(id2label=id2label))

    def predict(self, inputs: list[tuple[str, str]]) -> Any:
        return np.array(self._rows[: len(inputs)], dtype="float32")


def test_scorer_reads_contradiction_index_and_softmaxes() -> None:
    ce = _FakeCrossEncoder(
        rows=[[5.0, 0.0, 0.0], [0.0, 5.0, 0.0]],
        id2label={0: "contradiction", 1: "entailment", 2: "neutral"},
    )
    scorer = DebertaNLIScorer(Settings(), model=cast(Any, ce))
    results = scorer.score([("x", "y"), ("p", "q")])
    assert results[0].is_contradiction and results[0].contradiction_prob > 0.98
    assert not results[1].is_contradiction and results[1].contradiction_prob < 0.02


def test_scorer_respects_nonstandard_label_order() -> None:
    # contradiction is index 2 here; the scorer must find it via id2label, not assume index 0.
    ce = _FakeCrossEncoder(
        rows=[[0.0, 0.0, 5.0]],
        id2label={0: "entailment", 1: "neutral", 2: "contradiction"},
    )
    scorer = DebertaNLIScorer(Settings(), model=cast(Any, ce))
    (result,) = scorer.score([("x", "y")])
    assert result.is_contradiction and result.contradiction_prob > 0.98


def test_scorer_without_contradiction_label_raises() -> None:
    ce = _FakeCrossEncoder(rows=[[1.0, 0.0]], id2label={0: "entailment", 1: "neutral"})
    scorer = DebertaNLIScorer(Settings(), model=cast(Any, ce))
    try:
        scorer.score([("x", "y")])
    except NLIError as exc:
        assert "contradiction" in str(exc)
    else:
        raise AssertionError("expected NLIError when no contradiction label exists")


def test_build_nli_scorer_constructs_without_loading_model() -> None:
    assert isinstance(build_nli_scorer(Settings()), DebertaNLIScorer)
