# CrossCheck — Project Specification (v2)

A cross-document contradiction detection system built around a rigorous evaluation framework. Audits a corpus of policies, contracts, technical docs, or regulations and surfaces every pair of statements that conflict, with evidence, confidence scores, and classified contradiction types.

| Field | Value |
|---|---|
| Document type | Technical specification (handoff to Claude Code) |
| Target audience | Claude Code, operating in the project repository |
| Target completion | 14 weeks of part-time work (~15 hrs/week) |
| Primary language | Python 3.11+ |
| Primary LLM | Claude Sonnet 4.6 (configurable) |
| Delivery | Installable CLI + FastAPI service + Streamlit demo + eval report |

**How to use this document.** Read it end-to-end before writing code. Sections 1–4 explain the problem and shape of the system. Section 5 gives prescriptive tech choices — don't deviate without reason. Sections 6–7 specify the modules and repo layout. Section 8 is the phased build plan. Section 9 covers evaluation, which is the project's differentiator and must not be treated as an afterthought. Sections 10–12 cover conventions, testing, and deliverables.

**What changed in v2.** This revision incorporates a set of improvements over the original spec, all aimed at protecting the project's core credibility claim: that the reported numbers reflect real performance, not benchmark easiness. The substantive changes are flagged inline with **[v2]** markers and summarized in Section 0.

---

## 0. Summary of v2 Changes

These are the deltas from the original spec. Each is explained in context in its home section.

**Evaluation validity**
- Synthetic benchmark is generated with a *different* model family than the judge, to avoid measuring a model's ability to recognize its own output style. (§9.1)
- A small hand-written contradiction set (20–30 pairs) ships alongside the injected set, to expose the gap between injected and real-world drift. (§9.1)
- The real-corpus sanity check moves from Phase 9 to Phase 6 — it is the most credible result and must be discovered early. (§8, §9.4)
- Metrics are stratified by lexical/surface overlap (high vs low similarity), revealing whether the system only catches near-duplicate phrasing. (§9.2)
- A confidence-calibration plot (predicted confidence vs actual correctness) is a required README artifact. (§9.2, §13)

**Claim extraction**
- A dedicated gold set measures extraction quality on its own, separate from end-to-end metrics. (§7.1, §9.2)
- A decontextualization check flags claims with unresolved pronouns or dangling references. (§7.1)

**Retrieval**
- Hybrid BM25 + dense retrieval is the **default**, not an optional ablation. (§7.3)
- Negation-sensitivity of retrieval is tested explicitly. (§7.3, §9.2)

**Architecture / engineering**
- A cost ceiling / circuit breaker caps LLM spend per audit. (§4, §7.x, §11)
- The NLI threshold is per-type, not global. (§7.4)
- An idempotency / resume layer lets a failed audit resume instead of restarting. (§7.x)

**Scope realism**
- CONDITIONAL_TRIPLET is **cut from v1** and moved to roadmap. v1 ships five types cleanly. (§3, §6, §8)
- An explicit "no contradiction found" success path is defined and tested. (§7.5, §12)

**Demo / narrative**
- The demo GIF is captured against the real-corpus run, not synthetic data. (§7.7, §13)

---

## 1. Problem & Motivation

Enterprises accumulate overlapping documents: employee handbooks, vendor contracts, master service agreements, engineering specs, medical guidelines, regulatory filings. As these corpora grow, they drift out of sync with themselves. A policy section says one thing; another section, written two years later, says the opposite. A master agreement grants a right; a clause in a subordinate contract revokes it. A medical guideline in version 3.1 deprecates a treatment that version 2.8 still recommends, and both documents remain in the retrieval corpus because nobody pruned the old one.

Existing tools do not solve this well. "Chat with your PDFs" products are reactive — the user must already suspect a conflict exists to ask about one. Contract-review SaaS (Spellbook, Definely, ContractPodAI) treats each document in isolation. Recent academic work (LegalWiz, ContraGen, ArbGraph, Gokul et al. 2025) confirms both that the problem is real and that state-of-the-art models, including GPT-4, still perform only marginally better than chance on raw contradiction detection.

> **[v2] Credibility note.** The point above cuts both ways and the project must be honest about it. If frontier models are barely better than chance on *real* contradiction detection, then a strong F1 on a synthetic benchmark is at least as likely to reflect benchmark easiness as a solved problem. The entire v2 evaluation strategy (§9) exists to separate those two explanations. Do not let the synthetic headline number stand alone.

CrossCheck is a proactive cross-document auditor. Given a corpus, it produces a report of every pair of statements that contradict each other, classified by contradiction type, with direct evidence quotes, source citations, and a calibrated confidence score.

## 2. Definition of Done

The project is complete when all of the following are true:

