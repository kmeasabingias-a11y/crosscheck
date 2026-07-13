"""LLM judge against the real Claude model (spec v2 §7.4, §12).

Real-API integration test: confirms the judge flags an obvious cross-document contradiction
with a v1 type and verbatim evidence, and clears a genuinely unrelated pair. Marked
``integration`` (deselected by default) and self-skips when ``ANTHROPIC_API_KEY`` is unset, so
it never runs — or spends — in CI. Costs a few cents when run.
"""

import pytest

from crosscheck.config import get_settings
from crosscheck.detection.llm_judge import LLMJudge
from crosscheck.detection.taxonomy import V1_TYPES
from crosscheck.ids import pair_id
from crosscheck.llm import LLMClient
from crosscheck.models import Claim, Pair

pytestmark = pytest.mark.integration


def _claim(claim_id: str, text: str) -> Claim:
    return Claim(
        claim_id=claim_id,
        doc_id=claim_id[0].upper(),
        section_id=f"{claim_id}-s0",
        text=text,
        evidence_quote=text,
        evidence_offset=(0, len(text)),
        subject="insurance",
        predicate="",
        polarity="positive",
    )


def _pair(a_id: str, b_id: str) -> Pair:
    first, second = sorted((a_id, b_id))
    return Pair(pair_id=pair_id(first, second), claim_a_id=first, claim_b_id=second)


def _judge() -> LLMJudge:
    settings = get_settings()
    if not settings.anthropic_api_key:
        pytest.skip("ANTHROPIC_API_KEY not set; skipping real-judge integration test")
    return LLMJudge(LLMClient(settings), settings)


def test_real_judge_flags_obvious_contradiction() -> None:
    claims = [
        _claim("ins_pos", "Vendors must carry liability insurance."),
        _claim("ins_neg", "Vendors are not required to carry any insurance."),
    ]
    pair = _pair("ins_pos", "ins_neg")
    result = _judge().judge([pair], claims)

    assert len(result.contradictions) == 1
    verdict = result.contradictions[0]
    assert verdict.pair_id == pair.pair_id
    assert verdict.contradiction_type in V1_TYPES  # a concrete v1 type, not UNCLEAR
    assert result.hallucination_count == 0  # evidence quoted verbatim, so nothing dropped
    assert 0.0 <= verdict.confidence <= 1.0


def test_real_judge_clears_unrelated_pair() -> None:
    claims = [
        _claim("ins", "Vendors must carry liability insurance."),
        _claim("office", "The head office is open on weekdays."),
    ]
    pair = _pair("ins", "office")
    result = _judge().judge([pair], claims)

    assert len(result.verdicts) == 1
    assert not result.verdicts[0].is_contradiction
