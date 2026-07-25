"""Single cost-tracked wrapper around the LLM providers.

Every LLM call in CrossCheck goes through :class:`LLMClient` — there are no scattered
``client.messages.create`` calls elsewhere (spec v2 §11). The wrapper adds three things
on top of the raw SDK: structured output validated against a pydantic schema, running
cost tracking that feeds the audit cost ceiling, and uniform logging/error handling.

Phase 1 wires the Anthropic provider (Claude) for claim extraction and judging. The
OpenAI cross-model provider used by the eval harness (spec §9.1) is added in Phase 5 (D12).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TypeVar

import anthropic
from anthropic import Anthropic
from anthropic.types import Usage
from loguru import logger
from pydantic import BaseModel

from crosscheck.config import Settings

SchemaT = TypeVar("SchemaT", bound=BaseModel)

_CACHE_WRITE_MULTIPLIER = 1.25
_CACHE_READ_MULTIPLIER = 0.10


@dataclass(frozen=True)
class ModelPricing:
    """Per-million-token USD pricing for a model."""

    input_per_mtok: float
    output_per_mtok: float


# USD per 1M tokens, from the Anthropic pricing table (as of 2026-06).
# Cache writes bill at 1.25x the input rate, cache reads at 0.10x. Update here when
# prices change; an unpriced model is refused before it can be called.
MODEL_PRICING: dict[str, ModelPricing] = {
    "claude-opus-4-8": ModelPricing(5.00, 25.00),
    "claude-sonnet-4-6": ModelPricing(3.00, 15.00),
    "claude-haiku-4-5": ModelPricing(1.00, 5.00),
}


class LLMError(RuntimeError):
    """Raised when an LLM call fails or returns unusable output."""


class CostCeilingError(LLMError):
    """Raised when running audit spend has reached the configured ceiling."""


@dataclass
class CostTracker:
    """Accumulates token usage and USD spend across one audit's LLM calls."""

    total_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    call_count: int = 0

    def record(self, model: str, usage: Usage) -> float:
        """Add one call's usage to the totals; return that call's USD cost."""
        pricing = MODEL_PRICING[model]
        cache_write = usage.cache_creation_input_tokens or 0
        cache_read = usage.cache_read_input_tokens or 0
        cost = (
            usage.input_tokens * pricing.input_per_mtok
            + usage.output_tokens * pricing.output_per_mtok
            + cache_write * pricing.input_per_mtok * _CACHE_WRITE_MULTIPLIER
            + cache_read * pricing.input_per_mtok * _CACHE_READ_MULTIPLIER
        ) / 1_000_000
        self.total_usd += cost
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cache_write_tokens += cache_write
        self.cache_read_tokens += cache_read
        self.call_count += 1
        return cost


class LLMClient:
    """The single entry point for all LLM calls, with cost tracking and a ceiling.

    Construct one per audit. All calls go through :meth:`structured`, which validates the
    model's output against a pydantic schema. The client tracks running spend in
    :attr:`cost` and refuses to dispatch a new call once the ceiling is reached, raising
    :class:`CostCeilingError` so the orchestrator can finalize a partial report.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        client: Anthropic | None = None,
        cost_ceiling_usd: float | None = None,
    ) -> None:
        """Build from settings, or wrap an injected SDK client (for tests).

        Args:
            settings: Runtime configuration (API key, model tuning).
            client: An Anthropic SDK client to use directly; built from settings if None.
            cost_ceiling_usd: Hard spend cap for this audit; defaults to
                ``settings.max_audit_cost_usd``.

        Raises:
            LLMError: If no client is given and no Anthropic API key is configured.
        """
        if client is None:
            if not settings.anthropic_api_key:
                raise LLMError("ANTHROPIC_API_KEY is not set; add it to your .env.")
            client = Anthropic(
                api_key=settings.anthropic_api_key,
                max_retries=settings.llm_max_retries,
                timeout=settings.llm_timeout_seconds,
            )
        self._client = client
        self._settings = settings
        self._ceiling = (
            cost_ceiling_usd if cost_ceiling_usd is not None else settings.max_audit_cost_usd
        )
        self.cost = CostTracker()

    @property
    def cost_ceiling_usd(self) -> float:
        """The spend cap currently in force (temporarily lowered inside :meth:`budget`)."""
        return self._ceiling

    @contextmanager
    def budget(self, limit_usd: float) -> Iterator[None]:
        """Temporarily cap how much *more* this client may spend inside the block.

        The audit-wide ceiling is the client's own; this narrows it to the stricter of the
        two, so a single stage — in practice one document's claim extraction — cannot consume
        the whole audit budget (spec v2 §4's per-document cap). Inside the block, a call that
        would exceed the tightened cap raises :class:`CostCeilingError` exactly as it would at
        the audit ceiling; the caller tells the two apart by comparing spend against the audit
        ceiling it captured beforehand. The previous ceiling is always restored on exit.

        A non-positive ``limit_usd`` means "no extra cap" — the audit ceiling alone applies —
        so setting the per-document cap to 0 disables it rather than blocking every call.

        Args:
            limit_usd: Additional spend allowed inside the block, in USD.

        Yields:
            None; the tightened budget applies for the duration of the block.
        """
        previous = self._ceiling
        if limit_usd > 0:
            self._ceiling = min(previous, self.cost.total_usd + limit_usd)
        try:
            yield
        finally:
            self._ceiling = previous

    def structured(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[SchemaT],
        max_tokens: int | None = None,
    ) -> SchemaT:
        """Call the model and return its output validated against ``schema``.

        Args:
            model: The model ID (must be present in ``MODEL_PRICING``).
            system: The system prompt.
            user: The user message content.
            schema: A pydantic model the response is parsed into.
            max_tokens: Output-token cap; defaults to ``settings.llm_max_tokens``.

        Returns:
            An instance of ``schema`` built from the model's response.

        Raises:
            CostCeilingError: If the running spend has reached the ceiling.
            LLMError: If the model is unpriced, the call fails, or no output is returned.
        """
        if model not in MODEL_PRICING:
            raise LLMError(f"No pricing configured for model {model!r}; refusing to call it.")
        if self.cost.total_usd >= self._ceiling:
            raise CostCeilingError(
                f"Audit cost ceiling ${self._ceiling:.2f} reached "
                f"(spent ${self.cost.total_usd:.4f}); not dispatching further LLM calls."
            )
        try:
            response = self._client.messages.parse(
                model=model,
                max_tokens=max_tokens or self._settings.llm_max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
            )
        except anthropic.AnthropicError as exc:
            request_id = getattr(exc, "request_id", None)
            raise LLMError(f"LLM call failed (request_id={request_id}): {exc}") from exc

        call_cost = self.cost.record(model, response.usage)
        logger.debug(
            "llm call model={} in={} out={} cost=${:.4f} total=${:.4f}",
            model,
            response.usage.input_tokens,
            response.usage.output_tokens,
            call_cost,
            self.cost.total_usd,
        )
        if self.cost.total_usd >= self._ceiling:
            logger.warning(
                "cost ceiling ${:.2f} reached after {} call(s) (spent ${:.4f})",
                self._ceiling,
                self.cost.call_count,
                self.cost.total_usd,
            )
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError(f"Model {model} returned no parseable output ({response.stop_reason}).")
        return parsed
