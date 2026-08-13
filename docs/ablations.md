# CrossCheck ablations

Spec §9.3 asks for three ablations. These are them, run end-to-end on the hand-written benchmark
(`benchmarks/handwritten/`, 28 gold pairs, 5 documents, 173 claims).

Every arm changes exactly one thing against a common baseline, and the baseline is not assumed —
it is re-run first and required to reproduce the published F1 of .5778. An ablation delta measured
against a zero that no longer reproduces measures the harness, not the system.

Runner: `scripts/ablate.py <arm>`. Results, reports and metrics for every arm are written per-arm
so any figure below can be recomputed offline without re-running anything.

## The four arms

| arm | judge | retrieval | NLI | pairs judged | P | R | **F1** |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| `baseline` | Haiku 4.5 | hybrid | ≥0.05 | 528 | .765 | .464 | **.578** |
| `dense_only` | Haiku 4.5 | **dense** | ≥0.05 | 510 | .800 | .429 | **.558** |
| `judge_sonnet` | **Sonnet 4.6** | hybrid | ≥0.05 | 531 | .750 | .536 | **.625** |
| `nli_off` | Haiku 4.5 | hybrid | **off** | **1,730** | .762 | .571 | **.653** |

Measured judge cost per pair: **Haiku $0.00252**, **Sonnet $0.00737** — 2.9×. Cold-cache cost for
one hand-written audit is therefore $1.33 at baseline, $4.36 with NLI off, $3.91 with Sonnet.

All four arms completed; none hit its cost ceiling; judge-hallucination rate was 0.0000 throughout.

## 1. NLI filter on vs. off

**The filter is a pure cost optimisation. It buys no precision, and it costs real recall.**

| | baseline | `nli_off` | delta |
| --- | ---: | ---: | ---: |
| precision | .765 | .762 | **−.003** |
| recall | .464 | .571 | **+.107** |
| F1 | .578 | .653 | +.075 |
| pairs judged | 528 | 1,730 | +1,202 |

Judging the 1,202 pairs the NLI filter discards recovers **3 of 28 gold pairs** and produces
**one** additional false positive.

That last number is the finding. The two-stage NLI→judge architecture (§4) is justified in the spec
on cost grounds, with the implication that filtering also protects the judge from noise. It does
not. The judge rejects the discarded pairs perfectly well on its own — 1,202 extra pairs, one extra
false positive. What the filter actually does is remove **69% of judge spend** ($4.36 → $1.33 per
audit) at a price of **~$1.01 per additional gold pair found**.

So the architecture is right, but for one reason rather than two, and it is not free. On a corpus
where recall matters more than spend, turning the filter off is the single cheapest quality win
available.

## 2. Hybrid vs. dense-only retrieval

**No measurable difference on the stratum that matters, and the spec's stated rationale is not
what the data shows.**

| stratum | gold pairs | baseline TP | `dense_only` TP |
| --- | ---: | ---: | ---: |
| high overlap (≥0.30) | 2 | 1 | **0** |
| low overlap (<0.30) | 26 | **12** | **12** |

§7.3 makes hybrid the default on the argument that obligation reversals and scope conflicts are
"phrased very differently even when they conflict", so dense retrieval will miss them. §9.3 asks
for the delta to be read on the low-overlap stratum for that reason.

Read there, the two strategies are **identical**: 12 true positives each across 26 pairs. Hybrid's
entire measured advantage is a single high-overlap pair — and it is a `temporal_conflict`, not one
of the two types the spec names. Per type, `obligation_reversal` (1/5) and `scope_jurisdiction`
(0/3) are unchanged between the arms.

That result is mechanically sensible: BM25 is a lexical matcher, so it should help most where two
claims share surface form. The spec's reasoning has it backwards.

**Hybrid stays the default anyway**, for three reasons: it is not worse on any stratum; the
high-overlap stratum here holds only 2 gold pairs, so this benchmark cannot say much about it
either way; and `scope_jurisdiction` sits at 0/3 in *both* arms, which means this corpus cannot
test half of §7.3's claim at all — you cannot lose what was never found. The honest position is
that the justification in §7.3 is unsupported here, not that it is refuted.

Dense-only's higher precision (.800 vs .765) is one shed `direct_negation` false positive, not
better matching.

## 3. Judge model — Haiku 4.5 vs. Sonnet 4.6

**Sonnet buys recall, at 2.9× the price, and it buys it almost entirely on one type.**

| | baseline | `judge_sonnet` | delta |
| --- | ---: | ---: | ---: |
| precision | .765 | .750 | −.015 |
| recall | .464 | .536 | **+.071** |
| F1 | .578 | .625 | +.047 |
| cost / pair | $0.00252 | $0.00737 | **2.9×** |

