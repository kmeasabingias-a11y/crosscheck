"""Unit tests for the LLM judge (LLM mocked; no network).

The judge wraps a real :class:`LLMClient` around a mocked Anthropic SDK client (so the cost
tracking and ceiling are exercised for real), and the model's ``parse`` returns canned
``JudgedVerdict`` outputs. This pins down finalization (pair id, evidence substring check,
type coercion), the resume cache, and the cost-ceiling stop — all offline.
"""

from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

from anthropic import Anthropic
from anthropic.types import Usage

from crosscheck.config import Settings
from crosscheck.detection.llm_judge import (
    InMemoryVerdictCache,
    JudgedVerdict,
    JudgeError,
    LLMJudge,
)
from crosscheck.detection.taxonomy import ContradictionType
from crosscheck.ids import pair_id
from crosscheck.llm import LLMClient
from crosscheck.models import Claim, Pair


def _usage() -> Usage:
    return Usage(
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )


def _response(verdict: JudgedVerdict) -> SimpleNamespace:
    return SimpleNamespace(usage=_usage(), parsed_output=verdict, stop_reason="end_turn")


def _judge(
    responses: list[SimpleNamespace],
    *,
    cache: InMemoryVerdictCache | None = None,
    cost_ceiling_usd: float | None = None,
) -> tuple[LLMJudge, MagicMock]:
    mock = MagicMock()
    mock.messages.parse.side_effect = responses
    settings = Settings(anthropic_api_key="k")
    llm = LLMClient(settings, client=cast(Anthropic, mock), cost_ceiling_usd=cost_ceiling_usd)
    judge = LLMJudge(llm, settings, cache=cache)
    return judge, mock


def _claim(claim_id: str, text: str, quote: str | None = None) -> Claim:
    return Claim(
        claim_id=claim_id,
        doc_id=claim_id[0].upper(),
        section_id=f"{claim_id}-s0",
        text=text,
        evidence_quote=quote if quote is not None else text,
        evidence_offset=(0, len(quote if quote is not None else text)),
        subject="s",
        predicate="",
        polarity="positive",
    )


def _pair(a_id: str, b_id: str) -> Pair:
    first, second = sorted((a_id, b_id))
    return Pair(pair_id=pair_id(first, second), claim_a_id=first, claim_b_id=second)


_A = _claim("a1", "Vendors must carry liability insurance.")
_B = _claim("b1", "Vendors are not required to carry insurance.")
_CLAIMS = [_A, _B]
_PAIR = _pair("a1", "b1")


def _verdict(
    *,
    is_contradiction: bool = True,
    contradiction_type: ContradictionType | None = ContradictionType.OBLIGATION_REVERSAL,
    evidence_a: str = "must carry liability insurance",
    evidence_b: str = "not required to carry insurance",
    confidence: float = 0.9,
) -> JudgedVerdict:
    return JudgedVerdict(
        is_contradiction=is_contradiction,
        contradiction_type=contradiction_type,
        confidence=confidence,
        rationale="One requires insurance, the other exempts from it.",
        evidence_a=evidence_a,
        evidence_b=evidence_b,
        resolution_hint=None,
    )


def test_judges_contradiction_and_sets_pair_id() -> None:
    judge, mock = _judge([_response(_verdict())])
    result = judge.judge([_PAIR], _CLAIMS)
    assert mock.messages.parse.call_count == 1
    assert len(result.verdicts) == 1
    verdict = result.verdicts[0]
    assert verdict.pair_id == _PAIR.pair_id  # set in code, not by the model
    assert verdict.is_contradiction
    assert verdict.contradiction_type == ContradictionType.OBLIGATION_REVERSAL
    assert result.hallucination_count == 0
    assert len(result.contradictions) == 1


def test_drops_hallucinated_evidence() -> None:
    # evidence_a is not a substring of claim A -> dropped and counted, no verdict kept.
    judge, _ = _judge([_response(_verdict(evidence_a="fabricated words not in the claim"))])
    result = judge.judge([_PAIR], _CLAIMS)
    assert result.verdicts == []
    assert result.hallucination_count == 1
    assert result.hallucination_rate == 1.0


