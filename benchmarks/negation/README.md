# Negation-pair retrieval benchmark

A small set of known **cross-document negation pairs** used to check that the default hybrid
(BM25 + dense) retrieval and rerank actually surface a claim's negation as a candidate (spec §7.3,
§9.2, §12).

## Why it exists

Dense embeddings place a claim and its negation ("X is required" vs. "X is not required")
unpredictably — sometimes adjacent, sometimes far apart. If the negation isn't retrieved, the
contradiction is lost before any judge sees it. BM25 rescues these because the two are lexically
near-identical, which is exactly why hybrid retrieval is the default (§7.3). This benchmark makes
that claim measurable: **negation-pair retrieval recall** — how often the true negation partner
survives retrieval + rerank into the top of the ranking.

## Format

`negation_pairs.json` is a list of pairs. Each pair shares a `subject` and holds a `positive`
claim and its cross-document `negative`:

```json
{
"subject": "vendor liability insurance",
"positive": {"doc_id": "policy_v1", "text": "Vendors must carry liability insurance ...", "polarity":
"positive"},
"negative": {"doc_id": "policy_v2", "text": "Vendors are not required to carry liability insurance.",
"polarity": "negative"}
}

Rules for a good pair:
- The positive and negative must be in different documents (doc_id) — retrieval filters to
cross-document candidates.
- They must be a genuine negation of the same subject, not merely a numeric variant.
- Keep each pair's subject distinct from the others, so a partner has to be recognised on its own
merits rather than colliding with another subject's vocabulary.

Loading

crosscheck.evaluation.negation.load_negation_pairs(path) parses this file into NegationPair
objects; to_claim_pairs / to_claims turn the seeds into Claims (deterministic ids namespaced
under neg:) for indexing. The retrieval assertion lives in
tests/integration/test_negation_retrieval.py (real models; run with -m integration).
