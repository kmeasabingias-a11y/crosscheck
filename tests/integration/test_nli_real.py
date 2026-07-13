"""NLI filter against the real DeBERTa model (spec v2 §7.4, §12).

Real-model integration test: confirms the 3-way NLI cross-encoder scores an obvious contradiction
high and a neutral pair low, and that ``filter_pairs`` keeps the contradiction while dropping the
unrelated pair. Marked ``integration`` (deselected by default); on first run it downloads
``cross-encoder/nli-deberta-v3-base`` (~370 MB). Runs entirely offline after that — no Qdrant, no
API key.
"""

from typing import Literal

import pytest

from crosscheck.config import get_settings
from crosscheck.detection.nli_filter import build_nli_scorer, filter_pairs
from crosscheck.ids import pair_id
from crosscheck.models import Claim, Pair

pytestmark = pytest.mark.integration


def _claim(
    claim_id: str, text: str, polarity: Literal["positive", "negative"] = "positive"
) -> Claim:
    return Claim(
        claim_id=claim_id,
        doc_id=claim_id[0].upper(),
        section_id=f"{claim_id}-s0",
        text=text,
        evidence_quote=text,
        evidence_offset=(0, len(text)),
        subject="insurance",
        predicate="",
        polarity=polarity,
    )


def _pair(a_id: str, b_id: str) -> Pair:
    first, second = sorted((a_id, b_id))
    return Pair(pair_id=pair_id(first, second), claim_a_id=first, claim_b_id=second)


def test_real_nli_scores_contradiction_high_neutral_low() -> None:
    scorer = build_nli_scorer(get_settings())
    contradiction, neutral = scorer.score(
        [
            (
                "Vendors must carry liability insurance.",
                "Vendors are not required to carry insurance.",
            ),
            ("Vendors must carry liability insurance.", "The office is open on weekdays."),
        ]
    )
    assert contradiction.is_contradiction
    assert contradiction.contradiction_prob > 0.5
    assert not neutral.is_contradiction
    assert neutral.contradiction_prob < contradiction.contradiction_prob


def test_real_nli_filter_keeps_contradiction_drops_unrelated() -> None:
    claims = [
        _claim("ins_pos", "Vendors must carry liability insurance."),
        _claim("ins_neg", "Vendors are not required to carry insurance.", "negative"),
        _claim("office", "The office is open on weekdays."),
    ]
    pairs = [_pair("ins_pos", "ins_neg"), _pair("ins_pos", "office")]
    kept = filter_pairs(
        pairs,
        claims,
        build_nli_scorer(get_settings()),
        thresholds={},
        default_threshold=0.5,
    )
    kept_ids = {pair.pair_id for pair in kept}
    assert pair_id(*sorted(("ins_pos", "ins_neg"))) in kept_ids
    assert pair_id(*sorted(("ins_pos", "office"))) not in kept_ids
    for pair in kept:
        assert pair.nli_contradiction_prob is not None
