# Extraction gold set

Hand-labeled chunks used to measure **claim extraction quality on its own**, separate from
end-to-end contradiction metrics (spec §7.1, §9.2). End-to-end F1 can't tell you whether a miss
came from extraction or from detection; this set can.

## Layout

- `chunks/*.json` — one gold chunk per file, each conforming to `GoldChunk`
(`crosscheck.evaluation.extraction_gold`). Add one file per labeled chunk.

## Schema

```jsonc
{
"gold_id": "unique_snake_case_id",      // also the filename stem
"source": "where the text came from",   // doc name / section, for traceability
"text": "the chunk text, verbatim",     // self-contained; survives re-chunking
"claims": [                              // [] means "this chunk should yield NO claims"
    {
    "evidence_quote": "a verbatim substring of text that grounds the claim",
    "polarity": "positive",             // or "negative"
    "subject": "who/what the claim is about",   // optional, for clarity
    "note": "labeler note, e.g. how a pronoun was resolved"  // optional
    }
]
}

Labeling protocol

1. Source real chunks. Run the chunker over the seed corpus and copy real chunk text — don't
invent prose. Aim for ~50 chunks spanning the five v1 contradiction domains.
2. List every atomic, decontextualized assertion the chunk makes. One claim = one
independently checkable assertion. Split compound sentences into separate claims.
3. Anchor each with a verbatim evidence_quote — it must be an exact substring of text
(the scorer locates it by substring match, same as the extractor notarizes its own quotes).
4. Set polarity — negative for negations/prohibitions/exemptions ("not entitled",
"is waived", "must not"), positive otherwise.
5. Exclude non-claims — opinions ("we believe…"), questions, examples, and definitions
without an assertion. A chunk that is all non-claims gets "claims": []; that's how the set
measures false positives.
6. Note decontextualization — if a claim relies on a pronoun/demonstrative ("this
requirement", "they"), record the resolution in note.

Scoring

from pathlib import Path
from crosscheck.evaluation.extraction_gold import load_gold_set, to_chunk, score_extraction

# run the real extractor over each gold chunk (needs ANTHROPIC_API_KEY):
extracted = {g.gold_id: extractor.extract([to_chunk(g)]).claims for g in gold}
score = score_extraction(gold, extracted)
print(score.precision, score.recall, score.f1, score.polarity_accuracy)
