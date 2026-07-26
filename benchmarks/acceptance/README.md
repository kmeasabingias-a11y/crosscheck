# Acceptance corpus — Arden Systems

A 10-document fictional corpus used as the **Phase 3 acceptance smoke test** (spec v2 §8:
"run on a 10-doc corpus and produce a non-empty report") and as the corpus that closes the
**Phase 1 milestone** (10 documents → ≥200 well-formed claims).

This is deliberately *not* the synthetic benchmark. Phase 5 builds that: LLM-injected
contradictions, cross-model generation, ~200 gold-labelled pairs, deterministic from a seed.
Nor is it the real-corpus check — Phase 6 runs the system against real public documents
(NIST SP 800-53 Rev 4 vs Rev 5). This corpus exists for a narrower job: proving the eight
stages are wired together correctly, against input that is realistic in shape, cheap to
re-run, and guaranteed to contain something to find.

## Why fictional

Real public documents are the right choice for the benchmark and the real-corpus check, and
the wrong choice here. NIST SP 800-53 is 400+ pages, so claim extraction alone would blow the
cost ceiling before the pipeline reached retrieval, and — more importantly — a real corpus
offers no guarantee that contradictions exist. "Produced a non-empty report" is only an
acceptance signal if we know in advance what should be in it.

## Layout

```
benchmarks/acceptance/
├── corpus/     # the 10 documents the audit reads
├── sources/    # JSON prose for the DOCX/PDF documents
└── README.md
```

`corpus/` holds exactly one file per document. The Markdown and plain-text documents are
committed directly; the DOCX and PDF documents are rendered from `sources/` by
`scripts/build_acceptance_corpus.py`. The sources live in a *sibling* directory rather than
inside `corpus/`, so the auditor never parses a document and its own rendered twin — which
would show up as a spurious set of near-duplicate findings.

Rebuild the binaries with:

```bash
uv run python scripts/build_acceptance_corpus.py
```

## The documents

| # | File | Format | Sections | Words |
|---|---|---|---|---|
| 1 | `01_employee_handbook.md` | Markdown | 10 | 504 |
| 2 | `02_pto_policy_v2.md` | Markdown | 10 | 348 |
| 3 | `03_remote_work_policy.txt` | Plain text | 1 | 432 |
| 4 | `04_contractor_addendum.md` | Markdown | 10 | 364 |
| 5 | `05_expense_policy.txt` | Plain text | 1 | 423 |
| 6 | `06_vendor_master_agreement.docx` | DOCX | 9 | 474 |
| 7 | `07_vendor_addendum_eu.docx` | DOCX | 8 | 306 |
| 8 | `08_information_security_policy.pdf` | PDF (3 pages) | 3 | 436 |
| 9 | `09_it_standards_v3.pdf` | PDF (3 pages) | 3 | 397 |
| 10 | `10_data_retention_policy.md` | Markdown | 8 | 377 |

All four v1 formats are represented on purpose: the corpus is also the only place where the
PDF path runs against multi-page input with a running header and page-number footer, which
is what makes `_strip_running_headers_footers` engage (it needs three or more pages).

## Planted conflicts

These are what the audit *should* surface. They are recorded here as expectations for
reading a smoke-run report by hand — they are **not** gold labels, and nothing in the test
suite asserts against this list. Type labels are the author's expectation, not ground truth;
the judge may reasonably classify some differently (a superseded numeric threshold is
arguably `NUMERICAL_MISMATCH` or `TEMPORAL_CONFLICT`).

### Paid time off

| # | Claim A | Claim B | Expected type |
|---|---|---|---|
| 1 | Handbook §2: 20 PTO days | PTO v2 §2: 25 PTO days | NUMERICAL_MISMATCH |
| 2 | Handbook §2: available after 90 days service | PTO v2 §2: available immediately, waiting period withdrawn | DIRECT_NEGATION |
| 3 | Handbook §2: no carry-over | PTO v2 §3: up to 5 days carry over | DIRECT_NEGATION |
| 4 | Handbook §2: contractors not entitled to PTO | Contractor addendum §3: entitled after six months | DIRECT_NEGATION |
| 5 | PTO v2 supersedes Handbook §2, both still active | — | TEMPORAL_CONFLICT |

### Remote work

