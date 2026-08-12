# Real-corpus check — NIST SP 800-63B §5.1.1–5.1.3, Rev 3 vs Rev 4

The second §9.4 sanity check. The [first one](../nist_au/README.md) ran on SP 800-53 and found
nothing, for a reason that turned out to be about the corpus rather than the system: a control
catalogue states its requirements as `[Assignment: organization-defined …]` placeholders, so there
were **zero concrete requirement values** in either revision and four of the five contradiction
types were unreachable before the pipeline started (D46).

800-63B is the corrective: it is normative, it commits to real numbers, and Rev 4 changed several
of them.

**Result: 20 verdicts, 15 findings after roll-up, of which 4 are genuine — covering 2 distinct
contradictions, a hit rate of 26.7%.** The system found real conflicts in a real document for
the first time. It also produced a lot of noise, and the most valuable thing this run produced is
not the hit rate but a specific architectural defect it exposed — one that was hiding a real finding
under a false positive, and that is now fixed (D50).

## What was run

| | |
|---|---|
| Corpus | Rev 3 §5.1.1–5.1.3 and the Rev 4 equivalents, 6,321 words, 34 chunks |
| Claims | 283 (130 Rev 3, 153 Rev 4) |
| Candidate pairs | 4,809 → 2,830 reranked → **771 past NLI** (27.2%) |
| Verdicts | **20** → 15 findings after near-duplicate roll-up |
| Genuine contradictions | **2 distinct issues**, across 4 findings |
| Cost | **$2.5231** over 731 LLM calls, complete — not stopped by the ceiling |
| Judge hallucination rate | **0.0000** |

```bash
uv run python scripts/build_63b_slice.py
CROSSCHECK_JUDGE_MODEL=claude-haiku-4-5 \
uv run crosscheck audit benchmarks/realcorpus/nist_63b/corpus \
  --reset-store --max-cost 3.20 \
  --report benchmarks/realcorpus/nist_63b/report.json
```

**Sizing note.** Projected at ~$1.88 from the 800-53 rate; came in at $2.52. The gap is entirely
NLI survival: 800-53 passed 15% of reranked pairs to the judge, 800-63B passed **27.2%**, because a
normative document is far denser in negations than a template. The ceiling was raised from $2.50 to
$3.20 before dispatch for exactly this reason. At $2.50 this run would have stopped `partial`.

## Why these subsections

The first three under "Requirements by Authenticator Type", contiguous, from both revisions —
Rev 3's 5.1.1/5.1.2/5.1.3 against Rev 4's Passwords/Look-Up Secrets/Out-of-Band Devices. Contiguity
is the methodology, exactly as with AU-1…AU-5: the memorized-secrets section is where I already knew
the headline drift lived, and taking only that section because I knew the answers would make the
hit rate a statement about my document-picking rather than about the system.

## The classification rule and predictions, fixed before any finding was visible

The REAL/REFINEMENT line is arguable on a revision pair, so it was written down while the audit was
still in its extraction stage, not after the findings were on screen.

| verdict | rule |
|---|---|
| **REAL** | A substantive requirement difference: an implementer complying with one revision would be in breach of the other, or a stated threshold genuinely changed. |
| **REFINEMENT** | Renaming, reorganisation, or a strengthening that keeps compliance with the stricter rule compatible with the looser one. `SHOULD NOT` → `SHALL NOT` is a REFINEMENT. |
| **ARTIFACT** | Spurious pairing — claims not about the same subject, complementary halves of one rule, or a document convention read literally. |

Four predictions were recorded. Two held, one held for the wrong reason, one was wrong:

| # | prediction | outcome |
|---|---|---|
| 1 | The 8 → 15 character minimum is the clearest REAL candidate; missing it is an unexplainable recall failure | **Hit.** Found, `numerical_mismatch`, confidence 0.75 — but buried (see below) |
| 2 | `SHOULD NOT` → `SHALL NOT` on composition rules will be found, and should be graded REFINEMENT | **Right outcome, wrong mechanism.** Never reported — but no judged pair ever quoted it, so the filter dropped it rather than the judge declining it |
| 3 | The unchanged 64-character rule must NOT be reported | **Hit.** Not reported; never reached the judge |
| 4 | Expect a cluster of terminology false positives from "memorized secret" → "password" | **Wrong.** Zero terminology false positives. The rename caused no trouble at all |

