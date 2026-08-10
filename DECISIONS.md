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

**Addendum (2026-07-09) — dimension-check method rename.** `BgeDenseEmbedder._get_model` called
`get_sentence_embedding_dimension()`, which sentence-transformers 5.6 has **deprecated** (renamed to
`get_embedding_dimension()`, emits a `FutureWarning`). The unit tests didn't catch it because they
inject a *fake* model; the deprecated call only fires against a *real* sentence-transformers model,
which the negation retrieval integration test (D26) is the first to load. Switched the call to
`get_embedding_dimension()` (present in 5.6+, our pinned floor) and renamed the fake's method in
`test_embeddings.py` to match. Same behavior, no warning. Found by running the real model, not by
theory — the same lesson as D20.

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

---

## D24 — Candidate pair generation: `CandidateStrategy` Protocol (hybrid default), reciprocal dedup keeping max score, order-independent `pair_id` (2026-07-09)

**Decision.** Opened Phase-2 *retrieval* with `retrieval/candidate_gen.py` (+ `retrieval/__init__.py`),
which turns the stored claims into deduplicated cross-document `Pair` candidates (spec §7.3). Also
added `pair_id` to `ids.py` (deferred since D14) and two `Settings` fields.

- **Pluggable `CandidateStrategy` Protocol** — `neighbors(claim, *, top_k) -> list[ScoredClaim]`.
  Two concrete strategies: **`HybridStrategy`** (embeds the query claim dense **and** sparse, calls
  `ClaimRepo.search(dense=, sparse=, exclude_doc_id=claim.doc_id, top_k=)` → in-engine RRF) is the
  **default** (§7.3); **`DenseStrategy`** (dense only) is the §9.3 ablation baseline. A
  `build_candidate_strategy(repo, settings, *, dense_embedder=None, sparse_embedder=None)` factory
  `match`es on `settings.retrieval_strategy` and shares the embedder instances (so bge loads once);
  MMR is left as a future `CandidateStrategy` implementation, not built (no unused code, D17).
- **The query is embedded in the retrieval layer, not the store** — the strategies hold the
  query-side embedders and pass vectors into `ClaimRepo.search`, exactly the split D23 set up (the
  store's read side takes vectors; strategy lives one layer up).
- **`generate_candidate_pairs(claims, strategy, *, top_k) -> list[Pair]`** iterates the corpus,
  gets each claim's cross-document neighbours, and **deduplicates reciprocal hits** (B found for A,
  A found for B) into one `Pair` keyed by `pair_id`, **keeping the higher retrieval score** of the
  two directions. Claim ids are **sorted** so `claim_a_id`/`claim_b_id` are canonical regardless of
  direction; a defensive self-pair guard drops any `neighbor_id == claim_id`. Output is sorted by
  descending `retrieval_score`, ties broken by `pair_id`, so the result is deterministic.
- **`pair_id(claim_a_id, claim_b_id)`** in `ids.py` — sorts the two ids, then `_digest("pair", …)`;
  order-independent by construction, same 16-hex/kind-tagged scheme as the other ids (D14).
- **Config:** `retrieval_top_k = 25` (spec §7.3) and `retrieval_strategy: Literal["hybrid","dense"]
  = "hybrid"`. `retrieval_top_k` is an explicit param to the core function (not read from settings
  inside it), keeping the algorithm unit-testable without config (the D17 pattern); the orchestrator
  passes `settings.retrieval_top_k`.

**Options considered.**
- *Strategy shape:* a `Protocol` with concrete `Hybrid`/`Dense` classes vs. a single function with a
  `use_sparse: bool` flag vs. an enum dispatch.
- *Where the query is embedded:* in the strategy (retrieval layer) vs. inside `ClaimRepo.search`.
- *Build MMR now* vs. leave the interface open and ship only hybrid + dense.
- *Reciprocal dedup score:* keep the **max** of the two directions vs. first-seen vs. average.
- *Pair id ordering:* sort the two claim ids (canonical `a`/`b`) vs. keep query→neighbour direction
  and dedup on a `frozenset`.
- *`retrieval_top_k`:* explicit function arg vs. read from `Settings` inside `generate_*`.
- *`match` exhaustiveness:* trailing `assert_never` vs. rely on mypy's Literal narrowing vs. a
  `case _:` raise.
- *Factory embedders:* required shared instances vs. optional with `build_*` fallback (as in D23).

**Rationale / trade-offs.** The **Protocol + two classes** is the load-bearing call: §7.3 explicitly
wants retrieval strategies swappable for evaluation, and while hybrid-vs-dense today is *almost* just
"do we pass a sparse vector," MMR (and future strategies) are genuinely different algorithms, so the
seam belongs at the strategy level, not a boolean flag — and it keeps `generate_candidate_pairs`
strategy-agnostic. Embedding the query **in the strategy** (not the store) is the direct consequence
of D23: `ClaimRepo.search` takes vectors so the store stays a thin adapter, which means *someone*
above it must embed, and the strategy is the natural owner because *which* vectors to compute (dense
only vs dense+sparse) **is** the strategy. I did **not** build MMR — shipping hybrid + dense cleanly
now and leaving MMR as a documented future `CandidateStrategy` avoids unused code (D17) while the
interface already admits it. **Keeping the max score** on a reciprocal pair is the honest default:
retrieval is asymmetric (bge's query instruction is applied to the query side only, and RRF ranks
differ by direction), so a pair that either direction ranked highly is a strong candidate, and the
max preserves that signal; first-seen would be order-dependent and averaging would dilute a strong
one-directional hit. **Sorting the two ids** to canonicalise `a`/`b` makes the `Pair` itself
order-independent (not just the dedup key), so downstream stages and snapshots see a stable pair
regardless of which claim was the query — cleaner than deduping on a `frozenset` while leaving
`a`/`b` arbitrary. `retrieval_top_k` as an **explicit arg** keeps the core loop testable without
constructing `Settings`, the same discipline as `chunk_section` (D17). `assert_never` after the
`match` both satisfies mypy's missing-return check and gives a loud runtime guard if an unvalidated
value ever reaches it (verified: mypy clean; it is the first `match` statement in the codebase). The
factory mirrors D23 — embedders optional with a `build_*` fallback — so the orchestrator shares one
dense + one sparse instance across the repo and the strategy, but a quick script still works with no
wiring. What I gave up: a second embedder load if a caller forgets to share (same acceptable
footgun as D23, and the factory's docstring says to share); and MMR now (deferred, cheaply added
later behind the same Protocol).

**Verification.** In the scratchpad mirror (re-synced to the pushed HEAD): all four gates — ruff,
ruff-format, mypy `--strict` (clean over **37** files), pytest **89 passed** (the 82 so far + **7**
new: 1 `pair_id` order-independence case + 6 `test_candidate_gen.py`), zero warnings. The
candidate-gen tests cover both layers: the dedup/sort/self-skip logic of `generate_candidate_pairs`
against a *fake* strategy with canned neighbours (reciprocal A↔B collapses to one pair at the max
score 0.90; a self-hit is skipped; pairs come back score-descending), and the real `HybridStrategy`
/ `DenseStrategy` + factory against a real in-process Qdrant (`:memory:`) with the D23 fake
embedders — the cross-doc PTO pair is generated, no same-document pair is ever produced, and the
factory returns the class named by `retrieval_strategy`.

**Proposed by me**, following the spec (§7.3, §9.3, §11) and D4/D14/D17/D22/D23. Building only
hybrid+dense now (MMR deferred) and keeping the max reciprocal score are my recommended defaults and
are vetoable.

---

## D25 — Reranker: sentence-transformers `CrossEncoder` with the spec-exact bge-reranker-v2-m3 (fastembed can't carry it), `Reranker` Protocol, `rerank_pairs` resolves claim text (2026-07-09)

**Decision.** `retrieval/reranker.py` is the second retrieval file — the precision stage that
re-scores the candidate `Pair`s from D24 and keeps the top-K for detection (spec §7.3).

- **Backend = sentence-transformers `CrossEncoder("BAAI/bge-reranker-v2-m3")`** — the
  spec-prescribed model (§5). I first checked whether fastembed's `TextCrossEncoder` could carry it
  (that would reuse the ONNX stack and touch no torch): it lists `BAAI/bge-reranker-base`,
  ms-marco-MiniLM, and jina rerankers, but **not** `bge-reranker-v2-m3`. Since `torch` and
  `sentence-transformers` are already installed for the dense embedder (D22), sentence-transformers
  gives the **exact spec model with zero new dependencies** and reuses the same runtime — strictly
  better than switching to a weaker/different model to stay on fastembed.
- **`Reranker` Protocol** (`score_pairs(pairs: Sequence[tuple[str, str]]) -> list[float]`) with a
  concrete `CrossEncoderReranker` (lazy model load, injectable `model=` for tests) and a
  `build_reranker` factory — the exact shape of the embedders (D22), so tests stay hermetic and a
  different reranker can be swapped behind the interface.
- **`rerank_pairs(pairs, claims, reranker, *, top_k) -> list[Pair]`** resolves each pair's two claim
  ids to text via an in-memory `{claim_id: claim}` map built from `claims` (the orchestrator already
  holds the corpus in memory — no per-pair `ClaimRepo.get` round-trip), scores the `(text_a, text_b)`
  pairs with the reranker, attaches `rerank_score` to a `model_copy` of each pair, sorts by
  descending score (ties by `pair_id`), and truncates to `top_k`. A pair naming a claim absent from
  `claims` raises `RerankError` (a real wiring bug, surfaced loudly). Empty input short-circuits.
- **Config:** `rerank_model = "BAAI/bge-reranker-v2-m3"` (§5) and `rerank_top_k = 10` (§7.3, "keep
  top-10"). As with candidate-gen, `top_k` is an explicit `rerank_pairs` argument (unit-testable
  without `Settings`); the orchestrator passes `settings.rerank_top_k`.

**Options considered.**
- *Reranker backend:* sentence-transformers `CrossEncoder` (spec-exact model, torch already in) vs.
  fastembed `TextCrossEncoder` (ONNX, no torch — but it does **not** offer bge-reranker-v2-m3) vs.
  fastembed with a *different* model (`bge-reranker-base`).
- *Claim-text source:* pass the in-memory `claims` and build an id→claim map vs. resolve each id via
  `ClaimRepo.get` vs. carry the full claims on the `Pair`.
- *Reranker abstraction:* a `Reranker` Protocol + factory (as embedders) vs. a bare function.
- *Pair mutation:* return `model_copy`-updated pairs vs. mutate the inputs in place.
- *`(text_a, text_b)` order:* the canonical `a<b` order the pair already carries (D24) vs. some
  query/passage heuristic.
- *Unknown claim id:* raise `RerankError` vs. silently drop the pair.
- *Rerank on/off ablation:* orchestrator-level (skip the stage) vs. a `NoOpReranker`.