| # | Claim A | Claim B | Expected type |
|---|---|---|---|
| 6 | Handbook §5: remote up to two days per week | Remote policy §2: five days per week, unrestricted | NUMERICAL_MISMATCH |
| 7 | Handbook §5: must use a company-issued device | Remote policy §4: personal device permitted if encrypted | DIRECT_NEGATION |
| 8 | Remote policy §3: may work from any location worldwide | Security policy §6: only from the approved country list | SCOPE_JURISDICTION |

### Expenses

| # | Claim A | Claim B | Expected type |
|---|---|---|---|
| 9 | Handbook §6: receipts required over $25 | Expense policy §2: receipts required over $75 | NUMERICAL_MISMATCH |
| 10 | Handbook §6: claims within 30 days | Expense policy §2: claims within 60 days | NUMERICAL_MISMATCH |
| 11 | Handbook §6: alcohol not reimbursable | Expense policy §5: alcohol reimbursable with a client meal | DIRECT_NEGATION |
| 12 | Handbook §6: premium cabins need VP approval | Expense policy §3: premium economy needs no prior approval | OBLIGATION_REVERSAL |

### Vendor contracts

| # | Claim A | Claim B | Expected type |
|---|---|---|---|
| 13 | MSA §2: undisputed invoices paid within 30 days | EU addendum §2: within 45 days | NUMERICAL_MISMATCH |
| 14 | MSA §3: must carry $2M liability insurance | EU addendum §3: EU vendors exempt | OBLIGATION_REVERSAL |
| 15 | MSA §4: must not subcontract without consent | EU addendum §4: may subcontract on 10 days notice | OBLIGATION_REVERSAL |
| 16 | MSA §5: delete production data within 30 days | EU addendum §5: retain for 6 months | NUMERICAL_MISMATCH |
| 17 | MSA §7: governed by Delaware law | EU addendum §6: governed by Irish law | SCOPE_JURISDICTION |

### Security

| # | Claim A | Claim B | Expected type |
|---|---|---|---|
| 18 | Security policy §3: rotate passwords every 90 days | IT standards §3: fixed-schedule rotation prohibited | OBLIGATION_REVERSAL |
| 19 | Security policy §3: minimum 12 characters | IT standards §3: minimum 14 characters | NUMERICAL_MISMATCH |
| 20 | Security policy §5: logs retained 90 days | IT standards §5: logs retained 13 months | NUMERICAL_MISMATCH |
| 21 | Security policy §5: logs retained 90 days | Retention policy §3: logs retained 13 months | NUMERICAL_MISMATCH |
| 22 | Security policy §6: approved country list only | IT standards §6: any country, device posture instead | DIRECT_NEGATION |
| 23 | IT standards v3.0 supersedes Security policy v5.2, both active | — | TEMPORAL_CONFLICT |

Twenty-three planted conflicts across all five v1 types. Types 1–5 are each represented at
least twice, so a run that systematically misses one type is visible rather than ambiguous.

## Planted agreements

Detection is only half the signal — a system that flags everything scores well on recall and
is useless. These pairs restate the same rule across documents and **must not** be reported:

- MFA required on externally-reachable systems — Security policy §3 *and* IT standards §3.
- Full-disk encryption, endpoint agent, 14-day patching (48h critical) — Security policy §4
  *and* IT standards §4, near-identical wording.
- Least privilege, named accounts, quarterly review, 90-day disable — Security policy §2
  *and* IT standards §2.
- Corporate VPN required for remote access — Handbook §5, Remote policy §5, Security
  policy §6, IT standards §6.
- Log integrity via write-once storage, five-minute forwarding — both security documents.
- 14-day advance PTO request through the portal — Handbook §2 *and* PTO v2 §4.
- Accrued unused PTO paid out on termination — Handbook §8 *and* PTO v2 §7.

The two security documents are the sharpest test: they agree almost verbatim on four
controls and disagree on four others, so retrieval will surface many high-similarity pairs
where only some are contradictions. Precision here is the number worth watching.

## Known limitations

- **Not adversarial.** Every conflict is between explicitly stated rules. Real drift is
  often implied, buried in defined terms, or spread across clauses. The hand-written set in
  Phase 5 exists to expose that gap.
- **Lexically obvious.** Most pairs share subject vocabulary ("paid time off", "insurance",
  "passwords"), so dense retrieval alone will likely find them. That makes this corpus a
  weak test of the hybrid BM25 default — the low-overlap stratum in §9.2 is the real one.
- **One domain, one fictional company.** No cross-domain vocabulary shift.
- **Author-labelled.** The conflict list above is the author's intent, not reviewed ground
  truth, and carries the bias of having been written to be found.