- A user can run `crosscheck audit ./my-docs/` and receive a JSON and HTML report of contradictions within five minutes for a 100-document corpus on commodity hardware.
- The system supports PDF, DOCX, Markdown, and plain-text input out of the box.
- The README contains a results table with precision, recall, and F1 broken out by each of the **five v1 contradiction types**, measured against the synthetic benchmark that ships with the repo. **[v2]** The same table additionally reports results on the hand-written set and the lexical-overlap strata (§9.2).
- The synthetic benchmark generator is reproducible — running it from a seed produces the same labeled dataset every time.
- **[v2]** The README contains a confidence-calibration plot and a short, explicit statement of the synthetic-vs-real performance gap.
- A Streamlit demo renders a side-by-side view of conflicting passages with highlighted evidence spans and confidence scores.
- End-to-end tests pass in CI, with coverage ≥ 80% on core modules (ingestion, detection, evaluation).
- A 2–3 minute demo video is linked from the README. **[v2]** The demo GIF is captured against the real-corpus run, not synthetic data.
- The repo includes a one-command setup via Docker Compose that boots Qdrant and the API locally.
- **[v2]** An audit hits a configurable cost ceiling cleanly (stops and reports) rather than running unbounded.

## 3. Scope and Non-Goals

**In scope**
- Cross-document contradiction detection across a static corpus.
- **[v2] Five contradiction types in v1:** direct negation, numerical mismatch, temporal/versioning conflict, obligation reversal, scope/jurisdiction conflict.
- English-language documents.
- Document formats: PDF (text-based), DOCX, Markdown, plain text.
- Evaluation harness with synthetic benchmark generator **plus a hand-written validation set**.
- CLI, HTTP API, and Streamlit demo UI.

**Explicit non-goals**
- **[v2] Conditional (triplet) contradictions.** Cut from v1 and moved to roadmap. Partial support of the hardest type produces noisy, unconvincing numbers; v1 ships five types cleanly and lists triplets as future work. The taxonomy and schema leave room for it (§6), but no v1 detection or eval targets it.
- Contradiction resolution. CrossCheck detects and reports; deciding which claim wins is left to humans.
- Real-time generation-time arbitration (this is what ArbGraph does — a different product).
- OCR of scanned PDFs. Only text-extractable PDFs are supported in v1.
- Multi-language corpora. English only.
- Fine-tuning a foundation model. Use pretrained models and prompt engineering only.
- Authentication, user management, or multi-tenancy on the hosted demo.
- Legal advice or any representation that output is authoritative.

## 4. Architecture Overview

CrossCheck runs as an eight-stage pipeline. Each stage is a module with a defined input schema, defined output schema, and an interface that can be swapped for evaluation. Stages run in sequence by an orchestrator; fan-out and batching happen inside stages, not between them.

| # | Stage | Input | Output |
|---|---|---|---|
| 1 | Parse | File path | Structured document with sections |
| 2 | Chunk | Document | Chunks (semantic + overlap) |
| 3 | Extract claims | Chunks | Atomic claims with metadata |
| 4 | Embed & store | Claims | Vector DB records |
| 5 | Generate candidate pairs | Claim | Top-K cross-doc claims (hybrid BM25+dense) |
| 6 | Rerank | Pairs | Reranked pairs |
| 7 | NLI filter | Pairs | Likely-contradiction pairs |
| 8 | LLM judge | Pairs | Verified verdicts with evidence |

The two-stage verification (NLI filter → LLM judge) exists for cost control. LLM judgment is expensive (~$0.003–$0.015 per pair depending on model); NLI is roughly 1000× cheaper. A 500-claim corpus generates on the order of 10,000 candidate pairs after top-K retrieval. Sending all of those to an LLM judge is prohibitive. The NLI filter reduces this to a few hundred high-likelihood pairs, and the LLM judge does the careful reasoning only on those. This is the same pattern used in the ContraGen and Gokul et al. papers; it is the right default and should not be replaced with end-to-end LLM calls.

> **[v2] Cost ceiling.** The orchestrator enforces a configurable per-audit cost ceiling (`max_audit_cost_usd`, default e.g. 5.00) and a per-document cap. The single LLM wrapper (§11) tracks running spend; when the ceiling is reached the orchestrator stops dispatching new judge calls, finalizes the report with what it has, and marks the report `partial: true` with the reason. A runaway corpus must never silently rack up spend.

> **[v2] Resume / idempotency.** Audits are resumable. Each stage writes its outputs keyed by a deterministic content hash (claim cache already does this; extend the pattern to retrieval, NLI, and judge results). An audit that dies at document 90 of 100 resumes from where it stopped rather than restarting from zero. State lives in a small audit-state file plus the existing caches.

### Why not just use LangChain?

