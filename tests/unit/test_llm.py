"""Unit tests for the LLM wrapper."""

from typing import cast
from unittest.mock import MagicMock

import openai
import pytest
from anthropic import Anthropic
from anthropic.types import Usage
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from crosscheck.config import Settings
from crosscheck.llm import (
    CostCeilingError,
    CostTracker,
    LLMClient,
    LLMError,
    LLMTruncationError,
    OpenAIClient,
)


class _Out(BaseModel):
    x: int


def _usage(inp: int, out: int) -> Usage:
    return Usage(
        input_tokens=inp,
        output_tokens=out,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )


def test_cost_tracker_prices_sonnet() -> None:
    tracker = CostTracker()
    cost = tracker.record("claude-sonnet-4-6", _usage(1000, 500))
    assert cost == pytest.approx((1000 * 3.0 + 500 * 15.0) / 1_000_000)
    assert tracker.call_count == 1
    assert tracker.total_usd == pytest.approx(cost)


def test_missing_api_key_raises() -> None:
    with pytest.raises(LLMError):
        LLMClient(Settings(anthropic_api_key=None))


def test_unpriced_model_raises() -> None:
    # Deliberately not a real model name: this test used to say "gpt-4o", which silently
    # stopped testing anything the day gpt-4o was added to MODEL_PRICING for §9.1.
    client = LLMClient(Settings(anthropic_api_key="k"), client=cast(Anthropic, MagicMock()))
    with pytest.raises(LLMError, match="No pricing configured"):
        client.structured(model="not-a-real-model", system="s", user="u", schema=_Out)


def test_ceiling_blocks_call() -> None:
    client = LLMClient(
        Settings(anthropic_api_key="k"),
        client=cast(Anthropic, MagicMock()),
        cost_ceiling_usd=0.0,
    )
    with pytest.raises(CostCeilingError):
        client.structured(model="claude-sonnet-4-6", system="s", user="u", schema=_Out)


def _validation_error(payload: str) -> ValidationError:
    """Produce a real pydantic error by validating `payload`, as messages.parse would."""
    try:
        _Out.model_validate_json(payload)
    except ValidationError as exc:
        return exc
    raise AssertionError("expected a validation error")


def test_truncated_output_raises_truncation_error() -> None:
    mock = MagicMock()
    mock.messages.parse.side_effect = _validation_error('{"x": "abc')
    client = LLMClient(Settings(anthropic_api_key="k"), client=cast(Anthropic, mock))
    with pytest.raises(LLMTruncationError):
        client.structured(model="claude-sonnet-4-6", system="s", user="u", schema=_Out)


def test_schema_violation_is_not_a_truncation() -> None:
    mock = MagicMock()
    mock.messages.parse.side_effect = _validation_error('{"x": "no"}')
    client = LLMClient(Settings(anthropic_api_key="k"), client=cast(Anthropic, mock))
    with pytest.raises(LLMError) as caught:
        client.structured(model="claude-sonnet-4-6", system="s", user="u", schema=_Out)
    assert not isinstance(caught.value, LLMTruncationError)


# --- OpenAI provider (§9.1 cross-model generation) ----------------------------------------

_DEFAULT_OUT = _Out(x=7)


def _openai_client(
    settings: Settings,
    *,
    parsed: _Out | None = _DEFAULT_OUT,
    refusal: str | None = None,
    prompt_tokens: int = 1000,
    completion_tokens: int = 500,
    error: Exception | None = None,
    cost: CostTracker | None = None,
    ceiling: float | None = None,
) -> OpenAIClient:
    """Build an OpenAIClient over a fake SDK client."""
    sdk = MagicMock()
    if error is not None:
        sdk.chat.completions.parse.side_effect = error
    else:
        message = MagicMock()
        message.parsed = parsed
        message.refusal = refusal
        completion = MagicMock()
        completion.choices = [MagicMock(message=message)]
        completion.usage = MagicMock(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        )
        sdk.chat.completions.parse.return_value = completion
    return OpenAIClient(settings, client=cast(OpenAI, sdk), cost=cost, cost_ceiling_usd=ceiling)


