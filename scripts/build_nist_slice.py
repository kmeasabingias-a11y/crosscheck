"""Cut the NIST real-corpus slice used for the §9.4 sanity check.

§9.4 asks for one real, public, potentially-conflicting corpus — "an older and newer version of
the same regulation (NIST SP 800-53 Rev 4 vs. Rev 5)" — with the top-20 reported contradictions
inspected by hand and a hit rate reported. This script produces that corpus.

**Why a slice rather than the whole publication.** SP 800-53 is 400+ pages. The Access Control
family alone parses to 146 chunks and would cost roughly eight dollars to audit; the full Audit and
Accountability family, about $3.60. Neither fits a budget, and neither is necessary: the deliverable
is a hit rate over the top-20 findings, not precision and recall over a labelled set, so what
matters is that the corpus is real and genuinely contains version drift — not that it is exhaustive.

**Why these controls.** AU-1 through AU-5, contiguous, from both revisions. Contiguity is the point:
picking the controls where I already knew Rev 5 diverges would make the hit rate meaningless. The
first five controls are simply the first five.

The drift in this range is real and not manufactured. Rev 5 renames AU-2 from "Audit Events" to
"Event Logging" and AU-4 from "Audit Storage Capacity" to "Audit Log Storage Capacity", rewrites
AU-5's failure-response requirements, and restructures AU-1 around organization-, mission- and
system-level policy. Whether those are *contradictions* or merely *refinements* is exactly the
judgement the system is being tested on, and it is the reason precision here should be expected to
land below either labelled benchmark.

NIST publications are works of the US federal government and are not subject to domestic copyright,
so the slice is committed to the repo rather than being fetched at run time.

Run from anywhere::

    uv run python scripts/build_nist_slice.py
"""

from pathlib import Path

from crosscheck.ingestion.parsers import parse

_SEED_DIR = Path("/mnt/d/My_project/Crosscheck_Seed_Corpora/nist")
_OUT_DIR = Path(__file__).resolve().parent.parent / "benchmarks" / "realcorpus" / "nist_au"
_CORPUS_DIR = _OUT_DIR / "corpus"

#: The contiguous control range to keep. Matched against the *first whitespace token* of a heading,
#: never with startswith: "AU-1" is a prefix of AU-10 through AU-16, so a prefix match would
#: silently pull in two thirds of the family and quadruple the bill.
_CONTROLS = ("AU-1", "AU-2", "AU-3", "AU-4", "AU-5")

_SOURCES = (
    ("rev4_au_audit_and_accountability.md", "rev4_au_1_to_5.md"),
    ("rev5_au_audit_and_accountability.md", "rev5_au_1_to_5.md"),
)


def _control_id(heading: str | None) -> str:
    """The control identifier a section heading starts with, or an empty string."""
    return heading.split()[0] if heading and heading.split() else ""


def slice_document(source: Path, destination: Path) -> tuple[int, int]:
    """Write the selected controls of ``source`` to ``destination`` as Markdown.

    Args:
        source: A parsed-friendly NIST family document.
        destination: File to write.

    Returns:
        ``(sections_kept, words_kept)``.

    Raises:
        ValueError: If a requested control is missing, which would silently shrink the corpus.
    """
    document = parse(source)
    kept = [s for s in document.sections if _control_id(s.heading) in _CONTROLS]
    found = {_control_id(s.heading) for s in kept}
    missing = [control for control in _CONTROLS if control not in found]
    if missing:
        raise ValueError(f"{source.name} has no section(s) for {missing}")

    title = document.title or source.stem
    body = "\n\n".join(f"## {section.heading}\n\n{section.text.strip()}" for section in kept)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
    return len(kept), sum(len(section.text.split()) for section in kept)


def main() -> None:
    """Build the slice and print what it will cost to audit."""
    total_words = 0
    for source_name, out_name in _SOURCES:
        sections, words = slice_document(_SEED_DIR / source_name, _CORPUS_DIR / out_name)
        total_words += words
        print(f"wrote {out_name}: {sections} control(s), {words} words")
    print(f"total {total_words} words across {len(_SOURCES)} document(s)")


if __name__ == "__main__":
    main()