Do not use LangChain for this project. Build the pipeline directly with sentence-transformers, the qdrant-client SDK, and the Anthropic SDK. Reasons: (a) each stage has specific control-flow requirements (batching, caching, reranking, cost-capping, resume) that are clearer as plain Python; (b) a heavy framework obscures exactly the engineering depth that an interviewer will want to probe; (c) debuggability is significantly better; (d) the dependency surface is far smaller. LlamaIndex is acceptable for document parsing helpers only, not for orchestration.

## 5. Prescriptive Tech Stack

These choices are opinionated. Follow them unless there is a concrete, documented reason to deviate. If Claude Code substitutes a component, it must note the substitution in `DECISIONS.md` with rationale.

**Core runtime**

| Component | Choice | Rationale |
|---|---|---|
| Language | Python 3.11+ | Type hints, async support, ecosystem. |
| Package manager | uv (Astral) | Fast, reproducible, modern lock format. |
| Data validation | Pydantic v2 | Schema enforcement across module boundaries. |
| Config | pydantic-settings + .env | Typed config, no hardcoded strings. |
| CLI | Typer | Clean decorator-based CLI with type-driven parsing. |
| Logging | Loguru | Structured logs with zero setup. |
| Testing | pytest + hypothesis | Property-based tests for claim extractor. |
| Lint/type | ruff + mypy --strict | Hard failures in CI. |

**AI / ML components**

| Component | Choice | Rationale |
|---|---|---|
| Embedding model | BAAI/bge-large-en-v1.5 | Top-tier open-source, runs locally, no API cost. |
| Lexical retrieval **[v2]** | BM25 (e.g. rank_bm25 or Qdrant sparse vectors) | Required for the hybrid default; catches low-similarity contradictions. |
| Vector DB | Qdrant (self-hosted via Docker) | Production-grade, strong metadata filtering, Rust-backed performance. |
| Reranker | BAAI/bge-reranker-v2-m3 | Cross-encoder, excellent for pair reranking. |
| NLI model | cross-encoder/nli-deberta-v3-base | Fast 3-way NLI (entail / contradict / neutral). |
| LLM judge | Claude Sonnet 4.6 (anthropic SDK) | Strong reasoning, native fit with Claude Code. |
| Fallback / cross-judge LLM | GPT-4o (via openai SDK) | Config-swappable; also used as the cross-model judge in eval. |
| Benchmark generator LLM **[v2]** | A *different family* from the judge (e.g. generate with GPT-4o, judge with Claude, or vice versa) | Avoids self-recognition bias in synthetic eval. |
| Doc parsing | pdfplumber, python-docx, markdown-it-py | Format-specific; no mega-framework needed. |

**Service layer**

| Component | Choice | Rationale |
|---|---|---|
| HTTP API | FastAPI + uvicorn | Async, pydantic-native, OpenAPI for free. |
| Demo UI | Streamlit (v1), optional Next.js (stretch) | Streamlit ships fast; Next.js if polish time remains. |
| Containerization | Docker + docker-compose | One-command local boot (API + Qdrant). |
| CI | GitHub Actions | Run ruff, mypy, pytest, build image. |

## 6. Contradiction Taxonomy

CrossCheck classifies contradictions into a taxonomy inspired by LegalWiz (Mantravadi et al. 2025) and Gokul et al. 2025, generalized beyond the legal domain. Every detection must carry a type label; unknown or ambiguous cases are reported with type `UNCLEAR` and a low confidence score rather than dropped.

**v1 ships these five types:**

| Type | Definition | Example |
|---|---|---|
| DIRECT_NEGATION | One claim is the logical opposite of the other. | "All employees receive 20 PTO days." vs. "Employees are not entitled to PTO." |
| NUMERICAL_MISMATCH | Same subject, different quantities, dates, or thresholds. | "Refunds within 30 days." vs. "Refunds within 60 days." |
| TEMPORAL_CONFLICT | One claim supersedes/deprecates/postdates another, but both remain active in the corpus. | v3.1 guideline deprecates a treatment; v2.8 still in retrieval pool recommends it. |
| OBLIGATION_REVERSAL | One claim mandates an action; another prohibits or exempts from it. | "Vendors must carry liability insurance." vs. "Vendors are not required to carry insurance." |
| SCOPE_JURISDICTION | Claims agree in the general case but diverge by scope or jurisdiction. | "All contracts governed by Delaware law." vs. "EU vendor contracts governed by Irish law." |

> **[v2] Roadmap: CONDITIONAL_TRIPLET.** Three documents where A asserts X under condition C1, B asserts Y under C2, C1 and C2 overlap, and X, Y are incompatible. This is the hardest type and where off-the-shelf NLI performs worst. It is **out of scope for v1.** Keep the enum value reserved in `taxonomy.py` and leave the schema able to express it, but build no v1 detection or eval for it. Document it in the README as the headline roadmap item. Rationale: shipping the five well-trodden types with unusual rigor is a stronger portfolio signal than shipping a sixth, noisy, half-working type.