def _settings_with_openai() -> Settings:
    return Settings(openai_api_key="sk-test", anthropic_api_key="sk-ant")


def test_cost_tracker_prices_gpt_41() -> None:
    tracker = CostTracker()
    cost = tracker.record_tokens("gpt-4.1", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == pytest.approx(10.00)  # $2.00 input + $8.00 output


def test_record_tokens_and_record_agree_for_anthropic() -> None:
    """The Anthropic path delegates to record_tokens; the two must not drift."""
    via_usage = CostTracker()
    via_usage.record("claude-sonnet-4-6", _usage(1000, 500))
    via_tokens = CostTracker()
    via_tokens.record_tokens("claude-sonnet-4-6", input_tokens=1000, output_tokens=500)
    assert via_usage.total_usd == pytest.approx(via_tokens.total_usd)


def test_openai_missing_api_key_raises() -> None:
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        OpenAIClient(Settings(openai_api_key=None))


def test_openai_returns_parsed_output_and_records_cost() -> None:
    client = _openai_client(_settings_with_openai())
    out = client.structured(model="gpt-4.1", system="s", user="u", schema=_Out)

    assert out.x == 7
    # 1000 in @ $2/Mtok + 500 out @ $8/Mtok
    assert client.cost.total_usd == pytest.approx(0.002 + 0.004)
    assert client.cost.call_count == 1


def test_openai_unpriced_model_raises() -> None:
    client = _openai_client(_settings_with_openai())
    with pytest.raises(LLMError, match="No pricing configured"):
        client.structured(model="gpt-9-imaginary", system="s", user="u", schema=_Out)


def test_openai_ceiling_blocks_call_before_dispatch() -> None:
    client = _openai_client(_settings_with_openai(), ceiling=0.001)
    client.cost.total_usd = 0.002
    with pytest.raises(CostCeilingError):
        client.structured(model="gpt-4.1", system="s", user="u", schema=_Out)


def test_openai_truncation_raises_truncation_error() -> None:
    """OpenAI raises a typed length error; the Anthropic path has to sniff a pydantic one."""
    error = openai.LengthFinishReasonError(completion=MagicMock())
    client = _openai_client(_settings_with_openai(), error=error)
    with pytest.raises(LLMTruncationError, match="cut off"):
        client.structured(model="gpt-4.1", system="s", user="u", schema=_Out)


def test_openai_api_error_becomes_llm_error() -> None:
    client = _openai_client(
        _settings_with_openai(), error=openai.APIError("boom", MagicMock(), body=None)
    )
    with pytest.raises(LLMError, match="LLM call failed"):
        client.structured(model="gpt-4.1", system="s", user="u", schema=_Out)


def test_openai_refusal_becomes_llm_error() -> None:
    client = _openai_client(_settings_with_openai(), refusal="I cannot help with that")
    with pytest.raises(LLMError, match="refused"):
        client.structured(model="gpt-4.1", system="s", user="u", schema=_Out)


def test_openai_missing_parsed_output_raises() -> None:
    client = _openai_client(_settings_with_openai(), parsed=None)
    with pytest.raises(LLMError, match="no parsed output"):
        client.structured(model="gpt-4.1", system="s", user="u", schema=_Out)


def test_both_providers_can_share_one_cost_tracker() -> None:
    """One tracker across providers keeps a mixed run under a single ceiling."""
    shared = CostTracker()
    shared.record("claude-sonnet-4-6", _usage(1000, 0))  # $0.003
    client = _openai_client(_settings_with_openai(), cost=shared)
    client.structured(model="gpt-4.1", system="s", user="u", schema=_Out)

    assert shared.call_count == 2
    assert shared.total_usd == pytest.approx(0.003 + 0.002 + 0.004)
