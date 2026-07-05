"""End-to-end ingestion integration test: parse -> chunk -> extract.

Runs the real ingestion path over a small fixture corpus with real Anthropic calls
(spec v2 §12). Marked ``integration`` and skipped unless ANTHROPIC_API_KEY is set. The
Phase 1 milestone (a 10-doc corpus -> >=200 well-formed claims) is reached by pointing
``CROSSCHECK_TEST_CORPUS`` at that corpus and raising ``CROSSCHECK_TEST_MIN_CLAIMS``.
"""

import os
from pathlib import Path

import pytest

from crosscheck.config import get_settings
from crosscheck.ingestion.chunking import chunk_document
from crosscheck.ingestion.claim_extractor import ClaimExtractor
from crosscheck.ingestion.parsers import parse
from crosscheck.llm import LLMClient
from crosscheck.models import Chunk, Claim

pytestmark = pytest.mark.integration

_DEFAULT_CORPUS = Path(__file__).parent.parent / "fixtures" / "corpus"
_SUPPORTED = {".pdf", ".docx", ".md", ".markdown", ".txt", ".text"}


def _iter_corpus(root: Path) -> list[Path]:
    """Return the supported document files under ``root``, sorted."""
    return sorted(p for p in root.rglob("*") if p.suffix.lower() in _SUPPORTED)


def _assert_well_formed(claim: Claim, section_text: dict[str, str]) -> None:
    """Assert one extracted claim satisfies the pipeline's invariants."""
    assert claim.claim_id and claim.doc_id and claim.section_id
    assert claim.text.strip()
    assert claim.polarity in {"positive", "negative"}
    start, end = claim.evidence_offset
    assert 0 <= start < end
    assert end - start == len(claim.evidence_quote)
    # The evidence quote is grounded verbatim in its source section.
    assert claim.section_id in section_text
    assert claim.evidence_quote in section_text[claim.section_id]
    if claim.quantitative is not None:
        assert claim.quantitative.operator in {None, "=", "<", "<=", ">", ">=", "~"}


def test_ingestion_pipeline_end_to_end() -> None:
    settings = get_settings()
    if not settings.anthropic_api_key:
        pytest.skip("ANTHROPIC_API_KEY not set; skipping live ingestion integration test.")

    corpus = Path(os.environ.get("CROSSCHECK_TEST_CORPUS", str(_DEFAULT_CORPUS)))
    min_claims = int(os.environ.get("CROSSCHECK_TEST_MIN_CLAIMS", "6"))

    files = _iter_corpus(corpus)
    assert files, f"no supported documents found under {corpus}"

    documents = [parse(path) for path in files]
    section_text = {
        section.section_id: section.text for document in documents for section in document.sections
    }

    chunks: list[Chunk] = []
    for document in documents:
        chunks.extend(chunk_document(document, settings=settings))
    assert chunks, "chunking produced no chunks"

    extractor = ClaimExtractor(LLMClient(settings), settings)
    result = extractor.extract(chunks)

    for claim in result.claims:
        _assert_well_formed(claim, section_text)

    assert len({claim.claim_id for claim in result.claims}) == len(result.claims)
    assert len(result.claims) >= min_claims, (
        f"expected >= {min_claims} claims from {len(files)} document(s), got {len(result.claims)}"
    )
