"""Unit tests for the extraction gold set schema, loader, and scorer."""

from pathlib import Path
from typing import Literal

from crosscheck.evaluation.extraction_gold import (
    GoldChunk,
    GoldClaim,
    load_gold_set,
    score_extraction,
    to_chunk,
)
from crosscheck.models import Claim

_TEXT = "All employees receive 20 PTO days. Contractors are not entitled to PTO."
_POS = "All employees receive 20 PTO days."
_NEG = "Contractors are not entitled to PTO."


def _gold(claims: list[GoldClaim]) -> GoldChunk:
    return GoldChunk(gold_id="g1", source="unit-test", text=_TEXT, claims=claims)


def _extracted(quote: str, polarity: Literal["positive", "negative"]) -> Claim:
    start = _TEXT.find(quote)
    assert start >= 0
    return Claim(
        claim_id="c",
        doc_id="d",
        section_id="s",
        text=quote,
        evidence_quote=quote,
        evidence_offset=(start, start + len(quote)),
        subject="subject",
        predicate="predicate",
        polarity=polarity,
    )


def test_perfect_match_scores_one() -> None:
    gold = [
        _gold(
            [
                GoldClaim(evidence_quote=_POS, polarity="positive"),
                GoldClaim(evidence_quote=_NEG, polarity="negative"),
            ]
        )
    ]
    extracted = {"g1": [_extracted(_POS, "positive"), _extracted(_NEG, "negative")]}
    score = score_extraction(gold, extracted)
    assert (score.precision, score.recall, score.f1) == (1.0, 1.0, 1.0)
    assert score.polarity_accuracy == 1.0
    assert score.gold_claims == 2 and score.extracted_claims == 2


def test_partial_quote_still_matches_its_gold_claim() -> None:
    # A shorter extracted quote inside a gold quote refers to the same claim (matches).
    gold = [_gold([GoldClaim(evidence_quote=_NEG, polarity="negative")])]
    extracted = {"g1": [_extracted("Contractors are not entitled", "negative")]}
    score = score_extraction(gold, extracted)
    assert score.true_positives == 1 and score.false_positives == 0


def test_disjoint_extraction_is_false_positive() -> None:
    gold = [_gold([GoldClaim(evidence_quote=_POS, polarity="positive")])]
    extracted = {"g1": [_extracted(_POS, "positive"), _extracted(_NEG, "negative")]}
    score = score_extraction(gold, extracted)
    assert score.true_positives == 1
    assert score.false_positives == 1  # _NEG has no gold to match
    assert score.false_negatives == 0
    assert score.precision == 0.5 and score.recall == 1.0


def test_missing_extraction_is_false_negative() -> None:
    gold = [
        _gold(
            [
                GoldClaim(evidence_quote=_POS, polarity="positive"),
                GoldClaim(evidence_quote=_NEG, polarity="negative"),
            ]
        )
    ]
    extracted = {"g1": [_extracted(_POS, "positive")]}
    score = score_extraction(gold, extracted)
    assert score.true_positives == 1 and score.false_negatives == 1
    assert score.recall == 0.5 and score.precision == 1.0


def test_polarity_mismatch_still_matches_but_flags_polarity() -> None:
    gold = [_gold([GoldClaim(evidence_quote=_NEG, polarity="negative")])]
    extracted = {"g1": [_extracted(_NEG, "positive")]}  # right span, wrong polarity
    score = score_extraction(gold, extracted)
    assert score.true_positives == 1
    assert score.polarity_correct == 0
    assert score.polarity_accuracy == 0.0


def test_unresolved_gold_quote_is_counted_not_matched() -> None:
    gold = [_gold([GoldClaim(evidence_quote="a quote absent from the text", polarity="positive")])]
    score = score_extraction(gold, {"g1": []})
    assert score.unresolved_gold == 1
    assert score.gold_claims == 0  # excluded from the denominator


def test_empty_gold_with_no_extraction_has_no_findings() -> None:
    gold = [_gold([])]  # chunk is all non-claims
    score = score_extraction(gold, {"g1": []})
    assert (score.true_positives, score.false_positives, score.false_negatives) == (0, 0, 0)


def test_empty_gold_with_extraction_is_all_false_positive() -> None:
    gold = [_gold([])]
    score = score_extraction(gold, {"g1": [_extracted(_POS, "positive")]})
    assert score.false_positives == 1
    assert score.precision == 0.0


def test_load_gold_set_round_trips(tmp_path: Path) -> None:
    chunk = _gold([GoldClaim(evidence_quote=_POS, polarity="positive", subject="employees")])
    (tmp_path / "g1.json").write_text(chunk.model_dump_json(indent=2), encoding="utf-8")
    loaded = load_gold_set(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].gold_id == "g1"
    assert loaded[0].claims[0].subject == "employees"


def test_to_chunk_is_self_contained_and_namespaced() -> None:
    chunk = to_chunk(_gold([]))
    assert chunk.text == _TEXT
    assert chunk.char_span == (0, len(_TEXT))
    assert chunk.doc_id.startswith("gold:")
