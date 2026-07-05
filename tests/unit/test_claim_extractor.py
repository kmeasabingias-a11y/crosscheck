"""Unit tests for the claim extractor (LLM mocked; no network)."""

from types import SimpleNamespace
from typing import Literal, cast
from unittest.mock import MagicMock

from anthropic import Anthropic
from anthropic.types import Usage

from crosscheck.config import Settings
from crosscheck.ids import claim_id
from crosscheck.ingestion.claim_extractor import (
    ClaimExtractor,
    ExtractedClaim,
    InMemoryClaimCache,
    _ExtractionBatch,
    is_decontextualized,
)
from crosscheck.llm import LLMClient
from crosscheck.models import Chunk


def _usage() -> Usage:
    return Usage(
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )


def _response(batch: _ExtractionBatch) -> SimpleNamespace:
    return SimpleNamespace(usage=_usage(), parsed_output=batch, stop_reason="end_turn")


def _extractor(
    responses: list[SimpleNamespace],
    *,
    cache: InMemoryClaimCache | None = None,
    batch_size: int | None = None,
) -> tuple[ClaimExtractor, MagicMock]:
    mock = MagicMock()
    mock.messages.parse.side_effect = responses
    settings = Settings(anthropic_api_key="k")
    llm = LLMClient(settings, client=cast(Anthropic, mock))
    extractor = ClaimExtractor(llm, settings, cache=cache, batch_size=batch_size)
    return extractor, mock


def _chunk(text: str, chunk_id_: str = "c1", doc_id: str = "doc1", section_id: str = "s1") -> Chunk:
    return Chunk(
        chunk_id=chunk_id_,
        doc_id=doc_id,
        section_id=section_id,
        text=text,
        char_span=(0, len(text)),
    )


def _raw(
    chunk: Chunk,
    *,
    text: str,
    quote: str,
    polarity: Literal["positive", "negative"] = "positive",
) -> ExtractedClaim:
    return ExtractedClaim(
        chunk_id=chunk.chunk_id,
        text=text,
        evidence_quote=quote,
        subject="subject",
        predicate="predicate",
        conditions=[],
        polarity=polarity,
        quantitative=None,
    )


def test_extracts_and_finalizes() -> None:
    chunk = _chunk("Vendors must carry liability insurance.")
    quote = "must carry liability insurance"
    raw = _raw(chunk, text="Vendors must carry liability insurance.", quote=quote)
    extractor, mock = _extractor([_response(_ExtractionBatch(claims=[raw]))])

    result = extractor.extract([chunk])

    assert mock.messages.parse.call_count == 1
    assert len(result.claims) == 1
    claim = result.claims[0]
    start = chunk.text.find(quote)
    assert claim.evidence_offset == (start, start + len(quote))
    assert claim.claim_id == claim_id(chunk.doc_id, chunk.chunk_id, claim.evidence_offset)
    assert claim.doc_id == "doc1"
    assert claim.section_id == "s1"
    assert result.rejected_evidence_count == 0


def test_rejects_non_verbatim_quote() -> None:
    chunk = _chunk("Refunds are issued within 30 days.")
    raw = _raw(chunk, text="Refunds are issued within 30 days.", quote="within sixty days")
    extractor, _ = _extractor([_response(_ExtractionBatch(claims=[raw]))])

    result = extractor.extract([chunk])

    assert result.claims == []
    assert result.rejected_evidence_count == 1


def test_cache_prevents_second_call() -> None:
    chunk = _chunk("Vendors must carry insurance.")
    raw = _raw(chunk, text="Vendors must carry insurance.", quote="Vendors must carry insurance")
    cache = InMemoryClaimCache()
    extractor, mock = _extractor([_response(_ExtractionBatch(claims=[raw]))], cache=cache)

    first = extractor.extract([chunk])
    second = extractor.extract([chunk])

    assert mock.messages.parse.call_count == 1  # second run served entirely from cache
    assert first.cache_hits == 0
    assert second.cache_hits == 1
    assert len(second.claims) == 1


def test_batches_chunks() -> None:
    chunks = [_chunk(f"Fact number {i} is asserted here.", chunk_id_=f"c{i}") for i in range(5)]
    responses = [_response(_ExtractionBatch(claims=[])) for _ in range(3)]  # 5 chunks / size 2 -> 3
    extractor, mock = _extractor(responses, batch_size=2)

    result = extractor.extract(chunks)

    assert mock.messages.parse.call_count == 3
    assert result.chunk_count == 5
    assert result.claims == []


def test_decontextualization_flag_counts_but_keeps() -> None:
    chunk = _chunk("It is required for all vendors.")
    raw = _raw(
        chunk, text="It is required for all vendors.", quote="It is required for all vendors"
    )
    extractor, _ = _extractor([_response(_ExtractionBatch(claims=[raw]))])

    result = extractor.extract([chunk])

    assert len(result.claims) == 1  # flagged claims are kept, not dropped
    assert result.decontextualization_flags == 1
    assert result.decontextualization_failure_rate == 1.0


def test_unknown_chunk_id_dropped() -> None:
    chunk = _chunk("Vendors must carry insurance.")
    raw = ExtractedClaim(
        chunk_id="does-not-belong",
        text="Vendors must carry insurance.",
        evidence_quote="Vendors must carry insurance",
        subject="vendors",
        predicate="must carry insurance",
        conditions=[],
        polarity="positive",
        quantitative=None,
    )
    extractor, _ = _extractor([_response(_ExtractionBatch(claims=[raw]))])

    result = extractor.extract([chunk])

    assert result.claims == []


def test_empty_input_makes_no_calls() -> None:
    extractor, mock = _extractor([])
    result = extractor.extract([])
    assert result.claims == []
    assert result.chunk_count == 0
    assert mock.messages.parse.call_count == 0
    assert result.decontextualization_failure_rate == 0.0


def test_is_decontextualized_heuristic() -> None:
    assert is_decontextualized("Vendors must carry insurance.")
    assert is_decontextualized("30 days is the refund window.")
    assert not is_decontextualized("It is required.")
    assert not is_decontextualized("This applies to EU vendors.")
    assert not is_decontextualized("  They must comply.")


def test_keeps_quote_with_normalized_whitespace() -> None:
    # The model copies a real span but normalizes the source's line-wrap newline to a
    # space; the claim must be kept and anchored to the true source span (D20).
    chunk = _chunk("Vendor contracts within\nthe EU follow Irish law.")
    raw = _raw(
        chunk,
        text="Vendor contracts within the EU follow Irish law.",
        quote="Vendor contracts within the EU follow Irish law.",
    )
    extractor, _ = _extractor([_response(_ExtractionBatch(claims=[raw]))])

    result = extractor.extract([chunk])

    assert result.rejected_evidence_count == 0
    assert len(result.claims) == 1
    claim = result.claims[0]
    start, end = claim.evidence_offset
    assert claim.evidence_quote == chunk.text[start:end]  # stored as the real source span
    assert "\n" in claim.evidence_quote  # keeps the source newline, not the model's space
