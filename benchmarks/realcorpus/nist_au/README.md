# Real-corpus check — NIST SP 800-53 AU-1…AU-5, Rev 4 vs Rev 5

The §9.4 sanity check. Everything else in `benchmarks/` was written to be measured against — the
synthetic contradictions were injected by GPT-4.1, the hand-written ones by me. This is the one test
where nobody arranged the answer in advance.

**Result: 1 finding, 0 confirmed real.** And the interesting part is *why*, which took a `grep` to
establish and changes what the number means.

## What was run

| | |
|---|---|
| Corpus | AU-1 … AU-5 from each revision, 4,127 words, 19 chunks |
| Claims | 145 (69 Rev 4, 76 Rev 5) |
| Candidate pairs | 2,346 → 1,450 reranked → **217 past NLI** |
| Findings | **1** (grouped; 2 verdicts, 1 rolled up as a near-duplicate) |
| Cost | $0.8895, complete — not stopped by the ceiling |
| Judge hallucination rate | 0.0000 |

```bash
uv run python scripts/build_nist_slice.py
CROSSCHECK_JUDGE_MODEL=claude-haiku-4-5 \
uv run crosscheck audit benchmarks/realcorpus/nist_au/corpus \
  --reset-store --max-cost 1.40 \
  --report benchmarks/realcorpus/nist_au/report.json
```

## Why AU-1…AU-5

The full Access Control family would cost roughly $8.00 to audit and the full Audit and
Accountability family about $3.60, both estimated from this project's measured rate of ~$0.0063 per
claim. AU-1 through AU-5 are simply **the first five controls of the family** — contiguous, so the
result cannot be a statement about my skill at picking documents where I already knew conflicts
lived.

## The classification rule, fixed before the run finished

The REAL/REFINEMENT line is genuinely arguable on a revision pair, so it was written down in advance
rather than decided once the findings were visible.

| verdict | rule |
|---|---|
| **REAL** | A substantive requirement difference. §6 defines `TEMPORAL_CONFLICT` as "one claim supersedes/deprecates/postdates another, but both remain active in the corpus". |
| **REFINEMENT** | Renaming or reorganisation with no change to what an implementer must do. |
| **ARTIFACT** | Spurious pairing — `[Assignment: …]` boilerplate matched to itself, or two claims not about the same subject. |

## The single finding, and why it is a false positive

`temporal_conflict`, confidence 0.85:

> **Rev 4, AU-2 — Audit Events**
> "The organization reviews and updates the audited events [Assignment: organization-defined
> frequency]."
>
> **Rev 5, AU-2 — Event Logging**
> "(3) EVENT LOGGING | REVIEWS AND UPDATES [Withdrawn: Incorporated into AU-2.]"

The judge read "Withdrawn" as the requirement being removed. It was not. **"Incorporated into AU-2"
means the enhancement was folded into the base control**, and Rev 5's AU-2 says so in as many words:

> "e. Review and update the event types selected for logging [Assignment: organization-defined
> frequency]"

The obligation survives verbatim. Classified **REFINEMENT** under the rule above.

The failure is instructive rather than embarrassing: NIST's withdrawal markers are a domain
convention (`[Withdrawn: Incorporated into X]`, `[Withdrawn: Moved to Y]`) that reads as deletion to
anyone who does not know the convention, and the judge does not. A domain-aware prompt would fix
this specific case.

**Hit rate: 0 of 1.** The top-20 figure §9.4 asks for is not computable, because there is no top-20.

## Why so little was found — the structural answer

Counted directly over the two documents:

| | Rev 4 | Rev 5 |
|---|---|---|
| `[Assignment/Selection: …]` placeholders | 21 | 27 |
| Concrete requirement values (numbers, durations, percentages) | **0** | **0** |
| Negations ("shall not", "does not", "is not") in ~4,100 words | 1 | 3 |

Every number appearing in either document is a control identifier (`AU-2`, `SP 800-53`) or a list
enumerator. Not one is a requirement value. Even percentages are parameterised —
`[Assignment: organization-defined percentage]`.

**SP 800-53 is a control catalogue, not a set of assertions.** It is a template whose thresholds the
adopting organisation fills in. That structurally rules out four of the five v1 contradiction types
before the pipeline runs:

- `NUMERICAL_MISMATCH` — there are no numbers to mismatch
- `DIRECT_NEGATION` — four negations across 4,100 words
- `OBLIGATION_REVERSAL` — Rev 5 restructures and tightens; it never exempts
- `SCOPE_JURISDICTION` — no jurisdictions are named

Only `TEMPORAL_CONFLICT` remains reachable, and that is exactly the label the one finding carried.

Reading AU-4 and AU-5 by hand confirms it. Rev 5 renames "Audit Storage Capacity" to "Audit Log
Storage Capacity" and swaps "storage requirements" for "retention requirements"; it *adds* "within
[Assignment: organization-defined time period]" to AU-5's alert obligation. Tightenings and
renamings. An implementer complying with Rev 5 is never in breach of Rev 4.

## What this does and does not establish

**It does not show a recall failure.** Finding almost nothing in a document pair that contains
almost nothing findable is correct behaviour. The system also did not manufacture noise: 217 pairs
reached the judge and it declined 216 of them, which is the conservative direction to err in for an
auditing tool.

**It does not establish transfer either.** The open question — does this system find real conflicts
in the wild? — is still open. This run cannot answer it, and saying otherwise would be exactly the
over-claiming the project exists to avoid.

**What it does establish is that §9.4's own suggested corpus is a poor test for this system**, for a
reason that takes one `grep` to verify and that I would not have predicted from the spec. Two
successive editions of a standard do not contradict each other; the later supersedes the earlier.
§6's `TEMPORAL_CONFLICT` requires that both remain *active in the corpus*, which is not true of a
withdrawn revision.

## What a real corpus needs, for next time

Documents that state **filled-in, concrete requirements**, and that are genuinely co-active rather
than successive editions of one another.

The strongest public-domain candidate identified is **NIST SP 800-63B Rev 3 vs Rev 4** (Digital
Identity Guidelines). Same publisher and licence, but unlike 800-53 it commits to real values —
minimum 8 characters, permit at least 64, the well-known reversal on periodic password rotation —
and Rev 4 revised several of them. Deferred here on budget, not on doubt.

## Files

- `corpus/` — the sliced Markdown actually audited, cut by `scripts/build_nist_slice.py` from
  `Crosscheck_Seed_Corpora/nist/`. NIST publications are US federal government works and are not
  subject to domestic copyright, so the slice is committed.
- `report.json` — the audit's grouped contradiction report.

There is no `gold.json` and this benchmark is **not** in `benchmarks/suite.json`. It has no labels,
which is the point; `crosscheck eval` scores against gold sets, and inventing labels for a corpus
chosen because nobody had labelled it would defeat the exercise.
