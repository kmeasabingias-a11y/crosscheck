# DECISIONS.md — CrossCheck

This is my running log of the engineering decisions I make while building CrossCheck. I
record each decision in the same session I make it: what I decided, the options I weighed,
why I chose what I chose, and what I gave up. Decisions are numbered (`D1`, `D2`, …) and
dated so the walkthroughs and code comments can cross-reference them.

The project spec (`CLAUDE.md`, Part 2) is prescriptive about the tech stack. Where a
decision simply follows the spec, I still record it here with the rationale, so the "why"
lives in one place. Where I deviate from the spec, the entry says so explicitly.

Format for each entry: **date · decision · options considered · rationale and trade-offs
(what I gave up) · who proposed it**.

---

## D1 — src-layout with a single `crosscheck` package (2026-07-02)

**Decision.** The importable code lives under `src/crosscheck/`, installed as the
distribution `crosscheck`. Tests live in a top-level `tests/` tree, outside the package.

**Options considered.** (a) Flat layout (`crosscheck/` at the repo root); (b) src-layout
(`src/crosscheck/`).

**Rationale / trade-offs.** src-layout forces tests to run against the *installed* package
rather than accidentally importing from the working directory, which catches packaging
mistakes (missing `__init__.py`, files not shipped in the wheel) early. The cost is one
extra directory level and needing an editable install (`uv pip install -e .`) before tests
see the code — a fair trade for a project that ships as an installable CLI. This matches
the repo layout in the spec (§10).

**Proposed by me**, following the spec.

---

## D2 — uv for dependency management, hatchling as the build backend (2026-07-02)

**Decision.** `uv` manages the environment and lockfile; `hatchling` is the PEP 517 build
backend declared in `pyproject.toml`.

**Options considered.** Backend: hatchling vs. setuptools vs. uv's own `uv_build`.
Manager: uv (spec-mandated) vs. Poetry/pip-tools.

**Rationale / trade-offs.** uv is mandated by the spec (§5) — fast, reproducible, modern
lock format. For the build backend I chose hatchling because it is the most widely used,
well-documented default, handles src-layout with a one-line `packages` setting, and is
completely independent of the resolver so we are not coupling build to uv internals. I
gave up uv_build's marginally simpler config in exchange for the safer, better-understood
option. setuptools would work but its configuration surface is noisier.

**Proposed by me**, following the spec for uv.

---

## D3 — Pin Python to 3.11 (2026-07-02)

**Decision.** `requires-python = ">=3.11"` and `.python-version` pins `3.11`. mypy and ruff
target `py311`.

**Options considered.** 3.11 vs. 3.12 (spec says "3.11+").

**Rationale / trade-offs.** The heavy ML dependencies that arrive in later phases
(`torch`, `sentence-transformers`, `transformers`) have the most reliable prebuilt wheels
on 3.11, and 3.11 already gives us everything the spec's conventions require — `match`
statements and native generic syntax (§11). 3.12 offers nothing this project needs and
occasionally lags on ML wheel availability. What I gave up: a few 3.12 performance and
typing niceties. Easy to bump later if a dependency requires it.

**Proposed by me.** Open to changing to 3.12 if preferred.

---

## D4 — Grow dependencies phase-by-phase, not all up front (2026-07-02)

**Decision.** Phase 0's `pyproject.toml` declares only what Phases 0–1 actually use
(pydantic, pydantic-settings, typer, loguru, plus the dev toolchain). Heavier runtime
dependencies (anthropic, openai, qdrant-client, sentence-transformers, rank-bm25,
pdfplumber, python-docx, markdown-it-py, fastapi, uvicorn, streamlit, torch, transformers)
are added to the dependency list as the phase that needs them lands, each noted here.

**Options considered.** (a) Declare the entire spec stack in Phase 0; (b) add per phase.

**Rationale / trade-offs.** Installing torch and the transformer models in Phase 0 would
make every CI run slow and the dev environment large while we are only building pydantic
models, config, and tests — none of which need them. Adding dependencies as their phase
arrives keeps CI fast and the surface small early, and makes the lockfile diff for each
phase a readable record of what that phase pulled in. The cost is that `pyproject.toml`
grows over time and I have to remember to add each dependency with its phase — acceptable,
and each addition gets a line here.

**Proposed by me.**

---

## D5 — Loguru for logging; the setup file is named `logging_config.py` (2026-07-02)

**Decision.** Logging uses Loguru (spec §5/§11). The setup module is
`src/crosscheck/logging_config.py`, exposing a single `configure_logging(settings)` called
once at startup.

**Options considered.** File name `logging.py` vs. `logging_config.py`. (The library
choice, Loguru, is spec-mandated.)

**Rationale / trade-offs.** A module literally named `logging.py` inside the package risks
shadowing Python's stdlib `logging` on certain import paths and produces baffling errors;
`logging_config.py` avoids that entirely. The spec's repo layout (§10) doesn't name a
logging file, so I chose the location and name; everything else follows the spec's Loguru
mandate. No real trade-off.

**Proposed by me**, following the spec for Loguru.

---

## D6 — License: MIT (2026-07-02)

**Decision.** The project is MIT-licensed.

**Options considered.** MIT vs. Apache-2.0 vs. no license (all-rights-reserved).

**Rationale / trade-offs.** MIT is the conventional, frictionless choice for a portfolio
project meant to be read and reused; it maximizes the chance a reviewer can run and study
the code without legal questions. Apache-2.0 adds an explicit patent grant we don't need
here; "no license" would make the public repo legally unusable by others, undercutting the
portfolio goal. What I gave up vs. Apache-2.0: the explicit patent language — irrelevant
for this project.

**Proposed by me.** Open to changing.

---

## D7 — ruff as linter *and* formatter; mypy `--strict` with the pydantic plugin (2026-07-02)

**Decision.** ruff is the single lint+format tool (no black). mypy runs in `--strict` mode
with the `pydantic.mypy` plugin enabled. Both are configured in `pyproject.toml` and both
are hard failures in CI.

**Options considered.** black+ruff vs. ruff-only formatting; mypy strict vs. relaxed.

**Rationale / trade-offs.** The spec (§5, §11) mandates ruff-as-formatter and
`mypy --strict`. Running ruff for both roles removes a redundant tool and a possible
formatter disagreement. The pydantic plugin teaches mypy how pydantic models construct, so
strict mode doesn't drown us in false positives on model fields. The cost of strict mode is
more up-front annotation work; that's exactly the discipline the spec wants and it pays off
across module boundaries.

**Proposed by me**, following the spec.

---

## D8 — Phase 0 `docker-compose.yml` ships Qdrant only (2026-07-02)

**Decision.** The Phase 0 compose file defines only the Qdrant service. The full stack
(the CrossCheck API image + Qdrant) is assembled in Phase 7, once the `Dockerfile` exists.

**Options considered.** (a) Full API+Qdrant compose now with a placeholder build; (b)
Qdrant-only now, extend in Phase 7.

**Rationale / trade-offs.** There is no application image to build in Phase 0 — the API
module doesn't exist until Phase 7 — so a compose service pointing at a non-existent
Dockerfile would fail `docker compose up`. Shipping Qdrant alone gives us a real, bootable
vector DB for the storage/retrieval phases immediately, and Phase 7 adds the API service to
the same file. The spec's Phase 0 deliverable is exactly "docker-compose with Qdrant"; the
one-command full-stack boot is a Phase 7 / §2 item. No meaningful trade-off.

**Proposed by me**, following the spec's phasing.

---

## D9 — Config design: `CROSSCHECK_` prefix, unprefixed provider keys, `validate_by_name`, cost-ceiling defaults (2026-07-02)