Both of the two additional true positives are **`scope_jurisdiction`**, which moves from **0/3 to
2/3** — the weakest type in every report this project has produced, off zero for the first time.

Agreement between the two judges, over the pairs either one flagged:

| | value |
| --- | ---: |
| flagged by Haiku | 20 |
| flagged by Sonnet | 25 |
| flagged by both | 16 |
| **Jaccard agreement on positives** | **.552** |
| mean \|confidence delta\| where both agree | .044 |

The two judges agree on roughly half of what either flags. Where they agree they agree closely.
This is what makes the judge a product decision rather than a tuning detail — swapping it changes
about half the output.

Sonnet is not uniformly better. It added two false positives on `obligation_reversal` and one on
`numerical_mismatch`, while cleaning up `direct_negation` (3→2 FP) and making `temporal_conflict`
perfect (P 1.000 / R 1.000). Its `type_agreement` is *lower* (.733 vs .846): it finds more pairs
and labels their types less conventionally.

**Haiku remains the default.** Not because the result is weak — it is the second-strongest arm —
but because publishing Sonnet as the default would require re-judging the synthetic benchmark on
Sonnet too (~1,100 pairs) purely to keep `docs/eval-report.md` internally consistent. That is a
large spend to restate numbers rather than learn anything. The trade is documented here and the
switch is one config value.

## What the three say together

Per-type true positives, all four arms:

| type | gold | baseline | `dense_only` | `judge_sonnet` | `nli_off` |
| --- | ---: | ---: | ---: | ---: | ---: |
| direct_negation | 7 | 4 | 4 | 4 | 4 |
| numerical_mismatch | 9 | 4 | 4 | 4 | **5** |
| obligation_reversal | 5 | 1 | 1 | 1 | **3** |
| scope_jurisdiction | 3 | 0 | 0 | **2** | 0 |
| temporal_conflict | 4 | 4 | **3** | 4 | 4 |
| **total** | **28** | **13** | 12 | **15** | **16** |

**The two recall recoveries are on disjoint types.** Turning the NLI filter off recovers
`obligation_reversal` (+2) and `numerical_mismatch` (+1); upgrading the judge recovers
`scope_jurisdiction` (+2). Neither touches what the other recovers.

Two things follow.

**The stages lose different kinds of contradiction.** `obligation_reversal` recall goes .20 → .60
purely by not filtering, and is untouched by a better judge. `scope_jurisdiction` goes .00 → .67
purely by judging better, and is untouched by the filter. This is an independent line of evidence
for the same conclusion D57's recall funnel and D58's top-k sweep reached by other methods, and it
attributes the loss by *type* rather than by stage count.

**§7.3 identified the right fragile type and the wrong stage.** Obligation reversals are indeed
where the pipeline bleeds — but the culprit is the NLI filter, not dense-vs-hybrid retrieval.

Because the recoveries are disjoint, running both (NLI off *and* Sonnet) should be roughly additive
— ~18 of 28. That is untested: it would cost 1,730 pairs at Sonnet prices, ~$12.75 for one audit.
It is the obvious next experiment and it is not run here.

## Reading these numbers

- **28 gold pairs.** One pair is 3.6 points of recall. The `dense_only` result rests on a single
  true positive and a single false positive; treat one-pair deltas as suggestive, not established.
- **The high-overlap stratum has 2 gold pairs.** Any figure computed on it is anecdote.
- **Matching is section-level** (D36), the same generous convention the published eval uses, so
  these numbers are directly comparable to `docs/eval-report.md` but inherit its caveats.
- **Cost per pair is measured, not list price**, from each arm's own spend divided by its own
  uncached judge calls.
- **The pipeline is not bit-identical run to run.** Two identical baseline runs produced 2,840 and
  2,843 candidate pairs and 24 vs 25 findings — Qdrant's approximate search breaks ties differently
  against a freshly reset collection. Scored metrics were identical across both, and every arm here
  reproduced its precision, recall, F1 and counts exactly on re-run, so the noise does not reach the
  figures above. It does mean candidate/finding counts should not be read to the unit.

## Reproducing

```bash
docker compose up -d qdrant
uv run --frozen python scripts/ablate.py baseline        # must give F1 .5778 before trusting any arm
uv run --frozen python scripts/ablate.py dense_only
uv run --frozen python scripts/ablate.py judge_sonnet
uv run --frozen python scripts/ablate.py nli_off
```

Each arm writes its summary row, full metrics and full report. Re-runs are served from the verdict
cache: the four arms above cost **$7.17** the first time and **$0.04** to reproduce.
