"""Application configuration for CrossCheck, loaded from environment variables.

A single :class:`Settings` object is the typed, validated source of truth for all
runtime configuration. Values come from the environment and an optional ``.env``
file (see ``.env.example`` for the template). Phase 0 covers app basics, the LLM
provider keys, and the mandatory cost ceiling (spec v2 §4); Phase 1 adds model
selection, claim-extraction tuning, and chunking. Later phases extend the same panel
with Qdrant and per-type NLI-threshold settings.
"""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from crosscheck.detection.taxonomy import ContradictionType


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

    # --- Models (Phase 1) ---
    # Judge and claim extraction both default to Claude Sonnet 4.6 (spec "Primary LLM").
    # Haiku 4.5 is the cheaper option to benchmark for high-volume extraction (see D12).
    judge_model: str = "claude-sonnet-4-6"
    extraction_model: str = "claude-sonnet-4-6"

    # --- LLM call tuning (Phase 1) ---
    llm_max_tokens: int = 2048
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2

    # --- Claim extraction (Phase 1) ---
    # Chunks per extraction call, to amortize the system prompt (spec §7.1: batch 3-5).
    extraction_batch_size: int = Field(default=4, ge=1)
    # Output-token budget per chunk in a batch; the call's max_tokens is this times the
    # batch size (spec §7.1 budgets ~1500 output tokens per chunk).
    extraction_max_output_tokens_per_chunk: int = Field(default=1500, ge=1)

    # --- Chunking (Phase 1) ---
    # Sentence-aware chunks target 200-400 tokens with ~50-token overlap (spec §7.1).
    # Only the upper bound and overlap are knobs; the 200 lower bound is a soft target
    # that greedy packing realizes (short sections / trailing remainders may be smaller).
    chunk_max_tokens: int = Field(default=400, ge=1)
    chunk_overlap_tokens: int = Field(default=50, ge=0)

    # --- Qdrant storage (Phase 2, spec §7.2) ---
    # As with the provider keys (D9), also accept the standard QDRANT_URL / QDRANT_API_KEY
    # names so a Qdrant Cloud deployment's own env vars work unchanged.
    qdrant_url: str = Field(
        default="http://localhost:6333",
        validation_alias=AliasChoices("CROSSCHECK_QDRANT_URL", "QDRANT_URL"),
    )
    qdrant_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CROSSCHECK_QDRANT_API_KEY", "QDRANT_API_KEY"),
    )
    qdrant_collection: str = "claims"
    qdrant_timeout_seconds: float = Field(default=30.0, ge=0.0)

    # --- Embeddings (Phase 2, spec §5/§7.2) ---
    # Dense: bge-large-en-v1.5 (1024-d) via sentence-transformers, cosine. Sparse: BM25 via
    # fastembed, stored as Qdrant sparse vectors so hybrid retrieval runs in-engine (§7.3).
    # dense_embedding_model / sparse_model are consumed by the embedder (next Phase-2 file);
    # dense_vector_size sizes the collection's dense vector here.
    dense_embedding_model: str = "BAAI/bge-large-en-v1.5"
    dense_vector_size: int = Field(default=1024, ge=1)
    sparse_model: str = "Qdrant/bm25"
    # Instruction prepended to the *query* side only (bge's recommended retrieval setup):
    # the stored claim is the passage, the claim we search with is the query. Set to "" for
    # symmetric (s2s) embedding — a knob to revisit when tuning retrieval (spec §9.3).
    dense_query_instruction: str = "Represent this sentence for searching relevant passages: "

    # --- Retrieval (Phase 2, spec §7.3) ---
    # Candidate generation retrieves the top-K cross-document claims per claim (the reranker
    # then narrows to a smaller set). Hybrid BM25+dense is the default strategy; "dense" is the
    # dense-only ablation baseline (§9.3), swappable without touching pair generation.
    retrieval_top_k: int = Field(default=25, ge=1)
    retrieval_strategy: Literal["hybrid", "dense"] = "hybrid"
    # --- Reranking (Phase 2, spec §7.3, §5) ---
    # A cross-encoder reads both claims of a candidate pair together and rescoring them; the
    # top-K survive to the detection stages. bge-reranker-v2-m3 is spec-prescribed (§5) and runs
    # on the torch already pulled in for the dense embedder (D22), so it adds no new dependency.
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_top_k: int = Field(default=10, ge=1)

    # --- NLI filter (Phase 3, spec §7.4) ---
    # A 3-way NLI cross-encoder pre-screens candidate pairs before the (expensive) LLM judge: a
    # pair is kept if "contradiction" is the top label OR its contradiction probability clears a
    # threshold. Thresholds are PER contradiction type (§7.4); the type is usually unknown before
    # the judge, so the filter then uses the most permissive (lowest) threshold. `nli_thresholds`
    # stays empty until Phase-6 calibration fills it — until then every pair uses the default.
    nli_model: str = "cross-encoder/nli-deberta-v3-base"
    nli_default_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    nli_thresholds: dict[ContradictionType, float] = Field(default_factory=dict)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton.

    Cached so the environment is read once and every caller shares one object.
    Tests can call ``get_settings.cache_clear()`` to force a re-read with overrides.
    """
    return Settings()