## 7. Module Specifications

### 7.1 Ingestion — `crosscheck.ingestion`

`parsers.py` exposes a single entry point `parse(path: Path) -> Document` that dispatches on file extension. Each format-specific parser returns a `Document` (pydantic) with an ordered list of `Section` objects. Preserve section headings, page numbers where available, and list structure. Discard headers/footers in PDFs using a simple repetition heuristic.

```python
class Document(BaseModel):
    doc_id: str
    source_path: Path
    title: str | None
    sections: list[Section]
    metadata: dict[str, Any]

class Section(BaseModel):
    section_id: str
    heading: str | None
    text: str
    page_span: tuple[int, int] | None
```

`chunking.py` splits sections into chunks of 200–400 tokens with 50-token overlap. Use sentence-aware splitting (via `nltk.sent_tokenize` or spaCy). Each chunk carries its source section, offsets, and document metadata through the pipeline.

`claim_extractor.py` is the most delicate component. It uses an LLM prompt to extract atomic claims from a chunk. A claim is a single assertion that can be independently verified or contradicted. Non-claims (opinions, questions, examples, definitions without assertion) must be excluded. Use structured output (JSON mode) with this schema:

```python
class Claim(BaseModel):
    claim_id: str                  # deterministic hash of doc_id+chunk+offset
    doc_id: str
    section_id: str
    text: str                      # normalized, decontextualized claim
    evidence_quote: str            # verbatim span from source
    evidence_offset: tuple[int,int]
    subject: str
    predicate: str
    conditions: list[str]
    polarity: Literal['positive','negative']
    quantitative: dict | None      # {number, unit, operator} if numeric
```

The claim extractor must **decontextualize** — rewrite pronouns and ellipses so the claim stands alone. Cache extraction results keyed on a hash of the chunk text to avoid re-spending tokens on reruns. Budget ~1500 output tokens per chunk; batch chunks of 3–5 per LLM call to amortize system-prompt overhead.

> **[v2] Decontextualization check.** After extraction, run a cheap validator that flags claims still containing unresolved references — leading/standalone pronouns ("it", "this", "they") without an antecedent, dangling demonstratives, or elliptical fragments. Flagged claims are logged and counted as an observability metric (`decontextualization_failure_rate`). Bad decontextualization silently poisons every downstream stage, so it must be visible.

> **[v2] Extraction gold set.** Extraction quality is measured on its own, not just end-to-end. Hand-label a small set (~50 chunks) for "is each extracted claim atomic, decontextualized, and correctly typed by polarity," and report claim-extraction precision/recall separately in the eval report. End-to-end F1 cannot tell you whether a miss came from extraction or detection; this gold set can.

### 7.2 Storage — `crosscheck.storage`

Qdrant is the system of record. Create a single collection `claims` with dense vector size 1024 (bge-large) and payload including all claim fields. **[v2]** Also store a sparse (BM25) representation per claim so hybrid retrieval can be done in-engine. Use Qdrant's payload indexing on `doc_id`, `subject`, and `polarity` for efficient filtered search. The repo layer `ClaimRepo` exposes: `upsert(claims)`, `search(vector, filters, top_k)`, `get(claim_id)`, `count()`.

### 7.3 Candidate Pair Generation — `crosscheck.retrieval`

For each claim, retrieve the top-25 most similar claims from *other* documents (filter `doc_id != self.doc_id`). Deduplicate pairs (A,B) and (B,A). Rerank with the cross-encoder reranker; keep top-10. This is the critical performance knob — tune K based on eval results.

> **[v2] Hybrid is the default.** Use hybrid **BM25 + dense** retrieval as the default strategy, not an optional ablation. Many contradiction types are not semantically close in embedding space — obligation reversals and scope conflicts are often phrased very differently even when they conflict. Pure dense retrieval will miss them and silently cap the whole system. Keep dense-only and MMR available behind the pluggable interface for ablation, but ship hybrid.

> **[v2] Negation sensitivity.** Embeddings place "X is required" and "X is not required" unpredictably — sometimes adjacent, sometimes far apart. Add a targeted test: a fixture set of known negation pairs, asserting they appear in the top-K after retrieval+rerank. Report negation-pair retrieval recall as its own line in the metrics.

Export a pluggable interface so retrieval strategies (dense only, hybrid BM25+dense, MMR) can be swapped for evaluation.

### 7.4 Detection — `crosscheck.detection`

`nli_filter.py` runs the DeBERTa NLI cross-encoder on each candidate pair. Keep pairs where `P(contradiction) > threshold` or `P(contradiction)` is the argmax of the three labels.

