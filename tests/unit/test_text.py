"""Unit tests for verbatim-quote matching (D20 whitespace, D40 punctuation)."""

from crosscheck.text import locate_quote, quote_present

# Written as escapes so the test states which codepoints it means; the literals are
# indistinguishable on screen, which is the confusion this module exists to absorb.
_CURLY = "processed lawfully (\u2018lawfulness, fairness and transparency\u2019);"
_STRAIGHT = "processed lawfully ('lawfulness, fairness and transparency');"


def test_exact_match_returns_its_span() -> None:
    assert locate_quote("alpha beta gamma", "beta") == (6, 10)


def test_missing_quote_returns_none() -> None:
    assert locate_quote("alpha beta", "delta") is None


def test_blank_quote_is_never_present() -> None:
    assert locate_quote("alpha", "   ") is None
    assert locate_quote("alpha", "") is None


# --- D20: whitespace ----------------------------------------------------------------------


def test_a_rewrapped_line_break_still_matches() -> None:
    """Models normalise a source's hard wrap to a single space."""
    source = "the controller shall\nnotify the supervisory authority"
    span = locate_quote(source, "the controller shall notify the supervisory authority")
    assert span is not None
    assert source[span[0] : span[1]] == source  # the span is the real source text


def test_collapsed_runs_of_whitespace_match() -> None:
    assert locate_quote("a   b\t\tc", "a b c") is not None


# --- D40: punctuation ---------------------------------------------------------------------


def test_typographic_quotes_match_ascii_apostrophes() -> None:
    """The GDPR bug: 5 of 89 claims were dropped for exactly this."""
    span = locate_quote(_CURLY, _STRAIGHT)
    assert span is not None
    # The span indexes the original, so the stored quote keeps the source's real typography.
    assert _CURLY[span[0] : span[1]] == _CURLY


def test_the_match_is_symmetric() -> None:
    assert quote_present(_STRAIGHT, _CURLY)
    assert quote_present(_CURLY, _STRAIGHT)


def test_dash_variants_match_each_other() -> None:
    for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015", "\u2212"):
        assert quote_present(f"a {dash} b", "a - b"), dash
        assert quote_present("a - b", f"a {dash} b"), dash


def test_double_quote_variants_match() -> None:
    assert quote_present("he said \u201cno\u201d today", 'he said "no" today')


def test_whitespace_and_punctuation_tolerance_combine() -> None:
    source = "the term\n(\u2018controller\u2019) \u2014 meaning the body"
    assert quote_present(source, "the term ('controller') - meaning the body")


# --- what must still fail -----------------------------------------------------------------


def test_a_changed_word_is_still_a_fabrication() -> None:
    assert locate_quote(_CURLY, "processed unlawfully ('lawfulness, fairness');") is None


def test_an_invented_clause_is_still_a_fabrication() -> None:
    assert locate_quote(_CURLY, _STRAIGHT + " and shall be deleted") is None


def test_punctuation_tolerance_does_not_ignore_punctuation_entirely() -> None:
    """Folding variants is not the same as dropping characters."""
    assert locate_quote("a, b", "a b") is None
    assert locate_quote("total: 30", "total 30") is None