**Decision.** The `Settings` panel (`config.py`) uses `env_prefix="CROSSCHECK_"` for project
settings, but reads the two provider API keys from their **standard unprefixed names**
(`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) via `AliasChoices`, also accepting the prefixed
variants. `validate_by_name=True` is set on the model. The cost ceiling defaults are
`max_audit_cost_usd = 5.00` and `max_document_cost_usd = 0.50`, both guarded with `ge=0.0`.

**Options considered.**
- *Key naming:* prefix everything (`CROSSCHECK_ANTHROPIC_API_KEY`) vs. accept the providers'
  standard names.
- *The mypy `warn_required_dynamic_aliases` error from `AliasChoices`:* (a) add
  `validate_by_name=True` to the model; (b) disable `warn_required_dynamic_aliases` in the
  pydantic-mypy plugin config; (c) drop `AliasChoices` and resolve keys manually.
- *Cost defaults:* the spec suggests ~5.00 for the audit ceiling; the per-document cap and the
  numeric guard were mine to set.

**Rationale / trade-offs.** Accepting the unprefixed key names means a developer who already
has `ANTHROPIC_API_KEY` exported (the near-universal convention) needs no duplication — the
prefixed variant still works for anyone who wants namespacing. For the mypy error I chose
`validate_by_name=True` (option a) over disabling the plugin check (b): it's a targeted fix
that keeps the strict check active for every *other* model, and as a bonus lets tests construct
`Settings(anthropic_api_key="…")` directly instead of monkeypatching the environment.
Environment loading is unaffected because `validate_by_alias` stays on by default. I rejected
(c) as needless hand-rolled code. I verified on pydantic 2.13.4 that `validate_by_name` (the
current keyword; `populate_by_name` is the deprecated spelling) silences the error with no
runtime deprecation warning. `ge=0.0` rejects a negative budget at construction while allowing
`0.0` as a meaningful "spend nothing" value that the spec's cost-ceiling test relies on. What I
gave up: nothing material — the strict check remains everywhere else.

**Proposed by me**, following the spec for the cost ceiling.

---

## D10 — Schema design: `extra="forbid"` base, typed `Quantitative`, id-based `Pair`, reserved taxonomy (2026-07-02)

**Decision.** All pipeline schemas (`Section`, `Document`, `Quantitative`, `Claim`, `Pair`,
`Verdict`) inherit a shared `CrossCheckModel` base that sets `extra="forbid"`. The claim's
numeric core is a typed `Quantitative` model, not a bare dict. `Pair` carries the two claim
**ids** plus optional per-stage scores rather than embedding full `Claim` objects. The
`ContradictionType` taxonomy (`StrEnum`) keeps the five v1 types plus `UNCLEAR` and a
reserved, inert `CONDITIONAL_TRIPLET`, with a `V1_TYPES` frozenset naming only the five that
v1 detects.

**Options considered.**
- *Unknown fields:* pydantic default (`extra="ignore"`) vs. `extra="forbid"`.
- *Quantitative:* the spec's illustrative `dict | None` vs. a typed sub-model.
- *Pair:* embed full `Claim` objects vs. store claim ids and resolve from the repository.
- *Reserved type:* omit `CONDITIONAL_TRIPLET` entirely vs. keep it in the enum but inert.

**Rationale / trade-offs.** `extra="forbid"` turns schema drift into a loud failure exactly
where it's cheapest to catch — when parsing LLM structured output into a `Claim`/`Verdict`, a
hallucinated or renamed key raises instead of being silently dropped; it also pairs with the
`init_forbid_extra` mypy setting from D7. The cost is that a provider legitimately adding a
field means updating the model, which is the correct, deliberate response anyway. I typed
`Quantitative` because §11 forbids bare dicts in public APIs and the `{number, unit, operator}`
shape is known; `Document.metadata` stays `dict[str, Any]` as the justified exception (metadata
is genuinely open-ended). `Pair` stores ids because Qdrant is the system of record (§7.2), so
embedding claims would duplicate state and bloat the edge; the trade-off is a repository lookup
at judge time, which is cheap and already needed. Keeping `CONDITIONAL_TRIPLET` reserved (not
omitted) lets reports and schemas express it when the roadmap reaches it, while `V1_TYPES`
guards it and `UNCLEAR` out of v1 metrics. What I gave up: the convenience of loose,
dict-shaped data — deliberately, in favor of enforced contracts.

**Proposed by me**, following the spec (§6, §7, §11).

---

## D11 — Testing and CI: hermetic unit tests, mypy covers tests, CI mirrors local gates (2026-07-02)

**Decision.** Phase 0 ships hermetic unit tests under `tests/unit/` with **no
`tests/__init__.py`**. `mypy`'s `files` is widened from `["src"]` to `["src", "tests"]`, so the
tests are type-checked under `--strict`. The CI workflow (GitHub Actions) runs the exact four
local gates (ruff, ruff-format, mypy, pytest) on a clean runner, triggered on push/PR to `main`,
installing with `uv sync --frozen`, with least-privilege `contents: read` permissions and
ref-scoped `cancel-in-progress` concurrency.

**Options considered.**
- *mypy scope:* type-check `src` only vs. `src` + `tests`.
- *Test package:* add `tests/__init__.py` (tests as a package) vs. omit it.
- *Test isolation:* rely on ambient environment / a fixture `.env` vs. construct objects
  explicitly so no environment can affect results.
- *CI triggers:* every branch vs. `main` only.

**Rationale / trade-offs.** I type-check the tests too because a test that doesn't type-check
often doesn't test what its author thinks; the cost is real annotations and one justified
`# type: ignore[call-arg]` (for the intentional bad-kwarg test, which `init_forbid_extra` flags
and `warn_unused_ignores` keeps honest). I omit `tests/__init__.py` because both pytest and mypy
discover `tests/unit/` cleanly without it, and adding it would flip pytest into a different import
mode that fights the src-layout — I verified discovery works without it. Tests are hermetic
(values passed explicitly, which outrank env vars in pydantic-settings) so a developer's exported
`CROSSCHECK_*` var or local `.env` can't make them flake. CI is scoped to `main` to avoid
double-runs and conserve Actions minutes on a private repo, and `--frozen` guarantees CI installs
exactly the locked versions. What I gave up: type-checking tests adds a little annotation
overhead — a fair price for the rigor, and it matches the project's "evaluation/quality is
first-class" stance.

**Proposed by me**, following the spec (§5, §12).

---

## D12 — LLM wrapper design: Anthropic SDK, `messages.parse` structured output, class-based cost tracking (2026-07-03)

**Decision.** `crosscheck/llm.py` wraps the **Anthropic SDK directly** (Anthropic-only in
Phase 1; the OpenAI cross-model provider for the eval harness arrives in Phase 5 per D4).
Structured output uses `client.messages.parse(output_format=<pydantic model>)`, which returns
a validated instance. The "single wrapper" (spec §11) is a **class**, `LLMClient`, not a bare
module-level `call()` — it holds per-audit cost state. Cost tracking lives in a `CostTracker`
priced from a `MODEL_PRICING` table in `llm.py` (cache-aware: writes 1.25×, reads 0.10× the
input rate). The wrapper refuses to call an unpriced model, and checks running spend against a
per-audit ceiling before every dispatch, raising `CostCeilingError` when reached. Errors from
the SDK are caught at the `anthropic.AnthropicError` base and re-raised as `LLMError`. No
sampling parameters (`temperature`/`top_p`/`top_k`) are sent. Retries use the SDK's built-in
exponential backoff (`max_retries`). Model defaults: `judge_model = extraction_model =
"claude-sonnet-4-6"`; `llm_max_tokens = 2048`, `llm_timeout_seconds = 60`, `llm_max_retries = 2`.

**Options considered.**
- *SDK vs. framework:* raw Anthropic SDK (spec §4/§5) vs. LiteLLM/Instructor. Spec mandates raw.
- *Structured output:* `messages.parse` + pydantic vs. hand-rolled tool-use with a JSON schema
  vs. `output_config.format` + manual `json.loads`.
- *Wrapper shape:* class `LLMClient` (per-audit state) vs. a module-level `call()` function.
- *Sampling:* send `temperature=0` for determinism vs. send nothing.
- *Extraction model:* Sonnet 4.6 (quality) vs. Haiku 4.5 (cost) as the default.

**Rationale / trade-offs.** `messages.parse` is the SDK's recommended pydantic path — it
returns a validated `SchemaT` and, crucially, the SDK **strips JSON-schema constraints the
structured-output API doesn't support** (our `ge=0.0`/`le=1.0` bounds on `confidence`/probs)
and re-validates them client-side, so our existing models work unchanged. A class wrapper was
chosen over a bare `call()` because cost tracking needs per-audit state and a per-audit ceiling;
`LLMClient` still satisfies "all calls go through one wrapper," and takes an injectable `client`
so tests need no network. I send **no sampling parameters**: `temperature`/`top_p`/`top_k` are
removed on Opus 4.8/4.7 (a 400 error) and omitting them keeps the wrapper forward-compatible if
the judge model changes; determinism comes from the model's defaults and prompt design, not a
temperature knob. Pricing lives in a dated table in `llm.py` (the one place to update when
Anthropic changes prices); an unpriced model is refused *before* calling so the ceiling can
never be silently bypassed. Extraction defaults to Sonnet 4.6 to protect decontextualization
quality (bad extraction poisons every downstream stage, spec §7.1); Haiku 4.5 is left as a
config-swappable cost lever to benchmark once the extraction gold set exists. What I gave up:
the OpenAI path now (deferred, D4) and a temperature dial (unavailable on the newest models
anyway). Verified against `anthropic` 0.115.1 that `messages.parse`, `output_format`,
`parsed_output`, the four `usage` token fields, and `AnthropicError` all exist and type-check.

**Proposed by me**, following the spec (§4, §5, §11).

---

## D13 — Prompt library: versioned `<name>.v<N>.md` files, packaged, with a safe placeholder renderer (2026-07-03)

**Decision.** Prompts live under `src/crosscheck/prompts/` as plain-text files named
`<name>.v<N>.md` (e.g. `claim_extraction_system.v1.md`). A small loader in
`prompts/__init__.py` exposes `load_prompt(name, *, version=None) -> Prompt`; with no version
it resolves the **highest** `N` on disk. `Prompt` is a frozen dataclass (`name`, `version`,
`text`) with a `render(**subs)` method that does **literal `{{key}}` replacement, not
`str.format`**. Files are discovered with `importlib.resources.files(__package__)` and the index
is `lru_cache`d. Claim extraction ships as two prompts — a full instruction `system` prompt and a
thin `user` template carrying a `{{chunks}}` placeholder. No `pyproject.toml` change is needed:
hatchling's `packages = ["src/crosscheck"]` already ships non-`.py` package data into the wheel
(verified by building a probe wheel and confirming the `.md` file was included).