> **[v2] Per-type thresholds.** The NLI threshold is **per contradiction type**, not a single global value. Numerical mismatch and direct negation calibrate very differently from scope/jurisdiction conflicts. Thresholds are config values; calibrate each against the synthetic benchmark, targeting ≥95% recall at this stage (precision is recovered by the LLM judge). Where a pair's likely type is unknown pre-judge, use the most permissive applicable threshold.

`llm_judge.py` is the final verdict stage. For each pair that passes the NLI filter, construct a prompt that includes the two claims, their source document metadata, and surrounding context. The LLM returns structured output:

```python
class Verdict(BaseModel):
    pair_id: str
    is_contradiction: bool
    contradiction_type: ContradictionType | None
    confidence: float              # 0.0 to 1.0
    rationale: str                 # chain-of-thought explanation
    evidence_a: str                # verbatim quote from claim A
    evidence_b: str                # verbatim quote from claim B
    resolution_hint: str | None    # which to trust, if obvious
```

The prompt must instruct the model to quote verbatim from the provided claims only — no fabrication. Validate post-hoc that `evidence_a` and `evidence_b` are substrings of the source. Reject verdicts that fail this substring check and log them as judge-hallucinations (an observability metric you will report on).

### 7.5 Aggregation — `crosscheck.aggregation`

Build a `ContradictionReport` that groups verdicts by subject, sorts by confidence, and cross-links to source documents. Export as JSON (machine-readable) and HTML (human-readable, side-by-side evidence view with syntax highlighting on source quotes). The HTML export is the demo artifact — invest in its polish.

> **[v2] Empty-report success path.** A corpus with no contradictions is a valid, important result, not an error. Define and test the "no contradiction found" path explicitly: the report renders a confident, clearly-worded empty state ("No contradictions detected across N documents / M claim pairs evaluated"), the JSON is well-formed with an empty findings array, and the HTML/Streamlit empty state is designed, not blank. Demos frequently break here.

### 7.6 Evaluation — `crosscheck.evaluation`

The evaluation module is first-class, not a helper. It is the project's differentiator. See Section 9 for the full strategy; the module shape is:

- `synthetic_gen.py` — generates a labeled benchmark corpus. Takes a seed of real documents, uses an LLM (**[v2]** a different family from the judge) to inject contradictions of each v1 taxonomy type, records gold labels (pair_id, type, evidence spans), and writes to `benchmarks/synthetic/`. Deterministic given a seed.
- **[v2]** `handwritten/` — a small, human-authored contradiction set (20–30 pairs) with gold labels, kept separate from generated data.
- `metrics.py` — computes precision, recall, F1 per contradiction type; retrieval recall @ K (including the negation-pair subset); pair-level and corpus-level ROC; **[v2]** lexical-overlap-stratified F1; **[v2]** confidence calibration; claim-extraction precision/recall; judge-hallucination rate; decontextualization-failure rate; end-to-end latency and cost per document.
- `runner.py` — orchestrates an eval run: loads benchmark(s), runs the pipeline, collects verdicts, computes metrics, writes a markdown report to `benchmarks/results/<timestamp>/`.

### 7.7 API and UI — `crosscheck.api`, `ui/`

FastAPI routes: `POST /ingest` (multipart upload), `POST /audit` (start audit of ingested corpus), `GET /audit/{id}` (poll status and retrieve report), `GET /health`. Audits run in a background task; return a `202` with a task ID immediately. For v1, in-process task tracking is fine — do not introduce Celery. **[v2]** Audit status responses surface running cost and `partial` state so a ceiling-stopped audit is visible to the caller.

The Streamlit UI is the demo. Three screens: (1) upload, (2) progress, (3) results. The results view shows contradictions grouped by type, with each contradiction as an expandable card: two side-by-side passages with evidence spans highlighted in yellow, the verdict rationale below, and confidence rendered as a colored bar. **[v2]** It also handles the empty-result state gracefully.

> **[v2] Demo GIF source.** Capture the demo GIF against the **real-corpus run** (e.g. NIST SP 800-53 Rev 4 vs Rev 5), not synthetic data. "Found a real conflict in NIST" is far more compelling on screen than an injected example, and it reinforces the project's honesty about the synthetic-vs-real gap.

## 8. Phased Build Plan (14 Weeks)

Assumes ~15 hours per week. Each phase produces a working, testable artifact — no big-bang integration at the end. If a phase slips by more than one week, descope rather than extend; the eval and demo phases are non-negotiable.

**Phase 0 (Week 1) — Foundation.** Repo scaffold, `pyproject.toml` with uv, pydantic models for Document/Claim/Verdict, config system (including cost-ceiling settings), logging, docker-compose with Qdrant, CI workflow (ruff + mypy + pytest on push), empty-but-passing test suite, `DECISIONS.md` created.

