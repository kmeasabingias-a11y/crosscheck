"""Negation-sensitivity benchmark: schema and loader (spec v2 §7.3, §9.2, §12).

Embeddings place "X is required" and "X is not required" unpredictably — sometimes adjacent,
sometimes far apart — so a contradiction can be lost at the *retrieval* stage, before any judge
sees it. This benchmark is a small set of known cross-document negation pairs used to measure
whether the default hybrid (BM25 + dense) retrieval and rerank actually surface each negation
partner into the top-K. BM25 is what rescues these: a claim and its negation are lexically
near-identical, so lexical overlap ranks them together even when the dense embedding does not.

The data is a list of :class:`NegationPair` (a claim and its cross-document negation), loaded
from JSON. :func:`to_claim_pairs` turns the seeds into real :class:`~crosscheck.models.Claim`
objects with deterministic ids (namespaced under ``neg:``) so the retrieval stack can index them.
The retrieval assertion lives in ``tests/integration`` (it needs the real models); the loader here
is reused by the Phase-6 metrics module that reports negation-pair recall.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from loguru import logger
from pydantic import TypeAdapter

from crosscheck.ids import claim_id, content_hash
from crosscheck.models import Claim, CrossCheckModel


class ClaimSeed(CrossCheckModel):
    """One side of a negation pair: a claim's document, text, and polarity."""

    doc_id: str
    text: str
    polarity: Literal["positive", "negative"]


class NegationPair(CrossCheckModel):
    """A known contradiction: a claim and its cross-document negation.

    The two seeds share a ``subject`` and assert opposite polarity of the same thing. Retrieval
    must surface the ``negative`` as a candidate when querying with the ``positive`` (the pair is
    lexically near-identical, so hybrid retrieval should rank them together).
    """

    subject: str
    positive: ClaimSeed
    negative: ClaimSeed


_PAIRS_ADAPTER = TypeAdapter(list[NegationPair])


def load_negation_pairs(path: Path) -> list[NegationPair]:
    """Load the negation-pair benchmark from a JSON file (a list of pairs)."""
    pairs = _PAIRS_ADAPTER.validate_json(path.read_text(encoding="utf-8"))
    logger.info("loaded {} negation pair(s) from {}", len(pairs), path)
    return pairs


def _seed_to_claim(seed: ClaimSeed, subject: str) -> Claim:
    """Build a deterministic :class:`Claim` from a seed, namespaced under ``neg:``."""
    doc = f"neg:{seed.doc_id}"
    section = content_hash(f"{doc}\x1f{seed.text}")  # unique per (doc, text)
    span = (0, len(seed.text))
    return Claim(
        claim_id=claim_id(doc, section, span),
        doc_id=doc,
        section_id=section,
        text=seed.text,
        evidence_quote=seed.text,
        evidence_offset=span,
        subject=subject,
        predicate="",
        polarity=seed.polarity,
    )


def to_claim_pairs(pairs: Sequence[NegationPair]) -> list[tuple[Claim, Claim]]:
    """Build ``(positive_claim, negative_claim)`` for each negation pair.

    Ids are deterministic, so the same seed yields the same ``claim_id`` here as when the whole
    corpus is flattened for indexing (:func:`to_claims`) — the retrieval test can upsert the
    corpus and still identify each pair's partner by id.
    """
    return [
        (_seed_to_claim(pair.positive, pair.subject), _seed_to_claim(pair.negative, pair.subject))
        for pair in pairs
    ]


def to_claims(pairs: Sequence[NegationPair]) -> list[Claim]:
    """Flatten the pairs into the full claim corpus (both sides of every pair) for indexing."""
    return [claim for positive, negative in to_claim_pairs(pairs) for claim in (positive, negative)]
