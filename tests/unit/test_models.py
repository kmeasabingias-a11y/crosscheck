"""Unit tests for the pipeline schemas."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from crosscheck.models import Claim, Document, DocumentRef, Section, Verdict


def test_document_holds_sections() -> None:
    doc = Document(
        doc_id="d1",
        source_path=Path("a.pdf"),
        sections=[Section(section_id="s1", text="hello")],
    )
    assert doc.sections[0].section_id == "s1"


def test_verdict_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValidationError):
        Verdict(
            pair_id="p1",
            is_contradiction=True,
            confidence=1.5,
            rationale="r",
            evidence_a="a",
            evidence_b="b",
        )


def test_claim_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Claim(
            claim_id="c1",
            doc_id="d1",
            section_id="s1",
            text="t",
            evidence_quote="q",
            evidence_offset=(0, 1),
            subject="s",
            predicate="p",
            polarity="positive",
            bogus=1,  # type: ignore[call-arg]
        )


def _document() -> Document:
    return Document(
        doc_id="d1",
        source_path=Path("/corpus/08_information_security_policy.pdf"),
        title="Information Security Policy v5.2",
        sections=[
            Section(section_id="s1", heading="1. Purpose", text="body one", page_span=(1, 1)),
            Section(section_id="s2", heading="3. Passwords", text="body two", page_span=(2, 3)),
        ],
    )


def test_document_ref_keeps_citation_data_and_drops_section_text() -> None:
    ref = DocumentRef.from_document(_document())
    assert ref.doc_id == "d1"
    assert ref.title == "Information Security Policy v5.2"
    assert [section.heading for section in ref.sections] == ["1. Purpose", "3. Passwords"]
    assert ref.sections[1].page_span == (2, 3)
    # The whole point of the ref (D33): no source text travels with the audit result.
    assert "body one" not in ref.model_dump_json()
    assert "body two" not in ref.model_dump_json()


def test_document_ref_filename_is_the_citation_label() -> None:
    assert DocumentRef.from_document(_document()).filename == "08_information_security_policy.pdf"


def test_document_ref_resolves_a_section_and_returns_none_for_an_unknown_one() -> None:
    ref = DocumentRef.from_document(_document())
    found = ref.section("s2")
    assert found is not None and found.heading == "3. Passwords"
    assert ref.section("nope") is None
