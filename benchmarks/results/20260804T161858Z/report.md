# CrossCheck evaluation report

Generated 2026-08-04 16:18 UTC · crosscheck 0.1.0

## Configuration

These are the settings **at evaluation time**. A contradiction report does not record which model judged it, so scoring an old report under new settings will describe the new ones — check this block against the run you meant to score.

| setting | value |
| --- | --- |
| judge model | claude-haiku-4-5 |
| extraction model | claude-sonnet-4-6 |
| retrieval | hybrid, top-25 |
| reranker | BAAI/bge-reranker-v2-m3, top-10 |
| NLI model | cross-encoder/nli-deberta-v3-base |
| NLI threshold | 0.05 |
| NLI per-type thresholds | none |
| overlap cut | 0.30 |

## synthetic-v1

`/mnt/d/My_project/CrossCheck/benchmarks/synthetic/v1/gold.json` scored against `/mnt/d/My_project/CrossCheck/benchmarks/synthetic/v1/report.json`.

| benchmark | value |
| --- | --- |
| origin | injected |
| generator | gpt-4.1 |
| judge at authoring | claude-haiku-4-5 |
| cross-model (§9.1) | yes |
| seed | 20260801 |
| gold pairs scored | 139 |
| findings (grouped) | 108 |
| verdicts (expanded) | 256 |

### Detection — grouped (headline)

One row per contradiction as displayed, near-duplicates rolled up. This is the granularity the README quotes; see D42.

| metric | value |
| --- | --- |
| Precision | 0.852 |
| Recall | 0.662 |
| F1 | 0.745 |
| TP / FP / FN | 92 / 16 / 47 |
| Duplicates | 0 |

**By contradiction type**

| type | TP | FP | FN | P | R | F1 |
| --- | --- | --- | --- | --- | --- | --- |
| direct_negation | 22 | 8 | 8 | 0.733 | 0.733 | 0.733 |
| numerical_mismatch | 19 | 2 | 10 | 0.905 | 0.655 | 0.760 |
| obligation_reversal | 22 | 4 | 8 | 0.846 | 0.733 | 0.786 |
| scope_jurisdiction | 17 | 2 | 12 | 0.895 | 0.586 | 0.708 |
| temporal_conflict | 12 | 0 | 9 | 1.000 | 0.571 | 0.727 |

**By lexical overlap** — the stratum that shows whether the system only catches near-duplicate phrasing (§9.2).

| stratum | cut | TP | FP | FN | P | R | F1 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| high_overlap | 0.30 | 51 | 2 | 20 | 0.962 | 0.718 | 0.823 |
| low_overlap | 0.30 | 41 | 14 | 27 | 0.745 | 0.603 | 0.667 |

### Detection — per verdict (diagnostic)

Every judge verdict scored separately. Answers how often the *judge* was right, not how often what a user is shown is right.

| metric | value |
| --- | --- |
| Precision | 0.748 |
| Recall | 0.662 |
| F1 | 0.702 |
| Duplicates (not scored) | 133 |

### Calibration

**Confidence calibration** — predicted confidence against observed correctness (§9.2).

ECE 0.0597 · MCE 0.2500 · Brier 0.1218 · n=108

| confidence bin | n | mean confidence | accuracy | gap |
| --- | --- | --- | --- | --- |
| 0.7 to 0.8 | 2 | 0.750 | 0.500 | +0.250 |
| 0.8 to 0.9 | 24 | 0.848 | 0.667 | +0.181 |
| 0.9 to 1.0 | 82 | 0.934 | 0.915 | +0.020 |

A positive gap means overconfident. Empty bins are omitted here but kept in `eval.json` so a plotted diagram has a stable axis.

### Type agreement

0.413 of found contradictions carry the gold's own type. Matching deliberately ignores type (D36), so a mislabelled hit is still a hit. The taxonomy overlaps — an obligation reversal is usually also a direct negation — so read the confusion matrix in `eval.json` before treating this as an error rate.

### Observability and cost

| metric | value |
| --- | --- |
| judge hallucination rate | 0.0045 |
| decontextualization failure rate | 0.0104 |
| cost (this run) | $0.5759 |
| cost per 100 documents | $11.52 |

Cost reflects cache hits and so understates a cold run; it is spend, not price.

## handwritten-v1

`/mnt/d/My_project/CrossCheck/benchmarks/handwritten/gold.json` scored against `/mnt/d/My_project/CrossCheck/benchmarks/handwritten/report.json`.