**Options considered.**
- *Where prompt text lives:* inline Python string constants vs. external files. (Spec §11
  mandates external files — recorded here for the "why".)
- *File format / versioning:* single file per prompt with in-file version metadata vs.
  version-in-filename (`.vN.md`) vs. a version subdirectory per prompt.
- *Substitution mechanism:* Python `str.format` / `string.Template` vs. literal `{{key}}`
  `str.replace`.
- *One combined prompt vs. split system+user:* a single blob parsed into sections vs. two
  separately named files.
- *Resource access:* `Path(__file__).parent` vs. `importlib.resources.files`.
- *LLM output shape:* have the model emit full `Claim` objects (incl. `claim_id`,
  `evidence_offset`) vs. a **reduced** extraction schema the code completes.

**Rationale / trade-offs.** Version-in-filename keeps every prior revision on disk for
reproducibility and clean diffs, and "load highest unless pinned" means revising a prompt is
*adding* `…v2.md`, never editing history — which matters because a prompt change silently moves
every downstream number. I rejected `str.format` for rendering because document text routinely
contains literal `{` / `}` (JSON snippets, code, math) that `format` would try to interpret and
crash on or mis-fill; literal `{{key}}` replacement can never misread payload braces, and the
placeholder syntax is visually distinct from prose. Splitting claim extraction into `system`
(stable instructions) and `user` (per-call chunk data) matches the SDK's message roles and lets
the system prompt be cached later without touching the variable part. `importlib.resources` is
the zip-safe, install-correct way to read package data (works from a wheel, not just a source
checkout), and I confirmed the files ship in the wheel rather than assuming it. The prompt asks
the model for a **reduced** set of fields (`chunk_id`, `text`, `evidence_quote`, `subject`,
`predicate`, `conditions`, `polarity`, `quantitative`) and the extractor computes the
trust-sensitive fields itself — `evidence_offset` by locating the verbatim quote, `claim_id` by
hashing, `doc_id`/`section_id` from the chunk — so the model can't fabricate offsets or ids and
the verbatim-evidence rule is enforced in code, not just requested in the prompt (the same
defense the judge uses in §7.4). What I gave up: a touch more indirection than an inline string,
and a filename convention I have to keep to — both cheap next to keeping prompts diffable,
versioned, and out of the code.

**Proposed by me**, following the spec (§7.1, §11).

---

## D14 — `Chunk` model in `models.py` and a shared `ids.py` for deterministic ids (2026-07-03)

**Decision.** Added a `Chunk` schema (`chunk_id`, `doc_id`, `section_id`, `text`, `char_span`,
`token_count`) to `models.py`, between `Document` and `Quantitative`. Introduced a new
`src/crosscheck/ids.py` module holding the pipeline's deterministic id functions: `content_hash`
(hash of chunk text — the extraction cache key), `chunk_id` (from doc + section + span), and
`claim_id` (from doc + chunk + evidence offset). Each id is a 16-hex-char BLAKE2b digest of a
unit-separator-joined string, namespaced by a `kind` tag so different id types can't collide on
the same parts. `pair_id` is deferred to Phase 2 (retrieval), where its producer lives.

**Options considered.**
- *Where `Chunk` lives:* define it inside the chunker module vs. in `models.py` with the other
  boundary schemas.
- *Where hashing lives:* inline `hashlib` calls at each call site vs. a single `ids.py`.
- *Hash function:* `hashlib.sha256` vs. `blake2b` with a short `digest_size`; and hex length 8
  vs. 16 vs. 32 chars.
- *`chunk_id` basis:* hash of the chunk *text* vs. hash of its *position* (doc + section + span).
- *Whether to ship `chunk_id`/`pair_id` now* even though their producers (chunker, retrieval)
  don't exist yet.

