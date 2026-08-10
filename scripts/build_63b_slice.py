"""Cut the SP 800-63B real-corpus slice for the second §9.4 sanity check.

The first §9.4 attempt ran on SP 800-53 Rev 4 vs Rev 5 and found nothing — not because the system
missed anything, but because a control *catalogue* has nothing to find. 800-53 states requirements
as ``[Assignment: organization-defined frequency]`` placeholders that the adopting organization
fills in, so there were 48 placeholders and **zero concrete requirement values** across both
documents, and four negations in 4,100 words. NUMERICAL_MISMATCH, DIRECT_NEGATION,
OBLIGATION_REVERSAL and SCOPE_JURISDICTION are all structurally unreachable in such a corpus (D46).

SP 800-63B is the corrective. It is *normative*: it states concrete values and hard prohibitions —
minimum password lengths, a required maximum of at least 64 characters, explicit ``SHALL NOT``
requirements about composition rules and periodic rotation — and Rev 4 changed several of them.
That is a corpus in which the five v1 contradiction types are actually reachable.

**Why these subsections.** The first three under "Requirements by Authenticator Type", contiguous,
from both revisions:

===========================  =====================
Rev 3                        Rev 4
===========================  =====================
5.1.1 Memorized Secrets      Passwords
5.1.2 Look-Up Secrets        Look-Up Secrets
5.1.3 Out-of-Band Devices    Out-of-Band Devices
===========================  =====================

Contiguity is the point, exactly as it was for AU-1..AU-5. I already know that the
memorized-secrets section is where the headline drift lives (the 8-character minimum, the
"``SHALL`` permit at least 64 characters" rule, the reversal on periodic rotation), and selecting
*only* that section because I know the answers would make the resulting hit rate meaningless.
Taking the first three subsections is a rule that does not depend on knowing the answers.

Note that Rev 4 renames "Memorized Secrets" to "Passwords". A rename is a terminology change, not
a contradiction, and how the judge treats it is itself worth watching: the single finding on the
800-53 run was a false positive of exactly this kind, where NIST's ``[Withdrawn: Incorporated into
AU-2]`` marker was read as deletion when it meant relocation.

Sizing, from the measured rate of ~34.4 claims per 1,000 words and ~$0.0061 per claim: 6,329 words
across both documents, so roughly 218 claims and about $1.34 with a Haiku judge, or near $2.09 if
this corpus's much higher negation density pushes more pairs past the NLI filter than 800-53 did.

NIST publications are works of the US federal government and are not subject to domestic copyright,
so the slice is committed to the repo rather than fetched at run time. The HTML sources live
outside the repo in ``Crosscheck_Seed_Corpora/nist_63b/`` and came from::

    curl -o rev3.html https://pages.nist.gov/800-63-3/sp800-63b.html
    curl -o rev4.html https://pages.nist.gov/800-63-4/sp800-63b.html

Run from anywhere::

    uv run python scripts/build_63b_slice.py
"""

import html
import re
from pathlib import Path

_SEED_DIR = Path("/mnt/d/My_project/Crosscheck_Seed_Corpora/nist_63b")
_OUT_DIR = Path(__file__).resolve().parent.parent / "benchmarks" / "realcorpus" / "nist_63b"
_CORPUS_DIR = _OUT_DIR / "corpus"

#: One entry per revision: source file, output name, document title, and the heading range to keep.
#: The range is (start_title, end_title, heading_level) and is *exclusive* of the end heading, which
#: is the first subsection after the ones we want. Matching is on the heading text, so the level has
#: to be given explicitly: Rev 3 nests these at h4 while Rev 4 nests them at h3.
_SOURCES = (
    (
        "rev3.html",
        "rev3_5_1_1_to_5_1_3.md",
        "NIST SP 800-63B Rev 3 - Authenticator and Verifier Requirements (5.1.1-5.1.3)",
        ("Memorized Secrets", "Single-Factor OTP Device", 4),
    ),
    (
        "rev4.html",
        "rev4_5_1_1_to_5_1_3.md",
        "NIST SP 800-63B Rev 4 - Authenticator and Verifier Requirements (Passwords-Out-of-Band)",
        ("Passwords", "Single-Factor OTP", 3),
    ),
)

_HEADING_RE = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.DOTALL | re.IGNORECASE)

#: Block elements carrying requirement text. ``td`` is in here for a reason that cost me a
#: near-miss: Rev 3 lays out each subsection's introductory paragraph as a two-cell table (an icon
#: beside the text) while Rev 4 uses a plain ``<p>``. Matching only ``p`` therefore dropped Rev 3's
#: intros and kept Rev 4's — an *asymmetric* loss between the two documents being compared, which
#: is the one kind of corpus damage that can manufacture findings ("Rev 4 defines this, Rev 3 does
#: not") rather than merely lose them.
_BLOCK_RE = re.compile(r"<(h[1-6]|p|li|td)[^>]*>(.*?)</\1>", re.DOTALL | re.IGNORECASE)

