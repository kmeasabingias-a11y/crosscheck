"""Unit tests for the sentence-aware chunker."""

from itertools import pairwise
from pathlib import Path

from crosscheck.config import Settings
from crosscheck.ids import section_id
from crosscheck.ingestion.chunking import (
    approximate_token_count,
    chunk_document,
    chunk_section,
)
from crosscheck.models import Document, Section

# Ten short sentences, ~4 words each.
_TEN = " ".join(f"Sentence number {i} has a few words here." for i in range(10))


def _section(text: str) -> Section:
    return Section(section_id=section_id("docX", 0), heading=None, text=text)


def test_approximate_token_count_scales_with_words() -> None:
    assert approximate_token_count("") == 0
    assert approximate_token_count("one two three") >= 3


def test_single_sentence_is_one_chunk() -> None:
    section = _section("A lone short sentence.")
    chunks = chunk_section(section, "docX", max_tokens=400, overlap_tokens=50)
    assert len(chunks) == 1
    assert chunks[0].char_span == (0, len(section.text))
    assert chunks[0].token_count is not None and chunks[0].token_count > 0


def test_empty_section_yields_no_chunks() -> None:
    assert chunk_section(_section("   \n  "), "docX", max_tokens=400, overlap_tokens=50) == []


def test_char_span_slices_section_text_exactly() -> None:
    section = _section(_TEN)
    chunks = chunk_section(section, "docX", max_tokens=12, overlap_tokens=4)
    assert len(chunks) > 1  # small max forces several chunks
    for chunk in chunks:
        start, end = chunk.char_span
        assert chunk.text == section.text[start:end]


def test_chunks_respect_max_tokens() -> None:
    section = _section(_TEN)
    chunks = chunk_section(section, "docX", max_tokens=12, overlap_tokens=4)
    # No sentence here is bigger than max, so every chunk must stay within it.
    assert all(c.token_count is not None and c.token_count <= 12 for c in chunks)


def test_chunks_progress_with_no_gaps() -> None:
    # Sentences (~11 tokens) larger than max force single-sentence, contiguous chunks:
    # they must always progress and never leave a gap, even when overlap can't apply.
    section = _section(_TEN)
    chunks = chunk_section(section, "docX", max_tokens=12, overlap_tokens=4)
    for prev, nxt in pairwise(chunks):
        assert nxt.char_span[0] > prev.char_span[0]  # forward progress
        assert nxt.char_span[0] <= prev.char_span[1]  # no gap between chunks
        assert nxt.char_span[1] > prev.char_span[1]  # covers new ground (no subset chunk)


def test_overlap_creates_shared_span() -> None:
    # max=30 holds two ~11-token sentences; overlap=8 backs up one, so every boundary
    # genuinely overlaps.
    section = _section(_TEN)
    chunks = chunk_section(section, "docX", max_tokens=30, overlap_tokens=8)
    assert len(chunks) > 1
    for prev, nxt in pairwise(chunks):
        assert nxt.char_span[0] < prev.char_span[1]  # strict overlap


def test_zero_overlap_is_contiguous_partition() -> None:
    section = _section(_TEN)
    chunks = chunk_section(section, "docX", max_tokens=30, overlap_tokens=0)
    for prev, nxt in pairwise(chunks):
        assert nxt.char_span[0] == prev.char_span[1]  # abut exactly, no overlap, no gap


def test_chunk_ids_unique_and_deterministic() -> None:
    section = _section(_TEN)
    a = chunk_section(section, "docX", max_tokens=12, overlap_tokens=4)
    b = chunk_section(section, "docX", max_tokens=12, overlap_tokens=4)
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]  # deterministic
    assert len({c.chunk_id for c in a}) == len(a)  # unique


def test_oversized_single_sentence_becomes_one_chunk() -> None:
    long_sentence = "word " * 200 + "end."
    section = _section(long_sentence)
    chunks = chunk_section(section, "docX", max_tokens=10, overlap_tokens=2)
    assert len(chunks) == 1
    assert chunks[0].token_count is not None and chunks[0].token_count > 10


def test_chunk_document_flattens_sections() -> None:
    s0 = Section(
        section_id=section_id("docX", 0),
        text="First section sentence one. First section sentence two.",
    )
    s1 = Section(section_id=section_id("docX", 1), text=_TEN)
    doc = Document(doc_id="docX", source_path=Path("/tmp/x.md"), sections=[s0, s1])
    chunks = chunk_document(doc, settings=Settings(chunk_max_tokens=12, chunk_overlap_tokens=4))
    assert len(chunks) >= 2
    assert {c.section_id for c in chunks} == {s0.section_id, s1.section_id}
    assert len({c.chunk_id for c in chunks}) == len(chunks)  # ids unique across sections
