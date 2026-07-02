"""Unit tests for the pipeline schemas."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from crosscheck.models import Claim, Document, Section, Verdict


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
