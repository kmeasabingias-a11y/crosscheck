"""Verbatim-quote matching, tolerant of the things models normalise (D20, D40).

Three stages need to answer the same question — *is this quote really in that source text, and
where?* The extractor validates a claim's ``evidence_quote`` against its chunk, the judge
validates a verdict's evidence against the claims it was shown, and the report locates the
judge's quote inside the passage so it can be highlighted. The rule lived in three places until
this module; keeping one copy matters because a drift between them would make a quote acceptable
to one stage and a hallucination to another.

**What "verbatim" has to tolerate.** A model copying a span faithfully will still normalise its
typography. Two kinds show up constantly:

* **Whitespace** — a source's hard line wrap becomes a single space (D20, found on the acceptance
  corpus).
* **Punctuation** — typographic quotes and dashes become their ASCII equivalents (D40, found on
  GDPR, where a phrase wrapped in U+2018/U+2019 single quotation marks came back wrapped in
  ASCII apostrophes instead).

Neither is a fabrication, and rejecting them silently discards correct claims: on the first GDPR
document, 5 of 89 claims were dropped for exactly this before the punctuation rule existed. A
genuine hallucination — a changed or invented *word* — still fails, because only whitespace and
punctuation *variants* are folded, never content.

**Spans are into the original text.** Matching is done with a pattern built from the quote rather
than by normalising the haystack, so the returned offsets index the source as it really is. That
is what lets the caller store the true source span, and what lets the renderer mark it without
its offsets drifting (escaping ``&`` into ``&amp;`` would shift every later offset).
"""

import re

# Written as explicit codepoints rather than literal characters: the literals are visually
# indistinguishable from one another, which is the very confusion this module exists to absorb.
# (ruff's RUF001 also refuses them, correctly, everywhere except here.)

#: Apostrophe and single-quote variants a model may swap for one another.
_SINGLE_QUOTES = "'\u2018\u2019\u02bc\u2032"

#: Double-quote variants.
_DOUBLE_QUOTES = '"\u201c\u201d\u201e\u2033'

#: Hyphen, minus and dash variants.
_DASHES = "-\u2010\u2011\u2012\u2013\u2014\u2015\u2212"

_CHAR_CLASSES: tuple[tuple[str, str], ...] = (
    (_SINGLE_QUOTES, f"[{re.escape(_SINGLE_QUOTES)}]"),
    (_DOUBLE_QUOTES, f"[{re.escape(_DOUBLE_QUOTES)}]"),
    (_DASHES, f"[{re.escape(_DASHES)}]"),
)


def _word_pattern(word: str) -> str:
    """Build a regex for one word, letting punctuation variants match each other."""
    parts: list[str] = []
    for character in word:
        for members, character_class in _CHAR_CLASSES:
            if character in members:
                parts.append(character_class)
                break
        else:
            parts.append(re.escape(character))
    return "".join(parts)


def locate_quote(haystack: str, quote: str) -> tuple[int, int] | None:
    """Return the ``[start, end)`` span of ``quote`` within ``haystack``, or None.

    Tries an exact substring match first, then a flexible match in which each run of
    whitespace matches any run of whitespace and each quote or dash matches its typographic
    variants. Only word content must match exactly.

    Args:
        haystack: The source text the quote should appear in.
        quote: The span to find.

    Returns:
        The half-open character span into ``haystack``, or None when the quote is not present.
    """
    if not quote.strip():
        return None
    exact = haystack.find(quote)
    if exact >= 0:
        return (exact, exact + len(quote))
    pattern = re.compile(r"\s+".join(_word_pattern(word) for word in quote.split()))
    match = pattern.search(haystack)
    return match.span() if match is not None else None


def quote_present(haystack: str, quote: str) -> bool:
    """Return True if ``quote`` appears in ``haystack`` under the same tolerance.

    Args:
        haystack: The source text the quote should appear in.
        quote: The span to check.

    Returns:
        True when the quote is present exactly or up to whitespace and punctuation variants.
    """
    return locate_quote(haystack, quote) is not None