**Phase 1 (Weeks 2–3) — Ingestion pipeline.** Parsers for PDF/DOCX/MD/TXT, sentence-aware chunker, claim extractor with caching, batching, and **[v2]** the decontextualization check. Integration test: ingest a sample 10-document corpus and produce ≥200 well-formed claims. **[v2]** Stand up the extraction gold set.

**Phase 2 (Weeks 4–5) — Storage and retrieval.** Qdrant integration (dense + sparse), `ClaimRepo`, candidate pair generation with **[v2] hybrid BM25+dense default** and cross-encoder rerank. Integration test: retrieve top-10 cross-document candidates with correct filtering; **[v2]** negation-pair retrieval test passes.

**Phase 3 (Weeks 6–7) — Detection pipeline.** NLI filter with **[v2] per-type thresholds**, LLM judge with structured output and substring evidence validation, end-to-end pipeline runnable via CLI with the **[v2] cost ceiling and resume layer** wired in. Smoke test: run on a 10-doc corpus and produce a non-empty report.

**Phase 4 (Week 8) — Aggregation and reporting.** Report builder, JSON export, HTML export with side-by-side view and **[v2] designed empty state**. Mock up the HTML before coding.

**Phase 5 (Weeks 9–10) — Synthetic benchmark + hand-written set.** Contradiction injection for the five v1 types using **[v2] a non-judge model family**, deterministic generation from seed, gold label schema, ~200-pair benchmark shipped in the repo. **[v2]** Author the 20–30-pair hand-written set. Target: ≥85% of injected contradictions pass human review of gold labels.

**Phase 6 (Week 11) — Evaluation harness, tuning, and real-corpus check.** Metrics module (incl. **[v2]** lexical-overlap strata and calibration), runner, first end-to-end eval report. Tune per-type NLI thresholds, retrieval K, judge temperature. **[v2] Run the real-corpus sanity check here, not in Phase 9** — it is the most credible result and you want time to react to it. Produce the headline numbers for the README.

**Phase 7 (Week 12) — API and service layer.** FastAPI endpoints, background task handling, cost/partial surfacing, Dockerfile, docker-compose for full stack. curl-able API end-to-end.

**Phase 8 (Week 13) — Streamlit demo.** Upload → progress → results UI. Polish: loading, empty, error states. Deploy to Streamlit Community Cloud or Fly.io.

**Phase 9 (Week 14) — Documentation and demo video.** Complete README with problem statement, **[v2] real-corpus demo GIF**, quickstart, results table, **[v2] calibration plot and synthetic-vs-real gap statement**, architecture diagram, design decisions, references. 2–3 minute demo video. Final CI green. Tag v0.1.0.

## 9. Evaluation Strategy

This is the core differentiator. Other portfolio projects wave at evaluation. CrossCheck leads with it. The README's headline numbers come from this section — and so does its credibility.

### 9.1 Benchmark generation

Start with a seed corpus of real, publicly-available documents in a single domain (suggest: NIST Cybersecurity Framework documents, HIPAA-related guidance, or GDPR regulatory texts — all public, English, structured). For each v1 contradiction type, use an LLM with a crafted prompt to generate a contradictory claim and inject it into a paired document. Record the gold label: which pair contradicts, which type, which evidence spans support the judgment.

Target: ~200 labeled pairs covering the five v1 types. Deterministic from a seed so re-runs produce identical benchmarks. Ship under `benchmarks/synthetic/v1/`. Manually review ~10% of injected contradictions and document any that are implausible or mislabeled (Gokul et al. had this problem and called it out explicitly).

> **[v2] Cross-model generation.** Generate the synthetic benchmark with a *different model family* than the one used as the judge. If you judge with Claude Sonnet 4.6, generate with GPT-4o (or vice versa). Otherwise you are partly measuring a model's ability to recognize its own output style, which inflates scores in a way that does not transfer to real corpora.

> **[v2] Hand-written validation set.** Author a small (20–30 pair) hand-written contradiction set drawn from realistic phrasing, kept in `benchmarks/handwritten/`. Injected contradictions are cleaner and more lexically obvious than real drift; the hand-written set exists to expose that gap. Report its metrics separately. Expect lower numbers here — that is the point, and reporting them honestly is a strength.

### 9.2 Metrics

At minimum, report the following, broken out by contradiction type:

- **Pair-level precision, recall, F1** — did the system correctly classify each candidate pair?
- **[v2] Lexical-overlap-stratified F1** — the same metrics split by high vs low surface similarity between the two claims. This reveals whether the system only catches near-duplicate phrasing. A system that scores well overall but collapses on the low-overlap stratum is not actually solving the problem.
- **Retrieval recall @ K** — fraction of gold contradiction pairs appearing in top-K candidates after retrieval+reranking, **[v2]** including the negation-pair subset as its own line.
- **[v2] Claim-extraction precision/recall** — measured against the extraction gold set, separate from end-to-end.
- **Judge-hallucination rate** — fraction of LLM verdicts whose evidence quotes failed substring validation.
- **[v2] Decontextualization-failure rate** — fraction of claims flagged with unresolved references.
- **[v2] Confidence calibration** — a reliability plot of predicted confidence vs actual correctness, plus a scalar (e.g. expected calibration error). Almost no portfolio project shows calibration; it signals real rigor.
- **End-to-end latency** — wall-clock per document at P50 and P95.
- **End-to-end cost** — USD per 100 documents at default config.

### 9.3 Ablations to report

Pick three to run and report:

- NLI filter on vs. off — quantify cost savings and recall loss.
- Reranker on vs. off — quantify precision uplift.
- **[v2]** Hybrid vs. dense-only retrieval — quantify recall delta, especially on the low-overlap stratum (this justifies making hybrid the default).
- Claude Sonnet 4.6 vs. GPT-4o for the judge — quantify agreement rate and per-type accuracy.
- (Optional) BGE-large vs. OpenAI text-embedding-3 — quantify retrieval recall delta.

### 9.4 Real-corpus sanity check

Synthetic evaluation is not enough. Run the system on one real, public, potentially-conflicting corpus — for example, an older and newer version of the same regulation (NIST SP 800-53 Rev 4 vs. Rev 5), or overlapping ISO standards. Manually inspect the top-20 reported contradictions and report hit rate.

> **[v2]** Do this in **Phase 6**, not at the end. It is the anecdote that sells the project ("I ran it on NIST X and found 7 real conflicts in the top 10, two of which were news to me"), the source of the demo GIF, and the most likely place to discover that synthetic numbers are not transferring. Discovering that in Week 11 leaves room to fix it; discovering it in Week 14 does not.

## 10. Repository Structure

```
crosscheck/
├── README.md                  # Problem → real-corpus demo GIF → quickstart → results + calibration
├── CLAUDE.md                  # This spec, markdown form, for Claude Code
├── DECISIONS.md               # Running log of engineering decisions
├── pyproject.toml             # uv + project metadata
├── uv.lock
├── .env.example
├── docker-compose.yml         # Qdrant + API
├── Dockerfile
├── .github/workflows/ci.yml
│
├── src/crosscheck/
│   ├── __init__.py
│   ├── config.py              # Pydantic settings (incl. cost ceiling)
│   ├── models.py              # Document, Claim, Pair, Verdict
│   ├── cli.py                 # Typer entry point
│   ├── llm.py                 # single LLM wrapper: retries, logging, cost tracking + ceiling
│   ├── prompts/               # versioned prompt files
│   ├── ingestion/
│   │   ├── parsers.py
│   │   ├── chunking.py
│   │   └── claim_extractor.py # incl. decontextualization check
│   ├── storage/
│   │   ├── qdrant_client.py
│   │   └── claim_repo.py
│   ├── retrieval/
│   │   ├── candidate_gen.py   # hybrid BM25+dense default
│   │   └── reranker.py
│   ├── detection/
│   │   ├── taxonomy.py        # 5 v1 types + reserved TRIPLET
│   │   ├── nli_filter.py      # per-type thresholds
│   │   └── llm_judge.py
│   ├── aggregation/
│   │   ├── report.py          # incl. empty-report path
│   │   └── html_renderer.py
│   ├── evaluation/
│   │   ├── synthetic_gen.py   # cross-model generation
│   │   ├── metrics.py         # incl. strata, calibration, extraction gold
│   │   └── runner.py
│   ├── orchestrator.py        # audit() entry; cost ceiling + resume
│   └── api/
│       └── main.py
│
├── ui/
│   └── streamlit_app.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── benchmarks/
│   ├── synthetic/v1/          # generated corpus + gold labels
│   ├── handwritten/           # hand-authored validation set
│   └── results/               # timestamped eval reports
│
├── docs/
│   ├── architecture.md
│   ├── eval-report.md         # headline numbers, rendered from eval runner
│   └── demo.gif               # captured from real-corpus run
│
└── scripts/
    ├── setup.sh
    └── generate_benchmark.py
```

## 11. Coding Conventions

