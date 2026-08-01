"""Single cost-tracked wrapper around the LLM providers.

Every LLM call in CrossCheck goes through :class:`LLMClient` — there are no scattered
``client.messages.create`` calls elsewhere (spec v2 §11). The wrapper adds three things
on top of the raw SDK: structured output validated against a pydantic schema, running
cost tracking that feeds the audit cost ceiling, and uniform logging/error handling.

Two providers live here. :class:`LLMClient` wraps Anthropic (Claude) and runs the audit
pipeline — claim extraction and judging. :class:`OpenAIClient` wraps OpenAI and exists for one
purpose: generating the synthetic benchmark with a *different model family* than the judge, so
the eval is not partly measuring a model's ability to recognise its own output style (§9.1).
Both satisfy the :class:`StructuredLLM` protocol and share the same :class:`CostTracker`, so
spend is accounted the same way whichever provider a stage uses (D12, D37).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol, TypeVar

import anthropic
import openai
from anthropic import Anthropic
from anthropic.types import Usage
from loguru import logger
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from crosscheck.config import Settings

SchemaT = TypeVar("SchemaT", bound=BaseModel)

_CACHE_WRITE_MULTIPLIER = 1.25
_CACHE_READ_MULTIPLIER = 0.10


@dataclass(frozen=True)
class ModelPricing:
    """Per-million-token USD pricing for a model."""

    input_per_mtok: float
    output_per_mtok: float


# USD per 1M tokens. Anthropic rates as of 2026-06; OpenAI rates checked against the
# published pricing page on 2026-08-01. Anthropic cache writes bill at 1.25x the input rate
# and cache reads at 0.10x. Update here when prices change; an unpriced model is refused
# before it can be called, which is the point — a wrong number here silently corrupts every
# cost figure in the eval report.
MODEL_PRICING: dict[str, ModelPricing] = {
    # Anthropic — the audit pipeline (extraction, judging).
    "claude-opus-4-8": ModelPricing(5.00, 25.00),
    "claude-sonnet-4-6": ModelPricing(3.00, 15.00),
    "claude-haiku-4-5": ModelPricing(1.00, 5.00),
    # OpenAI — benchmark generation only (§9.1 cross-model requirement).
    "gpt-4.1": ModelPricing(2.00, 8.00),
    "gpt-4.1-mini": ModelPricing(0.40, 1.60),
    "gpt-4o": ModelPricing(2.50, 10.00),
}


class LLMError(RuntimeError):
    """Raised when an LLM call fails or returns unusable output."""


class CostCeilingError(LLMError):
    """Raised when running audit spend has reached the configured ceiling."""


class LLMTruncationError(LLMError):
    """Raised when structured output was cut off by the ``max_tokens`` cap.

    Distinct from a schema violation: the output is correct as far as it goes and simply
    stops mid-value, so a caller can recover by retrying with fewer items per call or a
    larger cap. A genuine schema violation would survive both, so the two get different
    types rather than a shared :class:`LLMError`.
    """


def _is_truncated(exc: ValidationError) -> bool:
    """True if a validation failure is output cut off mid-JSON rather than a bad schema.

    The Anthropic SDK validates the response text *inside* ``messages.parse``, so a
    response stopped by the ``max_tokens`` cap never reaches us as a response object whose
    ``stop_reason`` we could read — it arrives as a JSON syntax error. Truncation is
    specifically ``json_invalid`` with an "EOF while parsing" message; complete-but-invalid
    JSON reports "expected value", and a type or field error is not ``json_invalid`` at all.
    """
    return any(
        error.get("type") == "json_invalid" and "EOF while parsing" in str(error.get("msg", ""))
        for error in exc.errors()
    )


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
        """Add one Anthropic call's usage to the totals; return that call's USD cost."""
        return self.record_tokens(
            model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_write_tokens=usage.cache_creation_input_tokens or 0,
            cache_read_tokens=usage.cache_read_input_tokens or 0,
        )

    def record_tokens(
        self,
        model: str,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> float:
        """Add one call's token counts to the totals; return that call's USD cost.

        Provider-neutral, so a second SDK's usage object does not have to be translated into
        Anthropic's :class:`~anthropic.types.Usage` just to be priced.

        Args:
            model: Model id; must be present in :data:`MODEL_PRICING`.
            input_tokens: Prompt tokens billed at the full input rate.
            output_tokens: Completion tokens.
            cache_write_tokens: Tokens written to a prompt cache (billed at 1.25x input).
            cache_read_tokens: Tokens served from a prompt cache (billed at 0.10x input).

        Returns:
            The USD cost of this call.
        """
        pricing = MODEL_PRICING[model]
        cost = (
            input_tokens * pricing.input_per_mtok
            + output_tokens * pricing.output_per_mtok
            + cache_write_tokens * pricing.input_per_mtok * _CACHE_WRITE_MULTIPLIER
            + cache_read_tokens * pricing.input_per_mtok * _CACHE_READ_MULTIPLIER
        ) / 1_000_000
        self.total_usd += cost
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_write_tokens += cache_write_tokens
        self.cache_read_tokens += cache_read_tokens
        self.call_count += 1
        return cost


class StructuredLLM(Protocol):
    """What any provider wrapper must offer: schema-validated output and cost accounting.

    Stages depend on this rather than on a concrete client, so the benchmark generator can be
    pointed at a different provider than the judge (§9.1) without either knowing about the
    other.
    """

    cost: CostTracker

    def structured(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[SchemaT],
        max_tokens: int | None = None,
    ) -> SchemaT:
        """Call ``model`` and return its output validated against ``schema``."""
        ...


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
            LLMTruncationError: If the response was cut off by the ``max_tokens`` cap.
            LLMError: If the model is unpriced, the call fails, the response fails schema
                validation, or no output is returned.

        Note:
            A truncated call's tokens are not recorded against the cost tracker: the SDK
            raises before this method sees a response object, so its usage is unavailable.
            The spend is real but invisible, bounded by ``max_tokens`` per truncated call.
            Recording it exactly would mean replacing ``messages.parse`` with
            ``messages.create`` plus hand-rolled validation (see D32).
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
        except ValidationError as exc:
            cap = max_tokens or self._settings.llm_max_tokens
            if _is_truncated(exc):
                raise LLMTruncationError(
                    f"Model {model} output was cut off at the {cap}-token cap; "
                    "retry with fewer items per call or a larger cap."
                ) from exc
            raise LLMError(
                f"Model {model} returned output failing schema validation: {exc}"
            ) from exc

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


class OpenAIClient:
    """OpenAI wrapper for benchmark generation — the §9.1 cross-model provider.

    Deliberately *not* used by the audit pipeline. Its only job is to author the synthetic
    benchmark with a different model family than the judge, so a strong score is not partly
    the judge recognising its own house style. Satisfies :class:`StructuredLLM`, so it shares
    the cost tracker, the ceiling behaviour, and the error vocabulary with
    :class:`LLMClient`.

    ``temperature`` and ``seed`` default to values that make generation as reproducible as the
    API allows: §9.1 requires a benchmark that regenerates identically from a seed. Best-effort
    is the honest description — OpenAI documents ``seed`` as best-effort, not a guarantee —
    which is why the generated corpus and its gold labels are committed to the repo rather than
    regenerated on demand.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        client: OpenAI | None = None,
        cost: CostTracker | None = None,
        cost_ceiling_usd: float | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
    ) -> None:
        """Build from settings, or wrap an injected SDK client (for tests).

        Args:
            settings: Runtime configuration (API key, retry and timeout policy).
            client: An OpenAI SDK client to use directly; built from settings if None.
            cost: A tracker to share with another client; a fresh one is made if None.
            cost_ceiling_usd: Hard spend cap; defaults to ``settings.max_audit_cost_usd``.
            temperature: Sampling temperature; 0.0 for reproducible generation.
            seed: Best-effort determinism seed passed to the API.

        Raises:
            LLMError: If no client is given and no OpenAI API key is configured.
        """
        if client is None:
            if not settings.openai_api_key:
                raise LLMError("OPENAI_API_KEY is not set; add it to your .env.")
            client = OpenAI(
                api_key=settings.openai_api_key,
                max_retries=settings.llm_max_retries,
                timeout=settings.llm_timeout_seconds,
            )
        self._client = client
        self._settings = settings
        self._ceiling = (
            cost_ceiling_usd if cost_ceiling_usd is not None else settings.max_audit_cost_usd
        )
        self._temperature = temperature
        self._seed = seed
        self.cost = cost if cost is not None else CostTracker()

    @property
    def cost_ceiling_usd(self) -> float:
        """The spend cap currently in force."""
        return self._ceiling

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
            LLMTruncationError: If the response was cut off by the token cap.
            LLMError: If the model is unpriced, the call fails, the model refuses, or no
                parsed output is returned.

        Note:
            Cached input tokens are billed here at the **full** input rate rather than at
            OpenAI's cached discount. That overestimates spend slightly when prompt caching
            kicks in, which is the safe direction for a ceiling — it can stop an audit early,
            never late. Anthropic's cache rates are modelled exactly because that provider
            reports cache reads and writes as separate counters.
        """
        if model not in MODEL_PRICING:
            raise LLMError(f"No pricing configured for model {model!r}; refusing to call it.")
        if self.cost.total_usd >= self._ceiling:
            raise CostCeilingError(
                f"Cost ceiling ${self._ceiling:.2f} reached "
                f"(spent ${self.cost.total_usd:.4f}); not dispatching further LLM calls."
            )
        cap = max_tokens or self._settings.llm_max_tokens
        try:
            completion = self._client.chat.completions.parse(
                model=model,
                max_completion_tokens=cap,
                temperature=self._temperature,
                seed=self._seed,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=schema,
            )
        except openai.LengthFinishReasonError as exc:
            # The OpenAI SDK raises a typed error here, unlike the Anthropic path where
            # truncation surfaces as a pydantic ValidationError and has to be sniffed (D32).
            raise LLMTruncationError(
                f"Model {model} output was cut off at the {cap}-token cap; "
                "retry with fewer items per call or a larger cap."
            ) from exc
        except openai.OpenAIError as exc:
            raise LLMError(f"LLM call failed: {exc}") from exc

        choice = completion.choices[0]
        if choice.message.refusal:
            raise LLMError(f"Model {model} refused the request: {choice.message.refusal}")
        parsed = choice.message.parsed
        if parsed is None:
            raise LLMError(f"Model {model} returned no parsed output.")

        usage = completion.usage
        call_cost = (
            self.cost.record_tokens(
                model,
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
            )
            if usage is not None
            else 0.0
        )
        if usage is None:
            logger.warning("openai call model={} returned no usage; cost not recorded", model)
        logger.debug(
            "llm call model={} cost=${:.4f} total=${:.4f}",
            model,
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
        return parsed
