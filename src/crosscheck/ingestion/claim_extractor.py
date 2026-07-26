"""Claim extraction — the heart of ingestion.

Turns chunks into atomic, decontextualized :class:`~crosscheck.models.Claim` objects
by prompting the LLM (spec v2 §7.1). Three engineering ideas earn their place here:

1. **Batching** — several chunks per LLM call, to amortize the system prompt.
2. **Caching** — each chunk's raw extraction is cached by a hash of its text, so a
    rerun (or a resumed audit, §4) never re-spends tokens on text it has already seen.
3. **Code-side finalization** — the model returns a *reduced* claim (text, evidence,
    subject, …); this module computes the trust-sensitive fields itself. The evidence
    quote is located in the chunk (claims whose quote is not a verbatim substring are
    dropped and counted), and the offset, claim id, and document metadata are derived
    here rather than trusted from the model — the same defense the judge uses (§7.4).

It also runs the decontextualization check (§7.1): claims that open with a dangling
pronoun are counted so ``decontextualization_failure_rate`` is observable, since bad
decontextualization silently poisons every downstream stage.
"""

import json
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from loguru import logger
from pydantic import Field

from crosscheck.config import Settings
from crosscheck.ids import claim_id, content_hash
from crosscheck.llm import LLMClient, LLMTruncationError
from crosscheck.models import Chunk, Claim, CrossCheckModel, Quantitative
from crosscheck.prompts import load_prompt


class ExtractedClaim(CrossCheckModel):
    """A claim exactly as the LLM returns it, before code fills in ids and offsets.

    The extractor asks only for these fields; ``claim_id``, ``evidence_offset``,
    ``doc_id`` and ``section_id`` are computed in code from the source chunk so the
    model cannot fabricate them.
    """

    chunk_id: str
    text: str
    evidence_quote: str
    subject: str
    predicate: str
    conditions: list[str] = Field(default_factory=list)
    polarity: Literal["positive", "negative"]
    quantitative: Quantitative | None = None


class _ExtractionBatch(CrossCheckModel):
    """Structured-output wrapper: what one batched extraction call returns."""

    claims: list[ExtractedClaim] = Field(default_factory=list)


class ExtractionResult(CrossCheckModel):
    """The claims from one extraction pass, plus observability counters."""

    claims: list[Claim] = Field(default_factory=list)
    chunk_count: int = 0
    cache_hits: int = 0
    llm_call_count: int = 0
    rejected_evidence_count: int = Field(
        default=0, description="Claims dropped because the quote was not verbatim in the chunk."
    )
    decontextualization_flags: int = Field(
        default=0, description="Claims that opened with a dangling reference."
    )
    truncated_chunk_count: int = Field(
        default=0,
        description="Chunks skipped because the model's output stayed truncated after retries.",
    )

    @property
    def decontextualization_failure_rate(self) -> float:
        """Fraction of extracted claims flagged as not standing alone (0.0 if none)."""
        return self.decontextualization_flags / len(self.claims) if self.claims else 0.0


# First-word tokens that signal a claim did not stand on its own — a bare pronoun or
# demonstrative with no antecedent. Deliberately conservative to avoid false positives
# (existential "there"/"here" are intentionally excluded).
_DANGLING_OPENERS = frozenset(
    {
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "they",
        "them",
        "their",
        "he",
        "she",
        "him",
        "her",
        "his",
        "such",
    }
)
_FIRST_WORD_RE = re.compile(r"[A-Za-z']+")


def is_decontextualized(text: str) -> bool:
    """Return False when a claim opens with a dangling pronoun or demonstrative.

    A cheap heuristic for the decontextualization-failure metric (spec v2 §7.1): a
    well-formed claim names its subject, so one that begins with a bare "it"/"this"/
    "they" almost certainly carries an unresolved reference. Non-alphabetic openers
    (numbers, quotes) are treated as fine.

    Args:
        text: The claim's decontextualized text.

    Returns:
        True if the claim appears to stand alone; False if it looks unresolved.
    """
    match = _FIRST_WORD_RE.match(text.lstrip())
    if match is None:
        return True
    return match.group(0).lower() not in _DANGLING_OPENERS


