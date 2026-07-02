"""Application configuration for CrossCheck, loaded from environment variables.

A single :class:`Settings` object is the typed, validated source of truth for all
runtime configuration. Values come from the environment and an optional ``.env``
file (see ``.env.example`` for the template). Phase 0 covers app basics, the LLM
provider keys, and the mandatory cost ceiling (spec v2 §4). Later phases extend the
same panel with Qdrant, model-selection, and per-type NLI-threshold settings.
"""

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed, validated runtime configuration for CrossCheck.

    Fields are populated from environment variables. Project settings use the
    ``CROSSCHECK_`` prefix (e.g. ``CROSSCHECK_LOG_LEVEL``); the two provider API
    keys additionally accept their standard unprefixed names, so an existing
    ``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` in the shell works unchanged.
    """

    model_config = SettingsConfigDict(
        env_prefix="CROSSCHECK_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_by_name=True,
    )

    # --- App basics ---
    app_name: str = "CrossCheck"
    environment: str = "dev"
    log_level: str = "INFO"

    # --- LLM provider keys (used from Phase 1) ---
    # Read from the provider-standard names first (ANTHROPIC_API_KEY / OPENAI_API_KEY),
    # falling back to the CROSSCHECK_-prefixed variants. Default None so a missing key
    # never lives in code; the LLM wrapper validates presence when it actually calls out.
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "CROSSCHECK_ANTHROPIC_API_KEY"),
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "CROSSCHECK_OPENAI_API_KEY"),
    )

    # --- Cost ceiling (spec v2 §4 — mandatory circuit breaker) ---
    # Hard cap on total LLM spend per audit; when reached the orchestrator stops
    # dispatching new judge calls and finalizes a `partial` report.
    max_audit_cost_usd: float = Field(default=5.00, ge=0.0)
    # Per-document cap within a single audit.
    max_document_cost_usd: float = Field(default=0.50, ge=0.0)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton.

    Cached so the environment is read once and every caller shares one object.
    Tests can call ``get_settings.cache_clear()`` to force a re-read with overrides.
    """
    return Settings()
