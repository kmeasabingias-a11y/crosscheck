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