Prediction 4 being wrong is worth stating plainly: I expected the 800-53 failure mode
(`[Withdrawn:]` read as deletion) to recur as renames read as conflicts, and it did not.

## The defect this run exposed — since fixed (D50)

**A real contradiction was hidden underneath a false positive, and the report gave no sign of it.**

The `report.json` in this directory is the **rebuilt** one, so the counts above are post-fix: 15
findings rather than the 13 the run originally displayed, with the real password-length change
promoted to its own card. Rebuilding costs nothing — `build_report` reads the saved audit result
and makes no LLM calls — so the artefact matches the current code rather than preserving a bug for
narrative convenience. What follows is what the original report looked like.

Finding [3]'s headline is a false positive:

> **Rev 3** "…provide at least the minimum security strength specified in the latest revision of
> SP 800-131A (112 bits as of the date of this publication)"
> **Rev 4** "The salt SHALL be at least 32 bits in length"

These are different quantities — a hash security strength against a salt length — and Rev 3 states
the 32-bit salt rule itself, verbatim. Confidence 0.92.

Rolled up beneath it, at confidence 0.75, is this:

> **Rev 3** "…subscriber-chosen memorized secrets to be at least **8** characters in length"
> **Rev 4** "…passwords that are used as a single-factor authentication mechanism to be a minimum
> of **15** characters in length"

That is the single most legitimate contradiction in the corpus — the headline change between these
two revisions — and it is invisible to anyone reading the findings list.

The cause is in `_roll_up_near_duplicates`: findings are collapsed **by section pair**, keeping only
the most confident. Rev 3 §5.1.1.2 "Memorized Secret Verifiers" and Rev 4 "Password Verifiers" are
~1,200-word sections that legitimately contain many independent requirements — length, composition,
rotation, hashing, salting, rate limiting. Every finding between them collapses to one.

That assumption held everywhere it had been tested. The synthetic benchmark injects roughly one
contradiction per section; the hand-written set is five short registers. **Only a real document has
long sections carrying many independent obligations**, and this is the first time the pipeline has
seen one. It is also compounded by something already measured: confidence is not a proxy for
correctness — the 0.8–0.9 bin is overconfident by +.181 on synthetic and +.252 on hand-written — so
"keep the most confident" is not a safe tie-break.

**The fix (D50):** the roll-up key gained the claim's subject, so findings collapse only when they
share a section pair *and* a subject. On this run that promotes 2 of the 7 rolled-up findings —
including the 8→15 change — and leaves genuine duplicates collapsed. The evaluation harness now
does its own section-level grouping rather than inheriting the report's, because gold labels are
written at section level (D36) and the scoring unit must not move when the display does. Verified:
re-scoring both labelled benchmarks after the change reproduces `docs/eval-report.md` byte for byte.

Discovered as **D49**, fixed as **D50**.

## The two genuine contradictions

**1. An out-of-band method Rev 3 permits, Rev 4 forbids.** Findings [2] and [9], `obligation_reversal`,
confidence 0.92 and 0.85.

> **Rev 3** "The claimant compares secrets received from the primary channel and the secondary
> channel and confirms the authentication via the secondary channel."
> **Rev 4** "A third method of out-of-band authentication compares the secrets received from the
> primary and secondary channels and requests approval on the secondary channel. **This method is
> no longer considered acceptable** because it increases the likelihood that the subscriber would
> approve an authentication request without actually comparing the secrets as required."

An implementer following Rev 3 is non-compliant with Rev 4. Unambiguously REAL, and found twice
under two different pairings.

**2. Password length minimums raised.** Two findings, both REAL: one at 0.92 (6 → 15 characters for
randomly-chosen secrets) and one at 0.75 (8 → 15 for subscriber-chosen) — the latter being the card
that used to be invisible. Rev 4 raised the single-factor minimum to 15 characters while retaining
8 for passwords used within multi-factor.

## The eleven false positives, by cause

Grouping them by *why* they are wrong is more useful than listing them, because they are not one
failure repeated:

| cause | findings | example |
|---|---|---|
| **Cross-reference renumbering** | [5], [13] | "as described in Section 6.1.2" vs "as described in Sec. 4.1.2" — Rev 4 renumbered the suite; the requirement is identical. Labelled `numerical_mismatch` because two numbers differ |
| **Same value, different unit** | [10] | Rev 3 "at least 20 bits of entropy" vs Rev 4 "at least six decimal digits". Six decimal digits **is** 19.93 bits. Numerically equivalent, read as a mismatch |
| **Complementary halves of one rule** | [11] | Rev 3's "≥112 bits SHALL be hashed" paired against Rev 4's "<112 bits SHALL be salted and hashed". Rev 3 contains both halves; they agree |
| **Different quantities about different things** | [3] | 112-bit security strength vs 32-bit salt length |
| **Different actors** | [7] | The authenticator storing its own key vs the verifier not storing the identifying key |
| **Different entities of similar name** | [8] | Activation secrets vs transfer secrets. The judge's own rationale notes the distinction and reports the pair anyway |
| **Wrong sentence matched** | [6] | Rev 3 contains the identical "SHOULD NOT display the authentication secret while it is locked" sentence; the judge paired Rev 4's version against a *different* Rev 3 sentence |
| **Narrative description, not requirement** | [1], [12] | Prose describing two different (both valid) out-of-band flows |
| **Same mechanism, opposite direction** | [14] | Rev 3's "the authenticator SHALL accept transfer of the secret from the primary channel" against Rev 4's "the verifier shall transmit a random secret to the out-of-band authenticator" — the two ends of one exchange, not two rules in conflict |

The dominant pattern is **scope**: nine of the eleven pair two claims that are simply not about the
same thing — different actors, different entities, different quantities, different halves of a rule.
That is a retrieval-and-judging precision problem on real text, and it is the concrete thing to
attack next.

> **Table completed 2026-08-12.** This originally listed causes for ten of the eleven; the last row
> was added when the scope filter's own output was checked against it. Two rows here are now
> handled automatically — cross-reference renumbering and complementary halves — see D55.

## What this establishes, and what it does not

**Transfer is demonstrated, for the first time.** The system found genuine, non-obvious requirement
conflicts in a real document pair that nobody labelled, including the headline change. 800-53 could
not answer this question; this run does.

**Precision on real text is poor — 26.7%** (4 genuine findings of 15). That is far below the
synthetic benchmark's .852 and the hand-written set's .765, and it is the honest number for this
corpus. An auditor reading this report would spend most of their time dismissing pairs that are not
about the same subject. Note the direction the D50 fix moved this: surfacing a hidden *true* finding
raised the rate from 15.4% to 26.7%, because what the roll-up was suppressing here was a real
contradiction rather than noise.

**Corrected 2026-08-12 (D56).** This section previously said "3 genuine, about 20%". That count was
written before D50 surfaced the buried 8→15 password finding, and it was never updated when the
prose below it was: the run has 4 genuine findings and 11 false positives, which is the only
reading that sums to 15. The 20% figure was propagated to the top-level README and the `v0.1.0`
tag annotation before it was caught.

**The scope filter (D55) takes this to 33.3%** without re-running anything. It suppresses findings
[5], [12] and [15] — two renumbered cross-references and one pair of complementary threshold halves
— leaving 4 genuine of 12. The `report.json` committed here predates the filter and is the run
exactly as it happened; re-running the audit with the current code would produce the shorter list.

**Recall is not measured here and no recall claim is made.** There is no gold set — that is the
point of a real-corpus check — so "20 findings" is not "20 of N". The two pre-registered REAL items
were both found, which is a 2-of-2 on a sample of two, and nothing more than that.

**The caveat carried over from the 800-53 write-up still applies.** This is a successive-edition
pair, and the argument that "two successive editions do not contradict each other; the later
supersedes the earlier" is as true here as it was there. What changed is **findability, not
co-activity**: 800-53 stated no concrete values, so nothing was reachable; 800-63B states them, so
the system could be tested. The co-activity premise rests on §1's own motivating example — both
versions left in a retrieval corpus because nobody pruned the old one. That is a defensible framing,
not a proof.

## Files

- `corpus/` — the sliced Markdown actually audited, cut by `scripts/build_63b_slice.py` from
  `Crosscheck_Seed_Corpora/nist_63b/`. NIST publications are US federal government works and are not
  subject to domestic copyright, so the slice is committed.
- `report.json` — the audit's grouped contradiction report.

There is no `gold.json` and this benchmark is **not** in `benchmarks/suite.json`, for the same
reason as the 800-53 check: it has no labels, and inventing labels for a corpus chosen because
nobody had labelled it would defeat the exercise.