class ClaimCache(Protocol):
    """A cache of raw extracted claims, keyed by a hash of the chunk text (spec §7.1)."""

    def get(self, key: str) -> list[ExtractedClaim] | None:
        """Return the cached claims for this key, or None on a miss."""
        ...

    def put(self, key: str, claims: list[ExtractedClaim]) -> None:
        """Store the extracted claims for this key."""
        ...


class InMemoryClaimCache:
    """A process-local claim cache (the default; used by tests and single runs)."""

    def __init__(self) -> None:
        self._store: dict[str, list[ExtractedClaim]] = {}

    def get(self, key: str) -> list[ExtractedClaim] | None:
        """Return the cached claims for this key, or None on a miss."""
        return self._store.get(key)

    def put(self, key: str, claims: list[ExtractedClaim]) -> None:
        """Store the extracted claims for this key."""
        self._store[key] = claims


class DiskClaimCache:
    """A persistent claim cache: one JSON file per chunk-text hash.

    Survives across processes, so a re-run — or a resumed audit (spec v2 §4) — skips
    chunks it has already extracted instead of re-spending tokens.
    """

    def __init__(self, cache_dir: Path) -> None:
        """Create (if needed) and use ``cache_dir`` to store per-chunk extractions."""
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> list[ExtractedClaim] | None:
        """Return the cached claims for this key, or None on a miss."""
        path = self._dir / f"{key}.json"
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [ExtractedClaim.model_validate(item) for item in raw]

    def put(self, key: str, claims: list[ExtractedClaim]) -> None:
        """Store the extracted claims for this key."""
        payload = [claim.model_dump(mode="json") for claim in claims]
        (self._dir / f"{key}.json").write_text(json.dumps(payload), encoding="utf-8")


def _batched(items: Sequence[Chunk], size: int) -> Iterator[list[Chunk]]:
    """Yield successive ``size``-length batches from ``items``."""
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


def _locate_quote(text: str, quote: str) -> tuple[int, int] | None:
    """Find ``quote`` in ``text``, tolerating whitespace differences.

    Tries an exact substring match first. On a miss, falls back to a whitespace-flexible
    match (each run of whitespace in the quote matches any run of whitespace in the text),
    because the model occasionally copies a genuinely verbatim span but normalizes the
    source's line-wrap newlines to spaces — an exact check would wrongly reject it. Only
    word content must match, so a true hallucination (a changed or invented word) still
    fails. Returns the [start, end) span of the actual substring in ``text`` — so the
    stored quote stays verbatim to the source — or None if the words are not present.
    """
    if not quote.strip():
        return None
    exact = text.find(quote)
    if exact >= 0:
        return (exact, exact + len(quote))
    pattern = re.compile(r"\s+".join(re.escape(word) for word in quote.split()))
    match = pattern.search(text)
    return match.span() if match is not None else None


def _finalize_claim(raw: ExtractedClaim, chunk: Chunk) -> Claim | None:
    """Build a full :class:`Claim` from a raw extraction, or None if the quote is bad.

    The evidence quote must resolve to a span of the chunk (exactly, or up to whitespace
    differences); that span gives the offset and the verbatim source quote, from which the
    claim id is derived.
    """
    span = _locate_quote(chunk.text, raw.evidence_quote)
    if span is None:
        logger.warning(
            "extractor: evidence quote not found in chunk {} — dropping claim: {!r}",
            chunk.chunk_id,
            raw.evidence_quote,
        )
        return None
    quote = chunk.text[span[0] : span[1]]  # the real source span, verbatim (real whitespace)
    return Claim(
        claim_id=claim_id(chunk.doc_id, chunk.chunk_id, span),
        doc_id=chunk.doc_id,
        section_id=chunk.section_id,
        text=raw.text,
        evidence_quote=quote,
        evidence_offset=span,
        subject=raw.subject,
        predicate=raw.predicate,
        conditions=raw.conditions,
        polarity=raw.polarity,
        quantitative=raw.quantitative,
    )


# How far the per-chunk output cap may be raised when a single chunk still overflows it.
_MAX_CAP_MULTIPLIER = 2