#: Guards against double-counting when a matched block nests another (a ``td`` wrapping ``p``
#: tags would otherwise emit the text once for the cell and again for each paragraph).
_NESTED_BLOCK_RE = re.compile(r"<(?:p|li|h[1-6])[^>]*>", re.IGNORECASE)


def _plain(fragment: str) -> str:
    """Strip tags and entities from an HTML fragment, collapsing whitespace.

    The ``header-link`` anchors NIST appends to every heading carry no text of their own, so
    dropping tags is enough to remove them; the ``<i>`` icon inside leaves nothing behind.
    """
    text = re.sub(r"<[^>]+>", "", fragment)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _slice_html(source_html: str, start_title: str, end_title: str, level: int) -> str:
    """Return the HTML between two headings of the same level, end-exclusive.

    Args:
        source_html: The full page.
        start_title: Heading text the slice starts at (matched as a suffix).
        end_title: Heading text the slice stops before (matched as a suffix).
        level: The ``<hN>`` level both headings sit at.

    Returns:
        The raw HTML of the slice, starting at the opening ``<hN>`` of ``start_title``.

    Raises:
        ValueError: If either heading is missing, which would silently change the corpus size.
    """
    start = end = None
    for match in _HEADING_RE.finditer(source_html):
        if int(match.group(1)) != level:
            continue
        title = _plain(match.group(2))
        if start is None and title.endswith(start_title):
            start = match.start()
        elif start is not None and title.endswith(end_title):
            end = match.start()
            break
    if start is None:
        raise ValueError(f"no h{level} heading ending in {start_title!r}")
    if end is None:
        raise ValueError(f"no h{level} heading ending in {end_title!r} after {start_title!r}")
    return source_html[start:end]


def _to_markdown(fragment: str, base_level: int) -> str:
    """Convert a NIST HTML fragment to Markdown, keeping headings, paragraphs and bullets.

    Only block elements that carry requirement text are kept. Everything else — navigation,
    figures, the anchor icons — is dropped, because a claim extracted from a table of contents is
    noise that costs real money to judge.

    Args:
        fragment: The HTML slice.
        base_level: The source heading level that should become a Markdown ``##``.

    Returns:
        Markdown text.
    """
    blocks: list[str] = []
    for match in _BLOCK_RE.finditer(fragment):
        tag = match.group(1).lower()
        inner = match.group(2)
        # A layout cell that wraps real block elements is a container, not content: skip it and
        # let the nested matches supply the text once each.
        if tag == "td" and _NESTED_BLOCK_RE.search(inner):
            continue
        text = _plain(inner)
        if not text:
            continue
        if tag.startswith("h"):
            # Map the source level onto Markdown so the slice's own top heading becomes `##` and
            # its children nest under it. The parser splits sections on headings, so this is what
            # decides where one section ends and the next begins.
            depth = max(2, int(tag[1]) - base_level + 2)
            blocks.append(f"{'#' * depth} {text}")
        elif tag == "li":
            blocks.append(f"- {text}")
        else:
            blocks.append(text)
    return "\n\n".join(blocks)


def slice_document(source: Path, destination: Path, title: str, span: tuple[str, str, int]) -> int:
    """Write one revision's slice to ``destination`` as Markdown.

    Args:
        source: The downloaded NIST HTML page.
        destination: File to write.
        title: Document title for the Markdown H1.
        span: ``(start_title, end_title, heading_level)`` selecting the range to keep.

    Returns:
        The number of words written.
    """
    start_title, end_title, level = span
    page = source.read_text(encoding="utf-8", errors="replace")
    body = _to_markdown(_slice_html(page, start_title, end_title, level), level)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
    return len(body.split())


def main() -> None:
    """Build both slices and print what they will cost to audit."""
    total_words = 0
    for source_name, out_name, title, span in _SOURCES:
        words = slice_document(_SEED_DIR / source_name, _CORPUS_DIR / out_name, title, span)
        total_words += words
        print(f"wrote {out_name}: {words} words")

    # The measured rate from the completed 800-53 AU run: 145 claims from 4,216 words at
    # $0.8895 total, with rerank_top_k capping judge calls at 1.5 per claim (so cost is linear
    # in claims, not quadratic). Printed here so the bill is visible before the audit is run --
    # under-sizing a corpus is what made the hand-written run go partial.
    claims = total_words / 1000 * 34.4
    print(f"total {total_words} words across {len(_SOURCES)} document(s)")
    print(f"projected: ~{claims:.0f} claims, ~{claims * 1.5:.0f} judge calls")
    print(
        f"estimated: ${total_words / 1000 * 0.211:.2f} (Haiku judge), "
        f"${total_words / 1000 * 0.33:.2f} if NLI survival doubles"
    )


if __name__ == "__main__":
    main()
