"""Core pydantic schemas that flow between CrossCheck's pipeline stages.

Every object crossing a module boundary is one of these models (spec v2 §11: no bare
dicts in public APIs). Ingestion produces :class:`Document` / :class:`Section` and then
:class:`Chunk`; extraction produces :class:`Claim`; retrieval produces :class:`Pair`;
the judge produces :class:`Verdict`. All models forbid unknown fields, so schema drift —
a renamed LLM output key, say — fails loudly instead of being silently dropped.
"""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from crosscheck.detection.taxonomy import ContradictionType


class CrossCheckModel(BaseModel):
    """Shared base for all CrossCheck schemas.

    Sets ``extra="forbid"`` so constructing a model from a dict (e.g. parsed LLM
    JSON) with an unexpected key raises rather than silently discarding it.
    """

    model_config = ConfigDict(extra="forbid")


class Section(CrossCheckModel):
    """One heading-delimited section of a parsed document."""

    section_id: str
    heading: str | None = None
    text: str
    page_span: tuple[int, int] | None = None


class Document(CrossCheckModel):
    """A parsed source document as an ordered list of sections."""

    doc_id: str
    source_path: Path
    title: str | None = None
    sections: list[Section] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Chunk(CrossCheckModel):
    """A window of section text — the unit of claim extraction.

    Produced by the chunker (sentence-aware, 200-400 tokens with overlap) and consumed
    by the claim extractor. Carries its position (``char_span`` within the section) and
    document metadata so every claim can be traced back to its source.
    """

    chunk_id: str = Field(description="Deterministic id from doc_id + section_id + char_span.")
    doc_id: str
    section_id: str
    text: str
    char_span: tuple[int, int] = Field(description="[start, end) char offsets within the section.")
    token_count: int | None = None


class Quantitative(CrossCheckModel):
    """The numeric core of a quantitative claim (e.g. "refunds within 30 days")."""

    number: float
    unit: str | None = None
    operator: str | None = None  # e.g. "=", "<=", ">=", "<", ">", "~"


class Claim(CrossCheckModel):
    """An atomic, decontextualized assertion extracted from a chunk."""

    claim_id: str = Field(description="Deterministic hash of doc_id + chunk + offset.")
    doc_id: str
    section_id: str
    text: str = Field(description="Normalized, decontextualized claim that stands alone.")
    evidence_quote: str = Field(description="Verbatim span from the source chunk.")
    evidence_offset: tuple[int, int] = Field(description="[start, end) char offsets of the quote.")
    subject: str
    predicate: str
    conditions: list[str] = Field(default_factory=list)
    polarity: Literal["positive", "negative"]
    quantitative: Quantitative | None = None


class Pair(CrossCheckModel):
    """A candidate pair of cross-document claims moving through detection.

    Carries only the two claim ids plus the scores each stage attaches; the full
    claims live in the repository and are resolved by id when needed. Scores are
    optional because they're filled in progressively (retrieval → rerank → NLI).
    """

    pair_id: str = Field(description="Order-independent hash of the two claim ids.")
    claim_a_id: str
    claim_b_id: str
    retrieval_score: float | None = None
    rerank_score: float | None = None
    nli_contradiction_prob: float | None = Field(default=None, ge=0.0, le=1.0)


class Verdict(CrossCheckModel):
    """The judge's final ruling on one candidate pair."""

    pair_id: str
    is_contradiction: bool
    contradiction_type: ContradictionType | None = None
    confidence: float = Field(ge=0.0, le=1.0, description="Judge confidence, 0.0-1.0.")
    rationale: str = Field(description="Chain-of-thought explanation for the ruling.")
    evidence_a: str = Field(description="Verbatim quote from claim A (substring-validated).")
    evidence_b: str = Field(description="Verbatim quote from claim B (substring-validated).")
    resolution_hint: str | None = None
