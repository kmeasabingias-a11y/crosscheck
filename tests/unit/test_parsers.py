"""Unit tests for the document parsers."""

from pathlib import Path

import pytest
from docx import Document as DocxDocument

from crosscheck.ingestion.parsers import (
    UnsupportedFormatError,
    _strip_running_headers_footers,
    parse,
)


def test_txt_is_single_section(tmp_path: Path) -> None:
    p = tmp_path / "note.txt"
    p.write_text("Employees receive 20 PTO days.\nContractors do not.", encoding="utf-8")
    doc = parse(p)
    assert doc.metadata["format"] == "txt"
    assert doc.title == "note"
    assert len(doc.sections) == 1
    assert doc.sections[0].heading is None
    assert "20 PTO days" in doc.sections[0].text


def test_doc_id_is_content_addressed(tmp_path: Path) -> None:
    a = tmp_path / "a.txt"
    b = tmp_path / "b_different_name.txt"
    a.write_text("identical body text", encoding="utf-8")
    b.write_text("identical body text", encoding="utf-8")
    assert parse(a).doc_id == parse(b).doc_id  # same content -> same id, regardless of name
    c = tmp_path / "c.txt"
    c.write_text("different body text", encoding="utf-8")
    assert parse(c).doc_id != parse(a).doc_id


def test_markdown_splits_on_headings(tmp_path: Path) -> None:
    p = tmp_path / "policy.md"
    p.write_text(
        "Intro paragraph.\n\n# Leave Policy\nEmployees receive 20 PTO days.\n\n"
        "## Contractors\nContractors are not entitled to PTO.\n",
        encoding="utf-8",
    )
    doc = parse(p)
    assert doc.title == "Leave Policy"
    headings = [s.heading for s in doc.sections]
    assert headings == [None, "Leave Policy", "Contractors"]
    # Heading line is not duplicated inside the section body.
    leave = next(s for s in doc.sections if s.heading == "Leave Policy")
    assert "# Leave Policy" not in leave.text
    assert "20 PTO days" in leave.text


def test_markdown_without_headings_is_one_section(tmp_path: Path) -> None:
    p = tmp_path / "flat.md"
    p.write_text("Just a paragraph with no headings at all.", encoding="utf-8")
    doc = parse(p)
    assert len(doc.sections) == 1
    assert doc.title == "flat"


def test_docx_splits_on_heading_styles(tmp_path: Path) -> None:
    p = tmp_path / "handbook.docx"
    d = DocxDocument()
    d.add_heading("Overview", level=1)
    d.add_paragraph("Employees receive 20 PTO days.")
    d.add_heading("Exceptions", level=2)
    d.add_paragraph("Contractors are not entitled to PTO.")
    d.save(str(p))

    doc = parse(p)
    assert doc.title == "Overview"
    assert [s.heading for s in doc.sections] == ["Overview", "Exceptions"]
    assert "20 PTO days" in doc.sections[0].text
    assert "not entitled" in doc.sections[1].text


def test_unsupported_extension_raises(tmp_path: Path) -> None:
    p = tmp_path / "data.csv"
    p.write_text("a,b,c", encoding="utf-8")
    with pytest.raises(UnsupportedFormatError):
        parse(p)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        parse(tmp_path / "nope.md")


def test_strip_running_headers_and_page_numbers() -> None:
    pages = [
        "ACME CONFIDENTIAL\nBody of page one.\n1",
        "ACME CONFIDENTIAL\nBody of page two.\n2",
        "ACME CONFIDENTIAL\nBody of page three.\n3",
        "ACME CONFIDENTIAL\nBody of page four.\n4",
    ]
    cleaned = _strip_running_headers_footers(pages)
    joined = "\n".join(cleaned)
    assert "ACME CONFIDENTIAL" not in joined  # repeated header stripped
    assert not any(line.strip().isdigit() for line in joined.splitlines())  # page numbers gone
    assert "Body of page one." in cleaned[0]  # real content preserved


def test_strip_is_conservative_for_few_pages() -> None:
    pages = ["HEADER\nreal content\n1", "HEADER\nother content\n2"]
    cleaned = _strip_running_headers_footers(pages)
    # Too few pages to infer a running header, so HEADER stays; page numbers still go.
    assert cleaned[0].splitlines() == ["HEADER", "real content"]