@dataclass
class _BatchOutcome:
    """What one extraction batch produced, after any truncation retries."""

    grouped: dict[str, list[ExtractedClaim]] = field(default_factory=dict)
    llm_calls: int = 0
    failed_chunk_ids: set[str] = field(default_factory=set)


class ClaimExtractor:
    """Extracts atomic, decontextualized claims from chunks via the LLM.

    Construct one per audit. Prompts are loaded once at construction; the cache and
    batch size are injectable so tests run with no network and a process-local cache.
    """

    def __init__(
        self,
        llm: LLMClient,
        settings: Settings,
        *,
        cache: ClaimCache | None = None,
        batch_size: int | None = None,
    ) -> None:
        """Build an extractor.

        Args:
            llm: The shared cost-tracked LLM wrapper.
            settings: Runtime configuration (extraction model, batch size, token budget).
            cache: Where to cache raw extractions; a process-local cache if None.
            batch_size: Chunks per LLM call; defaults to ``settings.extraction_batch_size``.
        """
        self._llm = llm
        self._settings = settings
        self._cache: ClaimCache = cache if cache is not None else InMemoryClaimCache()
        resolved = batch_size if batch_size is not None else settings.extraction_batch_size
        self._batch_size = max(1, resolved)
        self._system_prompt = load_prompt("claim_extraction_system")
        self._user_prompt = load_prompt("claim_extraction_user")

    def extract(self, chunks: Sequence[Chunk]) -> ExtractionResult:
        """Extract claims from chunks, serving from cache and batching LLM calls.

        Args:
            chunks: The chunks to extract from, in corpus order.

        Returns:
            The finalized claims plus observability counters. Claims whose evidence
            quote is not a verbatim substring of their chunk are dropped and counted.

        Raises:
            CostCeilingError: Propagated from the LLM wrapper if the audit budget is
                reached mid-extraction; chunks already extracted stay in the cache so a
                resumed run continues from where this one stopped.
        """
        raw_by_chunk: dict[str, list[ExtractedClaim]] = {}
        pending: list[Chunk] = []
        cache_hits = 0
        for chunk in chunks:
            cached = self._cache.get(content_hash(chunk.text))
            if cached is None:
                pending.append(chunk)
            else:
                raw_by_chunk[chunk.chunk_id] = cached
                cache_hits += 1

        llm_calls = 0
        truncated = 0
        for batch in _batched(pending, self._batch_size):
            outcome = self._extract_with_retry(batch)
            llm_calls += outcome.llm_calls
            truncated += len(outcome.failed_chunk_ids)
            for chunk in batch:
                # A chunk the model could not finish is deliberately left *uncached*.
                # Caching an empty result would make the loss permanent: every resumed run
                # would serve zero claims for it from cache and never retry.
                if chunk.chunk_id in outcome.failed_chunk_ids:
                    continue
                claims = outcome.grouped.get(chunk.chunk_id, [])
                raw_by_chunk[chunk.chunk_id] = claims
                self._cache.put(content_hash(chunk.text), claims)

        return self._finalize(
            chunks, raw_by_chunk, cache_hits=cache_hits, llm_calls=llm_calls, truncated=truncated
        )

    def _extract_with_retry(self, batch: list[Chunk], *, cap_multiplier: int = 1) -> _BatchOutcome:
        """Extract one batch, splitting it and retrying when the model's output is truncated.

        A response cut off by the token cap is recoverable: the same chunks fit if fewer of
        them share a call, or if the cap is raised. So an overflowing batch is halved and
        each half retried, which degrades one claim-dense chunk to its own call rather than
        failing every chunk beside it. At a single chunk the cap is doubled once; if that
        still overflows, the chunk is reported as failed and left uncached so a later run
        retries it. One pathological chunk can therefore never kill an audit.

        Args:
            batch: The chunks to extract in one call.
            cap_multiplier: Multiplier applied to the configured per-chunk output cap.

        Returns:
            The grouped claims, the number of LLM calls actually made, and the ids of any
            chunks that could not be extracted.
        """
        try:
            grouped = self._extract_batch(batch, cap_multiplier=cap_multiplier)
        except LLMTruncationError as exc:
            if len(batch) > 1:
                middle = len(batch) // 2
                logger.warning(
                    "extractor: output truncated for a batch of {}; splitting and retrying ({})",
                    len(batch),
                    exc,
                )
                left = self._extract_with_retry(batch[:middle])
                right = self._extract_with_retry(batch[middle:])
                return _BatchOutcome(
                    grouped={**left.grouped, **right.grouped},
                    llm_calls=1 + left.llm_calls + right.llm_calls,
                    failed_chunk_ids=left.failed_chunk_ids | right.failed_chunk_ids,
                )
            if cap_multiplier < _MAX_CAP_MULTIPLIER:
                logger.warning(
                    "extractor: output truncated for chunk {}; retrying at {}x the cap",
                    batch[0].chunk_id,
                    cap_multiplier * 2,
                )
                retried = self._extract_with_retry(batch, cap_multiplier=cap_multiplier * 2)
                return _BatchOutcome(
                    grouped=retried.grouped,
                    llm_calls=1 + retried.llm_calls,
                    failed_chunk_ids=retried.failed_chunk_ids,
                )
            logger.warning(
                "extractor: chunk {} still truncated at {}x the cap — skipping it. Its claims "
                "are lost for this run; it stays uncached so a later run retries it. ({})",
                batch[0].chunk_id,
                cap_multiplier,
                exc,
            )
            return _BatchOutcome(llm_calls=1, failed_chunk_ids={batch[0].chunk_id})
        return _BatchOutcome(grouped=grouped, llm_calls=1)

    def _extract_batch(
        self, batch: list[Chunk], *, cap_multiplier: int = 1
    ) -> dict[str, list[ExtractedClaim]]:
        """Call the LLM on one batch and group returned claims by their source chunk id."""
        rendered = self._user_prompt.render(chunks=self._serialize(batch))
        result = self._llm.structured(
            model=self._settings.extraction_model,
            system=self._system_prompt.text,
            user=rendered,
            schema=_ExtractionBatch,
            max_tokens=(
                len(batch) * self._settings.extraction_max_output_tokens_per_chunk * cap_multiplier
            ),
        )
        valid_ids = {chunk.chunk_id for chunk in batch}
        grouped: dict[str, list[ExtractedClaim]] = {cid: [] for cid in valid_ids}
        for claim in result.claims:
            if claim.chunk_id not in valid_ids:
                logger.warning(
                    "extractor: dropping claim tagged with unknown chunk_id {!r}", claim.chunk_id
                )
                continue
            grouped[claim.chunk_id].append(claim)
        return grouped

    def _finalize(
        self,
        chunks: Sequence[Chunk],
        raw_by_chunk: dict[str, list[ExtractedClaim]],
        *,
        cache_hits: int,
        llm_calls: int,
        truncated: int = 0,
    ) -> ExtractionResult:
        """Turn raw extractions into validated Claims and tally observability counters."""
        claims: list[Claim] = []
        rejected = 0
        flags = 0
        for chunk in chunks:
            for raw in raw_by_chunk.get(chunk.chunk_id, []):
                claim = _finalize_claim(raw, chunk)
                if claim is None:
                    rejected += 1
                    continue
                if not is_decontextualized(claim.text):
                    flags += 1
                    logger.debug(
                        "extractor: claim {} may be unresolved: {!r}", claim.claim_id, claim.text
                    )
                claims.append(claim)

        result = ExtractionResult(
            claims=claims,
            chunk_count=len(chunks),
            cache_hits=cache_hits,
            llm_call_count=llm_calls,
            rejected_evidence_count=rejected,
            decontextualization_flags=flags,
            truncated_chunk_count=truncated,
        )
        logger.info(
            "extracted {} claims from {} chunks ({} cache hits, {} llm calls, "
            "{} rejected quotes, {} decontext flags, {} truncated chunks)",
            len(claims),
            result.chunk_count,
            cache_hits,
            llm_calls,
            rejected,
            flags,
            truncated,
        )
        return result

    @staticmethod
    def _serialize(batch: Sequence[Chunk]) -> str:
        """Render a batch of chunks into the ``{{chunks}}`` block of the user prompt."""
        return "\n\n".join(f"[chunk_id: {chunk.chunk_id}]\n{chunk.text}" for chunk in batch)