**Rationale / trade-offs.** `Chunk` is a *boundary* object — it flows from chunking to extraction
— so it belongs with the other cross-stage contracts in `models.py`, and putting it there let me
build and test the claim extractor *before* the chunker exists (the extractor takes `Chunk`s;
tests construct them directly). A single `ids.py` keeps every id derivation in one auditable
place, which matters because ids are load-bearing for caching and resume (§4): if two call sites
hashed "the same thing" slightly differently, the cache would silently miss. I chose `blake2b`
with an 8-byte digest (16 hex chars, 64 bits) over sha256 because these are content addresses,
not security tokens — 64 bits is far beyond collision risk at corpus scale (thousands–millions of
claims) and the short id keeps cache filenames and logs readable. The `kind` tag and the `\x1f`
unit-separator join prevent two different id *types* (or two different field groupings) from
colliding on coincidentally-equal concatenations. Critically, `chunk_id` hashes **position**, not
text, while the extraction cache key (`content_hash`) hashes **text** — so two chunks with
identical wording share a cache entry (we don't re-pay the LLM) yet keep distinct ids and correct
per-position provenance. I shipped `chunk_id` now (the `Chunk` model needs a documented id basis
and the chunker will use it) but deferred `pair_id` to the phase that first constructs a `Pair`,
to avoid unused code. What I gave up: a little indirection (ids behind function calls) — worth it
for one correct, tested definition of every id.

**Proposed by me**, following the spec (§4, §7.1, §7.2).

---

## D15 — Claim extractor: reduced LLM schema + code-side finalization, text-hash cache, batching, decontextualization heuristic (2026-07-03)

**Decision.** `ingestion/claim_extractor.py` extracts claims in these steps: (1) the LLM returns a
**reduced** `ExtractedClaim` (chunk_id, text, evidence_quote, subject, predicate, conditions,
polarity, quantitative) via `LLMClient.structured` on an internal `_ExtractionBatch` wrapper; (2)
the code **finalizes** each claim itself — it locates `evidence_quote` as a verbatim substring of
the chunk (dropping and counting any claim whose quote is absent or empty), computes
`evidence_offset` from that position, derives `claim_id` by hashing, and fills `doc_id`/
`section_id` from the chunk. Chunks are processed in batches of `extraction_batch_size` (default
4). Each chunk's raw extraction is cached by `content_hash(chunk.text)` behind a `ClaimCache`
`Protocol` with an `InMemoryClaimCache` default and a `DiskClaimCache` (one JSON file per hash)
for cross-run/resume persistence. A conservative `is_decontextualized` heuristic flags claims
that open with a bare pronoun/demonstrative; flagged claims are **kept but counted**, surfaced as
`ExtractionResult.decontextualization_failure_rate`. `CostCeilingError` is allowed to propagate;
per-chunk cache writes happen as work completes so a resumed run continues from where it stopped.

**Options considered.**
- *LLM output shape:* full `Claim` (model supplies offsets/ids) vs. reduced schema + code-side
  finalization.
- *Evidence trust:* trust the model's quote/offset vs. re-locate the quote in the chunk and
  reject non-substring quotes.
- *Cache key:* hash of chunk *text* vs. hash of chunk *position*; and cache the *reduced* output
  vs. the *finalized* `Claim`s.
- *Cache backend:* in-memory only vs. a `Protocol` with in-memory + on-disk implementations.
- *Cache abstraction:* `Protocol` (structural) vs. an ABC.
- *Decontextualization detector:* leading-pronoun heuristic vs. a second LLM validator vs.
  a dependency parse; and flag-and-keep vs. drop.
- *`decontextualization_failure_rate`:* a pydantic `computed_field` (serialized) vs. a plain
  `@property`.
- *Ceiling behavior:* catch `CostCeilingError` and return partial vs. let it propagate.

**Rationale / trade-offs.** The **reduced schema + code-side finalization** is the load-bearing
decision: offsets and ids are trust-sensitive, and a model that emits its own offsets can be
subtly or outright wrong. By having the model return only the verbatim `evidence_quote` and
re-locating it in the chunk myself, the offset is *correct by construction* and any hallucinated
quote is caught (`str.find` miss → drop + count), the same defense the judge uses in §7.4 — and
`claim_id` derives from the verified offset, so ids are stable and honest. I cache the **reduced**
output keyed by **text hash**, not finalized `Claim`s: the LLM result is position-independent, so
identical text anywhere reuses it (no re-spend), while finalization re-attaches the *current*
chunk's doc/section/offset — caching finalized claims would misattribute a shared-text chunk to
the wrong document. A `Protocol` cache (not an ABC) honors "composition over inheritance" (§11)
and lets tests inject an in-memory cache with zero ceremony; the `DiskClaimCache` gives the §4
resume story a concrete home now. For decontextualization I chose the **cheap leading-pronoun
heuristic** over a second LLM call (which would add cost and latency to every chunk) or a parser
dependency: it's deliberately conservative (excludes existential "there"/"here") to keep false
positives low, and it **flags without dropping** because the spec (§7.1) wants the failure *rate
observed*, not the claims silently discarded. I made the rate a plain `@property` rather than a
`computed_field` to avoid a known pydantic-mypy `--strict` friction (decorated-property warnings
under `warn_unused_ignores`); the raw counts are real fields, so the metrics module can still
serialize them. Letting `CostCeilingError` propagate keeps partial-report policy in the
orchestrator (§4) rather than duplicating it here, and because the cache is written per chunk as
work completes, nothing extracted is lost on a ceiling stop. Batching at 4 amortizes the system
prompt while staying within the spec's 3–5 guidance. What I gave up: strict `extra="forbid"` on
`ExtractedClaim` means a malformed batch raises rather than being partially salvaged — acceptable,
since structured output rarely emits extra keys and loud failure surfaces prompt/schema drift
early (D10); a per-batch resilience wrapper is noted as a possible later improvement.

**Proposed by me**, following the spec (§4, §7.1, §7.4, §11).

---

## D16 — Document parsers: content-hash `doc_id`, per-page PDF sections, structure-driven MD/DOCX, single-section TXT (2026-07-05)

**Decision.** `ingestion/parsers.py` exposes `parse(path) -> Document` dispatching on the
lowercased file extension through a `_PARSERS` table (`.pdf`, `.docx`, `.md`/`.markdown`,
`.txt`/`.text`). Each format parser returns a list of intermediate `_RawSection` tuples
(`heading`, `text`, `page_span`); a single shared `_assemble()` drops empty sections, computes
the document id, and stamps section ids — so all id logic lives in one place.

- **`doc_id` is a content hash** of the surviving section text (`ids.doc_id(full_text)`, a new
  helper alongside `content_hash`). Re-ingesting the same file is idempotent (§4 resume) and
  byte-identical duplicates collapse to one document rather than being reported as contradicting
  "themselves". A whitespace-only edit yields a new id — correct, because it *is* a changed doc.
- **`section_id` is position-based** (`ids.section_id(doc_id, ordinal)`), not heading-derived,
  because headings repeat, go missing, or change wording.
- **PDF** → one `Section` per page with a 1-based `page_span`, after a repetition heuristic
  (`_strip_running_headers_footers`) removes running headers/footers (a non-empty line appearing
  in the top/bottom 2 lines of ≥50% of pages, min 2 pages) and page-number-only lines (regex).
  With <3 pages there's too little signal, so only page numbers are stripped. No font-size
  heading detection.
- **Markdown** → sections split on headings, using markdown-it-py's block-token **line maps** to
  slice the verbatim source between one heading and the next. The heading line itself is captured
  in `Section.heading` and excluded from the body. Title = first heading (else filename stem).
- **DOCX** → sections split on heading-styled paragraphs (`Heading N` / `Title` / `Subtitle` via
  a style regex); non-heading paragraphs accumulate as body. Title = first `Title`/`Heading 1`,
  else the docx core-properties title, else stem.
- **TXT** → a single section (heading `None`); the chunker does all splitting.
- Unknown extension → `UnsupportedFormatError(ValueError)`; a missing path → `FileNotFoundError`.
- **Dependencies added** (D4 follow-through, Phase 1): `pdfplumber`, `python-docx`,
  `markdown-it-py`. Because `pdfplumber` and `python-docx` ship no type stubs, a
  `[[tool.mypy.overrides]]` block sets `ignore_missing_imports = true` for `pdfplumber.*` and
  `docx.*` (markdown-it-py is typed and needs no override).

**Options considered.**
- *`doc_id` basis:* content hash of the text vs. hash of the file path/filename. **(Raised as a
  question; the user was away, so this is my recommended default, vetoable.)**
- *PDF sectioning:* per-page + header/footer stripping vs. font-size heading heuristic vs. one
  whole-document section. **(Also raised; same status.)**
- *`section_id` basis:* position/ordinal vs. heading text.
- *MD body reconstruction:* markdown-it token line-maps to slice the source vs. re-rendering
  tokens back to text vs. a hand-rolled `#`-prefix line scanner.
- *TXT structure:* single section vs. blank-line-block splitting vs. heading-line heuristics.
- *DOCX title:* first heading vs. core-properties title vs. filename stem (chose a fallback
  chain of all three).
- *Missing-stub handling:* per-module mypy override vs. inline `# type: ignore` at each import.

**Rationale / trade-offs.** Content-addressing the `doc_id` is the load-bearing call: the whole
project leans on idempotent, resumable stages (§4), and `ids.py` is already built around content
hashes, so hashing the document text is the consistent choice — and it gives a real correctness
win (an accidentally-duplicated file can't manufacture a self-contradiction, and the
`doc_id != self.doc_id` cross-document retrieval filter stays meaningful). What I gave up is
human-readable ids and stability across content edits; both are non-issues because `title` and
`source_path` carry the readable provenance and an edited document *should* be treated as new.
Position-based `section_id` avoids collisions and `None`-heading gaps that a heading-derived id
would suffer. For PDFs I deliberately refused font-size heading detection: it's brittle across
uniform-font, multi-column, and OCR'd-then-flattened PDFs (which §3 doesn't support anyway), and
one honest `Section` per page with a real `page_span` is robust and gives the judge precise
provenance; the repetition heuristic is the spec's own suggestion (§7.1) and I kept it
conservative (only the page edges, a majority threshold, a guard for short docs) so it strips
boilerplate without eating body text. Using markdown-it's line maps to reconstruct MD bodies
means the section text is the *verbatim source*, not a lossy re-render — offsets stay honest for
the downstream evidence-quote check — and it handles ATX and setext headings uniformly. TXT as a
single section is the honest choice: plain text has no structure to recover, and inventing
"sections" from blank lines would fabricate provenance. The mypy override is the standard,
localized way to accept two untyped third-party libs without weakening `--strict` anywhere else
or scattering ignores. The common `_assemble()` centralizes id assignment so the four parsers
can't drift in how they hash or number — the same "one definition" discipline as `ids.py` (D14).
What I gave up overall: some format richness (DOCX tables, nested list semantics, PDF columns)
in exchange for four small, robust, testable parsers that produce clean `Section`s; richer
structure can be added behind the same `_RawSection` seam later if a corpus needs it.

**Proposed by me**, following the spec (§3, §7.1). The two flagged sub-decisions (`doc_id`
scheme = content hash, PDF sectioning = per-page + header/footer stripping) were my
recommendations; I **confirmed both explicitly on 2026-07-05** after reviewing the options, so
they are settled rather than provisional.

---

## D17 — Chunker: pysbd sentence splitting, greedy token-packing with a guarded overlap, injectable offline token counter (2026-07-05)

**Decision.** `ingestion/chunking.py` turns each parsed `Section` into overlapping,
sentence-aligned `Chunk`s. `chunk_section(section, doc_id, *, max_tokens, overlap_tokens,
count_tokens)` is the core; `chunk_document(document, *, settings, count_tokens)` maps it over a
document's sections and flattens. Key choices:

- **Sentence splitting = `pysbd`** (`Segmenter(language="en", clean=False, char_span=True)`), a
  pure-python, deterministic segmenter that returns per-sentence **character spans**. Chosen over
  nltk `punkt` and spaCy.
- **Greedy token packing.** Sentences are packed into a chunk until adding the next would exceed
  `max_tokens`; a lone sentence bigger than `max_tokens` becomes its own oversized chunk (logged,
  never split — sentence-awareness is preserved).
- **Guarded overlap.** After a chunk `[i, j)`, the next chunk starts a few sentences early to
  share ~`overlap_tokens` of context, under two guards: never back past `i + 1` (forward
  progress), and never back so far that sentence `j` no longer fits under `max_tokens` — which
  would reproduce the same chunk. When a lone large sentence blocks overlap, consecutive chunks
  fall back to **contiguous** (abutting, no gap). So the invariant is *contiguous-or-overlapping,
  always progressing, never a subset chunk* — not "always overlapping".
- **`char_span` is relative to the section text**, taken straight from pysbd's spans, so
  `chunk_id = ids.chunk_id(doc_id, section_id, char_span)` is exact and overlapping chunks get
  distinct ids. Each chunk's `token_count` is filled.
- **Token counter is injectable** (`TokenCounter = Callable[[str], int]`); the default
  `approximate_token_count` uses the ~0.75-words-per-token rule of thumb — **offline and
  deterministic**, so unit tests need no model download. A precise tokenizer (the bge tokenizer
  in Phase 2) can be injected without touching the algorithm.
- **Config (`config.py`):** `chunk_max_tokens = 400`, `chunk_overlap_tokens = 50` (spec §7.1's
  "200–400 tokens, 50 overlap"). **No separate `chunk_min_tokens` knob** — the 200 lower bound is
  a soft target that greedy max-packing already realizes; short sections and trailing remainders
  are legitimately allowed below it, so a hard min would be misleading.
- **Dependency added:** `pysbd` (Phase 1, per D4), plus `pysbd.*` added to the existing
  `[[tool.mypy.overrides]]` `ignore_missing_imports` list (no type stubs).

**Options considered.**
- *Sentence splitter:* pysbd vs. nltk `punkt` (`PunktSentenceTokenizer.span_tokenize`) vs. a
  spaCy blank-pipeline `sentencizer` vs. a regex splitter.
- *Token unit:* offline word-based approximation vs. `tiktoken` (cl100k BPE) vs. the real
  bge/transformers tokenizer, and whether to make it injectable.
- *Overlap mechanism:* fixed number of sentences vs. token-budget backup; guarded vs. unguarded.
- *Size band:* enforce a hard `min`/`max` vs. max-only with a soft min.
- *Chunker input:* take a `Settings` object (like the extractor) vs. take explicit
  `max_tokens`/`overlap_tokens` ints in the core function.