| benchmark | value |
| --- | --- |
| origin | handwritten |
| generator | — |
| judge at authoring | claude-haiku-4-5 |
| cross-model (§9.1) | n/a (hand-authored) |
| seed | — |
| gold pairs scored | 28 |
| findings (grouped) | 17 |
| verdicts (expanded) | 25 |

### Detection — grouped (headline)

One row per contradiction as displayed, near-duplicates rolled up. This is the granularity the README quotes; see D42.

| metric | value |
| --- | --- |
| Precision | 0.765 |
| Recall | 0.464 |
| F1 | 0.578 |
| TP / FP / FN | 13 / 4 / 15 |
| Duplicates | 0 |

**By contradiction type**

| type | TP | FP | FN | P | R | F1 |
| --- | --- | --- | --- | --- | --- | --- |
| direct_negation | 4 | 3 | 3 | 0.571 | 0.571 | 0.571 |
| numerical_mismatch | 4 | 0 | 5 | 1.000 | 0.444 | 0.615 |
| obligation_reversal | 1 | 0 | 4 | 1.000 | 0.200 | 0.333 |
| scope_jurisdiction | 0 | 0 | 3 | 0.000 | 0.000 | 0.000 |
| temporal_conflict | 4 | 1 | 0 | 0.800 | 1.000 | 0.889 |

**By lexical overlap** — the stratum that shows whether the system only catches near-duplicate phrasing (§9.2).

| stratum | cut | TP | FP | FN | P | R | F1 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| high_overlap | 0.30 | 1 | 0 | 1 | 1.000 | 0.500 | 0.667 |
| low_overlap | 0.30 | 12 | 4 | 14 | 0.750 | 0.462 | 0.571 |

### Detection — per verdict (diagnostic)

Every judge verdict scored separately. Answers how often the *judge* was right, not how often what a user is shown is right.

| metric | value |
| --- | --- |
| Precision | 0.722 |
| Recall | 0.464 |
| F1 | 0.565 |
| Duplicates (not scored) | 7 |

### Calibration

**Confidence calibration** — predicted confidence against observed correctness (§9.2).

ECE 0.1876 · MCE 0.2520 · Brier 0.1831 · n=17

| confidence bin | n | mean confidence | accuracy | gap |
| --- | --- | --- | --- | --- |
| 0.7 to 0.8 | 1 | 0.750 | 1.000 | -0.250 |
| 0.8 to 0.9 | 10 | 0.852 | 0.600 | +0.252 |
| 0.9 to 1.0 | 6 | 0.930 | 1.000 | -0.070 |

A positive gap means overconfident. Empty bins are omitted here but kept in `eval.json` so a plotted diagram has a stable axis.

### Type agreement

0.846 of found contradictions carry the gold's own type. Matching deliberately ignores type (D36), so a mislabelled hit is still a hit. The taxonomy overlaps — an obligation reversal is usually also a direct negation — so read the confusion matrix in `eval.json` before treating this as an error rate.

### Observability and cost

| metric | value |
| --- | --- |
| judge hallucination rate | 0.0000 |
| decontextualization failure rate | 0.0578 |
| cost (this run) | $0.4609 |
| cost per 100 documents | $9.22 |

Cost reflects cache hits and so understates a cold run; it is spend, not price.

## How to read these numbers

- **Matching is at section level** (D36): a finding counts when both sides land in the gold pair's two sections. That is deliberately coarse — extraction quality is measured separately against its own gold set — and it is generous to the system.
- **False positives are an upper bound on error** on an injected benchmark. Only what was injected is labelled, so a finding that flags a real but unlabelled contradiction counts against us.
- **Injected contradictions are cleaner than real drift.** Synthetic numbers are the ceiling, not the expectation; the hand-written set and the real-corpus check are what test transfer (§9.1, §9.4).

## Benchmarks side by side

The gap between these rows is the result. A number from an injected benchmark is a ceiling; a number from a hand-authored one is closer to what a real corpus would give (§9.1, §14).

| benchmark | origin | gold pairs | median overlap | P | R | F1 | low-overlap F1 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| synthetic-v1 | injected | 139 | 0.310 | 0.852 | 0.662 | 0.745 | 0.667 |
| handwritten-v1 | handwritten | 28 | 0.072 | 0.765 | 0.464 | 0.578 | 0.571 |

**The gap.** `handwritten-v1` (handwritten) scores F1 0.578, 0.167 below the 0.745 of the injected `synthetic-v1`. The two runs share every pipeline setting in the configuration block above, so the difference is attributable to the benchmarks rather than to the system.

Injected pairs are lexically closer to each other than hand-authored ones — a generator asked to negate a sentence answers in that sentence's vocabulary — and the median-overlap column quantifies it. Quote the lower number, or quote both.