**Rationale / trade-offs.** The backend is the load-bearing call, and it turned on a concrete fact:
fastembed cannot serve the spec's reranker, so the only way to honor §5's `bge-reranker-v2-m3` is
sentence-transformers — which, crucially, costs **nothing** here because D22 already pulled torch and
sentence-transformers for the dense embedder. Choosing fastembed would have meant *deviating from the
spec's model* (to `bge-reranker-base`, an older/weaker reranker) purely to avoid a dependency I
already have — a bad trade. So this is the rare case where following the spec's model and adding no
dependency coincide. Passing the **in-memory `claims`** (not `ClaimRepo.get`) keeps rerank a pure,
fast, hermetically testable transform with no I/O: the orchestrator has the corpus in memory straight
from extraction, and a few hundred candidate pairs resolve instantly through a dict — a per-pair
Qdrant fetch would be needless latency and would couple the reranker to the store. The **Protocol +
factory + lazy/injectable model** mirrors the embedders (D22) so the same hermetic-test story
applies (a fake CrossEncoder and a fake Reranker, no 2 GB download). I **`model_copy`** rather than
mutate so the caller's `Pair` list is untouched (the pairs may be inspected or re-used, e.g. for the
rerank-vs-no-rerank ablation on the same candidate set). I score in the pair's **canonical `a<b`
order** (already fixed by D24) so reranking is deterministic and reproducible in snapshots; bge
rerankers are near-symmetric for similar-length claims, so a query/passage heuristic would add
nondeterminism for no clear gain. An **unknown claim id raises** because it can only mean a wiring
bug (pairs and claims out of sync), and silent-dropping would hide it. The rerank on/off **ablation
lives in the orchestrator** (just don't call `rerank_pairs`) rather than a `NoOpReranker` class —
less code, and §9.3 measures the stage's presence, not a pass-through. What I gave up: ONNX's
lighter runtime for the reranker (irrelevant — torch is already resident and the reranker sees only
the post-retrieval shortlist, so CPU cross-encoding cost is small); and the theoretical
torch-free stack (already abandoned in D22).

**Verification.** In the scratchpad mirror (re-synced to the pushed HEAD): all four gates — ruff,
ruff-format, mypy `--strict` (clean over **39** files), pytest **95 passed** (the 89 so far + **6**
new `test_reranker.py`), zero warnings. Before writing, I confirmed against the installed libraries
that fastembed's `TextCrossEncoder.list_supported_models()` does **not** include bge-reranker-v2-m3,
and that sentence-transformers 5.6.0 exposes `CrossEncoder.predict(inputs=[(a, b), …])`. The tests
inject a fake `CrossEncoder` (records the pairs it saw, returns a numpy score array — like the real
model) to check `CrossEncoderReranker` wiring and float conversion, and a fake `Reranker` with canned
scores to check that `rerank_pairs` resolves claim ids to the right texts in canonical order, attaches
`rerank_score`, sorts, truncates to `top_k`, no-ops on empty input, and raises `RerankError` on an
unknown claim id. The real model is left to the Phase-6 eval / a live check with the reranker
downloaded.

**Proposed by me**, following the spec (§5, §7.3, §9.3, §11) and D4/D22/D23/D24. The
sentence-transformers-over-fastembed choice is forced by model availability; the in-memory
claim-resolution and orchestrator-level on/off ablation are my recommended defaults and are vetoable.

---

## D26 — Negation-pair retrieval benchmark: `NegationPair` set + real-model integration test asserting recall@1, closing Phase 2 (2026-07-09)

**Decision.** Added the negation-sensitivity benchmark and its retrieval test (spec §7.3/§9.2/§12),
the last Phase-2 retrieval piece. Structure mirrors the extraction gold set (D18): a data schema +
loader in `evaluation/`, the data under `benchmarks/`, a hermetic unit test, plus a real-model
integration test.

- **`evaluation/negation.py`.** `ClaimSeed{doc_id, text, polarity}` and `NegationPair{subject,
  positive, negative}` (pydantic). `load_negation_pairs(path)` parses a JSON list via a
  `TypeAdapter`. `to_claim_pairs(pairs)` builds `(positive_claim, negative_claim)` real `Claim`s with
  **deterministic ids namespaced under `neg:`** (so the same seed yields the same `claim_id` whether
  built for indexing or for partner-lookup); `to_claims` flattens them into the corpus. Only `text`
  matters to retrieval, so `predicate` is left empty on the synthetic claims.
- **`benchmarks/negation/negation_pairs.json` + `README.md`.** **8 pairs**, one per distinct subject
  (insurance, PTO, refunds, termination, data retention, remote work, warranty, subcontracting),
  positives in `policy_v1`, negatives in `policy_v2`. Each negation is a genuine polarity flip of the
  same subject, lexically near-identical to its positive.
- **`tests/integration/test_negation_retrieval.py`** (marked `integration`, deselected by default).
  Real models: shares one dense + one sparse embedder across the repo (index) and the hybrid strategy
  (query), upserts the corpus into a `:memory:` Qdrant, and for each pair retrieves the positive's
  cross-document neighbours (hybrid) then reranks them with the real cross-encoder. **Asserts
  recall@1** — the true negation partner must be the single best match — with a `0.75` floor.
- **`tests/unit/test_negation.py`** (hermetic). Validates the committed fixture (≥8 pairs, distinct
  subjects, cross-document, opposite polarity) and that `to_claim_pairs`/`to_claims` produce valid,
  unique-id, deterministic, cross-document claims. No models.

**Options considered.**
- *Assertion metric:* recall@1 (partner is the single best) vs. recall@K (partner in the top-K
  shortlist).
- *Fixture selectivity:* one distinct subject per pair (clean) vs. adding near-duplicate distractors
  to force competition.
- *Real vs fake models:* a real-model integration test vs. a hermetic test with fake embedders.
- *Module/data placement:* `evaluation/negation.py` + `benchmarks/negation/` (mirroring D18) vs.
  test-only fixture + loader.
- *Data file layout:* a single JSON list vs. one-JSON-per-pair (as the gold set does, D18).
- *Verification model:* the real bge stack (~3.5 GB) vs. small stand-ins via env override.

**Rationale / trade-offs.** The point of this test is empirical: does the *default hybrid* stack
actually surface a claim's negation, given that dense embeddings place negations unpredictably
(§7.3)? That can only be answered with **real models**, so the core deliverable is a real-model
integration test; the hermetic unit test guards the harness (fixture + id logic) so CI still has cheap
coverage. I assert **recall@1, not recall@K**, because with a clean one-subject-per-pair fixture the
cross-document candidate set is tiny (8 negatives), so "in top-K" is trivially true — the discriminating
question is whether the reranker ranks the *true* negation **above the seven unrelated negatives**,
which is exactly recall@1. I deliberately kept the fixture **clean (distinct subjects)** rather than
adding lexical distractors: retrieval's job is to *surface* the partner, not to distinguish negation
from a near-duplicate non-negation (that is the NLI/judge's job, §7.4), so distractors would test the
wrong stage. Mirroring **D18's placement** (schema/loader in `evaluation/`, data in `benchmarks/`)
makes the loader reusable by the Phase-6 metrics module that reports negation recall as its own line
(§9.2), rather than stranding it in a test. A **single JSON list** (not one-file-per-pair) because the
negation set is a small, fixed fixture, not an expanding labeling effort like the ~50 gold chunks —
one file is easier to read whole and the diff noise D18 worried about doesn't apply at this size.
**Deterministic `neg:`-namespaced ids** are what let the test upsert the flattened corpus and still
identify each pair's partner by id without threading extra state. What I gave up: the test needs the
real embedder + reranker (~3.5 GB) on first run, so it is integration-marked and out of CI — I verified
it with small stand-ins (all-MiniLM-L6-v2 @ 384-d + ms-marco-MiniLM-L-6-v2) via the existing
`CROSSCHECK_*` model settings, which is also the documented cheap-run path.

**Verification.** In the scratchpad mirror (synced to pushed HEAD): all four gates — ruff, ruff-format,
mypy `--strict` (clean over **42** files), pytest **99 passed, 2 deselected** (95 + **4** new hermetic
`test_negation.py`; the 2 deselected are the ingestion + negation integration tests). The **integration
test was actually run** against real (small stand-in) models on a `:memory:` Qdrant end-to-end — build
embedders → upsert → hybrid retrieve → cross-encoder rerank → **recall@1 = 1.00 (8/8)**, all eight
negation partners ranked first, comfortably clearing the 0.75 floor. Running it surfaced the D22
deprecation (fixed; see the D22 addendum) — the first time a real sentence-transformers model was
loaded in a test.

**Proposed by me**, following the spec (§7.3, §9.2, §12, §11) and D18/D21/D22/D23/D24/D25. The recall@1
metric and clean-fixture choice are my recommended defaults and are vetoable.

---

## D27 — Live-Qdrant storage/retrieval integration test (self-skipping, isolated throwaway collection), closing Phase 2 (2026-07-09)

**Decision.** Added `tests/integration/test_live_qdrant.py`, a committed integration test that runs the
storage + retrieval path against a **real Qdrant server** (spec §7.2/§7.3/§8/§12) — the one thing the
`:memory:` unit tests structurally cannot prove. The user chose this over jumping straight to Phase 3.

- **Marked `integration`, self-skips if no server.** It builds the client and calls
  `get_collections()`; any connection failure → `pytest.skip`. So it is safe under `-m integration`
  with or without Docker (CI has no server → skip), mirroring the API-key self-skip of the ingestion
  test (D19).
- **Isolated throwaway collection, never touches `claims`.** Uses
  `get_settings().model_copy(update={"qdrant_collection": "crosscheck_itest"})` so it inherits the
  env-loaded model settings but writes to a dedicated collection; `ensure_collection(recreate=True)`
  gives a clean slate and a `finally: delete_collection(...)` cleans up.
- **Asserts what `:memory:` can't.** (1) The payload **indexes actually exist server-side** —
  `client.get_collection(name).payload_schema` contains `doc_id`/`subject`/`polarity` (`:memory:`
  no-ops index creation, so this is untested until now). (2) The **server-side subject filter**
  returns only the matching subject — exercising the payload index, not just the vector search. Plus
  the standard path on the real wire: upsert/count, `get` round-trip + missing→None, hybrid retrieval
  applying the cross-document `doc_id != self` filter, and the true partner retrieved.
- **Real models, small stand-ins for verification** (same `CROSSCHECK_*` override as D26).
- **Also fixed a paste artifact:** the committed `benchmarks/negation/README.md` had a chat-only
  "⚠️ … only so this chat renders" note accidentally pasted into it (D26 hand-over); handed over a
  clean replacement. Harmless (docs, not code) but removed.

**Options considered.**
- *Server dependency:* self-skip if unreachable vs. hard-fail vs. spin Qdrant up inside the test.
- *Collection:* an isolated throwaway (`crosscheck_itest`) + delete vs. reuse the real `claims`.
- *Settings override:* `model_copy(update=...)` vs. constructing a fresh `Settings(...)`.
- *Whether to build it at all now* vs. folding a live check into the Phase-3/4 end-to-end test.

**Rationale / trade-offs.** The whole point is to cover the gap the `:memory:` tests leave: local mode
silently no-ops payload indexes (it even warns so), so nothing committed proved the real server accepts
the index config or that a payload-index-backed filter works — D21/D22 checked this live in dev, but
those checks weren't committed. This test makes that a standing regression guard. **Self-skip** (not
hard-fail) keeps one test that is a real check when a server is up and a clean no-op when it isn't,
so it can live under the same `-m integration` gate as the model tests and never breaks CI. An
**isolated throwaway collection with teardown** is a safety requirement: an integration test must
never clobber a developer's real `claims` data, and `recreate=True` also makes it robust to a leftover
collection from an interrupted run. `model_copy` over a fresh `Settings()` preserves any `CROSSCHECK_*`
model overrides the runner set (needed for the cheap-model path) while swapping only the collection
name. I built it now because the user asked to close Phase 2 cleanly before Phase 3; the alternative
(fold into the Phase-3/4 orchestrator test) is still fine later, but this gives the storage/retrieval
layer its own focused live guard independent of the judge. What I gave up: the test needs Docker to do
anything (it skips otherwise), so it is developer-run, not CI-run — acceptable and expected for a
live-infra test.

**Verification.** In the scratchpad mirror against the **real Qdrant 1.18.2** already running on
`:6333`: all four gates — ruff, ruff-format, mypy `--strict` (clean over **43** files), pytest
**99 passed, 3 deselected** (the 3 integration tests: ingestion, negation, live-Qdrant). The live test
itself **passed against the real server** (10.7s, small stand-in models) — payload schema carried all
three indexed fields, upsert/count/get/missing worked over the wire, the cross-document filter excluded
the self-doc, the insurance partner was retrieved, and the server-side `subject="insurance"` filter
returned exactly the one matching claim. The **self-skip path** was confirmed by pointing
`CROSSCHECK_QDRANT_URL` at a dead port: the test skipped cleanly with its guidance message. The
throwaway collection is deleted in `finally`.

**Proposed by me** at the user's direction (they chose the live test over starting Phase 3), following
the spec (§7.2, §7.3, §8, §12) and D19/D21/D22/D23/D24. The self-skip and isolated-collection choices
are standard and vetoable.

## D28 — NLI contradiction pre-filter: recall-first keep rule (argmax OR threshold), per-type thresholds with most-permissive fallback, bidirectional scoring, dynamic id2label index; no new dependency (2026-07-13)

**Decision.** Added `src/crosscheck/detection/nli_filter.py` — the cheap NLI pre-screen that sits
between candidate reranking and the LLM judge (spec §7.4; the two-stage cost-control architecture of
§4). This is the first file of **Phase 3 (Detection)**. Its shape deliberately mirrors the reranker
(D25) and embedders (D22): an `NLIScorer` `Protocol` + a `DebertaNLIScorer` (lazy/injectable, default
`cross-encoder/nli-deberta-v3-base`) + a `build_nli_scorer` factory, plus a pure
`filter_pairs(pairs, claims, scorer, *, thresholds, default_threshold, type_hints=None)` transform
that keeps the likely-contradiction pairs and stamps each survivor's `Pair.nli_contradiction_prob`.
The design carries several sub-decisions:

- **Recall-first keep rule.** A pair survives if contradiction is the NLI **argmax** (top of the three
  labels) **OR** its contradiction probability clears a threshold. The argmax OR-clause is the recall
  floor — the spec targets ≥95% recall at this stage and lets the judge recover precision.
- **Per-type thresholds, most-permissive when the type is unknown (§7.4).** Thresholds are a
  `dict[ContradictionType, float]` plus a scalar `default_threshold`. The true type isn't known until
  the judge, so `filter_pairs` uses `min(default, *thresholds.values())` (the most permissive/lowest
  threshold) unless the caller passes a `type_hints` mapping (pair_id → type) — which the Phase-6
  calibration harness, which knows the gold type, will use. `nli_thresholds` ships **empty**, so until
  Phase-6 calibration every pair uses the single default (0.5).
- **Bidirectional scoring.** NLI is directional, so each pair is scored in **both** orderings `(a,b)`
  and `(b,a)`; the results are combined by max P(contradiction) and argmax-in-either. This is ~2× the
  NLI calls but NLI is ~1000× cheaper than the judge, so it's negligible, and it defends recall against
  NLI's directional asymmetry. **I offered this as vetoable and the user chose to keep it.**
- **Dynamic contradiction index + manual softmax.** The contradiction label's position is read from
  the model's `id2label` (not hardcoded to 0), so a differently-ordered NLI model still works; the
  three logits are turned into probabilities with a small numerically-stable softmax.
- **Claim text resolved from the in-memory `claims`** (same as the reranker, D25), not the store;
  `NLIError` on an unknown claim id rather than a silent drop.
- **Config knobs are explicit params to `filter_pairs`** (`thresholds`/`default_threshold`), not read
  from `Settings` inside it — the D17/D24/D25 "core is testable without Settings" pattern; the
  orchestrator passes `settings.nli_thresholds` / `settings.nli_default_threshold`.
- Config added: `nli_model`, `nli_default_threshold` (0.5), `nli_thresholds` (empty). This also pulled
  a `from crosscheck.detection.taxonomy import ContradictionType` import into `config.py` (no circular
  import — `taxonomy.py` imports only stdlib).

**Options considered.**
- *NLI backend:* sentence-transformers `CrossEncoder` (already resident from D22) vs. fastembed vs. a
  raw `transformers` pipeline.
- *Keep rule:* argmax-OR-threshold (recall-first) vs. threshold-only vs. argmax-only.
- *Directionality:* bidirectional (score both orderings) vs. forward-only (canonical `(a,b)`).
- *Threshold when type unknown:* most-permissive (min) vs. the scalar default vs. deferring all
  type-specific thresholds to the judge.
- *Contradiction index:* read from `id2label` vs. hardcode 0 (the value for nli-deberta-v3-base).
- *Where thresholds live:* explicit function params vs. read `Settings` inside `filter_pairs`.

**Rationale / trade-offs.** The whole reason this stage exists is cost: a 500-claim corpus yields on
the order of 10k candidate pairs after retrieval, and judging all of them with the LLM is prohibitive
(§4). NLI is roughly 1000× cheaper, so its job is to cut ~10k pairs down to a few hundred **without
dropping real contradictions** — recall is the objective, precision is the judge's job. That single
fact drives the design. The **argmax OR-clause** guarantees that any pair the model actually calls a
contradiction survives even if its probability is modest, which is the recall floor the spec asks for.
**Bidirectional scoring** is the same instinct: NLI genuinely gives different scores depending on
which claim is the premise, and since the extra call is free relative to the judge, scoring both ways
removes an arbitrary, silent source of missed contradictions. **Most-permissive-when-unknown** is
required because the type-specific thresholds only make sense once you know the type, and we don't
until the judge — so pre-judge we must not let a strict per-type threshold reject a pair we can't yet
classify; the permissive floor keeps recall up, and the `type_hints` hook lets the calibration harness
(which *does* know the gold type) exercise the real per-type thresholds in Phase 6. Reading the
contradiction index from **`id2label`** costs nothing and makes the code correct for any label
ordering — I confirmed by probe that nli-deberta-v3-base is `{0: contradiction, 1: entailment,
2: neutral}`, but hardcoding that would silently produce garbage if the model were ever swapped.
Keeping thresholds as **explicit params** rather than reading `Settings` inside keeps `filter_pairs` a
pure function that's exact and offline to test — the same pattern as chunking (D17), candidate-gen
(D24), and the reranker (D25). The **sentence-transformers backend** reuses the torch/ST stack already
pulled in by D22, so the NLI model adds **no new dependency**. What I gave up: bidirectional doubles
NLI inference (irrelevant against judge cost); `nli_thresholds` being empty means the per-type logic is
dormant until Phase 6 (intended — calibration needs the benchmark first).

**Verification.** In the scratchpad mirror re-synced to the pushed HEAD, all four gates: ruff,
ruff-format, mypy `--strict` (clean over **46** source files), pytest **110 passed, 5 deselected**
(the 89 prior hermetic tests + **16** new in `test_nli_filter.py`, with the 5 integration tests
deselected). The new unit tests are fully hermetic: a **fake `NLIScorer`** with a canned
`(premise,hypothesis) → NLIResult` table exercises the keep/drop logic exactly — argmax keeps a pair
below threshold, a high probability keeps a non-argmax pair, a low-and-not-argmax pair is dropped, the
reverse ordering alone can keep a pair and sets the max probability, a `type_hint` applies that type's
stricter threshold while no-hint uses the permissive floor, empty in → empty out, and an unknown claim
id raises `NLIError`; a **fake CrossEncoder** (raw logits + `id2label`) confirms `DebertaNLIScorer`
finds the contradiction index dynamically (including a non-standard label order), softmaxes correctly,
and raises when no contradiction label exists. Separately, the opt-in real-model test
(`tests/integration/test_nli_real.py`, marked `integration`) was run earlier against the real
`nli-deberta-v3-base` (2 passed, ~13s): it scored "must carry insurance" vs "not required to carry
insurance" as a high contradiction and an unrelated office-hours claim as low, and `filter_pairs` kept
the former and dropped the latter. No new dependency (the model loads on the existing ST/torch stack).

**Proposed by me**, following the spec (§7.4, §4) and the established D22/D24/D25 module shape
(Protocol + lazy/injectable impl + factory + pure transform). The recall-first keep rule, per-type /
most-permissive thresholds, and dynamic `id2label` index are spec-driven; the **bidirectional-scoring
default was flagged as my recommendation and explicitly kept by the user** rather than switched to
forward-only.

## D29 — LLM judge: reduced `JudgedVerdict` + code-side finalization, whitespace-tolerant evidence substring check, per-pair judging with graceful cost-ceiling stop, resume verdict cache (model-keyed), taxonomy coercion to UNCLEAR (2026-07-14)

**Decision.** Added `src/crosscheck/detection/llm_judge.py` — the final detection stage (spec §7.4),
which turns each NLI-surviving candidate pair into a structured `Verdict` via the shared cost-tracked
`LLMClient` (D12). Plus two versioned prompts (`contradiction_judge_system.v1.md`,
`contradiction_judge_user.v1.md`, per D13), hermetic unit tests, and an opt-in real-model integration
test. No config change — `judge_model` already existed (D12). The design carries several
sub-decisions, each mirroring an existing precedent:

- **Reduced LLM schema + code-side finalization** (the extractor pattern, D14/D15). The model returns
  a `JudgedVerdict` (ruling fields only); code sets `pair_id` from the pair being judged and builds
  the full `Verdict`. The model never supplies the id.
- **Substring-validated evidence, whitespace-tolerant** (§7.4; reuses D20). For a claimed
  contradiction, `evidence_a`/`evidence_b` must be verbatim substrings of the two claims (checked
  against `claim.text` + `claim.evidence_quote`, both of which the prompt shows). The check tolerates
  whitespace differences exactly as the extractor's `_locate_quote` does, because Claude normalizes a
  source's line-wrap newlines to spaces while copying a span verbatim (the D20 lesson) — an exact
  check would wrongly reject genuine quotes. A contradiction whose evidence isn't found is **dropped
  and counted** as a judge-hallucination (`hallucination_count` / `hallucination_rate`, §9.2).
  Non-contradiction verdicts skip evidence validation (there's nothing to substantiate).
- **Per-pair judging** (not batched). One pair per LLM call, so the cost ceiling and the resume cache
  are naturally per-pair, evidence validation is per-pair, and one call maps to exactly one verdict.
- **Graceful cost-ceiling stop** (§4). The `LLMClient` raises `CostCeilingError` before dispatching
  once spend hits the ceiling; the judge catches it, marks the result `partial=True`, and returns the
  verdicts gathered so far rather than propagating. This is exactly the §4 "stop dispatching new judge
  calls, finalize with what it has, mark partial" behavior, located at the judge itself.
- **Resume verdict cache** (§4; the extractor's cache trio, D14/D15). `VerdictCache` Protocol +
  `InMemoryVerdictCache` (default) + `DiskVerdictCache` (one JSON per key). Key =
  `content_hash(judge_model + "\n" + claim_a.text + "\n" + claim_b.text)`. **The judge model is folded
  into the key** — a deliberate difference from the extractor cache (which is single-model) — so a
  cross-model eval run (Claude vs GPT-4o judge, §9.3) never serves one model's verdicts for the other.
- **Taxonomy invariants enforced in code, not just the prompt** (§6). A returned reserved
  `CONDITIONAL_TRIPLET` is coerced to `UNCLEAR` (with a warning), and a contradiction the model left
  untyped also becomes `UNCLEAR`, so "every detection carries a valid v1-or-UNCLEAR type" holds
  regardless of what the model emits.
- **Returns all verdicts, positive and negative.** The audit report only needs contradictions, but the
  eval harness (§9.2 precision/recall, calibration) needs the negatives too, so filtering is deferred
  to aggregation (`JudgeResult.contradictions` is a convenience view).

**Options considered.**
- *Per-pair vs. batched judging* (several pairs per call to amortize the system prompt).
- *Cost ceiling*: catch `CostCeilingError` in the judge and return `partial` vs. propagate and let the
  orchestrator collect incrementally.
- *Verdict cache*: build it now in the judge vs. defer all resume plumbing to the orchestrator; and
  whether to fold the judge model into the cache key.
- *Evidence haystack*: validate against `claim.text` only vs. `text` + `evidence_quote`; exact vs.
  whitespace-tolerant substring.
- *Verdict set*: return all verdicts vs. only contradictions.
- *Untyped/triplet verdicts*: coerce to `UNCLEAR` vs. reject vs. trust the model.

**Rationale / trade-offs.** **Per-pair** wins because the whole two-stage architecture already cut the
work to a few hundred pairs (§4), so the amortization batching would buy is small — and the system
prompt is cacheable across calls anyway (the wrapper tracks cache tokens, D12), which recovers most of
it. In exchange, per-pair gives clean cost-ceiling granularity, per-pair evidence validation, and a
one-call-one-verdict mapping that batching would muddy (a batched call that hits the ceiling mid-batch,
or returns a verdict for the wrong pair, is exactly the kind of bug I don't want). **Catching the
ceiling in the judge** (vs. propagating) is what preserves partial results: propagating before
returning would throw away the verdicts already computed, whereas the spec wants the report finalized
"with what it has." **Building the cache now** keeps the most expensive stage's resume support
co-located with the expensive call, exactly as the extractor does; the `DiskVerdictCache` is the same
"one JSON per hash in a dir" shape the orchestrator's resume layer will point at, so there's no rework
— and folding the model into the key is a small correctness fix for the cross-model eval that the
extractor didn't need. **Validating against `text` + `evidence_quote`** (both shown in the prompt) is
strictly more lenient than `text` alone and avoids counting a legitimate source-span quote as a
hallucination, which would pollute the metric; whitespace tolerance is the same D20 defense that
recovered ~17% of extractor claims. **Returning all verdicts** costs nothing (they're already
computed) and is required for honest precision/recall and calibration in eval — dropping negatives
here would blind the metrics. **Coercing to UNCLEAR** enforces the §6 invariant in code so a
prompt-following lapse can't leak a reserved or missing type downstream. What I gave up: per-pair calls
mean N HTTP round-trips rather than N/batch (fine at a few hundred pairs, and parallelism can be added
later if needed); the judge now owns a cache concept (a little more surface in one file, but familiar
from the extractor). Deferred to later phases, deliberately: **judge temperature** tuning (§8 Phase 6)
— the `LLMClient.structured` wrapper doesn't expose temperature yet, and adding it is a wrapper change,
not a judge change, so it waits for the Phase-6 tuning pass; and the **per-document cost cap**
(`max_document_cost_usd`) stays an orchestrator concern (the judge works over corpus-wide pairs, not
per-document, and respects the single audit ceiling via the wrapper).

**Verification.** In the scratchpad mirror re-synced to the pushed HEAD (`112194c`), all four gates:
ruff, ruff-format, mypy `--strict` (clean over **49** source files), pytest **121 passed, 7
deselected** — the 110 prior tests plus **11** new hermetic `test_llm_judge.py` cases and **2**
deselected integration tests. The unit tests wrap a real `LLMClient` around a mocked Anthropic client
(so cost tracking and the ceiling run for real) and feed canned `JudgedVerdict`s: a contradiction is
finalized with the code-set `pair_id` and preserved type; hallucinated evidence is dropped and counted
(`hallucination_rate == 1.0`); a negative verdict is kept with no evidence validation and isn't counted
as a hallucination; `CONDITIONAL_TRIPLET` and a missing type both coerce to `UNCLEAR`; a source-span
quote and a whitespace-normalized quote are both accepted; the cache serves a repeat pair without a
second call; a low ceiling stops after one pair with `partial=True` and `llm_call_count == 1` while
`pair_count == 2`; an unknown claim id raises `JudgeError`; and empty input makes no calls. **The user
then ran the opt-in real-model test against live Claude (`test_judge_real.py`, 2 passed, ~21s):** the
real judge flagged the insurance obligation-reversal with a concrete v1 type and evidence that passed
the substring check (`hallucination_count == 0`), and cleared the unrelated office-hours pair as a
non-contradiction — confirming the `JudgedVerdict` schema round-trips through the live API and the
prompt's verbatim-evidence instruction actually holds against real output.

**Proposed by me**, following the spec (§7.4, §4, §6, §9.2) and the established D12/D13/D14/D15/D20
patterns (single LLM wrapper, versioned prompts, reduced-schema + code-side finalization,
whitespace-tolerant verbatim check). The two judgment calls I flagged — **including the verdict cache
now** and **returning all verdicts (not just contradictions)** — were presented with rationale for the
user to veto; both were kept.

## D30 — Orchestrator: cache-based resume rather than document-skipping, per-document cost cap via a temporary LLM budget, corpus-scaled rerank budget, `AuditResult` instead of an early report (2026-07-25)

**Decision.** Added `src/crosscheck/orchestrator.py` — the `audit()` entry point that runs all eight
spec §4 stages in sequence (parse → chunk → extract → embed/store → candidate-gen → rerank → NLI
filter → judge) — plus the supporting changes it needs: a `budget()` context manager and
`cost_ceiling_usd` property on `LLMClient`, an `audit_state_dir` setting, and the real `crosscheck
audit` CLI command in place of the Phase-0 stub. This completes Phase 3. The design carries five
sub-decisions:

- **One `LLMClient` per audit, shared by extraction and the judge.** Both spending stages take the
  same instance, so they share one `CostTracker` and therefore one ceiling. Separate clients would
  mean two independent half-ceilings that could together spend double the cap.
- **Resume means "re-spend no tokens", not "skip documents".** A resumed audit re-parses, re-chunks
  and re-embeds (all local, all free) but serves extraction from `DiskClaimCache` and judging from
  `DiskVerdictCache`, both pointed at the audit's state directory, and re-upserts idempotently by
  `claim_id`. The state directory is keyed by a deterministic `audit_id = content_hash(resolved
  corpus path)`, so resuming is automatic rather than something the user opts into with a run id. A
  small `audit_state.json` breadcrumb records how far the last run got.
- **The per-document cap is enforced by temporarily narrowing the shared client's ceiling.**
  `with llm.budget(settings.max_document_cost_usd)` around each document's extraction. Both caps
  therefore raise the same `CostCeilingError`, and the orchestrator tells them apart by comparing
  spend against the audit ceiling captured before the loop: audit ceiling → stop ingesting and mark
  the result `partial`; per-document cap → warn, abandon that one document, continue. A non-positive
  cap means "no cap".
- **The rerank budget is scaled by corpus size:** `top_k = rerank_top_k * max(1, len(claims))`.
- **The orchestrator returns an `AuditResult`, it does not build a report.** The result carries the
  verdicts plus the claims and judged pairs needed to render them, the stage counters, and the cost.

**Options considered.**
- *Resume*: cache-based (chosen) vs. skipping already-ingested documents, which would need a new
  "scroll all claims" method on `ClaimRepo` to reload their text for the downstream stages.
- *Per-document cap*: temporary budget on the shared client (chosen) vs. warn-only after the fact vs.
  a second `LLMClient` per document vs. leaving `max_document_cost_usd` unused.
- *Rerank budget*: corpus-scaled (chosen) vs. passing `rerank_top_k` straight through vs. changing
  `rerank_pairs` to group per claim.
- *Output*: `AuditResult` now and aggregation in Phase 4 (chosen) vs. building a minimal
  `ContradictionReport` here.
- *Store hygiene*: non-destructive upsert plus a warning (chosen) vs. recreating the collection on
  every audit.

**Rationale / trade-offs.** **Cache-based resume** wins because it targets the thing that actually
costs money. Only two of the eight stages spend anything, both already had content-hashed disk caches
from D14/D15 and D29, and pointing them at the state directory buys the whole §4 promise with no new
machinery. Document-skipping would be strictly stronger, but it would require reaching back into
finished Phase-2 code to add a bulk-read method to `ClaimRepo` purely to reload claim text that the
rerank/NLI/judge stages resolve from memory — a lot of new surface to avoid re-doing work that is
free. What I gave up is stated plainly: a resumed run does re-parse and re-embed. The tests prove the
part that matters — a second audit of the same corpus makes zero LLM calls and costs $0.0000.

The **per-document cap** needed to be *enforced*, not merely observed. §4 asks for it and §14 lists
an unbounded audit as an anti-pattern, yet `max_document_cost_usd` had been dead config since Phase 0
because a per-document cap needs something that knows where one document ends — which no single stage
does. Narrowing the shared client's ceiling reuses the existing breaker instead of inventing a second
one, and `budget()` can only ever narrow (`min(previous, spent + limit)`), so no caller can use it to
buy more room than the audit was given. Warn-only was the cheaper option and I rejected it as not
being enforcement at all. The honest limitation: the ceiling is checked before a call, not predicted
from it, so a cap smaller than a single call's cost still permits the first call — the cap bounds how
far a document can overrun, it doesn't prevent it starting.

The **rerank budget** is the one I'd have shipped wrong without noticing. `rerank_pairs` keeps a
corpus-wide top-K (D25), while §7.3's "keep top-10" reads naturally as ten *per claim*. Passing
`rerank_top_k` straight through would have a 500-claim corpus generate thousands of candidates and
then keep ten in total — the funnel would silently collapse and every stage would still log a
plausible number. Scaling by claim count keeps the intended budget while letting it pool where the
cross-encoder found signal (a claim with five real conflicts keeps all five; one with none
contributes none), and it leaves finished, tested Phase-2 code untouched. The trade-off is that the
distribution is no longer uniform per claim, which I prefer — but it makes retrieval `K` and this
multiplier joint tuning knobs for Phase 6.

**Returning `AuditResult`** keeps the Phase 3/4 boundary clean: writing a half-report here would mean
writing it twice. It carries `claims` and `judged_pairs` because a `Verdict` identifies its pair by
`pair_id` alone and cannot be rendered without them, and it keeps non-contradiction verdicts because
precision/recall/calibration (§9.2) are undefined without negatives. Finally, **non-destructive
upsert plus a `_warn_on_foreign_claims` check** keeps resume cheap without silently mixing corpora:
recreating by default would wipe the store on every resume, so instead `reset_store=True` is
available and the orchestrator logs a warning when the collection holds more claims than the current
corpus produced.

**Empty paths** are treated as ordinary results throughout (§7.5): no files, only unsupported files,
no claims extracted, and no contradictions all produce a well-formed `AuditResult`. The no-files case
returns before constructing anything, so auditing an empty directory needs neither an API key nor a
running Qdrant.

**Provenance.** Mine, following the spec. The eight-stage sequence, both cost caps, the resume
requirement, and the empty-report path are spec-driven (§4, §7.5). The four judgement calls —
cache-based resume over document-skipping, `budget()` over warn-only, the corpus-scaled rerank
budget, and deferring the report to Phase 4 — were my recommendations and were flagged as vetoable at
hand-over.

## D31 — Acceptance corpus: a fictional 10-document policy set under `benchmarks/acceptance/`, with DOCX/PDF rendered from JSON sources; `fpdf2` added as a dev dependency (2026-07-26)

**Decision.** Built the corpus that unblocks the Phase 3 acceptance smoke test: 10 fictional
documents for "Arden Systems" covering all four v1 input formats, with 23 conflicts planted across
all five v1 contradiction types and a set of deliberate cross-document *agreements* to give the run
precision signal. It also closes the Phase 1 milestone (10 documents → ≥200 claims), since
`tests/integration/test_ingestion_pipeline.py` already reads `CROSSCHECK_TEST_CORPUS`. Four
sub-decisions:

- **Fictional, not real public documents.** The corpus is invented rather than drawn from NIST/GDPR/
  HIPAA texts.
- **`benchmarks/acceptance/`, not `tests/fixtures/`.** It sits beside the existing `extraction_gold/`
  and `negation/` eval assets. `tests/fixtures/corpus/` stays the tiny 3-document corpus the fast
  tests use.
- **DOCX and PDF are rendered from JSON in a sibling `sources/` directory**, not committed as
  hand-made binaries and not generated from prose inlined in the build script.
- **`fpdf2` as a dev dependency**, which also let me close a real coverage hole: `_parse_pdf` had
  never executed under test.

**Options considered.**
- *Corpus content*: fictional policy set (chosen) vs. real public documents now vs. both (fictional
  now + a `fetch_seed_corpus.py` for Phase 5/6).
- *Location*: `benchmarks/acceptance/` (chosen) vs. `tests/fixtures/acceptance_corpus/`.
- *Binary documents*: render from JSON sources (chosen) vs. prose inlined in the build script vs.
  commit hand-made binaries vs. drop PDF/DOCX and ship a Markdown/text-only corpus.
- *PDF writer*: `fpdf2` (chosen) vs. `reportlab` vs. hand-rolling minimal PDFs vs. leaving
  `_parse_pdf` untested.

**Rationale / trade-offs.** **Fictional wins on the one thing this corpus is for.** Its job is to
prove the eight stages are wired together, and "produced a non-empty report" is only an acceptance
signal if I know in advance what should be in it. Real documents give no such guarantee, and SP
800-53 at 400+ pages would exhaust the cost ceiling during extraction before the pipeline ever
reached retrieval. What I gave up is authenticity, and I'm not pretending otherwise — the README
states the corpus is lexically obvious, non-adversarial, and author-labelled. Real documents keep
their proper homes: LLM-injected gold labels in Phase 5, and the NIST Rev 4 vs Rev 5 check in
Phase 6. I declined the "both" option because a seed-corpus fetcher written now would be built
against guesses about what Phase 5 needs.

**Rendering binaries from JSON sources came out of a failure.** The first version of
`build_acceptance_corpus.py` carried ~400 lines of document prose inline as Python string literals.
Transcribing it corrupted the file: one block was pasted five times, three documents' worth of prose
vanished, and `main()` was lost. Every planted contradiction outside the vendor agreement was gone —
and because the file still *looked* plausible, it would have produced a near-empty smoke run that I
might have misread as a detection failure rather than a corpus failure. The fix is structural, not
clerical: prose is data, so it belongs in data files. The script dropped from ~520 lines to ~120, the
prose became reviewable in `git diff` instead of buried in string concatenation, and the corruption
mode disappeared with it. Sources live in a *sibling* directory rather than inside `corpus/` for a
concrete reason — a source file and its rendered twin inside the audited directory would be parsed as
two documents and reported as spurious near-duplicate findings.

**`fpdf2` over `reportlab`** because this is fixture generation: pure-Python, no system libraries, a
small API. `reportlab` offers layout control this doesn't need. Hand-rolling PDFs was rejected on the
grounds that untested fixture-generation code is a bad foundation for tests. The dependency paid for
itself immediately: `_parse_pdf` (`parsers.py` 214–229) had zero coverage because nothing in the repo
could write a PDF — the original Phase 1 verification was done in a throwaway mirror project with
`reportlab`, so it never left a test behind. Three tests now cover one-section-per-page with correct
`page_span`s, the metadata-title-then-stem fallback, and running-header stripping on real
pdfplumber-extracted text. `parsers.py` coverage went 89% → 97% and the suite 131 → 134.

The PDFs are laid out over three pages with a running header and page-number footer on purpose:
`_strip_running_headers_footers` only infers a running header at three or more pages, so a shorter
fixture would leave that branch unexercised against real extracted text.

**Provenance.** Mine. The four sub-decisions were my recommendations, each presented with
alternatives and accepted. The restructure to JSON sources was my proposal after diagnosing the
corrupted hand-over — and the underlying mistake was mine too: putting 400 lines of prose in a file
that had to be transcribed by hand.

## D32 — Truncated structured output: a typed `LLMTruncationError`, split-and-retry in the extractor, and a 4000-token per-chunk budget (2026-07-27)

**Decision.** The Phase 3 acceptance smoke test crashed on document 5 of 10 with a raw pydantic
`ValidationError`. The fix has three parts, in three layers:

- **`llm.py` owns the failure mode.** `structured()` now also catches `pydantic.ValidationError`
  and re-raises either `LLMTruncationError` (a new `LLMError` subclass) or a plain `LLMError`,
  discriminated by a `_is_truncated()` helper.
- **`claim_extractor.py` recovers instead of dying.** `_extract_with_retry()` wraps
  `_extract_batch()`: on truncation it halves the batch and retries each half; at a single chunk it
  doubles the cap once; if that still overflows it logs a warning, counts the chunk in a new
  `truncated_chunk_count`, and **leaves it uncached**.
- **`config.py` raises the budget.** `extraction_max_output_tokens_per_chunk` 1500 → 4000.

**The bug.** `LLMClient.structured()` calls `messages.parse()`, which validates the response text
*inside* the SDK. A response stopped by the `max_tokens` cap therefore arrives as a pydantic
`ValidationError` — not an `anthropic.AnthropicError` — so the existing `except` didn't catch it and
it propagated through `_extract_batch` → `_ingest` → `audit()` → CLI, killing a run that had already
paid for 138 claims. The guard I wrote in D12 for exactly this class of failure —
`if parsed is None: raise LLMError(...)` — never fires, because the SDK throws before `response` is
ever assigned.

The contributing cause was a miscalibrated budget. `max_tokens = len(batch) * 1500` gave
`05_expense_policy.txt` (a single-section TXT → 2 chunks) a 3000-token cap, but a dense 400-token
policy chunk yields 15–25 claims and each claim serialises to ~120–180 output tokens across `text`,
`evidence_quote`, `subject`, `predicate`, `conditions`, `polarity` and `quantitative`. The spec's
"~1500 output tokens per chunk" (§7.1) is simply wrong for claim-dense text. The near-miss is visible
in the same log: `03_remote_work_policy.txt`, also 2 chunks, produced 26 claims and just fit.

**Options considered.**
- *Detection*: catch `ValidationError` and sniff the error shape (chosen) vs. replace `messages.parse`
  with `messages.create` plus hand-rolled validation so `stop_reason` is directly readable.
- *Recovery*: split-and-retry then give up (chosen) vs. raise the cap only vs. skip the batch and
  continue vs. fail the audit cleanly.
- *Budget*: 4000 (chosen) vs. leave at 1500 and rely on the retry vs. compute a cap from chunk length.
- *Failed chunks*: leave uncached (chosen) vs. cache the empty result.

**Rationale / trade-offs.** All three parts earn their place, and none is sufficient alone.
Detection-only converts a crash into a clean error but still loses the audit. Budget-only is a guess
that a denser document defeats. Recovery is what makes the pipeline robust, and the spec's whole
cost-ceiling/resume design implies an audit must not die from one bad batch.

Discriminating truncation by error shape is the part I like least, because it depends on a pydantic
message string. I checked it empirically rather than assuming: truncation is `json_invalid` with
"EOF while parsing"; complete-but-invalid JSON reports "expected value"; a type or field error is not
`json_invalid` at all. Both branches are unit-tested, so a pydantic change that breaks the
discrimination fails the suite rather than silently reclassifying every truncation as a schema error.

**Leaving a failed chunk uncached is the subtle one, and it matters most.** Caching an empty result
would be the natural thing to write and would be a silent, permanent data-loss bug: every resumed run
would serve zero claims for that chunk straight from cache and never retry, and because the resume
path is the *normal* path, the loss would compound invisibly across runs. Skipping the cache write
costs one re-extraction and keeps the failure recoverable.

**A known gap I chose to accept rather than hide.** A truncated call's tokens are *not* recorded
against the cost tracker, because the SDK raises before `structured()` holds a response object whose
usage it could read. The spend is real but invisible to the ceiling, bounded by `max_tokens` per
truncated call. Closing it properly means the `messages.create` migration, which would revisit D12's
structured-output choice — a bigger change than this bug warranted, and now rarely exercised given
the 4000-token default (the acceptance run recorded **0 truncated chunks**, so the retry ladder never
fired). It is documented in the `structured()` docstring rather than left for someone to discover.

Raising the budget is close to free: `max_tokens` is a cap, not a spend — you are billed for tokens
actually generated — so a generous cap costs nothing and the audit ceiling still bounds a runaway.

**How I verified it.** Four gates green (ruff, ruff-format, mypy --strict, pytest at 138). Two unit
tests cover the LLM layer (truncation → `LLMTruncationError`; schema violation → plain `LLMError`)
and two cover the extractor (a truncated 2-chunk batch splits and both halves succeed; a chunk that
truncates twice is skipped, counted, and **not** cached). Then the real acceptance run: all 10
documents ingested, 65 chunks, **342 claims, 0 truncated chunks, 0 rejected quotes, 0 hallucinations**
— and `05_expense_policy.txt`, the document that crashed, extracted 36 claims in one call.

**What the acceptance run also surfaced (open, for later phases).** The run stopped `partial` at the
$0.40 ceiling after judging 4 of 906 surviving pairs. Two verdicts were real planted conflicts; two
were the *same* false positive in both directions — both security documents state "updates within 14
days, and within 48 hours where critical", and the judge paired the general rule from one document
with the critical-case rule from the other and called it a numerical mismatch. It is a refinement,
not a conflict, and that text is a planted *agreement*. Two follow-ups, neither fixed here:

1. **Judge prompt**: general rule vs. scoped exception is being misread as contradiction (Phase 6).
2. **Aggregation**: one semantic finding surfaced twice; grouping belongs in Phase 4 (§7.5).

The funnel is also loose — rerank keeps 3420/5572 and NLI keeps 906/3420 — so a complete audit of
this corpus costs roughly $9 at ~$0.010/judged pair. That is above the $5.00 default ceiling and is
a tuning target for Phase 6, not a defect. The full non-partial run is deferred to a later session.

**Provenance.** Mine, prompted by a real crash rather than by review. The three-part shape and the
uncached-failure rule were my recommendations and were accepted; the acceptance-run findings above
are observations, recorded here so the Phase 4 and Phase 6 work starts from evidence.

## D33 — Report cross-linking: a lightweight `DocumentRef` index on `AuditResult`, not the full `Document` (2026-08-01)

**Decision.** `AuditResult` gains `documents: list[DocumentRef]`, replacing the bare
`document_ids: list[str]`. A `DocumentRef` carries the `doc_id`, the `source_path`, the title, and a
list of `SectionRef` (`section_id`, `heading`, `page_span`) — enough to render "01_employee_handbook.md
§ 2. Paid Time Off" and nothing more. `document_ids` survives as a derived property so existing
callers keep working.

**The gap.** Spec §7.5 requires the report to "cross-link to source documents", and that turned out
to be unbuildable from an `AuditResult`. A `Claim` carries `doc_id` and `section_id`; both are
content hashes. The `Document` and `Section` objects that know the filename and the heading are
created inside `_ingest` and discarded when the loop moves on, so by the time aggregation runs there
is no way back from a hash to a human-readable citation. Every finding could name its claims and
none could name where they came from.

**Options considered.**
- *A lightweight ref index* (chosen).
- *Put `documents: list[Document]` on the result* — full fidelity, no new model.
- *Re-parse the corpus inside `report.py`* — no schema change at all.

**Rationale / trade-offs.** Carrying whole `Document` objects would have been the smaller diff, and
I rejected it on two grounds. It duplicates every section's full text into the result — and
therefore into the `-o` JSON — which roughly doubles the payload for data the report never renders;
the claims already carry the only source text a reader sees, in `evidence_quote`. More importantly
it is the same source-text exposure that made me gitignore `.crosscheck/` in D30: an audit result is
something you hand to someone, and it should not silently contain the full text of every document
that was audited. A ref index is a few hundred bytes per document and leaks nothing that is not
already in a citation.

Re-parsing inside `report.py` avoids the schema change but is worse on every other axis: it re-reads
and re-parses the corpus for presentation, it fails if the files moved after the audit, and it can
drift — the report would describe the documents as they are *now*, not as they were when the audit
ran. Aggregation should render what the audit produced, not go back to disk for it.

What I gave up: the report cannot show surrounding section context beyond the claim's own
`evidence_quote`, because the section text is no longer in scope. That is acceptable — the mockup
shows the evidence span highlighted inside the claim's verbatim quote, which is what §7.5 asks for.
If wider context turns out to matter for the demo, the honest fix is to widen `evidence_quote` at
extraction time, not to ship whole documents through the pipeline.

**Provenance.** Mine, and the reason I mocked the HTML before writing the renderer, as spec §8
Phase 4 instructs. The gap is invisible from the schema — `AuditResult` looks complete until you try
to render a citation from it — and would have surfaced halfway through `html_renderer.py` otherwise.

## D34 — Findings are grouped by document pair, not by `Claim.subject` (2026-08-01)

**Decision.** The report groups findings by the **pair of documents** they span
("`01_employee_handbook.md` ↔ `02_pto_policy_v2.md`"), sorted by confidence within each group. Each
finding still displays its `subject` on the card. This is a deliberate deviation from spec §7.5,
which says to group by subject.

**Why the spec's grouping fails.** I checked it against the 342 claims cached from the acceptance
corpus rather than assuming it would work:

```
claims:                342
distinct subjects:     173
singletons:            108   (62% of distinct subjects)
after casefold+strip:  168   (normalisation merges 5)
most common:  Vendor 15 · employees 14 · addendum 12 · contractors 11 · policy 10
```

`Claim.subject` is the *grammatical* subject of the assertion, which is what the §7.1 schema's
`subject`/`predicate` split asks the extractor for. It is not a topic. Grouping by it files the PTO
carry-over conflict next to a health-insurance conflict under "Employees", and splits the four
vendor conflicts across "Vendor", "European Vendors", and "Master Services Agreement". With 62% of
subjects appearing exactly once, most groups would hold a single finding — which is not a grouping.

**Options considered.**
- *Group by document pair* (chosen).
- *Group by normalised `subject`* — spec-literal; casefolding merges 173 → 168, so it stays broken.
- *Cluster claim embeddings into topics* — the vectors already exist, so this is nearly free.

**Rationale / trade-offs.** Document-pair grouping is total and deterministic: retrieval already
filters `doc_id != self`, so every finding spans exactly two documents and lands in exactly one
group, with no threshold and no tie-break. It also matches how the report is actually read — the
question a reader brings is "where do these two documents disagree", and the answer is a heading
they can act on. It costs nothing: the grouping key is already in the pair.

I passed on embedding clusters despite the vectors being free. It introduces a cluster-count or
distance threshold that would need tuning, it makes the report non-deterministic in a way that
breaks the D-series regression-snapshot test, and it buys a topic label that document-pair grouping
mostly implies anyway — the handbook-vs-PTO-v2 group *is* the paid-time-off group in this corpus.
If a real corpus later produces one document pair with thirty unrelated conflicts, clustering
becomes worth revisiting; on ten documents it is complexity without a payoff.

What I gave up: a conflict that recurs across three or more documents appears once per document
pair rather than as one topical finding. The acceptance corpus has exactly this case — logs retained
90 days in the security policy versus 13 months in *both* the IT standards and the retention policy.
The near-duplicate roll-up in the report handles the presentation; the underlying JSON keeps every
verdict, because the evaluation harness needs them individually.

**Provenance.** Mine, recommended after the subject-cardinality check above and accepted. The check
is the part worth keeping: the spec's grouping sounded right and the data said otherwise, and it
cost one query against a cache that already existed.

## D35 — The HTML report is rendered without a templating engine (2026-08-01)

**Decision.** `aggregation/html_renderer.py` builds the report's HTML with plain Python string
composition. The CSS lives in a module-level constant, every interpolation goes through a single
`_esc()` helper wrapping `html.escape`, and there is no Jinja2 (or any other engine) in the
dependency list.

**Options considered.**
- *Hand-rolled with `html.escape`* (chosen).
- *Declare `jinja2` and put the page in a template file* — autoescaping for free, better
  separation of markup from code.
- *A minimal `str.format`/`Template` scheme over an external `.html` asset* — no engine, markup
  still out of Python.

**Rationale / trade-offs.** Jinja2 was genuinely tempting, and it is the option I would pick for a
web application. Two things decided against it here. First, the dependency surface is an explicit
design value in this project — §4's stated reason for refusing LangChain is that a heavy framework
obscures the engineering and enlarges the dependency graph, and pulling in a templating engine for
exactly one page cuts against the same principle. Second, I checked what was actually available:
`jinja2` is in `uv.lock`, but only as a **platform-conditional transitive dependency of torch**
(`sys_platform` markers). Depending on it without declaring it would be fragile in a way that
would not show up until someone's platform resolved differently, and declaring it means adding a
direct dependency after all.

The third option — a template asset plus simple substitution — I rejected because it is the worst
of both: it either reinvents a templating engine badly, or it forces build-backend package-data
configuration for a single file. Keeping the CSS in a module constant avoids both, and since it is
a plain string rather than an f-string, its many `{` braces need no escaping.

What I gave up is real and worth naming: markup interleaved with Python is harder to read than a
template, and there is no autoescaping safety net. The mitigation is that escaping happens at
exactly one choke point, and it is tested adversarially rather than assumed — the suite renders a
claim whose text is `<script>alert("xss")</script> & <img src=x onerror=1>` and asserts the tags
come out escaped and the document still parses as balanced HTML. Claim text comes from documents
CrossCheck did not author, so treating it as untrusted input is not theoretical.

The `_highlight` helper is the one place the escaping order matters: it slices the raw passage on
the span offsets **first**, then escapes each fragment, then wraps the middle in `<mark>`. Escaping
before slicing would invalidate the offsets, because `&amp;` is five characters where `&` was one.

**Determinism.** Output is a pure function of the report. `generated_at` defaults to `None` and the
renderer omits the timestamp entirely when it is unset, so the §12 regression snapshot over a
frozen fixture is byte-stable and diffable. A page that changes on every run is a snapshot nobody
reads.

**How I verified it.** Four gates green (ruff, ruff-format, mypy --strict over 56 files, 175
tests). Fifteen renderer tests: HTML balance via `html.parser` on every state, the self-contained
assertion (no `http://`, no `<link`, no `src=`), evidence spans marked, escaping of both claim text
and rationale, the designed empty state carrying real counts, the partial banner appearing only
when partial, and byte-identical output across two renders. Two sample pages were rendered from
the real renderer and checked against the approved mockup.

**Provenance.** Mine. I raised the Jinja2 option, recommended hand-rolling, and the recommendation
was accepted before implementation.

## D36 — Gold labels match predictions at section level, not claim level (2026-08-01)

**Decision.** A gold contradiction is identified by the **unordered pair of sections** it spans:
`{(document, section_id), (document, section_id)}`. A predicted finding counts as a match when its
two sides land in those two sections, in either order. Character spans are recorded on every gold
side but are not used for matching. `evaluation/gold.py` owns the schema (`GoldSide`, `GoldPair`,
`GoldSet`), the loader, and the single-pair `matches()` predicate; aggregate scoring belongs to the
Phase 6 metrics module.

**The problem.** The system extracts its own claims. A claim id is a content hash of text *the
extractor chose*, so it cannot be known when a benchmark is authored, and it changes whenever the
extractor splits a sentence differently or a prompt is retuned. A gold label written at claim level
would therefore match nothing on the run after the one that produced it. Something coarser than a
claim and finer than a document is required, and the section is the natural unit — it is what the
parser already produces, what a citation names, and what a human reviewing an injected
contradiction actually looks at.

**Options considered.**
- *Section-pair matching* (chosen).
- *Span overlap* — gold carries char offsets; a prediction matches if its evidence overlaps.
- *Claim-text similarity* — fuzzy-match the prediction's claim text against the authored text.

**Rationale / trade-offs.** The deciding argument is attribution. §9.2 already measures claim
extraction on its own against a separate gold set, and the whole point of doing so is that
end-to-end F1 cannot tell you whether a miss came from extraction or from detection. If the
end-to-end matcher were also sensitive to extraction behaviour — as both span overlap and text
similarity are — then a change in the extractor would move the detection numbers, and the two
metrics would stop being independent readings. Section matching deliberately makes end-to-end
scoring blind to how the extractor carved up a section.

Span overlap is the better metric in principle and I have kept the door open rather than closed:
every `GoldSide` records `evidence_quote` and `char_span`, so a stricter overlap metric can be
computed in Phase 6 without regenerating a single benchmark. Text similarity I rejected outright —
it introduces a similarity threshold, which is a tuning knob inside the measuring instrument.

**What it costs, stated plainly.** Section matching cannot distinguish two different contradictions
that span the same two sections. `duplicate_section_keys()` exists to surface exactly that: a
generator should call it and relocate or merge the offenders, because a collision would silently
let one finding score as though it had found both. The loader does not reject collisions, since a
real corpus may legitimately contain two conflicts in one section pair, but they must be visible.

**Two guards worth more than the schema.** A gold pair whose sides lack section ids — a
hand-written pair authored without parsing the corpus — degrades to **document-level** matching and
says so via `granularity`, and the loader warns, because such a pair matches *any* finding between
those documents and will overstate recall. That was a silent-empty-key bug in my first draft: a
missing section id produced a `""` key that matched nothing, quietly turning a real label into a
guaranteed false negative.

`GoldSet.cross_model` compares the generator's model family against the judge's and returns
**`None` when either is unrecorded** rather than defaulting to a comfortable answer. §9.1's
cross-model requirement is the single easiest thing to violate by accident, and "we don't know"
must not read as "it's fine". `load_gold_set` warns loudly when the two families match.

Gold labels are also validated against `V1_TYPES`, so `UNCLEAR` and the reserved
`CONDITIONAL_TRIPLET` are rejected at parse time — a gold label for a type v1 does not detect would
score against nothing and depress recall for a reason unrelated to the system's quality.

**How I verified it.** Four gates green (ruff, ruff-format, mypy --strict over 59 files, 210
tests). Twenty-one tests covering order-independent ids, the type validator, review verdicts
removing pairs from the usable set, the cross-model guard in all three states, matching including
the reversed-gold and wrong-section cases, type disagreement still counting as a match, the
document-level degradation path, collision detection, and JSON round-tripping.

**Provenance.** Mine, recommended and accepted before implementation. The document-level
degradation and the `None` cross-model state were both added after I wrote the first version and
found it would fail quietly rather than loudly.

## D37 — The benchmark generator is GPT-4.1, added as a second provider behind a shared protocol (2026-08-01)

**Decision.** Synthetic benchmark generation uses **`gpt-4.1`** via a new `OpenAIClient` in
`llm.py`, alongside the existing Anthropic `LLMClient`. Both satisfy a new `StructuredLLM`
protocol and share `CostTracker`. `openai>=2.52` is now a direct dependency, and `config.py`
gains `generator_model: str = "gpt-4.1"`. This deviates from the spec's suggested `gpt-4o`.

**Why a second provider at all.** §9.1's headline v2 requirement is that the benchmark be
generated by a *different model family* than the judge. Generating and judging with one family
partly measures a model recognising its own house style, which inflates scores in a way that does
not transfer to real corpora — and this project's whole credibility argument rests on not doing
that. Claude judges, so something that is not Claude must generate.

**Why GPT-4.1 rather than the spec's GPT-4o.** The spec names GPT-4o as an *example* of a
different family; the requirement is the family, not the model. I checked current published rates
rather than trusting a remembered number:

| model | input /Mtok | output /Mtok |
|---|---|---|
| gpt-4o | $2.50 | $10.00 |
| gpt-4.1 | $2.00 | $8.00 |
| gpt-5 | $1.25 | $10.00 |

GPT-4.1 wins on the three properties a *generator* actually needs. Instruction-following fidelity
— it must produce exactly the requested contradiction type, leave the surrounding document intact
and emit valid structured JSON, which is a compliance task rather than a reasoning one.
Reproducibility — `temperature=0` plus `seed`, which §9.1 requires. And predictable cost, at 20%
under GPT-4o.

I looked seriously at GPT-5, whose input is *half* GPT-4o's. I rejected it for exactly the
properties above: reasoning tokens bill as output and make cost unpredictable, and reasoning models
tend to disregard `temperature` and `seed`. Non-determinism in the instrument you measure with is
the wrong trade at any price. It is a one-line config change if that judgement turns out wrong.

**Options considered.**
- *Second provider, GPT-4.1* (chosen).
- *Second provider, GPT-4o* — the spec's literal suggestion; dearer and no better here.
- *Generate with a different Claude model (Opus vs Sonnet)* — same family, so it fails the actual
  requirement while appearing to satisfy it. The worst option, because it looks compliant.
- *Skip synthetic generation, do the real-corpus check only* — a real fallback if no key existed,
  and arguably the more credible result, but it abandons per-type metrics entirely.

**Design.** `OpenAIClient` mirrors `LLMClient`'s surface exactly rather than generalising it, and
both are described by a `StructuredLLM` protocol — the same pattern already used for `NLIScorer`,
`Reranker` and the embedders. Refactoring `LLMClient` into a provider-generic base would have
touched a module that four verified stages depend on, to no benefit: the two SDKs differ enough in
their error and usage shapes that the shared part is only the signature.

`CostTracker.record` gained a provider-neutral sibling, `record_tokens`, so a second SDK's usage
object need not be translated into Anthropic's `Usage` just to be priced. A test asserts the two
paths agree, since a drift between them would corrupt cost reporting silently.

**One rate is deliberately wrong, in the safe direction.** OpenAI cached input tokens are billed
here at the **full** input rate, because OpenAI reports cached tokens inside `prompt_tokens` rather
than as a separate counter with a stable discount. That overestimates spend when prompt caching
engages. Overestimating stops an audit early; underestimating lets it overrun a ceiling that exists
precisely to prevent that. Anthropic's cache rates are modelled exactly because that provider
reports reads and writes separately.

**Truncation is typed here, unlike D32.** The OpenAI SDK raises `LengthFinishReasonError`, so the
`max_tokens` overflow that cost an hour on the Anthropic path — where it surfaces as a
`pydantic.ValidationError` that has to be sniffed by error shape — is a one-line `except` here.
Both paths converge on the same `LLMTruncationError`, so callers do not care which provider they
are on.

**A test that had quietly stopped testing anything.** Adding OpenAI pricing broke
`test_unpriced_model_raises`, which used `"gpt-4o"` as its example of an unpriced model. It had been
passing for the right reason and would have started passing for no reason at all the moment that
model was priced — except it failed loudly instead, because the fake response then flowed into the
logging path. It now uses `"not-a-real-model"` and asserts on the error message. Worth recording:
a negative test keyed on a real external identifier has an expiry date.

**How I verified it.** Four gates green (ruff, ruff-format, mypy --strict over 59 files, **221
tests**). Eleven new tests cover pricing, the neutral recording path agreeing with the Anthropic
one, the missing-key error, parsed output with cost recorded, unpriced-model refusal, the ceiling
blocking before dispatch, typed truncation, API errors, refusals, missing parsed output, and two
providers sharing one tracker. Then a live call: `gpt-4.1` produced a valid `NUMERICAL_MISMATCH`
injection through structured output for **$0.00095**, which extrapolates to roughly $1–2 for the
full 200-pair benchmark.

**Provenance.** Mine. I recommended GPT-4.1 over the spec's GPT-4o with the pricing table above and
the reasoning-model argument against GPT-5; accepted before implementation.

## D38 — Injection targets are chosen by topical relatedness, not at random (2026-08-01)

**Decision.** `synthetic_gen.py` pairs a source section with a target section using **dense
embedding similarity** — the same `BgeDenseEmbedder` the pipeline retrieves with — instead of
drawing both uniformly. `related_sections()` computes neighbours in *other* documents above a
cosine floor of 0.55; `plan_injections()` is pure and takes those neighbours as an argument, so
planning stays hermetically testable without loading a model. Section ids are resolved by
re-parsing the written corpus rather than computed up front.

**What the first dry run showed.** I built the random version first and ran it against the
acceptance corpus before writing any of this down. Ten injections, nine generated, $0.03 — and the
output was unusable:

- "Employees are not permitted to delete any customer production data" was injected into **§ 5.
  Remote Work** of the employee handbook.
- Gold label, typed `numerical_mismatch`: *"Employees must return all company property on their
  last day of employment"* against *"**Contractors** are required to return all company property
  within 14 days"*. Two populations, two rules — not a contradiction.
- Another: *"The Company may withdraw consent to a **subcontractor** on 30 days notice"* against
  *"Managers may decline a **paid time off** request… 7 days notice"*. Unrelated subjects, labelled
  a numerical mismatch because both mention days.

**The mechanism, which is the part worth remembering.** Asked to contradict two unrelated sections,
an instruction-following model does not refuse — it complies. It manufactures a fake conflict or
drops an obviously foreign sentence into the target. The failure was mine, not the model's: I asked
for something that does not exist.

**Why bad gold is worse than no gold.** A wrong label corrupts the metrics in *both* directions. The
system correctly declining to flag "contractors return property in 14 days" versus "employees
return property on their last day" is scored as a **miss** — recall is depressed for being right.
That is not a noisy benchmark, it is an actively misleading one, and it would have been invisible
in a headline F1.

**Options considered.**
- *Embedding-based topical pairing* (chosen).
- *Keep random pairing and rely on the model to refuse* — the empty-`source_claim` path already
  existed and the dry run proved the model does not use it often enough.
- *Have the LLM pick a target from a shortlist* — an extra call per injection, and it optimises for
  what the model finds easy to contradict rather than what a real corpus looks like.
- *Hand-author the pairings* — accurate and unscalable; the point is 200 pairs from a seed.

**Rationale / trade-offs.** Reusing the pipeline's own embedder means "related" is defined the same
way at generation time as at retrieval time, which keeps the benchmark honest about what the system
can see. It is local, free, deterministic, and adds no dependency. Neighbours below the floor are
**dropped rather than padded** — a source with no topical partner produces no injection, because a
forced pairing is exactly the failure being fixed.

The floor at 0.55 is a judgement call and the one number here I would expect to tune. Too high and
a small corpus yields nothing; too low and the original problem returns. On the acceptance corpus,
38 of 38 candidate sections found a partner.

**A second dry run found a subtler flaw.** With topical pairing the contradictions became genuine —
13-month versus 6-month log retention, subcontracting consent versus no-approval — but every
`temporal_conflict` injection opened with a bracketed marker: `[Supersedes 09_it_standards_v3.md]`.
My prompt had licensed "a supersession marker" for that type, and the model took it literally. Real
policy documents contain no such annotation, so it is a **lexical tell** a detector could learn
instead of learning to detect contradictions — and it named the source file, which no target
document would. One whole type would have been artificially easy.

The prompt now forbids filenames, brackets and editorial annotations outright, and requires
supersession to be written into the prose the way a real document does ("Effective July 2023,
application and access logs are retained for 6 months in accordance with the revised retention
schedule"). The third run produced exactly that, with no markers.

**Why section ids are resolved afterwards.** A `section_id` derives from `doc_id`, a content hash of
the whole document — so injecting text changes *every* section id in that document. Labelling
before writing would produce gold that cites ids the pipeline can never compute. The generator
therefore writes the corpus, re-parses it, and locates each claim in the result. A test asserts
every gold `section_id` appears in a fresh parse, which is the check that would have caught this
had I got it wrong.

**How I verified it.** Four gates green (ruff, ruff-format, mypy --strict over 61 files, **246
tests**). Twenty-five tests, with a topic-keyed fake embedder so relatedness is asserted rather
than hoped for: neighbours never share a document, always share a topic, unrelated sections are
dropped, plans only pair related sections, no section pair is reused, gold ids match a fresh parse,
injected text is really in the written corpus, and every rejection path counts rather than crashes.
Then three real runs against the acceptance corpus at ~$0.03 each.

**Provenance.** Mine. The random version was my first design and the dry run refuted it; the
relatedness fix was my recommendation and was accepted. Recording the sequence because the lesson
generalises: **generate a real artifact and read it before trusting a generator**, since every test
passed on the version producing nonsense.

## D39 — Injection results are cached, and the cache key includes the rendered prompts (2026-08-01)

**Decision.** `synthetic_gen.py` gains the same cache trio as the extractor and judge:
`InjectionCache` protocol, `InMemoryInjectionCache` (default) and `DiskInjectionCache`. The key is
`content_hash("injection", generator_model, rendered_system_prompt, rendered_user_prompt)`. What is
stored is the model's **raw** answer, before validation. A failed *call* is never cached.

**Why now.** The first real generation run — 141 injections against the GDPR seed corpus — was
killed by a ten-minute tool timeout at roughly injection 120, and every one of those calls was lost.
Extraction and judging have been resumable since D30; generation was the one LLM stage that was not,
and it is the stage most likely to be re-run, because the whole point of a benchmark generator is
that you tune it and regenerate.

**The part that matters: the key includes the prompts.** The obvious key is the model plus the two
section texts. That would have been a trap. Regenerating after editing the injection prompt is
precisely the workflow — I had already changed that prompt once, to kill the `[Supersedes ...]`
lexical tell (D38) — and a key that ignored the prompt would have replayed the *old* output and made
the fix appear to do nothing. A silent no-op is worse than no cache at all, because it looks like
evidence that the prompt did not matter. Hashing the fully rendered system and user prompts makes
any edit invalidate every entry, which is the correct and slightly expensive behaviour.

**Caching the raw answer rather than the validated result** separates model behaviour from code.
The verbatim check that rejects a paraphrased `source_claim` is code; if I tighten it, the fix
should take effect on replay without re-spending tokens. So a rejected injection *is* cached — the
model genuinely said that, at temperature 0, and replaying it is correct — while an `LLMError` is
not, because that failure is transient. That is D32's rule applied to a new stage: never cache a
failure you would want to retry.

**Options considered.**
- *Key on model + prompts, cache raw output* (chosen).
- *Key on model + section texts* — smaller and faster to reason about, and silently wrong the first
  time the prompt changes.
- *Include a hand-maintained prompt version number in the key* — works, until someone edits a prompt
  and forgets to bump it. Hashing the text cannot be forgotten.
- *No cache* — the status quo that just cost a ten-minute run.

**How I verified it.** Four gates green (ruff, ruff-format, mypy --strict over 61 files, **251
tests**). Five new tests: the key changes with system prompt, user prompt and model but is stable
for identical input; a second run serves every injection from cache with zero LLM calls and zero
cost; a `DiskInjectionCache` re-opened over the same directory behaves as a new process would; a
failed call leaves the cache empty and a later run recovers; and rejected output is cached so a
validation fix replays free.

**Provenance.** The user asked for the cache before regenerating. The prompt-in-the-key design and
the raw-versus-validated distinction were mine.

## D40 — One shared quote matcher, tolerant of punctuation as well as whitespace; longer LLM timeout (2026-08-01)

**Decision.** The verbatim-quote rule moves into a new module, `crosscheck/text.py`, exposing
`locate_quote()` and `quote_present()`. The extractor, the judge and the report builder all
delegate to it. The rule now folds **punctuation variants** — typographic quotes and dashes —
in addition to whitespace. Separately, `llm_timeout_seconds` goes 60 → 300 and
`extraction_batch_size` 4 → 3.

**Both bugs came from the same thirty seconds of running on real documents.** The GDPR benchmark
probe was the first time this system had seen text it had not written itself, and it failed twice.

**Bug one: smart quotes silently discarded correct claims.** The extractor returned

> `processed lawfully ... ('lawfulness, fairness and transparency');`

with ASCII apostrophes, while the GDPR source has U+2018/U+2019. The verbatim check rejected it,
and the claim was dropped. Five of 89 claims on the first document alone — **5.6%** — for a reason
having nothing to do with correctness. It never surfaced before because the acceptance corpus is
fictional prose I wrote in ASCII (D31); every real document is typeset.

This is the worst shape of bug: no error, no crash, just quietly fewer claims. Downstream it would
have depressed recall and been indistinguishable from a detection failure.

The fix folds quote and dash variants exactly as D20 folds whitespace — a model normalising
typography is not fabricating. Word content must still match exactly, so a changed or invented word
still fails, and there are tests pinning that: `a, b` does not match `a b`, and `total: 30` does not
match `total 30`. Folding variants is not the same as ignoring punctuation.

**Why a shared module now, rather than a fourth copy.** The rule already existed three times — in
`claim_extractor`, in `llm_judge` as a boolean, and in `report` as a span. I noted the duplication
when writing the report builder (walkthrough 30) and deliberately deferred it. This bug is the
argument for having done it: the punctuation fix had to land in three places, and a drift between
them would mean a quote acceptable to the extractor but a hallucination to the judge. Detection
importing from aggregation would have inverted the dependency direction, which is why the shared
home is a leaf module rather than one of the existing ones. `report.locate_quote` is re-exported so
existing imports keep working.

**Spans stay in the original text.** Matching builds a pattern from the quote rather than
normalising the haystack, so offsets index the source as it really is. That is what lets the
extractor store the true source span and the renderer mark it without drift — normalising first
would shift every offset after the first substitution.

**Bug two: the timeout could not cover a dense batch.** `extraction_batch_size=4` ×
`extraction_max_output_tokens_per_chunk=4000` asks for up to **16,000 output tokens** in one
request, against a 60-second timeout. That cannot complete; both retries also timed out and the
audit died. D32 raised the per-chunk budget to 4000 and the timeout never caught up — the
acceptance corpus hid it because its chunks produced far shorter outputs than the cap.

300 seconds, and a batch of 3 rather than 4 so a single request cannot ask for 16k tokens. Both
are cheap: `max_tokens` is a cap, not a spend, and a smaller batch only amortises the system prompt
slightly less.

**Options considered.**
- *Shared module + punctuation folding + longer timeout* (chosen).
- *Normalise both sides and match on the normalised strings* — simpler, and it breaks every
  offset, which the extractor and the renderer both depend on.
- *Strip punctuation entirely before comparing* — would accept genuine fabrications that differ
  only in punctuation, e.g. a list where `a, b` and `a b` mean different things.
- *Streaming for long extraction calls* — the SDK's actual recommendation for large `max_tokens`,
  and a bigger change to `llm.py` than the problem warrants now. Worth revisiting if 300s proves
  insufficient.

**How I verified it.** Four gates green (ruff, ruff-format, mypy --strict over 63 files, **264
tests**). Thirteen tests on the new module: exact spans, rewrapped line breaks, collapsed
whitespace, typographic quotes matching ASCII in both directions, all seven dash variants, double
quotes, whitespace and punctuation combined, and three tests pinning what must *still* fail.
Behaviour was also checked directly against the real GDPR sentence that triggered the bug.

**A note on the literals.** The character classes are written as `‘`-style escapes rather than
literal characters, because the literals are visually indistinguishable from one another — which is
precisely the confusion the module exists to absorb. Ruff's RUF001 refuses them anyway, correctly,
everywhere except here.

**Provenance.** Mine, found by the probe rather than by review. The duplication was flagged in
walkthrough 30 before it caused harm; this is the second time a real-document run has found what
the fictional corpus could not (D38 was the first).

## D41 — The NLI threshold moves 0.5 → 0.05, because above ~0.49 it was mathematically a no-op; per-type thresholds stay empty (2026-08-02)

**Decision.** `nli_default_threshold` goes **0.5 → 0.05**, calibrated against the 139-pair GDPR
benchmark. `nli_thresholds` stays **empty** — I am not filling in per-type values. Both the
`config.py` comment and the `nli_filter.py` docstring now record why, because the reasoning is not
recoverable from the numbers alone.

**The finding: the knob had never done anything.** D28's keep rule is *contradiction is the argmax*
**OR** *P(contradiction) ≥ threshold*. With three labels, a contradiction probability of 0.5 or more
**forces** contradiction to be the argmax — the other two labels have at most 0.5 left to share. So
every threshold at or above ~0.49 collapses to the argmax arm alone and filters nothing extra. The
shipped default of 0.5 sat exactly on that boundary. I verified it rather than reasoning it out:
across all 4,790 post-rerank pairs, the number kept by the probability arm but not the argmax arm is
**zero**, and the highest contradiction probability among all non-argmax pairs is **0.4890**. Since
D28 the threshold has been decorative; the filter has always been pure argmax.

That is the real result here. The sweep I set out to run was a recall/cost tuning exercise; what it
actually found was a config value that could never have had an effect at any setting we would
plausibly have tried, since every "more permissive" value we might have reached for (0.4, 0.45)
barely moves and everything above is identical.

**What the sweep bought.** The curve, at the operating points that matter:

| threshold | pairs judged | NLI-stage gold recall |
|---|---|---|
| 0.50 (old, = argmax only) | 875 | 120/138 = 87.0% |
| 0.20 | 973 | 121/138 = 87.7% |
| 0.10 | 1028 | 122/138 = 88.4% |
| **0.05 (chosen)** | **1105** | **123/138 = 89.1%** |
| 0.02 | 1272 | 124/138 = 89.9% |
| 0.00 (no filter) | 4790 | 138/138 = 100% |

0.05 is the knee. It buys 3 gold pairs for 230 extra judged pairs (+26%, about +$0.60 a run at the
measured Haiku rate). The next step down, 0.02, pays 167 more pairs for a single additional gold
pair, and below that the curve falls off a cliff into judging everything.

**Why §7.4's ≥95% recall target is not reachable by tuning, and why I am not going to pretend
otherwise.** Four of the five types only clear 95% at a threshold of essentially zero. The reason is
in the distribution of what gets dropped: of the 18 gold pairs the filter loses, **14 score below
P=0.02** and 8 below 0.005. DeBERTa is not marginally uncertain about these — it is confidently
wrong. Only the top four dropped pairs (0.279, 0.159, 0.078, 0.020) are anywhere near a decision
boundary, and 0.05 collects three of them. Reaching 95% means setting the threshold to 0 and
judging all 4,790 pairs, which deletes the filter's entire reason for existing (~$12.45 versus
~$2.27 per run) and would still be a worse trade than spending that money on a better second stage.
So the residual is a **model limitation, recorded as such**, not an open tuning task. `temporal_conflict`
is worst at 71% and that is the expected shape: superseding language is semantically unlike the text
it supersedes, which is not what an NLI model is trained on.

**Why `nli_thresholds` stays empty.** Two independent reasons, either sufficient. First, production
never has a type hint — the type is what the judge decides — so `filter_pairs` takes
`min(default, *thresholds.values())`, and five calibrated per-type numbers would collapse to
whichever is lowest. Second, per the no-op finding, any of those values above ~0.49 would be inert
anyway. Per-type thresholds remain genuinely useful as a **diagnostic** — they are how I know
`temporal_conflict` is the weak type — and `filter_pairs` keeps the `type_hints` parameter so the
eval harness can use them with gold types. They are just not a shippable knob, and filling the dict
in would have implied a precision the mechanism does not have.

**Options considered.**
- *0.05, and treat the rest as a model limit* (chosen).
- *Leave it at 0.5.* Defensible on cost, and it is what the system has effectively been running.
  Rejected because it costs 3 recoverable gold pairs for $0.60, and mainly because leaving a value
  that provably does nothing is a trap for whoever reads the config next — including me.
- *0.02, for the maximum non-degenerate recall.* One more gold pair for 167 more judged pairs; the
  worst marginal rate on the whole curve short of collapsing to 0.
- *0.00 to hit the §7.4 ≥95% target.* Meets the letter of the spec by disabling the stage. This is
  the option I would have had to take to report "target met", and it is not worth it — I would
  rather report 89.1% with the reason than 100% with no filter.
- *Fill in per-type thresholds.* Inert for the two reasons above.
- *Swap the NLI model, or add a lexical bypass for superseding language.* The actual lever for the
  remaining 11%, and out of scope for a config change — noted as the next Phase-6 investigation.

**A note on method, because it nearly cost a second run.** `funnel.py` performed this exact
rerank+NLI computation and discarded the scores, so any threshold question meant paying ~25 minutes
of CPU again. This time the scoring pass dumps every pair's full three-way distribution, in both
orderings, to `nli_scores.json` (4,790 pairs, 2.7 MB), and the sweep runs offline against that file
in under a second. Recording the argmax **separately** from the probability is what makes the dump
reusable: the argmax arm is threshold-independent, so a dump that stored only "kept/not kept at 0.5"
would make every raised threshold look like it lost pairs it actually keeps — and would have hidden
the no-op finding completely.

**Verified end-to-end, not just at the NLI stage.** Both runs scored with the same scorer against
the same 139-pair gold set, same judge (`claude-haiku-4-5`), same `rerank_top_k=10`:

| | t=0.50 (before) | t=0.05 (after) |
|---|---|---|
| Precision | 0.748 | **0.748** |
| Recall | 0.640 | **0.662** |
| F1 | 0.690 | **0.702** |
| TP / FP / FN | 89 / 30 / 50 | 92 / 31 / 47 |
| pairs judged | 874 | 1103 |
| judge hallucinations | 5 (0.6%) | 5 (0.45%) |

The sweep predicted +3 gold pairs at the NLI stage and end-to-end recall gained exactly 3. Better
than I expected: the judge converted all three, against its 74.2% average conversion on what it
sees. **Precision did not move** — the 229 extra pairs produced 3 true positives and 1 false
positive. That was the one thing the offline sweep could not predict, and it is the result that
justifies the change; had precision dropped a point or two I would have reverted to argmax-only.

Per-type recall moved where the dropped-pair probabilities said it would: obligation_reversal
.667 → .733 (+2) and scope_jurisdiction .552 → .586 (+1). direct_negation, numerical_mismatch and
temporal_conflict are unchanged — every one of their remaining misses sits below P=0.02.

**On cost, do not read the headline.** The new run cost $0.5759 against the baseline's $0.6998,
which looks like a saving and is not one — it is an artifact of 892 cache hits versus 624. Per call
both runs sit at ~$0.0027. The honest statement is the one from the sweep: this config judges 26%
more pairs, so on a cold cache it costs about a quarter more.

**Reproducing this requires setting the judge model explicitly.** `.env` pins
`CROSSCHECK_JUDGE_MODEL=claude-sonnet-4-6`, but every benchmark number in this file was produced
with Haiku via a command-line override. I lost a $1.50 run to that: the verdict cache key folds in
the judge model (deliberately — §9.3 cross-model runs must never serve one model's verdicts for
another), so a Sonnet run missed all 764 Haiku-keyed verdicts, paid Sonnet's 3× rate, and hit the
cost ceiling at 194 of 1,103 pairs. Two things worth keeping from that: the ceiling behaved exactly
as §2 requires — stopped dispatch, finalized a well-formed report, set `partial` with a reason —
and `resumed.cost_usd` is **logged but never seeded into the `CostTracker`**, so `--max-cost` bounds
the current run's spend only, not the audit's lifetime spend. Worth knowing before trusting a
ceiling on a resumed audit.

**Provenance.** Mine. The sweep was the step I had queued after the Phase-5 funnel diagnostic
identified NLI as the binding constraint (18 of 19 pre-judge losses, retrieval at 100%).

## D42 — Detection metrics score findings *as displayed*; the old ad-hoc precision was mixing units and understating itself (2026-08-02)

**Decision.** Added `src/crosscheck/evaluation/metrics.py`, the §9.2 scorecard, replacing the
throwaway `score.py` I had been running out of the runs folder. The headline granularity is
**`grouped`** — the report's findings as a user sees them, near-duplicates rolled up — with
`per_verdict` reported beside it as a diagnostic. On the v1 GDPR benchmark this moves the numbers:

| | old `score.py` | `grouped` (new headline) | `per_verdict` (diagnostic) |
|---|---|---|---|
| Precision | 0.748 | **0.852** | 0.748 |
| Recall | 0.662 | **0.662** | 0.662 |
| F1 | 0.702 | **0.745** | 0.702 |
| TP / FP / FN | 92 / 31 / 47 | 92 / 16 / 47 | 92 / 31 / 47 |

**The correction raises my own headline, so here is the argument in full.** `score.py` counted true
positives as *gold pairs matched* (92) and false positives as *findings that matched nothing* (31),
then divided. Those are different kinds of object: the numerator counts targets, the denominator
adds predictions. The result is not a proportion of anything, and it was wrong in the flattering
direction only by accident — it could as easily have gone the other way.

Fixing it needs a decision about what one prediction *is*, and the codebase already answers that
twice, consistently. The report rolls same-section near-duplicates under a single finding (D34),
because the extractor may split one section into several claims so one disagreement surfaces as
several verdicts. Gold labels match at section level (D36). **Both already treat the section pair as
the unit.** Scoring the grouped findings therefore makes every column count the same object, and the
benchmark confirms it empirically: 108 grouped findings claim 92 distinct gold pairs with **zero**
duplicates, against 133 duplicates when near-duplicates are expanded. The units line up exactly
because they were designed to.

So `grouped` is not the generous reading, it is the only coherent one — and `metrics.py` asserts
this rather than assuming it, reporting `duplicate_count` so that a future divergence between the
roll-up and the gold set shows up as a number instead of silently inflating precision.

**Two things I am deliberately not claiming.** The 16 remaining false positives are an *upper bound*
on error: an injected benchmark labels only what was injected, so a finding flagging a contradiction
that genuinely exists in GDPR but was never labelled counts against us. And section-level matching is
coarse in our favour — a finding lands if both sides fall in the right two sections, regardless of
whether it identified the same sentences. Precision 0.852 sits between those two biases and I would
not defend it to three decimal places.

**What the strata revealed, which is the point of building this.** Splitting by lexical overlap of
the two claim texts (Jaccard, cut at 0.30):

| stratum | P | R | F1 |
|---|---|---|---|
| high overlap (n=71) | 0.962 | 0.718 | 0.823 |
| low overlap (n=68) | 0.745 | 0.603 | 0.667 |

The system is clearly weaker when the two claims share little surface form — F1 drops 15.6 points —
but it does **not** collapse, which is the failure §9.2 is watching for. A system that only catches
near-duplicate phrasing would show a low-overlap stratum near zero. This is the number that says
hybrid retrieval (D24) is earning its place, and it belongs in the README next to the headline.

**Also decided here.**
- **Cut at 0.30, not the median.** The benchmark's median overlap is 0.310 and 0.30 splits it 71/68.
  A fitted cut (the exact median) would rebalance on every benchmark and stop runs being comparable;
  a round constant does not.
- **Jaccard on tokens, not embedding similarity.** A better similarity would be a worse stratifier —
  it would fold in the semantic signal the strata are meant to hold constant.
- **Duplicates are counted, never scored.** Section-level matching cannot distinguish a duplicate
  from its parent, so calling it a false positive would punish extraction granularity.
- **Type agreement stays out of the match test.** A mislabelled hit is still a true positive (D36);
  finding a contradiction and typing it are separate questions, and `type_confusion` now reports the
  full gold→predicted matrix so the low agreement (0.413 grouped) can be adjudicated rather than
  quoted. My prior is that much of it is taxonomy overlap — an obligation reversal usually *is* also
  a direct negation — but that is a hypothesis until someone reads the matrix.
- **Extraction P/R is not here.** It stays in `extraction_gold.py` against its own gold set, because
  §9.2 wants extraction attributable separately from end-to-end detection.
- **Latency P50/P95 is not implemented.** Nothing records per-document wall-clock yet; adding the
  metric without the instrumentation would produce a field that silently reads zero. Deferred with
  the instrumentation, not faked.

**Options considered.**
- *Grouped as headline, per-verdict alongside* (chosen).
- *Per-verdict as headline.* Answers "how often was the judge right", not "how often is what I am
  shown right". It is the honest diagnostic, not the product metric.
- *Keep the mixed-unit formula for continuity with earlier notes.* Rejected — continuity with a
  number that is not a proportion is not worth having, and nothing is published yet.
- *Count duplicates as false positives.* Would read precision 92/256 = 0.359 and punish the system
  for how finely the extractor split a section.

**Provenance.** Mine. I found the unit mismatch while answering my own question about whether the
score was any good — which is an argument for having to explain a number to someone, and for not
leaving the thing that computes your headline in a scratch folder outside the repo.

## D43 — The evaluation runner does not run the pipeline, and every report it writes carries the configuration it was scored under (2026-08-03)

**Decision.** Added `src/crosscheck/evaluation/runner.py` and a `crosscheck eval` command. It loads
labelled benchmarks with the reports produced for them, scores each through `metrics.py` (D42), and
writes a timestamped directory under `benchmarks/results/` containing `eval.json` (machine-readable,
the full metrics tree) and `report.md` (the document that becomes `docs/eval-report.md`, §13).

**Deviation from §7.6, deliberately.** The spec says the runner "runs the pipeline, collects
verdicts, computes metrics". Mine does the last two and **not** the first. `crosscheck audit`
produces the report; `crosscheck eval` scores it.

The reason is that these two things have wildly different costs. An audit is ~25 minutes of CPU and
real money; scoring is free and finishes in under a second. Welding them together means re-running
the audit to fix a typo in a table, and it makes the numbers harder to trust rather than easier —
every table regeneration becomes a *new* run with its own retrieval nondeterminism, so two versions
of the same report would disagree slightly for no reason. Splitting them means the artifact is a
pure function of a report plus a gold set, and I can iterate on presentation as many times as I like
without touching the pipeline. The composition §7.6 describes still exists; it is just spelled as two
commands instead of one.

**Every report states its configuration, because a number without one is a rumour.** This is the
direct lesson of the run that cost $1.50 yesterday: a benchmark audit silently used Sonnet when the
baseline it was being compared against had used Haiku, which missed every cached verdict and hit the
cost ceiling. Nothing about the resulting report showed which judge produced it. So `RunConfig` now
captures judge model, extraction model, retrieval strategy and K, reranker and K, NLI model and
thresholds, and the overlap cut, and it is rendered at the top of every report.

**With an honest limitation printed in the output rather than hidden in my head.** A
`ContradictionReport` still does not record which model judged it — `CostSummary` tracks spend, not
models — so the configuration block describes settings **at evaluation time**. Score an old report
under new settings and the block will describe the new ones. The markdown says exactly that, in the
report, above the table. The real fix is to stamp the judge model onto the report at build time;
that is a schema change touching the regression snapshot, so it is follow-up work rather than
something to bundle here. Writing the caveat down where a reader will hit it is the honest interim.

**Caveats travel with the tables.** `BenchmarkResult.warnings` computes the conditions that make
numbers unsafe to quote — a partial audit (recall is understated, unjudged pairs count as misses), a
non-zero `duplicate_count` at grouped granularity (the roll-up and the gold matching have diverged),
a gold set whose generator and judge share a family (§9.1 violated, partly measuring
self-recognition), an *unknown* cross-model status, and pairs excluded by review. They render into a
blockquote at the top of the benchmark's section. A caveat that lives in the author's memory is not
a caveat; this project's whole credibility argument is that the numbers come with their conditions
attached.

**Smaller choices.**
- **Empty calibration bins are dropped from the markdown but kept in `eval.json`.** A table of
  mostly-empty rows is noise to read; a plot needs the stable axis. Different consumers, different
  shapes, same data.
- **`generated_at` is optional and defaults to None**, exactly as `build_report` does (D35), so a
  fixture-driven test can assert byte-stability. The CLI passes a real timestamp.
- **The CLI takes one benchmark, the module API takes many.** Only the synthetic set exists today;
  when the hand-written set lands (§9.1) it should appear as a second section of the *same* report
  next to the synthetic one, since the whole point is reading the gap between them. The list-shaped
  API is there so that costs nothing later; a multi-benchmark CLI syntax can wait until there is a
  second benchmark to pass it.
- **`eval` shadows the builtin.** Noqa'd at the definition. It is the name a user expects on the
  command line, and the builtin is not used in that module.

**Options considered.**
- *Score-only runner, audit stays a separate command* (chosen).
- *Runner runs the pipeline as §7.6 literally says.* Rejected on cost and reproducibility, above.
- *Score inside `crosscheck audit` and write metrics with the report.* Tempting, and it would tie a
  number to its run properly — but it forces a gold set to exist for every audit, which is wrong for
  the real-corpus case where there are no labels at all.
- *Leave the provenance block out and rely on the commit history.* This is what I effectively had,
  and it is what cost the $1.50.

**Provenance.** Mine. The provenance block exists because of a concrete failure the day before, not
because it seemed tidy.

---

## D44 — The hand-written validation set is five registers of one company, and its gold labels are built by a script, not typed (2026-08-04)

**Decision.** Added `benchmarks/handwritten/` — a five-document, 2,124-word fictional corpus with 28
hand-authored cross-document contradictions — and `scripts/build_handwritten_gold.py`, which
resolves those contradictions into `gold.json`. This is the §9.1 deliverable that Phase 5 was
supposed to produce and did not.

**Why it had to exist before anything else in Phase 6.** The synthetic headline (P .852 / R .662 /
F1 .745) was standing alone in `docs/eval-report.md`. §14 names exactly that — "letting the synthetic
headline number stand alone" — as the single biggest credibility risk in the project, and §1 explains
why it is not a stylistic concern: if frontier models are barely better than chance on real
contradiction detection, a strong F1 on a synthetic benchmark is at least as likely to reflect
benchmark easiness as a solved problem. Nothing in the repo could distinguish those two explanations.

**The design: one company, five registers.** Five documents state the same organisation's rules in
five voices — a public privacy notice ("we", "you", "your information"), a contractual DPA
("Processor", "Personal Data", "Sub-processor", "Business Day"), an internal engineering standard
("objects", "buckets", "fabric", "lifecycle job"), a sales trust overview (absolute and unqualified),
and an operational runbook (imperative). Every planted conflict crosses two registers.

That is not decoration. It is where real corpora actually drift — a marketing page promises what the
contract does not require and the standard does not implement, and nobody re-reads all four together
— and it is what drives lexical overlap down. Measured with the project's own `lexical_overlap`:

| set | pairs | median overlap | low-overlap stratum (< 0.30) |
|---|---|---|---|
| `synthetic/v1` (injected, GPT-4.1) | 139 | 0.310 | 68 / 139 (49%) |
| `handwritten` | 28 | **0.072** | **26 / 28 (93%)** |

Four times less surface similarity. The reason injected pairs look alike is structural: a generator
asked to negate a sentence returns the negation in that sentence's vocabulary, because that is the
only vocabulary the prompt supplied. The register shift is the only way I could think of to break
that without also making the conflicts arguable.

**The line I held: adversarial in phrasing, unambiguous in substance.** A pair a careful human would
argue about is a bad gold label however realistic it feels. Two candidates were cut on that test — a
"we never sell your data" against "aggregated insights are licensed to partners" pair, and a
deletion-request pair whose other side was an ordinary statutory-retention carve-out. Neither is
clearly a contradiction, so neither is in the set. The techniques that survived are the ones that hide
a *certain* conflict rather than soften it: buried exemptions in a legacy-estate paragraph, defined
terms resolved three sections away ("ten days" against "ten Business Days"), implication rather than
statement (the runbook never says PII is in the logs — it says triage starts by searching the logs
for the user's email address, "which is recorded on every authenticated request"), and absolute
claims against named exceptions.

**Every document is Markdown, deliberately.** The acceptance corpus deliberately spans all four v1
formats; this one deliberately does not. Gold labels match on the unordered pair of sections (D36),
and a plain-text document parses to exactly *one* section, so every contradiction touching it would
share a section key and `duplicate_section_keys` could not tell them apart. Format coverage is the
acceptance corpus's job; 28 distinguishable labels is this one's.

**The gold set is built, not written.** A gold label carries a `section_id`, which is a content hash
that changes on any edit to the document, plus two character spans. Hand-maintaining 28 pairs of
those means 56 opaque hex strings transcribed by hand and stale on the first typo fix — and D31 was
already a transcription corruption. So the script holds the pairs in the form a human can check
(file name, heading, verbatim sentence, and an argument for why it is a contradiction) and resolves
everything machine-shaped: section by unique heading-prefix match, span by `locate_quote`, and the
stored `text`/`evidence_quote` sliced back out of the source so the label is the document's own bytes
rather than what I typed. A quote that cannot be found is a hard error, because an unreachable gold
pair depresses recall forever and looks exactly like a detection miss.

It refuses to write past two invariants: a section-level collision (two pairs spanning the same two
sections are indistinguishable to the scorer), and a same-document pair (retrieval only considers
cross-document candidates, so it could never be found by any judge at any threshold).

**Types are unbalanced on purpose.** 9 numerical, 7 direct negation, 5 obligation reversal, 4
temporal, 3 scope/jurisdiction. The synthetic set is near-uniform because a generator was asked for
that; real corpora drift on numbers and flat denials constantly and on jurisdiction rarely. The cost
is statistical power on the small types — 3 pairs means 33 points of recall per finding — so the
README says outright that per-type rows on the small types are indicative only.

**Planted agreements are in the corpus too.** MFA in three documents, AES-256 at rest in two, annual
penetration testing in two, 24-hour backups in two. Without them the set measures recall and nothing
else, because a system that flagged every cross-document pair would score perfectly. The sharpest is
deliberate: the trust overview and the engineering standard agree almost exactly on encryption at
rest and disagree completely on key custody, one sentence apart.

**A consequence in the runner.** `BenchmarkResult.warnings` raised "cross-model status is unknown" on
this set every run — technically true, since a hand-authored set records no generator, and
meaningless, since there is no generator to record. Both cross-model warnings are now gated on
`origin == "injected"`. Only an injected benchmark can be inflated by self-recognition. Left ungated,
the loudest caveat in the report would sit above the benchmark whose provenance is least in doubt,
which is worse than no caveat — it trains a reader to skip the blockquote.

**What this set is not.** It is fictional, and written by the person doing the measuring, who knew
the taxonomy while writing. `reviewed` is `false` on every pair — §9.1 sets an ≥85% human-review bar
for the injected set, and a second reviewer is worth more here, because these labels rest on argument
rather than on a template. And 28 pairs is small enough that one finding moves recall by 3.6 points.
All three are in the README rather than in my head. The independent test is the real-corpus check
(§9.4); this set is a bridge to it, not a substitute.

**Options considered.**
- *Five registers of one fictional company, gold built by script* (chosen).
- *Hand-label a real public corpus instead.* That is §9.4, and it is the next thing to run. It is not
  a substitute: without labels covering the whole corpus you get a hit-rate on the top-20, not
  precision and recall, so it cannot be scored beside the synthetic set in the same table.
- *Generate the set with a second model and call it "realistic".* That is a second synthetic set with
  a different generator, not a hand-written one, and it would inherit the same
  negation-in-the-source-vocabulary property that makes injected pairs easy.
- *Reuse the acceptance corpus (Arden Systems) and label it.* Rejected on its own README's evidence:
  it is "lexically obvious" and "not adversarial" by construction, and it says so — which is what
  told me what this corpus needed to be.

**What it measured, the same day.** 173 claims from 25 chunks, 2,842 candidate pairs, 528 surviving
the NLI filter, 17 findings. Scored against the 28 gold pairs under settings identical to the
synthetic run:

| benchmark | P | R | F1 | low-overlap F1 | median overlap |
|---|---|---|---|---|---|
| `synthetic-v1` (injected) | .852 | .662 | **.745** | .667 | 0.310 |
| `handwritten-v1` | .765 | .464 | **.578** | .571 | 0.072 |

Four things in that, in descending order of how much they changed my mind:

1. **Most of the headline gap is lexical overlap, not the benchmark being hand-written.** Overall F1
   falls 0.167, but *low-overlap* F1 falls only 0.096 — and the hand-written set is 93% low-overlap
   against the synthetic set's 49%. Controlling for surface similarity, the two benchmarks nearly
   agree. That is a better result for the system than the headline suggests, and I would not have
   been able to say it without the strata §9.2 requires.
2. **Recall carries the loss; precision mostly holds.** −0.198 recall against −0.087 precision. The
   system finds fewer hard contradictions, but what it reports is still mostly right — which is the
   right failure mode for an auditing tool, where a false positive costs a reviewer's afternoon.
3. **The calibration structure replicates.** On the synthetic set the 0.8–0.9 confidence bin was
   overconfident by 18 points while 0.9–1.0 was well calibrated. On the hand-written set: 0.8–0.9
   overconfident by 25 points (n=10, .852 confidence against .600 accuracy), 0.9–1.0 well calibrated
   (n=6, .930 against 1.000). "Trust ≥0.9, discount 0.8–0.9" was a single-benchmark observation
   yesterday; it is now a finding that transfers. ECE is worse (.1876 against .0597) but ECE is a
   scalar over 17 samples and the bins are what matter.
4. **`scope_jurisdiction` scored 0 of 3, and `obligation_reversal` 1 of 5.** Both were among the
   weaker types on the synthetic set too (.586 and .733 recall), so this is the same weakness
   amplified, not a new one. Three pairs is not a measurement — but zero of three is worth chasing,
   and it is now written down rather than averaged away. Meanwhile `temporal_conflict` scored 4 of 4,
   inverting its position as the *worst* synthetic type (.571). Supersession language
   ("replaces", "withdrawn", "remains authoritative") is apparently easier to catch when a human
   writes it naturally than when a model injects it.

**One number I do not trust yet: type agreement of 0.846**, against 0.413 on the synthetic set. The
honest reading is that I assigned the gold types myself, knowing the taxonomy, so my labels are
biased toward what the judge would say. It is not evidence the system classifies better here.

**Judge hallucination rate was 0.0000** — every evidence quote passed the substring check across 528
judged pairs.

**Provenance.** Mine. The register-shift design came from re-reading the acceptance corpus's
"Known limitations" section, which had already written down what a hand-written set would have to fix.

---

## D45 — `crosscheck eval --suite` scores several benchmarks into one report (2026-08-04)

**Decision.** Added `BenchmarkSuite` and `load_suite` to the evaluation runner, and a `--suite`
option to `crosscheck eval`. `benchmarks/suite.json` is committed and lists the synthetic and
hand-written sets; `docs/eval-report.md` is regenerated from it with one command.

**This closes a follow-up D43 left open deliberately.** That entry noted the module API took a list
of benchmarks from day one while the CLI took exactly one, on the grounds that a multi-benchmark
syntax could wait until there was a second benchmark to pass it. There now is one.

**Why it is not a convenience feature.** The gap between the injected and hand-written sets *is* the
result — it is the thing §9.1 asks for and the thing §14 says must never be omitted. A reader who has
to open two files and hold both tables in their head to compute that gap will not do it, and the
synthetic number is the one that will get quoted. Adjacent sections under a single configuration
block make the comparison the default reading rather than an act of diligence.

**A committed manifest rather than a repeatable option.** `--benchmark name=gold:report` would work,
but it puts the reproduction recipe in shell history. The manifest *is* the recipe: it is in the
repo, it is diffable, and the published report cannot quietly diverge from the benchmarks it claims
to score. Paths with colons or equals signs also need no escaping.

**Paths resolve relative to the manifest, not the working directory.** That is what makes a committed
manifest portable across checkouts and `cd`s. An empty benchmark list raises rather than rendering a
cheerful empty report.

**The gap statement is computed, not typed.** §13 requires "an explicit synthetic-vs-real gap
statement". The obvious way to satisfy it is to write a sentence into `docs/eval-report.md` after
generating the file — which breaks the property D43 was built around, that the report is a pure
function of `(reports, gold sets, config)`. A hand-added sentence goes stale the next time the
numbers move, and a stale claim under an authoritative-looking table is worse than no claim.

So `_comparison_section` renders it: a side-by-side table (name, origin, gold pairs, median gold
overlap, P/R/F1, low-overlap F1) whenever a run holds two or more benchmarks, plus a sentence with
both F1s and the delta substituted in whenever exactly one benchmark is injected and one is not. It
names the hand-authored set first, because the lower number is the one that should be quoted. It can
assert that the difference is attributable to the benchmarks rather than the system only because
every benchmark in a run is scored under one `RunConfig` rendered once at the top — the claim and the
thing that makes it true live in the same file.

`median_gold_overlap` was added to `BenchmarkMetrics` to feed that table. It is a property of the
benchmark rather than of the system, and it earns its place by being the cheapest evidence available
for how hard a benchmark is: no API calls, no audit, computable the moment a gold set exists. It is
what let the hand-written set be justified on a measurement rather than on the argument that injected
data ought to be easier. `_stratum_f1` returns `None` for an empty stratum and the table prints `—`;
on a set where one stratum holds 2 of 28 pairs, a fabricated 0.000 would read as catastrophic failure
rather than as no data.

**Smaller choices.**
- **`GOLD` and `REPORT` became optional positionals**, and the command validates that exactly one of
  the two forms was supplied, exiting 2 with a usage message. Typer cannot express "required unless
  another option is present", so the check is explicit rather than declarative.
- **Warnings on stderr are now prefixed with the benchmark name.** With two sections in one report an
  unlabelled caveat no longer says which set it belongs to.
- **The `eval` command got its first tests.** It had none; argument validation is the part most
  likely to break and the cheapest to cover.

**Options considered.**
- *Committed JSON manifest* (chosen).
- *Repeatable `--benchmark` option.* Rejected: recipe lives in shell history, and quoting is fiddly.
- *Keep `eval` single-benchmark and concatenate two reports by hand.* Rejected — the concatenation is
  where the honesty lives, so it should not be a manual step anyone can skip.

**Provenance.** Mine, executing the plan D43 recorded.

---

## D46 — The §9.4 real-corpus check ran on NIST SP 800-53 and found nothing, because the corpus cannot contain what the system looks for (2026-08-04)

**Decision.** Ran the §9.4 sanity check on NIST SP 800-53 AU-1…AU-5, Rev 4 against Rev 5, via a new
`scripts/build_nist_slice.py`. Result: **1 finding, 0 confirmed real.** Recorded as a negative
result with a structural explanation rather than retried until it produced a better number.

**Sized before dispatch, for once.** The full AC family estimated at ~$8.00 and the full AU family at
~$3.60, against ~$1.89 of credit — using the ~$0.0063-per-claim rate this project paid to learn on
the hand-written run (D44), which overran 3× because I guessed instead. AU-1…AU-5 estimated at
$1.04; it came in at **$0.8895, complete, under a $1.40 ceiling**. The estimate is now trustworthy
enough to plan with.

**Contiguous controls, not chosen ones.** AU-1 through AU-5 are the first five of the family. Picking
the controls where I already knew Rev 5 diverged would have made the hit rate a statement about my
document selection rather than about the system.

**The classification rule was fixed before the findings were visible**, because REAL-versus-
REFINEMENT is genuinely arguable on a revision pair and deciding it afterwards would have made the
figure worthless. REAL = a substantive requirement difference; REFINEMENT = renaming or
reorganisation that changes nothing an implementer must do; ARTIFACT = spurious pairing.

**The one finding is a false positive, and the reason is a domain convention.** The judge paired
Rev 4's "The organization reviews and updates the audited events" with Rev 5's "(3) … [Withdrawn:
Incorporated into AU-2.]" and read *Withdrawn* as removal. It is not: "Incorporated into AU-2" means
the enhancement was folded into the base control, and Rev 5's AU-2 restates the obligation verbatim
at item (e). NIST's withdrawal markers read as deletion to anyone who does not know the convention,
and the judge does not.

**Why almost nothing was found — the part that matters.** Counted over the two documents: **48
`[Assignment: organization-defined …]` placeholders, zero concrete requirement values, four
negations in ~4,100 words.** Every number in either document is a control identifier or a list
enumerator. Even percentages are parameterised.

SP 800-53 is a **control catalogue, not a set of assertions** — a template whose thresholds the
adopting organisation fills in. That structurally rules out four of the five v1 types before the
pipeline starts: nothing to mismatch numerically, almost no negations, no exemptions (Rev 5
restructures and tightens, it never excuses), and no jurisdictions. Only `TEMPORAL_CONFLICT` is
reachable, which is precisely the label the single finding carried.

**So this is not a recall failure.** Finding almost nothing in a document pair containing almost
nothing findable is correct. The system also did not manufacture noise — 217 pairs reached the judge
and it declined 216, which is the right direction to err for an auditing tool. Reading AU-4 and AU-5
by hand agrees: Rev 5 renames "Audit Storage Capacity" to "Audit Log Storage Capacity" and *adds* a
time bound to AU-5's alert requirement. An implementer complying with Rev 5 is never in breach of
Rev 4.

**What it does not establish.** Transfer. Whether this system finds real conflicts in the wild is
still an open question, and this run cannot answer it. Saying otherwise would be the exact
over-claiming §14 warns against — the same discipline that produced the hand-written set applies to
its own negative results.

**The genuinely useful output is that §9.4's own suggested corpus is a poor test for this system**,
for a reason verifiable with one `grep` that I would not have predicted from reading the spec. Two
successive editions of a standard do not contradict; the later supersedes the earlier. §6's
`TEMPORAL_CONFLICT` requires both to remain *active in the corpus*, which is false of a withdrawn
revision.

**Next corpus, deferred on budget rather than doubt:** NIST SP 800-63B Rev 3 vs Rev 4. Same publisher
and licence, but it commits to concrete values — minimum 8 characters, permit at least 64, the
well-known reversal on periodic password rotation — and Rev 4 revised several of them.

**A one-character bug the slice script exists to avoid.** Controls are matched on the first
whitespace token of a heading, never with `startswith`: `"AU-1"` is a prefix of `AU-10` through
`AU-16`, so a prefix match would have silently pulled in eleven extra controls, quadrupled the
corpus and the bill, and shown no symptom beyond a chunk count I might have shrugged at. The script
also raises when a requested control is *missing*, since a silently-shrunk corpus is the mirror
failure.

**Where the result lives.** `benchmarks/realcorpus/nist_au/`, with its own README. It is deliberately
**not** in `benchmarks/suite.json` and not in `docs/eval-report.md`: the runner scores against gold
sets, and inventing labels for a corpus chosen because nobody had labelled it would defeat the
exercise. Two kinds of evidence, two artifacts.

**Options considered.**
- *Record the negative result and defer the retry* (chosen).
- *Retry immediately on 800-63B.* Rejected on budget — ~$0.80 of ~$1.00 left, with no reserve and no
  way to size the slice until the documents were in hand.
- *Widen to the whole AU family for more findings.* Rejected: it multiplies cost by four to search a
  corpus already shown to be structurally incapable of containing four of the five types.
- *Reclassify the withdrawal finding as REAL and report a 1-of-1 hit rate.* Rejected, and worth
  naming as the temptation it was — the pre-registered rule exists precisely to make that
  unavailable after the fact.

**Provenance.** Mine. The structural diagnosis came from asking why the NLI pass rate was 15% here
against 23% and 30% on the benchmarks, then counting placeholders instead of theorising.

---

## D47 — The service layer resets the claim store on every audit, runs one at a time, and reads live spend off the audit's own LLM client (2026-08-05)

**Decision.** Added `src/crosscheck/api/main.py` (FastAPI), the four routes §7.7 specifies plus one
extra, and `fastapi` / `uvicorn[standard]` / `python-multipart` as dependencies. 20 tests, 98%
coverage on the module.

**Every audit resets the claim collection, unconditionally.** This is the important one. Retrieval's
only cross-document filter is `doc_id != self` — there is no corpus predicate anywhere in
`claim_repo` or `candidate_gen`. On the command line an operator remembers `--reset-store` when
switching corpora (and I nearly forgot it twice today). Through an API nobody is watching, so
auditing corpus B after corpus A would silently pair B's claims against A's leftovers and report
contradictions spanning two unrelated document sets — with no error, no warning, and a
confident-looking HTML report.

So the service does not expose the flag. It resets. The cost is resume-across-corpora, which an
upload-driven service never uses: each corpus arrives once and is audited once, and the verdict
cache still makes a *retry of the same corpus* cheap because the corpus id is content-derived.

*Options considered.* Exposing `reset_store` in the request body, defaulting true — rejected,
because it makes a correctness-critical flag a caller's responsibility, which is the exact trap
being closed. Scoping retrieval by corpus properly (a payload field plus a query filter) is the real
fix; it touches the claim schema, the repo, candidate generation and the frozen regression snapshot,
so it is follow-up work rather than something to bundle into the API. Recorded as the known gap.

**One audit at a time; a second gets 409, not a queue.** The pipeline loads ~1.3 GB of models and is
CPU-bound. Two concurrent audits thrash a laptop and can exhaust a container. A queue is state that
has to be explained, bounded, drained and made visible; a demo service does not need one, and `409`
naming the in-flight audit is a more honest answer than silently accepting work that will not start
for ten minutes. `GET /health` reports `audit_in_flight` so a caller can see why.

**Live cost comes free from a parameter that already existed.** `orchestrator.audit` takes an
optional `llm` client, so the service constructs one, keeps the reference on the task record, and
returns `CostSummary.from_tracker(llm.cost)` on every poll. §7.7[v2] requires that running spend and
`partial` state are visible to the caller; this gets it without threading a progress callback
through eight pipeline stages. Verified over HTTP: an audit polled mid-flight reported
`$0.0000/0.02`, then `$0.0350/0.02` with `partial: true`.

**The orchestrator is synchronous, so it goes to a thread.** `asyncio.to_thread`, with the task
handle held on the record — a bare `asyncio.create_task` reference can be garbage-collected
mid-flight. Blocking the event loop would mean `GET /audit/{id}` could not answer during an audit,
which defeats the point of returning 202.

**Corpus ids are content-derived.** `POST /ingest` hashes every uploaded file's name and bytes,
order-independent, so uploading the same documents twice lands on the same corpus directory, the
same audit id, and the same caches. That is the CLI's resume behaviour reached through HTTP. Bytes
are hashed as bytes rather than decoded, so two different binaries cannot collide by both decoding
to replacement characters.

**Unsupported uploads are skipped and reported, not rejected.** A `.yml` in a folder of policies
should not fail the whole request. `parsers.SUPPORTED_SUFFIXES` was added as a public constant so
the API can filter before dispatching instead of catching an exception per file.

**One extra route beyond the four.** `GET /audit/{id}/report.html` serves the rendered report — §13
calls the HTML export the demo artifact, `html_renderer` already produces a self-contained page, and
a link a reviewer can open beats a JSON blob they have to render themselves.

**Two things the HTTP smoke test exposed, recorded rather than fixed.**

1. **The cost ceiling is a "stop dispatching" bound, not a hard cap on the total.** The audit above
   was given a $0.02 ceiling and finished having spent $0.0350, because the check runs *before* a
   call and a single Sonnet extraction call cost more than the remaining headroom. This matches §4's
   wording ("stops dispatching new judge calls") and is correct behaviour, but "max_cost" reads like
   a guarantee it does not give. Worth renaming or documenting in the README.
2. **A ceiling stop during the first extraction batch reports all-zero stats.** `extraction_llm_calls`
   was 0 while `cost.call_count` was 1, because the orchestrator bails before recording the batch.
   Only reachable when the ceiling bites in the very first batch, so it is cosmetic — but it is the
   kind of inconsistency that makes a reader distrust every other counter.

**Uploads live under `.crosscheck/uploads/`**, which is already gitignored. They are somebody else's
documents; the same reason the claim cache must never be committed applies to them. A
`max_upload_bytes` bound (default 10 MB) exists because a service with no auth needs *some* limit and
the cost ceiling does not help — parsing happens before any LLM call.

**Provenance.** Mine. The reset-on-every-audit decision came from noticing that money trap #3 in my
own notes is a human-discipline workaround, and that an API removes the human.

---

## D48 — The container ships without its models; a one-shot warm-up service fills a named volume before the API accepts traffic (2026-08-10)

**Decision.** Added `Dockerfile`, `.dockerignore`, `src/crosscheck/warmup.py` and a
`crosscheck warm-models` CLI command, and grew `docker-compose.yml` from Qdrant-only to the full
stack (`qdrant` + `warm-models` + `api`). This closes Phase 7. `docker compose up` is the whole
quickstart §2 asks for.

**The models do not go in the image.** bge-large (1.3 GB), bge-reranker-v2-m3 (2.2 GB) and
nli-deberta-v3-base (704 MB) come to 4.2 GB — nearly twice the size of the entire built image,
which came in at 2.27 GB once the CPU-only torch wheel turned out to be just 183 MB. They live in a named
`models` volume, written once by a `warm-models` service that runs `crosscheck warm-models` and
exits, and the API waits on that exit code via `depends_on: condition: service_completed_successfully`.

*Options considered.* **Baking them into a layer above the source COPY** was the obvious
alternative and I nearly took it: one self-contained image, works offline, no extra service, no
volume semantics to explain. What decided it against was where the 4.2 GB then lives. As a layer it
has to be rebuilt on every machine, it is re-pulled after any change to a layer beneath it, and
`docker compose build --no-cache` — the thing you reach for precisely when something is wrong —
destroys it. As a volume it survives all of that, including every code change during development,
which is the case that actually recurs. The image is ~1.9 GB instead of ~6 GB and the bytes over
the wire are identical either way; only *how often* you pay them differs. **Downloading lazily on
first use** (the status quo, no warm-up at all) was rejected outright: it puts a ten-minute download
inside the first audit request, where it reads as a hang, and a failed download surfaces as a
mysterious audit error rather than a startup error.

**The warm-up runs real inferences rather than downloading files.** The obvious implementation is
`huggingface_hub.snapshot_download` per repo id, and it is wrong twice. A full snapshot pulls every
artefact in a repo — bge-large publishes `pytorch_model.bin` *and* `model.safetensors` *and* ONNX
exports — so it fetches gigabytes the pipeline never opens; and the `allow_patterns` list needed to
avoid that is a second, drifting copy of sentence-transformers' own loading rules. Driving the real
embedder, reranker and NLI scorer through one tiny inference caches exactly the files the pipeline
opens, by construction, because it *is* the pipeline opening them. It also buys a real smoke test:
a non-zero exit means the models cannot load in this container at all, said at startup rather than
at first audit. Cost on a warm cache is ~28 s per `up`, which is a fair price for never debugging a
half-downloaded model.

**The warm-up is a CLI command, not a script in `scripts/`.** `scripts/` is outside mypy's `files`
list and has no test precedent — nothing in it is imported by anything. This code gates the API
starting, so it is runtime behaviour, and it belongs where the rest of the runtime lives: importable,
`mypy --strict`-checked, and unit-tested like every other module. `crosscheck warm-models` is also
genuinely useful by hand — pre-downloading before a demo on a bad connection is exactly the case
§7.7's demo story cares about. Model names are read from `Settings`, never listed in the module, so
repointing the config at a different reranker warms the one configured rather than the one that was
current when the file was written.

**`FASTEMBED_CACHE_PATH` is set explicitly, and it is not cosmetic.** fastembed resolves its cache to
a directory under the system temp dir when the variable is unset. The three torch models honour
`HF_HOME` and would have cached correctly while BM25 silently re-downloaded on every container
start — the kind of bug that never fails, just quietly costs. Confirmed the fetch is real: warming
BM25 pulls 18 files from the hub.

**`HF_HUB_DISABLE_XET=1`, forced — the hub's Xet transfer deadlocks here.** This was not planned;
the first cold `docker compose up` found it. The download reached 64 MB and then moved **zero bytes
in three minutes**. The xet client's own log explained itself: its adaptive concurrency controller
read the early small-file successes as headroom and climbed one connection at a time — *"success
ratio 1.000 is above threshold 0.800 ... increased concurrency from 48 to 49"* — and wedged there.

I did not want to guess at this, so I tested it as a controlled comparison: identical image,
identical volume, cleared partial state, only `HF_HUB_DISABLE_XET` changed. The classic HTTPS path
pulled **570 MB in 40 seconds (~13 MB/s)** and completed all four models. That is not a marginal
difference, it is stalled versus working, so the variable is baked into the image rather than left
to the operator.

I suspect an interaction between ~50 concurrent sockets and WSL2's NAT, and I have not proven that
— what I have proven is the stall and the fix. A reproducible hang on the *very first run* is the
worst possible failure for a "one command and it works" quickstart, and it is not a trade worth
making for a faster transfer that sometimes works. Worth noting the warm-up design paid for itself
immediately here: this surfaced as a visible, named startup step rather than as an audit that
silently hung.

**`.dockerignore` is an allow-list, not a deny-list.** Everything is excluded and the four paths the
build reads are added back. A deny-list rots — every new directory ships to the daemon until someone
notices — and the working tree carries a 1.5 GB `.venv` and a 134 MB `.mypy_cache`. On this repo it
matters twice over, because the tree lives on the Windows filesystem via WSL where the daemon reads
the context one small file at a time. Context goes from ~1.7 GB to under 1 MB.

**Smaller calls.** Non-editable install (`uv sync --no-editable`), so the runtime stage carries only
the venv and no source tree — verified the six prompt `.md` files, which load through
`importlib.resources`, are present in the built wheel. Non-root `crosscheck` user at a fixed uid, so
the volume's ownership is predictable across rebuilds. Healthcheck written in stdlib `urllib` rather
than installing `curl` into a slim base for a four-line probe. Dependencies installed in a layer
keyed on `pyproject.toml` + `uv.lock` alone, with `README.md` copied later alongside the source,
because the README will change constantly in Phase 9 and must not invalidate a 1.3 GB dependency
layer. `uv` pinned to 0.11.7, the version that produced `uv.lock`.

**Verified, not assumed.** `docker compose build`: exit 0, no warnings, **2.27 GB**, build context
**1.05 MB** (from ~1.7 GB of working tree). Cold `up` from an empty volume: 4/4 models, exit 0,
4.2 GB, ~4.5 minutes. Warm `up`: **21.8 seconds** for the whole stack, with the warm-up re-loading
all four models in 19 s and the API reaching `healthy`. `GET /health` → `200 {"status":"ok",...}`.
`POST /ingest` with three files → `201`, two staged and the `.yml` skipped, both persisted into the
`audit_state` volume. Prompts confirmed loading from site-packages inside the container, and `/app`
confirmed to hold only the venv — no source tree. The one thing I did **not** do is run a paid audit
through the container; the pipeline is already covered by the CLI runs and the $0.035 HTTP smoke
test in D47, and the remaining credit is earmarked for the SP 800-63B real-corpus retry.

**What this does not do.** Qdrant is depended on as `service_started`, not `service_healthy` — the
image ships no shell or HTTP client to write a probe with, and the API does not touch Qdrant until
an audit runs. No multi-arch build; the image is amd64 as built. The Streamlit UI is not in the
stack yet; it arrives with Phase 8.

**Provenance.** Mine, after weighing the two shipping options explicitly. I went with the
recommendation on both the volume-vs-layer call and on moving the warm-up out of `scripts/` into the
package.

---

## D49 — The 800-63B real-corpus check found real contradictions, ~15% precision, and a roll-up rule that hides true positives under false ones (2026-08-10)

**Decision.** Ran the §9.4 real-corpus check a second time, on NIST SP 800-63B Rev 3 vs Rev 4
§5.1.1–5.1.3, after D46 established that SP 800-53 could not contain what the system looks for.
Added `scripts/build_63b_slice.py` and `benchmarks/realcorpus/nist_63b/`. 283 claims, 771 pairs
judged, **20 verdicts, $2.5231, complete**. Full analysis in that directory's README.

**The headline: transfer is demonstrated, and precision on real text is poor.** Two genuine
contradictions out of 13 findings — a hit rate near **15%**, against .852 precision on the
synthetic benchmark and .765 on the hand-written set. The system found real, non-obvious conflicts
in a document pair nobody labelled, including the headline 8→15 character password-length change
and Rev 4's deprecation of an out-of-band method Rev 3 permits. That is the first time this project
can say transfer happened at all; 800-53 could not answer the question. It is also the first honest
measurement of how much noise real text produces, and the README reports both.

**The genuinely valuable finding is a defect, not the hit rate.** A real contradiction was rolled up
*underneath a false positive* and is invisible in the findings list. `_roll_up_near_duplicates`
collapses findings **by section pair**, keeping the most confident. Rev 3 §5.1.1.2 and Rev 4
"Password Verifiers" are ~1,200-word sections carrying many independent obligations — length,
composition, rotation, hashing, salting — so all findings between them collapsed to one, and a
0.92-confidence false positive about salt lengths outranked the 0.75-confidence real password-length
change.

The assumption "one contradiction per section pair" held everywhere it had been tested: the
synthetic generator injects roughly one per section, and the hand-written set is five short
registers. **Only a real document has long sections carrying many independent requirements.** It is
compounded by something already measured — the 0.8–0.9 confidence bin is overconfident by +.181
(synthetic) and +.252 (hand-written), so "keep the most confident" is not a safe tie-break.

*The fix, not applied here.* Roll up on the **claim pair's subject and quantity**, not the section
pair — or keep section-pair grouping but stop discarding: promote every finding whose subject
differs from the primary's. The second is smaller and strictly better than today's behaviour. Not
done in this commit because it changes `report.py`, the HTML renderer's disclosure behaviour, and
the frozen regression snapshot, and I would rather land the measurement that motivates it first.
The 800-63B report is committed as-is so the before state is on record.

**Sizing worked, and the ceiling mattered.** Projected $1.88 from the measured 800-53 rate; actual
$2.52. The entire gap is NLI survival — 15% on 800-53 against **27.2%** here, because a normative
document is far denser in negations than a template. I raised the ceiling from $2.50 to $3.20
before dispatch on exactly that reasoning; **at $2.50 the run would have stopped `partial`** and the
extraction spend would have been wasted. Also corrected a standing error in my own notes: judge cost
is **linear** in claims, not "quadratic-ish", because `rerank_top_k` caps pairs per claim at 10.

**Predictions were pre-registered before any finding was visible**, because the REAL/REFINEMENT line
is arguable on a revision pair and deciding it afterwards would be grading my own homework. Two held,
one held for the wrong reason (the composition-rule pair was dropped by the filter, not declined by
the judge), and **one was wrong** — I predicted a cluster of terminology false positives from the
"memorized secret" → "password" rename, expecting the 800-53 `[Withdrawn:]` failure to recur. There
were none.

**The false positives are eleven different bugs, not one repeated.** Cross-reference renumbering
(§6.1.2 → §4.1.2) read as `numerical_mismatch`; "20 bits of entropy" against "six decimal digits",
which is the *same value* (19.93 bits) in a different unit; complementary halves of one rule (≥112 /
<112 bits) read as a reversal; different actors (authenticator vs verifier) conflated. Nine of the
eleven pair claims that are simply **not about the same thing**, which makes scope discrimination —
not judge reasoning — the concrete thing to attack next.

**The corpus bug caught before spending.** The first slice dropped Rev 3's section intros, which NIST
lays out in `<table><td>` while Rev 4 uses `<p>`. The loss was **asymmetric**, which is the dangerous
kind: it would have handed the system a corpus where Rev 4 defines terms Rev 3 appears not to, and on
a set with no gold labels nothing downstream would have caught the manufactured findings. Found by
reading the generated Markdown; verified by Rev 3 gaining exactly the 403 words of intros while
Rev 4 stayed byte-identical. Third time on this project that reading a real artefact caught what
every test passed through (D38, D42).

**The 800-53 caveat still stands and is repeated in the README.** This is still a successive-edition
pair. What 800-63B changes is *findability*, not *co-activity*: the earlier corpus stated no concrete
values so nothing was reachable. The co-activity premise rests on §1's own motivating example — both
versions left in a retrieval corpus because nobody pruned the old one — and that is a defensible
framing rather than a proof.

**Provenance.** Mine. The corpus choice was already recorded as the next step in D46; the
pre-registration and the decision to raise the ceiling before dispatch were both mine, and both paid
off — the first by making prediction 4's failure reportable, the second by keeping the run complete.

---

## D50 — Near-duplicate roll-up keys on subject as well as section pair, and the eval harness stops inheriting the report's display rule (2026-08-10)

**Decision.** Fixed the defect D49 found. `Finding.roll_up_key` is now `(section_a, section_b,
normalised subject)` instead of the section pair alone, so two findings collapse only when they
span the same sections *and* share a subject. Separately, `metrics.collapse_to_sections()` was
added and `score_benchmark` now derives its `grouped` set with it rather than reading
`report.findings`. 366 tests (9 new).

**Why subject, and why nothing cleverer.** Subject is compared casefolded with whitespace
collapsed, and that is all — no stemming, no synonyms. The failure being fixed is *silently hiding
a real contradiction*, so the comparison is deliberately biased towards treating subjects as
different: a spurious extra card costs a reader seconds, a suppressed finding costs them the
finding. `test_subject_comparison_does_not_stem` pins that, keeping "verifier" and "verifiers"
distinct on purpose.

D34 rejected subject as a *grouping* key because it fragments — 342 claims produced 173 subjects,
62% singletons. That objection does not apply here: this is not grouping, it is a discriminator
inside an already-narrow bucket (one document pair, one section pair), where fragmenting is the
desired behaviour rather than the failure mode.

**The part that took the most thought: this is a presentation defect, not a scoring defect.** Gold
labels are written at section level (D36), so the section pair is the correct *measurement* unit —
a second finding on a section pair whose gold is already claimed can only score as a duplicate or
a false positive. Until now the report's display roll-up and the metric's scoring unit were the
same operation, and `score_benchmark` just read `report.findings`. Splitting a card would therefore
have silently moved every published number.

So the two concerns are now separately expressed. The report decides what to *show*; `metrics`
decides what to *score*, and does its own section-level collapse. **Verified rather than asserted:
re-running `crosscheck eval --suite` after the change reproduces `docs/eval-report.md` byte for
byte** — same precision, recall, F1, per-type breakdowns, overlap strata, calibration bins and ECE
on both benchmarks; the only diff is the timestamp. That was the whole risk of this change and it
is now a checked property, with `test_splitting_a_card_does_not_change_the_scored_set` guarding it.

A pleasant consequence: the committed `synthetic/v1/report.json` and `handwritten/report.json` were
built by the *old* roll-up and are not being regenerated (their audit results are long gone, and one
was keyed to a deleted path). They score identically anyway, which is exactly the invariance this
split buys.

**Effect on the real corpus.** The 800-63B report goes from 13 findings to 15, verdict count
unchanged at 20. Two of the seven rolled-up findings are promoted, one of them the genuine
8-to-15-character password change that had been buried under a 0.92-confidence false positive about
salt lengths. Reported precision on that corpus therefore *rises* from ~15% to ~20% — because what
the roll-up was suppressing there was a true positive, not noise. `benchmarks/realcorpus/nist_63b/
report.json` was rebuilt from the saved audit result (free — `build_report` makes no LLM calls) so
the committed artefact matches the current code rather than preserving a bug for narrative
convenience; the README describes the original behaviour in prose and quotes.

**What this does not fix.** Two genuinely different contradictions that share a section pair *and*
a subject are still collapsed. That is a narrower hole than before and I have no evidence it bites,
but it is not closed. The deeper issue D49 identified is untouched: nine of the eleven false
positives pair claims that are simply not about the same thing, which is a retrieval-and-judging
precision problem, not a reporting one.

**Provenance.** Mine, following the recommendation to fix this before Phase 8 and 9 — the demo GIF
and README both render the findings list, and capturing them beforehand would have put a salt-length
false positive on screen as the headline with the real password change invisible beneath it.

---

## D51 — The Streamlit demo runs in two modes, talks to the service over HTTP, and keeps every decision out of the page (2026-08-10)

**Decision.** Phase 8. Added `ui/streamlit_app.py`, the `crosscheck.ui` package (`client.py`,
`presenter.py`), a `ui` optional-dependency extra, a `requirements.txt` for the free host, and a
fourth `ui` service in docker-compose. 410 tests (44 new).

**Two modes, and explorer is not a degraded one.** Live mode appears when a service is reachable:
upload, audit, poll, render. Explorer mode appears when none is, and reads reports committed to the
repo. This is forced by arithmetic — the pipeline needs 4.2 GB of models and a running Qdrant, and
no free host provides that — but it is also the better artefact. §13 wants a deployed URL; a
reader with thirty seconds wants to see *a real contradiction found in a published NIST standard*,
not a progress bar. So the deployed demo leads with the 800-63B run and says plainly in the sidebar
that running your own corpus means `docker compose up` locally.

*Options considered.* **Fly.io running the whole stack** would make the deployed demo the real
thing, and the spec explicitly allows it — rejected on cost, since it means a standing monthly bill
for a portfolio project whose entire remaining budget is $17.50 of API credit. **Community Cloud
running the pipeline** is not an option at 4.2 GB. **No deployment at all** fails §13.

**Measured before designing around it.** I assumed the explorer would need a dependency split to
fit Community Cloud's ~1 GB, and was wrong: importing the report module and parsing a real report
costs **174 MB RSS**, because the embedder, reranker and NLI models are all imported lazily and
explorer mode never triggers them. Torch is installed and never resident. So no restructuring
happened — §14 says descope what the spec does not ask for, and the measurement said the spec did
not need it here. `requirements.txt` exists only because the host speaks pip rather than uv; the
lockfile stays the source of truth everywhere else.

**The UI drives the pipeline over HTTP, not by importing the orchestrator.** A localhost hop costs
nothing and buys three things: the Phase 7 service layer stays the single way an audit starts, so
its decisions about resetting the store and refusing concurrent runs apply to the demo instead of
being quietly bypassed; the UI is a client of a documented contract rather than a second entry
point into the pipeline; and the demo can point at a service anywhere, which is exactly what the
compose `ui` service does (`http://api:8000`) without loading a single model in the Streamlit
process. Request and response bodies are the API's own pydantic models, imported rather than
restated, so the schema cannot drift.

**No Streamlit import anywhere under `src/`.** Every decision the page makes — mode, highlight
segmentation, grouping, confidence banding, which bundled reports exist — lives in
`crosscheck.ui.presenter` and `crosscheck.ui.client`, leaving `streamlit_app.py` with widget calls.
Streamlit re-runs the whole script on every interaction, which makes logic embedded in a page
genuinely hard to test, and this is the deliverable the project is judged on. The split is the same
reasoning that moved the container warm-up out of `scripts/` (D48): importable, `mypy --strict`,
unit-tested.

**The page is still rendered in CI.** Unit tests on pure functions cannot catch an import error, a
session-state mistake, or an exception raised mid-render — the failures that actually happen in
Streamlit. So `test_streamlit_app.py` drives the real page through Streamlit's `AppTest` harness,
which is why `streamlit` is also in the dev group. Two traps found by writing it: `AppTest.from_file`
resolves a relative path against its own package rather than the working directory, and a sidebar
`text_input` supplies its default on every run, so session state cannot be pre-seeded — the mode
has to be steered through the environment.

**Confidence is rendered against the measured calibration, not as a raw number.** ≥0.90 is shown as
well calibrated; 0.80–0.90 is shown but labelled overconfident, because that band measured +.181 on
the synthetic set and +.252 on the hand-written one and *replicated across both*, making it a
property of the judge rather than of a benchmark. Putting that on the card is the cheapest way the
demo shows the rigour the project is actually about.

**Verified.** Explorer mode renders the 800-63B report headlessly: 3 bundled reports with the real
corpus first, 20 contradictions / 2 documents / 771 pairs / $2.5231, grouped in taxonomy order
(5 direct negation, 6 numerical mismatch, 4 obligation reversal), 15 expandable cards, no exception.
Live mode renders the upload screen against the running API. The four-service stack comes up with
`ui` healthy on :8501 and reaching the API by service name. I did **not** run a paid audit through
the UI: that path is the API's, already covered by its tests and the $0.035 HTTP smoke test in D47,
and the credit is better spent elsewhere.

**Known gaps.** The image grew 2.27 → 2.71 GB, since it now carries Streamlit and the committed
reports and serves as one image for all three roles. Explorer mode reads whatever is committed, so
a stale report on disk is a stale demo. The demo GIF and the deployment itself are Phase 9.

**Provenance.** Mine, following the recommendation to build one app that is live locally and an
explorer when deployed, rather than choosing between them.