def test_negative_verdict_kept_without_evidence_validation() -> None:
    # Not a contradiction: empty evidence is fine and it is not a hallucination.
    judge, _ = _judge(
        [
            _response(
                _verdict(
                    is_contradiction=False,
                    contradiction_type=None,
                    evidence_a="",
                    evidence_b="",
                    confidence=0.2,
                )
            )
        ]
    )
    result = judge.judge([_PAIR], _CLAIMS)
    assert len(result.verdicts) == 1
    verdict = result.verdicts[0]
    assert not verdict.is_contradiction
    assert verdict.contradiction_type is None
    assert result.hallucination_count == 0
    assert result.contradictions == []


def test_conditional_triplet_coerced_to_unclear() -> None:
    judge, _ = _judge(
        [_response(_verdict(contradiction_type=ContradictionType.CONDITIONAL_TRIPLET))]
    )
    result = judge.judge([_PAIR], _CLAIMS)
    assert result.verdicts[0].contradiction_type == ContradictionType.UNCLEAR


def test_missing_type_on_contradiction_becomes_unclear() -> None:
    judge, _ = _judge([_response(_verdict(contradiction_type=None))])
    result = judge.judge([_PAIR], _CLAIMS)
    assert result.verdicts[0].contradiction_type == ContradictionType.UNCLEAR


def test_evidence_from_source_quote_is_accepted() -> None:
    # The judge may quote a claim's raw source span, not just the assertion.
    claim_a = _claim(
        "a1", "Vendors must carry liability insurance.", quote="carry liability insurance"
    )
    judge, _ = _judge([_response(_verdict(evidence_a="carry liability insurance"))])
    result = judge.judge([_PAIR], [claim_a, _B])
    assert len(result.verdicts) == 1
    assert result.hallucination_count == 0


def test_whitespace_tolerant_evidence() -> None:
    # Claim text has a line-wrap newline; the model quotes it with a space (D20).
    claim_a = _claim("a1", "Vendors must carry\nliability insurance.")
    judge, _ = _judge([_response(_verdict(evidence_a="must carry liability insurance"))])
    result = judge.judge([_PAIR], [claim_a, _B])
    assert len(result.verdicts) == 1
    assert result.hallucination_count == 0


def test_cache_prevents_second_call() -> None:
    cache = InMemoryVerdictCache()
    judge, mock = _judge([_response(_verdict())], cache=cache)
    first = judge.judge([_PAIR], _CLAIMS)
    second = judge.judge([_PAIR], _CLAIMS)
    assert mock.messages.parse.call_count == 1  # second run served from cache
    assert first.cache_hits == 0
    assert second.cache_hits == 1
    assert len(second.verdicts) == 1


def test_cost_ceiling_stops_and_marks_partial() -> None:
    # Ceiling so low the first recorded call trips it, so the second pair is never dispatched.
    pair2 = _pair("a1", "c1")
    claim_c = _claim("c1", "The office is open on weekdays.")
    judge, mock = _judge([_response(_verdict()), _response(_verdict())], cost_ceiling_usd=0.0001)
    result = judge.judge([_PAIR, pair2], [_A, _B, claim_c])
    assert result.partial
    assert result.llm_call_count == 1
    assert mock.messages.parse.call_count == 1
    assert len(result.verdicts) == 1
    assert result.pair_count == 2  # both pairs were on the work-list


def test_unknown_claim_raises() -> None:
    bad = _pair("a1", "z9")
    judge, _ = _judge([])
    try:
        judge.judge([bad], _CLAIMS)
    except JudgeError as exc:
        assert "z9" in str(exc)
    else:
        raise AssertionError("expected JudgeError for an unknown claim id")


def test_empty_returns_empty() -> None:
    judge, mock = _judge([])
    result = judge.judge([], _CLAIMS)
    assert result.verdicts == []
    assert result.pair_count == 0
    assert result.hallucination_rate == 0.0
    assert mock.messages.parse.call_count == 0