**Rationale / trade-offs.** I picked **pysbd over nltk** primarily on two grounds: nltk's
`sent_tokenize` requires a **runtime data download** (`punkt`/`punkt_tab`), which is a wart for
reproducible CI and `docker compose up`, whereas pysbd is pip-only and pure-python; and pysbd
returns **character spans natively**, which is exactly what `Chunk.char_span` needs (nltk's
`span_tokenize` also gives spans but keeps the download problem). spaCy's rule-based sentencizer
avoids a model download too, but pulls a much heavier dependency for a job pysbd does in one
class. pysbd also handles abbreviations (`Dr.`, `p.m.`, `Jan.`) well, which matters for the
legal/policy corpora in scope. For the **token counter** I deliberately kept the Phase-1 default
**offline**: `tiktoken` downloads a vocab file on first use and the real bge tokenizer needs
transformers/torch (a Phase-2 dependency), and unit tests must be hermetic (spec §12), so a
word-based approximation is the honest default — but I made the counter **injectable** so nothing
about the algorithm changes when the exact tokenizer arrives. The cost is that early token counts
are approximate and a Phase-2 tokenizer swap will re-chunk (new `chunk_id`s, a one-time cache
miss) — acceptable this early, and flagged. The **overlap guard** is the subtle part and came out
of verification: an unguarded backup could emit a chunk wholly contained in the previous one (and
then fail to overlap the next), wasting an LLM extraction call on redundant text; the guard makes
every chunk cover new ground. I take explicit int params in `chunk_section` (not a whole
`Settings`) so the core algorithm is trivially unit-testable without constructing config, while
`chunk_document` still offers the `settings`-driven convenience the orchestrator will use. I
dropped a hard `min` knob to avoid unused/misleading config (an anti-pattern the spec warns
against). What I gave up overall: exact token accounting now, and richer overlap at a few
big-sentence boundaries — both minor next to a deterministic, offline, dependency-light chunker
whose offsets are correct by construction.

**Addendum — pysbd warning filter.** pysbd's own source uses invalid regex escape sequences
(`\s`, `\.` in plain string literals), which emit three `DeprecationWarning`s on import and clutter
every test run. I added a **narrowly scoped** pytest `filterwarnings` entry —
`"ignore:invalid escape sequence:DeprecationWarning"` — that silences exactly that message. It is
message-scoped, not a blanket `DeprecationWarning` ignore, so it cannot hide a deprecation in our
own code (ruff's `W605` would flag any bad escape we wrote anyway). The alternative (leaving the
noise, or pinning/patching pysbd) wasn't worth it for a harmless third-party lint issue.

**Proposed by me**, following the spec (§7.1, §11) and D4/D14.

---

## D18 — Extraction gold set: chunk-text-anchored schema, one-JSON-per-chunk store, span-overlap scorer (2026-07-05)

**Decision.** Stood up the extraction gold set (spec §7.1, §9.2) so claim-extraction quality is
measured on its own, separate from end-to-end F1. Shape:

- **Schema (`evaluation/extraction_gold.py`).** `GoldChunk{gold_id, source, text, claims}` and
  `GoldClaim{evidence_quote, polarity, subject?, note?}`. Each gold chunk is **self-contained** —
  it stores the chunk text verbatim, and each gold claim is anchored by a **verbatim
  `evidence_quote`** (not raw offsets), which the scorer resolves to a span the same way the
  extractor notarizes its own quotes (D15). An **empty `claims` list is meaningful**: it asserts
  the chunk is all non-claims and the extractor should return nothing.
- **Storage.** One JSON file per chunk under `benchmarks/extraction_gold/chunks/`, loaded by
  `load_gold_set(dir)` (sorted by filename). A `README.md` documents the labeling protocol.
  Three hand-labeled starter chunks ship as the format-by-example (positive/negative/quantitative
  claims, a decontextualization case, and an empty non-claims chunk); the human expands to ~50.
- **Scorer.** `score_extraction(gold, extracted_by_gold_id, *, overlap_threshold=0.5)` matches
  each extracted claim to at most one gold claim **in the same chunk** by evidence-span overlap,
  greedily one-to-one by descending overlap. Overlap is measured as **fraction of the shorter
  span** (not IoU), so a short extracted quote inside a longer gold quote (or vice versa) still
  counts as the same claim. Matched pairs are true positives, unmatched extractions false
  positives, unmatched gold false negatives; **polarity agreement** is tallied among matches;
  gold quotes not found verbatim are counted as `unresolved_gold` (labeling errors) and excluded.
  `ExtractionScore` exposes `precision`/`recall`/`f1`/`polarity_accuracy` as properties over the
  raw counts. The scorer is **LLM-free** (takes already-extracted claims), so it is unit-testable
  now and reused unchanged by the Phase 6 metrics module. A `to_chunk(gold)` helper builds a
  `Chunk` (ids namespaced under `gold:`) so the Phase 6 runner can feed the extractor trivially.

**Options considered.**
- *Gold anchoring:* store the chunk text + verbatim quotes (self-contained) vs. reference live
  `chunk_id`s from a corpus run.
- *Storage:* one JSON per chunk vs. a single JSON/JSONL file vs. YAML.
- *Matching key:* evidence-span overlap vs. exact-quote equality vs. semantic/LLM equivalence.
- *Overlap metric:* fraction-of-shorter vs. IoU vs. containment-only, and the 0.5 threshold.
- *What to score:* detection P/R + polarity vs. also scoring subject / atomicity / numeric typing.
- *Module home:* `evaluation/extraction_gold.py` vs. folding into a future `metrics.py`.

