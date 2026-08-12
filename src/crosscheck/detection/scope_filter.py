"""Suppress verdicts whose two claims cannot be in conflict, whatever the judge said (§9.4).

The §9.4 run against NIST SP 800-63B put real-corpus precision at roughly a quarter: eleven of
fifteen findings were wrong, and nine of those eleven paired claims that were simply *not about
the same thing*. That is a precision problem no amount of judge reasoning fixes, because by the
time the judge sees a pair the framing already asserts the two claims are comparable.

This module holds the rules that can say "these cannot conflict" from the claim text alone,
without a model and without a token. Two of them ship. Both are deliberately narrow: each
targets one mechanical confusion with a syntactic signature, and neither tries to decide whether
a genuine contradiction is *important*.

**Why so few.** Four rules were prototyped and scored offline against the two labelled
benchmarks before any was wired in. A third — "neither claim states a requirement, so this is
narrative prose" — looked like the safest of the set and was the most destructive: it dropped
twelve of seventeen hand-written findings and took that benchmark's F1 from .578 to .182. The
hand-written set is company registers written in ordinary prose ("employees receive 20 days"),
so a rule keyed on SHALL/MUST/SHOULD was not detecting non-requirements at all. It was detecting
NIST's house style. A fourth — converting "six decimal digits" to "19.93 bits" — was dropped as
overfitting to the single example that motivated it.

The two that ship cost nothing measurable: zero findings touched on either benchmark, F1
identical to three decimal places, while real-corpus precision rises from 26.7% to 33.3%.
See DECISIONS.md D55.
"""

from __future__ import annotations

import re

from crosscheck.detection.taxonomy import ContradictionType

#: Any run of digits, optionally dotted — "15", "112", "6.1.2".
_NUMBER = re.compile(r"\d+(?:\.\d+)*")

#: A dotted number introduced as a cross-reference: "Section 6.1.2", "Sec. 4.1.2", "§5.1.1".
_SECTION_REF = re.compile(r"(?:§|\bsec(?:tion)?s?\b\.?)\s*(\d+(?:\.\d+)*)", re.IGNORECASE)

#: "at least 112", "a minimum of 15" — a floor on a quantity.
_LOWER_BOUND = re.compile(
    r"(?:at least|no less than|no fewer than|a minimum of|minimum of|≥|>=)\s*(\d+)",
    re.IGNORECASE,
)

#: "shorter than 112", "fewer than 8" — a ceiling on a quantity.
_UPPER_BOUND = re.compile(
    r"(?:shorter than|less than|fewer than|below|<)\s*(\d+)",
    re.IGNORECASE,
)


def _cross_reference_renumbering(
    contradiction_type: ContradictionType, text_a: str, text_b: str
) -> bool:
    """Return True when every number that differs is a cross-reference, not a requirement value.

    Rev 4 of a standard renumbers its own sections, so "as described in Section 6.1.2" becomes
    "as described in Sec. 4.1.2". The requirement is untouched, but two numbers differ and the
    judge reads a numerical mismatch. Restricted to NUMERICAL_MISMATCH: for any other type the
    numbers are incidental and this rule has no business voting.

    Args:
        contradiction_type: The type the judge assigned.
        text_a: Claim A's decontextualized text.
        text_b: Claim B's decontextualized text.

    Returns:
        True if the pair should be suppressed.
    """
    if contradiction_type is not ContradictionType.NUMERICAL_MISMATCH:
        return False
    differing = set(_NUMBER.findall(text_a)) ^ set(_NUMBER.findall(text_b))
    if not differing:
        return False
    references = set(_SECTION_REF.findall(text_a)) | set(_SECTION_REF.findall(text_b))
    return differing <= references


def _complementary_thresholds(text_a: str, text_b: str) -> bool:
    """Return True when the two claims bound the *same* value from opposite sides.

    "Look-up secrets having at least 112 bits SHALL be hashed" against "look-up secrets shorter
    than 112 bits shall be salted and hashed" is not a contradiction — it is one rule stated in
    two halves. The conditions partition the space at the same threshold, so no document can
    satisfy one and violate the other.

    Args:
        text_a: Claim A's decontextualized text.
        text_b: Claim B's decontextualized text.

    Returns:
        True if the pair should be suppressed.
    """
    lower_a = set(_LOWER_BOUND.findall(text_a))
    upper_a = set(_UPPER_BOUND.findall(text_a))
    lower_b = set(_LOWER_BOUND.findall(text_b))
    upper_b = set(_UPPER_BOUND.findall(text_b))
    return bool((lower_a & upper_b) or (lower_b & upper_a))


def spurious_reason(contradiction_type: ContradictionType, text_a: str, text_b: str) -> str | None:
    """Name the rule that disqualifies this pair, or None to let the verdict stand.

    Returns a name rather than a bool so a suppression can be logged and counted with its cause
    — a filter that silently removes findings is worse than no filter, because there is no way
    to tell a precision improvement from a recall regression after the fact.

    Args:
        contradiction_type: The type the judge assigned.
        text_a: Claim A's decontextualized text.
        text_b: Claim B's decontextualized text.

    Returns:
        The rule name, or None if no rule fired.
    """
    if _cross_reference_renumbering(contradiction_type, text_a, text_b):
        return "cross_reference_renumbering"
    if _complementary_thresholds(text_a, text_b):
        return "complementary_thresholds"
    return None