- Python 3.11+ features only (match statements, native generics).
- Type hints on every function signature. `mypy --strict` must pass.
- Pydantic v2 for all data crossing module boundaries. No bare dicts in public APIs.
- Ruff as both linter and formatter. Config in `pyproject.toml`; no black.
- Docstrings on every public function/class. Google style.
- No wildcard imports. No bare `except:` without a specific exception type.
- Prefer composition over inheritance. No class hierarchies deeper than two levels.
- All LLM calls go through a single wrapper `crosscheck.llm.call()` that handles retries, logging, **and cost tracking that feeds the audit cost ceiling**. No scattered `client.messages.create()` calls.
- Every LLM prompt lives in a versioned prompt file under `src/crosscheck/prompts/`. Prompts are not inlined in Python.
- Structured logging with Loguru. INFO for pipeline stages, DEBUG for per-item detail, WARNING for degraded operation (including ceiling-stopped audits), ERROR only for actionable failures.

## 12. Testing Strategy

- **Unit tests** — every module has tests. Mock LLM responses using pre-recorded fixtures; no real API calls in unit tests. Target 80%+ coverage on core modules.
- **Integration tests** — end-to-end pipeline run on a 3-document fixture corpus. Real LLM calls allowed, marked `@pytest.mark.integration`, skipped by default in CI unless `ANTHROPIC_API_KEY` is set.
- **Property tests (hypothesis)** — for the claim extractor: generated claims must satisfy invariants (evidence_quote is substring of chunk, polarity matches semantics, offsets are valid).
- **[v2] Negation-retrieval test** — known negation pairs must survive retrieval+rerank into top-K.
- **[v2] Empty-corpus test** — a contradiction-free fixture produces a well-formed empty report and a graceful empty UI state.
- **[v2] Cost-ceiling test** — an audit with a low ceiling stops cleanly, finalizes a `partial` report, and does not exceed the cap.
- **Benchmark tests** — `@pytest.mark.benchmark`, run on demand, report metrics to `benchmarks/results/`.
- **Regression snapshots** — the end-to-end pipeline produces a deterministic report on a frozen 5-document fixture (LLM calls mocked). Committed; any change must be deliberate.

## 13. Final Deliverables

The repository root must contain, at minimum:

- A README opening with a one-sentence pitch, a **[v2] real-corpus demo GIF**, a 60-second quickstart, the headline evaluation table (five types), **[v2] the confidence-calibration plot, and an explicit synthetic-vs-real gap statement**.
- A working `docker-compose up` that boots the full stack locally.
- A reproducible eval report at `docs/eval-report.md` with numbers per contradiction type, **[v2] plus hand-written-set and lexical-overlap-strata results**.
- A 2–3 minute demo video (Loom or YouTube, unlisted) linked from the README.
- A deployed Streamlit demo URL (Streamlit Community Cloud is fine).
- `DECISIONS.md` capturing non-obvious choices made during the build.
- Tagged release `v0.1.0` on GitHub.

## 14. Anti-Patterns to Avoid

- Reaching for LangChain or LlamaIndex agents to avoid writing orchestration code. The orchestration is the engineering; don't hide it.
- Treating evaluation as a final-week task. Start the synthetic benchmark by Week 9 — it takes longer than expected.
- **[v2] Letting the synthetic headline number stand alone.** Always pair it with the hand-written-set numbers, the low-overlap stratum, and the real-corpus anecdote. Over-claiming from synthetic data is the single biggest credibility risk.
- **[v2] Shipping CONDITIONAL_TRIPLET as half-working.** Cut it cleanly to roadmap; partial support of the hardest type produces unconvincing numbers.
- Inlining prompts in Python code. Use the `prompts/` directory.
- Shipping without a demo GIF. The GIF is a dealbreaker for recruiter skim.
- Over-engineering the UI at the expense of eval rigor. Streamlit is fine; real numbers matter more than React.
- Letting LLM judge output go unvalidated. Substring-check every evidence quote.
- **[v2] Letting an audit run unbounded.** The cost ceiling is mandatory, not optional.
- Padding the README with AI-generated prose. Write it tight; let the numbers do the work.
- Adding features that aren't on this spec. If in doubt, descope.

## 15. References

- Gokul, Tenneti, Nakkiran (2025). *Contradiction Detection in RAG Systems: Evaluating LLMs as Context Validators.* arXiv:2504.00180. Motivates the two-stage NLI→LLM architecture.
- Mantravadi et al. (2025). *LegalWiz: A Multi-Agent Generation Framework for Contradiction Detection in Legal Documents.* arXiv:2510.03418. Source of the taxonomy and synthetic benchmark methodology.
- Li, Raheja, Kumar (2023). *ContraDoc: Understanding Self-Contradictions in Documents with LLMs.* arXiv:2311.09182.
- ArbGraph (2026). github.com/1212Judy/ArbGraph. Generation-time arbitration — the adjacent direction CrossCheck differentiates from.
- Koreeda, Manning (2021). *ContractNLI.* arXiv:2110.01799. Document-level NLI, the foundational benchmark.

— End of specification (v2). This is already in markdown — copy it to `CLAUDE.md` at the repo root before starting the build. —
