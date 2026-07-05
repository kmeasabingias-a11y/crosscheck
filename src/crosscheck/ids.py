"""Deterministic, content-addressed identifiers for pipeline objects.

Ids are short stable hashes of the fields that define an object, so reruns produce
identical ids and stage outputs can be cached and resumed (spec v2 §4 idempotency,
§7.1 claim cache). Each id is a hex digest of a canonical, separator-joined string,
tagged by a ``kind`` so different id types can never collide on the same parts.
"""

import hashlib

_DIGEST_BYTES = 8  # 64-bit digest -> 16 hex chars; ample against corpus-scale collisions
_SEP = "\x1f"  # ASCII unit separator: will not occur in normal text fields


def _digest(kind: str, *parts: str) -> str:
    """Return a stable hex digest of ``parts``, namespaced by ``kind``."""
    payload = _SEP.join((kind, *parts))
    return hashlib.blake2b(payload.encode("utf-8"), digest_size=_DIGEST_BYTES).hexdigest()


def content_hash(text: str) -> str:
    """Hash a chunk's text for the extraction cache key (spec v2 §7.1).

    Args:
        text: The chunk text.

    Returns:
        A stable 16-character hex digest of the text.
    """
    return _digest("content", text)


def doc_id(text: str) -> str:
    """Deterministic id for a document from its full normalized text (spec v2 §4).

    Content-addressed, so re-ingesting the same file yields the same id (idempotent
    resume) and byte-identical duplicates collapse to one document rather than being
    reported as contradicting themselves.

    Args:
        text: The document's full concatenated section text.

    Returns:
        A stable 16-character hex id.
    """
    return _digest("doc", text)


def section_id(doc_id: str, ordinal: int) -> str:
    """Deterministic id for a section from its document id and position.

    Position-based (not heading-based) because headings can repeat, be missing, or
    change wording; the ordinal is stable for a given parse of a given document.

    Args:
        doc_id: The section's document id.
        ordinal: The section's zero-based index within the document.

    Returns:
        A stable 16-character hex id.
    """
    return _digest("section", doc_id, str(ordinal))


def chunk_id(doc_id: str, section_id: str, char_span: tuple[int, int]) -> str:
    """Deterministic id for a chunk from its position in the corpus.

    Args:
        doc_id: The chunk's document id.
        section_id: The chunk's section id.
        char_span: The chunk's [start, end) character offsets within the section.

    Returns:
        A stable 16-character hex id.
    """
    return _digest("chunk", doc_id, section_id, str(char_span[0]), str(char_span[1]))


def claim_id(doc_id: str, chunk_id: str, evidence_offset: tuple[int, int]) -> str:
    """Deterministic id for a claim (spec §7.1: hash of doc_id + chunk + offset).

    Args:
        doc_id: The claim's document id.
        chunk_id: The id of the chunk the claim came from.
        evidence_offset: The [start, end) offsets of the evidence quote in the chunk.

    Returns:
        A stable 16-character hex id.
    """
    return _digest("claim", doc_id, chunk_id, str(evidence_offset[0]), str(evidence_offset[1]))
