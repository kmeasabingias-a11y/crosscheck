"""Unit tests for the deterministic id helpers."""

from crosscheck.ids import chunk_id, claim_id, content_hash, doc_id, section_id


def test_ids_are_deterministic_and_short() -> None:
    a = content_hash("hello world")
    b = content_hash("hello world")
    assert a == b
    assert len(a) == 16


def test_content_hash_distinguishes_text() -> None:
    assert content_hash("a") != content_hash("b")


def test_chunk_id_depends_on_position() -> None:
    base = chunk_id("doc1", "sec1", (0, 100))
    assert base == chunk_id("doc1", "sec1", (0, 100))
    assert base != chunk_id("doc1", "sec1", (0, 101))
    assert base != chunk_id("doc2", "sec1", (0, 100))


def test_claim_id_depends_on_offset_and_doc() -> None:
    base = claim_id("doc1", "chunkA", (5, 20))
    assert base == claim_id("doc1", "chunkA", (5, 20))
    assert base != claim_id("doc1", "chunkA", (5, 21))
    assert base != claim_id("doc1", "chunkB", (5, 20))


def test_id_kinds_do_not_collide() -> None:
    # Same leading part, different id kinds -> different digests.
    assert content_hash("x") != claim_id("x", "", (0, 0))


def test_doc_id_is_content_addressed() -> None:
    assert doc_id("same text") == doc_id("same text")
    assert doc_id("a") != doc_id("b")


def test_section_id_depends_on_document_and_position() -> None:
    base = section_id("docA", 0)
    assert base == section_id("docA", 0)
    assert base != section_id("docA", 1)
    assert base != section_id("docB", 0)
