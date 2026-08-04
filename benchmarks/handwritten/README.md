# Hand-written validation set — Vantis

Twenty-eight cross-document contradictions I wrote by hand, in a five-document fictional corpus,
to answer one question the synthetic benchmark cannot: **do the headline numbers survive contact
with drift that does not announce itself?**

Spec v2 §9.1 requires this set, and §14 names the thing it exists to prevent — "letting the
synthetic headline number stand alone" — as the single biggest credibility risk in the project.

## The problem it exists to expose

Injected contradictions are made by asking a model to negate a sentence. The negation comes back
in the vocabulary of the sentence it negated, because that is what the prompt gave it to work
with. So the two sides of an injected pair look alike, and a retriever that only knows how to find
things that look alike will still find them. The measured overlap says exactly that:

| set | pairs | median lexical overlap | low-overlap stratum |
|---|---|---|---|
| `synthetic/v1` (injected, GPT-4.1) | 139 | 0.310 | 68 / 139 (49%) |
| `handwritten` (this set) | 28 | **0.072** | **26 / 28 (93%)** |

Four times less surface similarity, and nearly every pair falls below the 0.30 stratum cut. That
gap is the point. Numbers from this set are the honest ones; numbers from the synthetic set are
the ceiling.

## How the corpus is built to be hard

Five documents describe **one company's rules in five registers**. The same obligation appears as
plain-English reassurance, as contractual language with defined terms, as terse engineering
standard, as sales copy, and as an operational runbook — and the wording has almost nothing in
common between them.

| file | register | voice |
|---|---|---|
| `01_privacy_notice.md` | public-facing | "we", "you", "your information" |
| `02_data_processing_addendum.md` | contractual | "Processor", "Personal Data", "Sub-processor", "Business Day" |
| `03_data_handling_standard.md` | internal engineering | "objects", "buckets", "fabric", "tenant", "lifecycle job" |
| `04_trust_and_security_overview.md` | sales / trust centre | confident, absolute, unqualified |
| `05_incident_response_runbook.md` | operations | imperative, second person, procedural |

That is not a stylistic flourish. It is where real corpora drift: a marketing page promises what
the contract does not require and the standard does not implement, and nobody re-reads all four
together. Every document is Markdown so that every one of them has real headings — a plain-text
document would collapse to a single section and several gold pairs would then span the same
section pair and become impossible to tell apart when scoring (see "Section-level matching").

Specific techniques used to keep overlap low while keeping the conflict unambiguous:

- **Different names for the same thing** — "Sub-processor" / "vendor addition"; "Personal Data" /
  "tenant objects" / "your information"; "Security Incident" / "declared incident".
- **Buried exemptions** — the promise that nothing is kept indefinitely is contradicted in a
  legacy-estate paragraph about pre-migration buckets, not in the retention section.
- **Defined-term traps** — "within ten days" against "within ten Business Days", where
  `Business Day` is defined three sections away as excluding weekends and Irish public holidays.
- **Implication rather than statement** — the runbook does not say PII is in the logs; it says
  triage starts by searching the logs for the user's email address, "which is recorded on every
  authenticated request".
- **Absolute claim against named exception** — "there is no unencrypted path into Vantis, and
  there never has been" against a legacy ingest endpoint that accepts unencrypted connections.

## What is planted

28 pairs, by type:

| type | pairs |
|---|---|
| `numerical_mismatch` | 9 |
| `direct_negation` | 7 |
| `obligation_reversal` | 5 |
| `temporal_conflict` | 4 |
| `scope_jurisdiction` | 3 |

The types are **deliberately not balanced**. This set is meant to look like a real corpus, and
real corpora drift on numbers and flat denials far more often than they drift on jurisdiction. The
consequence is that per-type figures on the three- and four-pair types are indicative only; read
the overall number and the strata, not the `scope_jurisdiction` row.

Each pair is recorded in `gold.json` with both section ids, both verbatim quotes, character spans,
and a `notes` field saying why it is a contradiction. The reasoning matters as much as the label —
several of these need a sentence of argument, and a reviewer should be able to disagree with me
in writing.

## Planted agreements

A set that only contains contradictions measures recall and nothing else. These rules are restated
across registers and **must not** be reported:

- Multi-factor authentication is required to sign in — notice §2, standard §3, overview §1.
- Encryption at rest with AES-256 — DPA §3 and standard §3, agreeing.
- An independent penetration test at least once a year — DPA §3 and overview §2.
- A current Sub-processor list published at the trust centre — DPA §2, notice §2, overview §3.
- Backups taken every 24 hours — notice §3 and standard §2.
- Log integrity through write-once storage and five-minute SIEM forwarding — standard §4.
- Incident severity is triaged before anything is declared — runbook §1 and §2.

The overview and the standard are the sharpest test: they agree almost exactly on encryption at
rest and disagree completely on key custody, one sentence apart.

## Section-level matching

Gold labels match predictions on the **unordered pair of sections** a contradiction spans (D36),
not on claim ids. Two pairs spanning the same two sections would be indistinguishable when
scoring, so `scripts/build_handwritten_gold.py` refuses to write a gold set containing such a
collision. All 28 pairs here span distinct section pairs; several sections carry three or four
separate contradictions, each against a different counterpart.

## Regenerating

`gold.json` is built, not hand-maintained:

```bash
uv run python scripts/build_handwritten_gold.py
```

The pairs live in that script as file name, heading and verbatim sentence — the form a human can
check against the corpus. Section ids are content hashes and character spans are offsets, so both
are *resolved* by parsing the corpus with the pipeline's own parser rather than copied by hand.
Edit a document and re-run; a quote that no longer exists is a hard error rather than a silent
false negative.

## Honest limitations

- **Fictional, and written by the person who is measuring.** I knew the detection taxonomy while
  writing, so these are conflicts of the kinds the system looks for. A truly independent set would
  be annotated from a corpus nobody wrote for this purpose — that is what the real-corpus check
  (§9.4) is for, and it is the next thing to run.
- **Not independently reviewed.** `reviewed` is `false` on every pair. §9.1 sets a bar of ≥85%
  passing human review for the injected set; this set has had one pair of eyes, mine, and a second
  reviewer would be worth more here than on the synthetic set because the labels rest on argument
  rather than on a template.
- **28 pairs is a small sample.** A single finding moves overall recall by 3.6 points. Treat
  differences of one or two points against the synthetic set as noise; the gap worth discussing is
  a large one.
- **One company, one domain.** No cross-domain vocabulary shift, and no genuinely adversarial
  author trying to hide a conflict from a reader.
