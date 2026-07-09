"""Unit tests for the negation benchmark schema/loader (hermetic — no models).

Validates the committed fixture and the seed->Claim conversion. The actual retrieval recall is a
real-model integration test (``tests/integration/test_negation_retrieval.py``).
"""

from pathlib import Path

from crosscheck.evaluation.negation import (
    ClaimSeed,
    NegationPair,
    load_negation_pairs,
    to_claim_pairs,
    to_claims,
)

_FIXTURE = Path(__file__).parents[2] / "benchmarks" / "negation" / "negation_pairs.json"


def test_committed_fixture_is_well_formed() -> None:
    pairs = load_negation_pairs(_FIXTURE)
    assert len(pairs) >= 8
    subjects = [pair.subject for pair in pairs]
    assert len(set(subjects)) == len(subjects), "subjects should be distinct across pairs"
    for pair in pairs:
        # Cross-document, opposite polarity, non-empty and distinct text.
        assert pair.positive.doc_id != pair.negative.doc_id
        assert pair.positive.polarity == "positive"
        assert pair.negative.polarity == "negative"
        assert pair.positive.text.strip() and pair.negative.text.strip()
        assert pair.positive.text != pair.negative.text


def test_to_claim_pairs_are_valid_and_cross_document() -> None:
    pairs = load_negation_pairs(_FIXTURE)
    claim_pairs = to_claim_pairs(pairs)
    assert len(claim_pairs) == len(pairs)
    for (positive, negative), pair in zip(claim_pairs, pairs, strict=True):
        assert positive.doc_id != negative.doc_id
        assert positive.claim_id != negative.claim_id
        assert positive.text == pair.positive.text
        # Evidence is grounded verbatim (the whole seed text) and offsets are valid.
        assert positive.evidence_quote == positive.text
        assert positive.evidence_offset == (0, len(positive.text))


def test_claim_ids_are_unique_and_deterministic() -> None:
    pairs = load_negation_pairs(_FIXTURE)
    corpus = to_claims(pairs)
    assert len(corpus) == 2 * len(pairs)
    ids = [claim.claim_id for claim in corpus]
    assert len(set(ids)) == len(ids), "every claim id in the corpus must be unique"
    # Deterministic: rebuilding yields the same ids.
    assert [claim.claim_id for claim in to_claims(pairs)] == ids


def test_to_claims_flattens_pair_order() -> None:
    pair = NegationPair(
        subject="s",
        positive=ClaimSeed(doc_id="a", text="X is required.", polarity="positive"),
        negative=ClaimSeed(doc_id="b", text="X is not required.", polarity="negative"),
    )
    corpus = to_claims([pair])
    assert [claim.polarity for claim in corpus] == ["positive", "negative"]
    assert corpus[0].doc_id == "neg:a" and corpus[1].doc_id == "neg:b"