**Rationale / trade-offs.** Anchoring gold to the **stored chunk text** (not a live `chunk_id`)
makes the set a stable, reproducible artifact: it survives re-chunking (a Phase-2 tokenizer swap
re-draws chunk boundaries and changes every `chunk_id`, per D17) and can be reviewed and diffed on
its own. Verbatim `evidence_quote` labeling is far easier for a human than typing offsets, and it
lets the scorer derive spans by the same substring-locate the extractor uses — so gold and
prediction are compared in one consistent coordinate system. **One JSON per chunk** matches the
existing `DiskClaimCache` "one file per unit" style, gives clean per-chunk diffs as the set grows
to ~50, and lets the labeler add one file at a time; I rejected YAML (a dependency, and JSON round-
trips pydantic for free) and a single mega-file (noisy diffs, merge pain). **Span overlap** is the
only matching key that is both objective and deterministic — exact-quote equality is too brittle
(the extractor may quote a slightly different span for the same fact) and semantic matching needs
an LLM (non-deterministic, and it would make the gold scorer depend on the very thing it audits).
**Fraction-of-shorter** overlap (verified: a partial quote inside a gold quote matches) tolerates
quote-length differences better than IoU, which unfairly penalizes a correct-but-shorter quote;
0.5 is a sane default and is a keyword arg so it can be tuned once real numbers exist. I score
**detection P/R + polarity** because that is exactly what §7.1 asks ("atomic, decontextualized,
and correctly typed by polarity"); atomicity and decontextualization are labeling-time properties
(gold claims are atomic by construction; the `is_decontextualized` heuristic already surfaces the
decontextualization rate separately, D15), and subject is stored for labeling clarity but not
scored to avoid brittle string comparisons. Putting it in `evaluation/` (a new package this phase)
gives the Phase 6 `metrics.py`/`runner.py` a ready import. What I gave up: a fully automatic
"is this claim atomic" check (genuinely needs human judgment, which is the point of a *gold* set)
and semantic-equivalence matching (deliberately, for determinism).

**Proposed by me**, following the spec (§7.1, §9.2, §11).

---

## D19 — Phase 1 ingestion integration test: real-LLM, self-skipping, env-parametrized to hit the 10-doc/≥200-claim milestone (2026-07-06)

**Decision.** Added `tests/integration/test_ingestion_pipeline.py`, the Phase 1 end-to-end
ingestion test (spec §12, Phase 1 milestone). It runs the **real** path — `parse → chunk_document
→ ClaimExtractor.extract` — over a fixture corpus with real Anthropic calls, asserts every
extracted claim is well-formed, that claim ids are unique, and that the count clears a threshold.

- **Marked `@pytest.mark.integration`** (module-level `pytestmark`) and **self-skips** when
  `ANTHROPIC_API_KEY` is unset (`pytest.skip`), so CI stays green without a key while a keyed run
  exercises the whole path. The marker is already registered in `pyproject.toml` (Phase 0), so no
  config change.
- **Committed fixture corpus** at `tests/fixtures/corpus/` — three small real-prose documents
  (`handbook.md`, `refund_policy.txt`, `vendor_agreement.md`, spanning PTO/insurance/refund/
  jurisdiction so they double as future contradiction material). They parse to 5 chunks holding
  ~20 atomic claims, so the **default threshold `min_claims=6` is comfortably clearable** by a
  real extractor while keeping each run to a few cents.
- **Env-parametrized to reach the Phase 1 milestone.** `CROSSCHECK_TEST_CORPUS` and
  `CROSSCHECK_TEST_MIN_CLAIMS` override the corpus and threshold, so the *same test* becomes the
  "10-doc corpus → ≥200 well-formed claims" milestone by pointing it at the seed corpus with
  `CROSSCHECK_TEST_MIN_CLAIMS=200`. This reconciles §12's "3-document fixture" with Phase 1's
  "10-document / ≥200 claims" as two runs of one test rather than two tests.
- **Well-formedness invariants** (`_assert_well_formed`): non-empty ids/text, polarity in the
  allowed set, a valid `evidence_offset` whose length matches `evidence_quote`, the quote grounded
  **verbatim in its source section**, and a legal `quantitative.operator` when present.
- **No new source code and no orchestrator.** The parse→chunk→extract loop lives in the test, not
  in a new pipeline module — the full audit orchestrator (with retrieval/detection/judge, the cost
  ceiling across stages, and resume) is Phase 3 and shouldn't be pre-built to satisfy one test.

**Options considered.**
- *Skip mechanism:* self-skip on a missing key inside the test vs. a CI `-m "not integration"`
  deselect vs. an autouse fixture.
- *Fixture size / threshold:* commit a 3-doc fixture with a low threshold (§12) vs. commit a
  full 10-doc corpus and assert ≥200 (Phase 1) vs. one env-parametrized test covering both.
- *Grounding check:* re-derive the offset against the chunk vs. assert the quote is a substring
  of its section vs. trust the extractor's own substring notarization.
- *Where the ingest loop lives:* inline in the test vs. a new `ingestion/pipeline.py` helper vs.
  wait for the Phase 3 orchestrator.
- *A mocked end-to-end (offline) test now* vs. deferring it to the §12 regression snapshot.

**Rationale / trade-offs.** A **self-skip on the key** keeps one test that is both the cheap CI
smoke test and the milestone check, and it can't be forgotten the way an external `-m` filter can;
the test simply does nothing useful without a key rather than failing. **Env-parametrization** is
what lets a single small committed fixture (fast, near-free, always present) scale up to the real
Phase 1 milestone on demand — committing a 10-doc corpus that hits 200 claims would make every
keyed run slow and expensive and bloat the repo, while a 3-doc fixture alone would never actually
demonstrate the "≥200" deliverable. The **grounding check** asserts the quote is a verbatim
substring of its *section* (not re-deriving the chunk offset) because that is the strongest claim
the test can make without re-plumbing chunk objects, and it independently re-checks the extractor's
own notarization end-to-end. I kept the loop **in the test** to avoid pre-building the orchestrator
(spec anti-pattern: the orchestration is Phase 3 engineering, not test scaffolding). I **deferred a
committed mocked end-to-end test**: doing it now would need a fake that parses the extractor's
internal prompt serialization to emit valid quotes — coupling a shipped test to an implementation
detail — and §12 already calls for a proper mocked **regression snapshot** of the *full* pipeline,
which is better built once the pipeline through the judge exists (Phase 3–4) than as a throwaway
ingestion-only mock now. (I did use exactly such a fake to verify this hand-over offline, but it
stays in the scratchpad, not the repo.) What I gave up: CI does not exercise the parse→chunk→extract
composition on every push (only the keyed run does) — an acceptable gap, since each stage is
unit-tested and the composition is a few lines, and the §12 regression snapshot will close it.

**Addendum (2026-07-06) — deselect integration by default.** Once a real `ANTHROPIC_API_KEY`
lives in `.env`, the self-skip no longer fires locally, so a plain `uv run pytest` would run the
live integration test (real spend, ~$0.04, ~40s) on every invocation. Added `-m 'not integration'`
to `addopts` so a plain run **deselects** it; you opt in explicitly with `uv run pytest -m
integration`. CI is unaffected (it has no key, so the test was a no-op there either way), and the
self-skip stays as a second belt-and-braces guard. Verified: plain run → "deselected", `-m
integration` → selected.

**Proposed by me**, following the spec (§12, Phase 1); the offline-vs-deferred choice is my
recommendation and is revisitable.

---

## D20 — Whitespace-tolerant evidence-quote location in the claim extractor (2026-07-06)

**Decision.** `claim_extractor._finalize_claim` no longer requires the model's `evidence_quote`
to be a byte-exact substring of the chunk. A new `_locate_quote(text, quote)` tries an exact
`str.find` first and, on a miss, falls back to a **whitespace-flexible** regex match — the quote's
words in order, with each inter-word gap matching `\s+`. It returns the `[start, end)` span of the
**actual** chunk substring; `_finalize_claim` then stores `chunk.text[start:end]` (the real source
span, with its real newlines) as `evidence_quote` and derives the offset and `claim_id` from that
span. A genuine content change (a different or invented word) still fails to match and is dropped
and counted, exactly as before.

**Why (found by real-LLM inspection, not theory).** Running extraction over the fixture corpus with
Claude Sonnet 4.6 dropped **3 of 18 otherwise-valid claims (~17%)**. Every drop was the same
failure: the source wraps a line mid-sentence (`"Shipping fees\nare not refunded."`), the model
copied the span but normalized the newline to a space (`"Shipping fees are not refunded."`), and the
exact-substring check rejected it as a hallucination. Whether the model preserves or normalizes the
newline is non-deterministic, so this was a silent, flaky recall loss in the foundation stage that
caps the whole system (spec §7.1). The other 15 claims were high quality — decontextualization
resolved the hard `"This requirement is waived"` case, polarity was correct throughout, and
quantitatives (`20 days =`, `1000000 USD >=`, `14 business days <=`) were exact — so the fix targets
exactly this whitespace gap and nothing else.

**Options considered.**
- Whitespace-flexible regex fallback that returns the real source span (chosen).
- Normalize both chunk and quote (collapse whitespace) and map the match back to an original offset
  — same effect, but the offset-mapping is fiddlier and error-prone.
- Tighten the *prompt* to forbid the model from altering whitespace — unreliable; can't be enforced
  in code, and the "notarize in code, don't trust the model" principle (D15) says enforce here.
- Store the model's quote verbatim and loosen only the substring check — rejected: then
  `evidence_quote` wouldn't equal `chunk.text[offset]`, breaking the downstream grounding invariant
  the integration test checks (D19).

**Rationale / trade-offs.** The fallback keeps the extractor's "notarize, don't trust" guarantee
(D15) fully intact — content must still match word-for-word, offsets are still computed in code, and
the stored quote is still a real verbatim span of the source (now with the correct newline rather
than the model's space) — while removing a whitespace-only false-negative that was costing ~17% of
claims. Exact matches are unchanged (tried first, identical offset), so the change is backward
compatible: the existing `test_extracts_and_finalizes` (exact quote) and `test_rejects_non_verbatim_quote`
(`"within sixty days"` vs `"within 30 days"` — a real content mismatch) both still pass. What I gave
up: a sliver of strictness — a quote that differs from the source *only* in whitespace is now
accepted rather than rejected, which is the entire point. Verified in the mirror (exact match,
newline-for-space kept with a verbatim source quote, changed-word still dropped, empty quote
dropped) with a new `test_extractor_wsfix`-style case added to `test_claim_extractor.py`.

**Proposed by me**, after inspecting real extractor output (spec §7.1, §9.2).

---

## D21 — Qdrant storage foundation: one `claims` collection (dense+sparse), UUID5 point ids, idempotent lifecycle (2026-07-07)

**Decision.** Phase 2 opens with the storage foundation, `storage/qdrant_client.py` (connection +
collection lifecycle) plus the config it needs. The higher-level CRUD (`ClaimRepo`) is the next
file; this one owns only the primitives.

- **Client pin.** `qdrant-client>=1.15` (resolves to **1.18.0**), matching the server image already
  in compose (`qdrant/qdrant:v1.18.2`). Added to `pyproject.toml` runtime deps (D4 follow-through,
  Phase 2). qdrant-client ships `py.typed`, so `mypy --strict` passes with **no** override needed.
- **One `claims` collection, two named vectors.** A single collection holds every claim, with a
  named **dense** vector (`size = dense_vector_size = 1024`, **Cosine** — bge-large-en-v1.5) and a
  named **sparse** vector configured with **`Modifier.IDF`**. Storing both vectors per point lets
  hybrid BM25+dense retrieval (spec §7.2/§7.3, the v2 default) run **entirely in-engine** via
  Qdrant's Query API fusion — no client-side score merging. The sparse vector is generic
  term-frequency-with-server-side-IDF, so it is agnostic to *which* client-side encoder produces it
  (that choice is deferred to the embedder file, below).
- **Payload = the full claim; keyword indexes on `doc_id`, `subject`, `polarity`.** These three are
  the fields we filter on — above all the cross-document `doc_id != self` filter that runs on every
  retrieval (§7.3) — so they get explicit payload indexes; the rest of the claim rides in the
  payload unindexed.
- **Point id = deterministic UUID5 of `claim_id`.** Qdrant point ids must be an unsigned int or a
  UUID, but our `claim_id` is a 16-hex digest. `to_point_id(claim_id)` = `uuid5(fixed_namespace,
  claim_id)`; the original `claim_id` is also kept in the payload so we can look up by our own id.
  The fixed namespace makes the mapping stable across machines and reruns — required for idempotent
  upserts and resume (§4).
- **Idempotent `ensure_collection(client, settings, *, recreate=False)`.** Create-if-absent by
  default (an interrupted audit resumes against the same store); `recreate=True` drops and rebuilds
  (destructive — for a clean re-ingest or a dense-size change). Logging: INFO on create, DEBUG when
  already present, WARNING on a `recreate` drop (§11 log levels).
- **Config additions.** `qdrant_url` / `qdrant_api_key` (accepting the standard `QDRANT_URL` /
  `QDRANT_API_KEY` names too, via `AliasChoices`, mirroring the provider-key pattern in D9),
  `qdrant_collection` (`"claims"`), `qdrant_timeout_seconds` (30). Plus the embedding block:
  `dense_embedding_model` (`BAAI/bge-large-en-v1.5`), `dense_vector_size` (1024), `sparse_model`
  (`Qdrant/bm25`) — `dense_vector_size` sizes the collection here; the two model-name settings are
  consumed by the embedder next. All qdrant fields carry defaults, so the D9 `mypy`
  `warn_required_dynamic_aliases` friction does not recur (it only fires for *required* aliased
  fields).

**Options considered.**
- *Collection layout:* one collection with per-claim dense **and** sparse named vectors vs. two
  collections (one dense, one sparse) vs. dense-only now + add sparse later.
- *Sparse config:* `Modifier.IDF` (server computes BM25 IDF) vs. store precomputed BM25 weights with
  no modifier.
- *Point id:* UUID5 of `claim_id` vs. `int(claim_id, 16)` as a uint64 vs. a fresh random UUID with
  `claim_id` only in the payload.
- *Where `to_point_id` lives:* the storage layer vs. `ids.py`.
- *Collection lifecycle:* idempotent create-if-absent vs. unconditional `recreate_collection`.
- *Qdrant env names:* `CROSSCHECK_`-prefixed only vs. also accept standard `QDRANT_URL`/`QDRANT_API_KEY`.

**Rationale / trade-offs.** The load-bearing call is **one collection with both vectors per point**:
it is exactly what Qdrant's in-engine hybrid fusion (RRF/DBSF over dense+sparse prefetches) expects,
so §7.3's "hybrid is the default" needs no bespoke merge code — I verified end-to-end against live
Qdrant 1.18.2 that a dense prefetch + a sparse prefetch fuse under `FusionQuery(RRF)` with the
`doc_id != self` filter applied. Two separate collections would force client-side score fusion and
double the filtering/bookkeeping for no gain. **`Modifier.IDF`** means we send plain term-frequency
sparse vectors and Qdrant applies corpus IDF at query time — real BM25 semantics without us tracking
global document frequencies ourselves. I chose **UUID5 over `int(claim_id,16)`**: a 64-bit int *is*
a legal Qdrant id, but round-trips through JSON in some client paths risk precision surprises above
2^53, whereas a UUID is unambiguous everywhere and still fully deterministic from `claim_id`; a
random UUID was rejected because a non-derivable point id breaks idempotent re-upsert (the same claim
would land as a new point on rerun). `to_point_id` lives in the **storage layer, not `ids.py`**,
because it is a re-encoding of an existing pipeline id to satisfy an *external system's* id format,
not the birth of a new content-addressed id — `ids.py` stays about the pipeline's own ids (D14).
**Idempotent `ensure_collection`** (not unconditional recreate) is the whole point of the §4 resume
story — a re-run must not silently wipe the store; `recreate` is opt-in and loud. Accepting the
standard `QDRANT_URL`/`QDRANT_API_KEY` names costs nothing and matches D9, so a Qdrant Cloud user's
existing env works unchanged. What I gave up: nothing structural — the design is the Qdrant-blessed
hybrid setup, verified live before hand-over.

**Deferred to the embedder file (next), flagged for a decision:** *how* the client produces the
sparse vector — the spec (§5) suggests **`rank_bm25`**, but rank_bm25 is a standalone Python scorer
that does **not** emit Qdrant sparse vectors, so it cannot do the in-engine hybrid this collection is
built for. My recommendation is **`fastembed`'s `SparseTextEmbedding("Qdrant/bm25")`** (a Qdrant-native
substitution) for sparse and **sentence-transformers `bge-large-en-v1.5`** (spec-prescribed) for
dense, in a new `storage/embeddings.py` (a small deviation from the spec's two-file storage layout,
since both storage and retrieval need the encoders). That substitution + module will be recorded as
its own decision once written and verified.

**Verification.** Copied the repo into the scratchpad mirror, added `qdrant-client`, applied the
config + module, and ran all four gates (ruff, ruff-format, mypy `--strict` over 30 files, pytest:
**69 passed** = repo's 65 + 4 new hermetic `test_qdrant_client.py` cases) plus a **live check**
against the running Qdrant: `to_point_id` deterministic/distinct, collection built with dense
size-1024/Cosine + sparse IDF, payload indexes on the three fields, `ensure_collection` idempotent on
the second call, and `recreate=True` dropping+rebuilding to an empty collection.

**Proposed by me**, following the spec (§5, §7.2, §7.3, §11) and D4/D9/D14.

---

## D22 — Embedders: sentence-transformers dense + fastembed BM25 sparse, in `storage/embeddings.py`; CPU-only torch pin (2026-07-07)

**Decision.** The second Phase-2 file, `storage/embeddings.py`, turns claim text into the two
vectors the `claims` collection holds. Two encoders behind small `Protocol`s, both lazy-loading:

- **Dense = sentence-transformers `BAAI/bge-large-en-v1.5`** (1024-d, cosine) — the spec-prescribed
  model (§5). `BgeDenseEmbedder` normalizes to unit vectors (`normalize_embeddings=True`) and, on
  first load, checks the model's real dimension against `dense_vector_size`, raising `EmbeddingError`
  on a mismatch (a wrong-sized model would silently corrupt the collection).
- **Sparse = fastembed `SparseTextEmbedding("Qdrant/bm25")`** — a **substitution** from the spec's
  suggested `rank_bm25` (§5), because rank_bm25 is a standalone scorer that does not emit Qdrant
  sparse vectors and so cannot feed the in-engine hybrid the collection is built for (D21).
  `Bm25SparseEmbedder` uses fastembed's `.embed()` for the document/indexing side and `.query_embed()`
  for the query side; corpus IDF is applied by Qdrant (the collection's `Modifier.IDF`), so nothing
  here tracks global document frequencies.
- **Passage vs query split.** Both embedders expose `embed_passages` (indexing) and `embed_query`
  (retrieval). The dense embedder prepends a **query instruction on the query side only** — bge's
  recommended asymmetric setup (stored claim = passage, search claim = query) — configurable via the
  new `dense_query_instruction` setting (default the bge string; `""` disables it for symmetric s2s
  embedding, a §9.3 tuning knob).
- **New module = layout deviation.** `storage/embeddings.py` is not in the spec's two-file
  `storage/` layout (§10), but the encoders are needed by *both* storage (upsert) and retrieval
  (query), so a shared module is the natural home. A provider-neutral `SparseVector` dataclass
  (plain `indices`/`values` lists, no numpy or Qdrant types) is the boundary type; the repo converts
  it to Qdrant's `SparseVector` at the edge.
- **Lazy + injectable.** Models load on first embed call (importing the module and constructing an
  embedder stay offline and instant — tests, `--help`, config validation don't pay for a download),
  and both concrete embedders accept an injected `model=` for hermetic tests.
- **CPU-only torch pin.** sentence-transformers pulls `torch`, whose default Linux wheel bundles the
  full CUDA stack (~20 `nvidia-*` packages, **5.1 GB** venv) that is dead weight without a GPU.
  CrossCheck targets commodity hardware (§2), so `pyproject.toml` declares `torch>=2.2` directly and
  redirects it to the PyTorch CPU index (`[[tool.uv.index]] pytorch-cpu` + `[tool.uv.sources]`), with
  a `sys_platform == 'linux' or 'win32'` marker so macOS (already CPU on PyPI) is unaffected. This
  drops the venv to **1.4 GB** (a 183 MB CPU wheel). Deps added (per D4): `sentence-transformers`,
  `fastembed`, `torch`; `sentence_transformers.*` and `fastembed.*` added to the mypy
  `ignore_missing_imports` override (belt-and-braces — they ship partial types, but this keeps CI
  robust if a runner resolves them without types).

**Options considered.**
- *Sparse encoder:* fastembed `Qdrant/bm25` vs. the spec's `rank_bm25` vs. a hand-rolled
  tokenizer + term-frequency sparse vector.
- *Dense stack:* sentence-transformers (prescribed) vs. fastembed's ONNX bge (would avoid torch).
- *Module home:* new `storage/embeddings.py` vs. folding the encoders into `claim_repo.py`.
- *Query instruction:* on (asymmetric s2p) vs. off (symmetric s2s) vs. configurable — and whether to
  apply it to passages too.
- *Model lifecycle:* eager load in `__init__` vs. lazy on first use; and injectable model vs. not.
- *torch wheel:* default (CUDA) vs. CPU-index pin; and declare torch directly vs. leave it transitive.
- *Sparse boundary type:* a neutral `SparseVector` dataclass vs. returning Qdrant's `SparseVector`
  vs. raw numpy arrays.

**Rationale / trade-offs.** The **fastembed substitution** is forced by the D21 architecture: the
whole point of storing a sparse vector per claim is in-engine hybrid fusion, and rank_bm25 simply
can't produce the vector Qdrant fuses — so following the spec's *letter* here would defeat its own
§7.3 "hybrid is the default" intent. fastembed is by Qdrant, produces exactly the term-frequency
sparse vectors the `Modifier.IDF` collection expects, and handles tokenization/stemming/stopwords
robustly; I keep **sentence-transformers for dense** because it *is* prescribed and torch arrives
with the Phase-2 reranker anyway, so using fastembed's ONNX bge to dodge torch would buy nothing and
add a second dense stack. A **new module** beats stuffing encoders into the repo because retrieval
(a different package) needs the query-side encoders too; a **neutral `SparseVector`** keeps
embeddings.py free of Qdrant imports so the two layers stay swappable (§7.3's pluggable-strategy
requirement). **Lazy + injectable** is what keeps the unit tests hermetic (5 new tests inject fakes,
no 1.3 GB download) while the real path still works — the same "inject the client" pattern as the LLM
wrapper (D12) and the claim cache (D15). The **query instruction on the query side only**, made
configurable, follows bge's own guidance while leaving room to test symmetric embedding during Phase-6
tuning; applying it to passages too would double-count the instruction and is wrong for the indexing
side. The **CPU torch pin** is not cosmetic — a 5.1 GB vs 1.4 GB venv is the difference between a
`docker compose up` / CI install that is merely large and one that is punishing, and the platform
marker keeps the pin from breaking a macOS contributor. Declaring `torch` directly is required for
uv's source redirect to bind (it only applies to declared deps). What I gave up: a hard dependency on
the PyTorch CPU index URL (documented, standard), and the theoretical option of a torch-free ONNX-only
stack (deferred; revisit only if the reranker also turns out not to need torch).

**Verification.** In the mirror: all four gates (ruff, ruff-format, mypy `--strict` over 32 files,
pytest **74 passed** = 69 + 5 new hermetic `test_embeddings.py`), confirmed the CPU pin (`torch
2.12.1+cpu`, 0 nvidia packages, venv 5.1 GB → 1.4 GB), probed both library APIs, and ran a **live
end-to-end check against real Qdrant** — real sentence-transformers (a small stand-in model to avoid
the 1.3 GB bge download; the code is model-agnostic and dimension-checked) + real fastembed BM25 →
upsert dense+sparse points → hybrid RRF query with the `doc_id != self` filter, which correctly
excluded the self-doc and ranked the true PTO-negation partner first, with every sparse index inside
Qdrant's uint32 range.

**Proposed by me**, following the spec (§5, §7.2, §7.3, §9.3, §11) and D4/D12/D15/D21. The fastembed
substitution is a deliberate, documented deviation from the spec's `rank_bm25` suggestion.

---

## D23 — `ClaimRepo`: vector-taking hybrid `search`, typed filter args, `ScoredClaim` result, add missing `storage/__init__.py` (2026-07-09)

**Decision.** The third Phase-2 file, `storage/claim_repo.py`, is the CRUD + retrieval layer over
the `claims` collection (spec §7.2). It holds the `upsert` / `search` / `get` / `count` surface the
spec names, backed by the D21 collection and the D22 embedders. Alongside it I added the missing
`storage/__init__.py` and a small `ScoredClaim` boundary model in `models.py`.

- **`upsert(claims, *, batch_size=128) -> int`.** Embeds each claim's **`text`** (the
  decontextualized assertion — that is what we search over, not the raw quote) with both embedders,
  builds a Qdrant `PointStruct` per claim carrying **both** named vectors plus the full claim as
  payload (`claim.model_dump(mode="json")`), and upserts in batches. The point id is
  `to_point_id(claim_id)` (D21), so re-upsert **overwrites** rather than duplicating — idempotent,
  per the §4 resume story. Returns the number written; empty input is a no-op returning 0.
- **`search(*, dense, sparse=None, exclude_doc_id=None, subject=None, polarity=None, top_k)
  -> list[ScoredClaim]`.** Takes **pre-computed query vectors**, not text. When `sparse` is given it
  runs the §7.3 **hybrid** query — a dense prefetch + a sparse prefetch fused in-engine with
  `FusionQuery(RRF)` — and when it is omitted it runs **dense-only** (the ablation baseline, §9.3).
  The cross-document `doc_id != self` filter is the first-class `exclude_doc_id` argument; `subject`
  and `polarity` (the other two indexed fields, D21) are optional typed filters. A private
  `_build_filter` assembles the Qdrant `Filter` internally.
- **`get(claim_id) -> Claim | None`** retrieves by the derived point id and rebuilds the claim from
  payload (`Claim.model_validate`), returning `None` when absent. **`count() -> int`** wraps
  `client.count`.
- **`ScoredClaim{claim: Claim, score: float}`** in `models.py` is the search result type — the
  fused RRF score for hybrid, the raw cosine for dense-only. Retrieval turns these into `Pair`s
  (`retrieval_score`) next file.
- **`storage/__init__.py`** added (it was missing — the package worked only via PEP 420 implicit
  namespace packaging, inconsistent with every other subpackage and a latent wheel-packaging risk).

**Options considered.**
- *`search` signature:* the spec's literal `search(vector, filters, top_k)` (single dense vector,
  raw filter object) vs. a hybrid-capable `search(dense, sparse=None, <typed filter args>, top_k)`.
- *Read-path embedding:* `search` takes pre-computed vectors vs. `search` takes query **text** and
  embeds internally.
- *Filter surface:* accept a Qdrant `Filter` across the public boundary vs. expose typed args
  (`exclude_doc_id` / `subject` / `polarity`) and build the `Filter` inside.
- *Result type:* a `ScoredClaim` model vs. `list[tuple[Claim, float]]` vs. bare payload dicts.
- *Where `ScoredClaim` lives:* `models.py` (boundary schemas) vs. `claim_repo.py` (local return).
- *What text to embed on upsert:* `claim.text` vs. `claim.evidence_quote`.
- *Batch-size knob:* a method default param vs. a new `Settings` field.
- *`storage/__init__.py`:* add it vs. keep relying on implicit namespace packaging.

**Rationale / trade-offs.** The load-bearing call is **`search` takes vectors and exposes typed
filter args**, a deliberate, minimal deviation from the spec's illustrative `search(vector, filters,
top_k)`. Two reasons. (1) Hybrid is the default (§7.3), so a *single* `vector` param can't express
the query; the D21 collection is built for in-engine dense+sparse fusion, and the signature has to
carry both — with `sparse=None` collapsing cleanly to the dense-only ablation (§9.3) so the same
method serves both without a second code path leaking out. (2) Taking **pre-computed vectors**
(rather than text) keeps the *retrieval strategy* — which embedders, dense-only vs hybrid, MMR later
— in the pluggable `crosscheck.retrieval` layer (§7.3's "export a pluggable interface"), and leaves
`ClaimRepo` a thin, hermetically testable adapter with no query-side policy baked in. The embedders
still live on the repo because the **indexing** side (`upsert`) genuinely needs them; the
orchestrator will construct one dense + one sparse embedder and inject the same instances into both
the repo (upsert) and the retrieval layer (query embedding) so the 1.3 GB bge model loads once.
**Typed filter args instead of a raw `Filter`** keep Qdrant's types from leaking across the API
boundary (the §11 "no bare dicts / clean contracts" spirit) and name exactly the three fields the
collection actually indexes — anything else would be an unindexed filter we don't want to invite.
**`ScoredClaim` as a model** (not a tuple or dict) honors §11 and self-documents what the score
means; it lives in `models.py` with the other boundary schemas because retrieval consumes it, the
same home as `Pair`. I embed **`claim.text`**, not the evidence quote, because the decontextualized
assertion is the semantic unit retrieval compares (a bare quote can be elliptical); this matches how
the extractor treats `text` as the claim proper (D15). **Batch size is a method default param**, not
a `Settings` field — an internal perf detail, and adding config nobody tunes is the anti-pattern D17
already refused. Adding **`storage/__init__.py`** removes a real inconsistency and a wheel risk for
the cost of one file. What I gave up: strict fidelity to the spec's illustrative signature — worth
it, and recorded here as the deviation the spec asks me to log; and a second embedder instance if a
caller *doesn't* share one — acceptable, since embedders are lazy and injectable.

**Verification.** In the scratchpad mirror: all four gates — ruff, ruff-format, mypy `--strict`
(clean over **34** files), pytest **82 passed** (the 74 so far + **8** new `test_claim_repo.py`
cases), zero warnings. The new tests exercise the **full CRUD + hybrid path end-to-end** against a
real in-process Qdrant via the client's `:memory:` local mode — which I first probed to confirm it
supports Query-API RRF fusion with filters — using injected fake embedders with deterministic 4-d
dense and tiny sparse vectors: `upsert`+`count`, upsert idempotency (re-upsert keeps count at 3),
empty-upsert no-op, `get` round-tripping a full claim (payload → `Claim`, list offset re-coerced to
a tuple), `get(missing) -> None`, hybrid search excluding the self-doc and ranking the true partner
first, the dense-only branch returning the same, and a polarity filter narrowing results. Payload
indexes are a documented no-op in local mode (server-only), silenced with a message-scoped
`filterwarnings` mark (the D17 pattern); the real indexes are covered by the live check in D21.

**Proposed by me**, following the spec (§7.2, §7.3, §9.3, §11) and D4/D14/D21/D22. The `search`
signature and `ScoredClaim` location are my recommended defaults and are vetoable.
