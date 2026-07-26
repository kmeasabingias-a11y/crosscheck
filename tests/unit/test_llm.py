"""Unit tests for the LLM wrapper."""

from typing import cast
from unittest.mock import MagicMock

import pytest
from anthropic import Anthropic
from anthropic.types import Usage
from pydantic import BaseModel, ValidationError

from crosscheck.config import Settings
from crosscheck.llm import CostCeilingError, CostTracker, LLMClient, LLMError, LLMTruncationError


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
    client = LLMClient(Settings(anthropic_api_key="k"), client=cast(Anthropic, MagicMock()))
    with pytest.raises(LLMError):
        client.structured(model="gpt-4o", system="s", user="u", schema=_Out)


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
