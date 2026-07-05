"""Sentence-aware chunking — turning sections into extractable windows.

The parser yields :class:`~crosscheck.models.Section` objects that can be any size;
this module slices each into :class:`~crosscheck.models.Chunk` windows of a bounded
token count, aligned to sentence boundaries, with a little overlap so a claim that
straddles a boundary is not lost (spec v2 §7.1). Chunks are the unit the claim
extractor consumes, so this is what connects parse -> chunk -> extract.

Three design choices shape this file (see DECISIONS.md D17):

1. **pysbd for sentence splitting** — pure-python and download-free (unlike nltk's
    punkt data), and it returns per-sentence character offsets, which ``char_span``
    and ``chunk_id`` require.
2. **An injectable, offline token counter** — the default approximates subword tokens
    with the ~0.75-words-per-token rule of thumb, so unit tests need no model download;
    a precise tokenizer (bge, Phase 2) can be injected without touching the algorithm.
3. **A guarded overlap** — the next chunk starts a few sentences early for context, but
    never so early that it merely reproduces the current chunk. Consecutive chunks are
    therefore always contiguous-or-overlapping, always progressing, never a subset.
"""

import math
from collections.abc import Callable

import pysbd
from loguru import logger

from crosscheck.config import Settings
from crosscheck.ids import chunk_id
from crosscheck.models import Chunk, Document, Section

TokenCounter = Callable[[str], int]

_WORDS_PER_TOKEN = 0.75  # OpenAI rule of thumb: ~1 subword token per 0.75 English words.

# pysbd is pure-python and deterministic; char_span=True yields per-sentence [start, end)
# offsets, and clean=False preserves the text verbatim so those offsets stay valid.
_SEGMENTER = pysbd.Segmenter(language="en", clean=False, char_span=True)


def approximate_token_count(text: str) -> int:
    """Estimate subword-token count without loading a tokenizer.

    Uses the ~0.75-words-per-token rule of thumb, so it is deterministic and needs no
    model download — unit tests stay offline. A precise tokenizer (e.g. the bge
    tokenizer) can be injected as ``count_tokens`` for real runs.

    Args:
        text: The text to size.

    Returns:
        An approximate subword-token count (0 for empty/whitespace text).
    """
    words = len(text.split())
    return max(words, math.ceil(words / _WORDS_PER_TOKEN))


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """Return the [start, end) character spans of each sentence in ``text``."""
    return [(segment.start, segment.end) for segment in _SEGMENTER.segment(text)]


def chunk_section(
    section: Section,
    doc_id: str,
    *,
    max_tokens: int,
    overlap_tokens: int,
    count_tokens: TokenCounter = approximate_token_count,
) -> list[Chunk]:
    """Split one section into overlapping, sentence-aligned chunks.

    Sentences are packed greedily until adding the next would exceed ``max_tokens``;
    each subsequent chunk starts a few sentences early so consecutive chunks share about
    ``overlap_tokens`` of context. Chunk boundaries never cut a sentence, so a lone
    sentence longer than ``max_tokens`` becomes an oversized single-sentence chunk
    (logged). Offsets are relative to the section text.

    Args:
        section: The section to chunk.
        doc_id: The document id, threaded into each chunk and its id.
        max_tokens: Upper bound on a chunk's token count (soft for a lone long sentence).
        overlap_tokens: Approximate token overlap between consecutive chunks.
        count_tokens: How to count tokens; the offline approximation by default.

    Returns:
        The section's chunks in order (empty if the section has no sentences).
    """
    text = section.text
    spans = _sentence_spans(text)
    if not spans:
        return []
    sentence_tokens = [count_tokens(text[start:end]) for start, end in spans]

    chunks: list[Chunk] = []
    n = len(spans)
    i = 0
    while i < n:
        total = 0
        j = i
        while j < n:
            tokens = sentence_tokens[j]
            if total > 0 and total + tokens > max_tokens:
                break
            total += tokens
            j += 1

        char_span = (spans[i][0], spans[j - 1][1])
        chunks.append(
            Chunk(
                chunk_id=chunk_id(doc_id, section.section_id, char_span),
                doc_id=doc_id,
                section_id=section.section_id,
                text=text[char_span[0] : char_span[1]],
                char_span=char_span,
                token_count=total,
            )
        )
        if total > max_tokens:
            logger.warning(
                "chunker: one sentence exceeds max_tokens ({} > {}) in section {}",
                total,
                max_tokens,
                section.section_id,
            )
        if j >= n:
            break

        # Start the next chunk a few sentences early to create ~overlap_tokens of
        # overlap. Two guards keep it honest: never back up past i + 1 (forward
        # progress), and never back up so far that sentence j — the first sentence not
        # yet emitted — no longer fits under max_tokens, which would just reproduce this
        # chunk. When a lone large sentence blocks any overlap, chunks stay contiguous.
        overlap = 0
        next_i = j
        while (
            next_i > i + 1
            and overlap < overlap_tokens
            and overlap + sentence_tokens[next_i - 1] + sentence_tokens[j] <= max_tokens
        ):
            next_i -= 1
            overlap += sentence_tokens[next_i]
        i = next_i

    return chunks


def chunk_document(
    document: Document,
    *,
    settings: Settings,
    count_tokens: TokenCounter = approximate_token_count,
) -> list[Chunk]:
    """Chunk every section of a document, in order.

    Args:
        document: The parsed document.
        settings: Supplies ``chunk_max_tokens`` and ``chunk_overlap_tokens``.
        count_tokens: How to count tokens; the offline approximation by default.

    Returns:
        All chunks across all sections, flattened in document order.
    """
    chunks: list[Chunk] = []
    for section in document.sections:
        chunks.extend(
            chunk_section(
                section,
                document.doc_id,
                max_tokens=settings.chunk_max_tokens,
                overlap_tokens=settings.chunk_overlap_tokens,
                count_tokens=count_tokens,
            )
        )
    logger.info(
        "chunked doc {} into {} chunk(s) across {} section(s)",
        document.doc_id,
        len(chunks),
        len(document.sections),
    )
    return chunks
