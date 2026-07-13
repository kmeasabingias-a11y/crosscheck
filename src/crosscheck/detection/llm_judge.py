"""LLM judge — the final verdict stage of detection (spec v2 §7.4).

The NLI filter cuts thousands of candidate pairs down to a few hundred likely
contradictions; this stage does the careful reasoning on those. For each pair the judge
sees the two atomic claims (with their source provenance) and returns a structured
:class:`~crosscheck.models.Verdict`: whether they contradict, the contradiction type,
a calibrated confidence, a rationale, and verbatim evidence quotes.

Three defenses matter here, and each mirrors a pattern already used upstream:

1. **Code-side finalization** (like the claim extractor, D14/D15). The model returns a
    *reduced* :class:`JudgedVerdict` — the ruling only. This module sets ``pair_id`` from
    the pair being judged and substring-validates the evidence, so the model cannot
    fabricate either. A contradiction whose ``evidence_a``/``evidence_b`` is not a
    (whitespace-tolerant) substring of the two claims is discarded and counted as a
    judge-hallucination (spec §7.4, §9.2).
2. **Resume cache** (like the extractor's claim cache, spec §4). Each pair's raw verdict
    is cached by a hash of the two claim texts and the judge model, so a re-run — or an
    audit resumed after the cost ceiling stopped it — never re-spends tokens on a pair it
    has already judged.
3. **Cost ceiling** (spec §4). Judging is per-pair, so when the shared LLM wrapper reports
    the audit ceiling is reached, the judge stops dispatching, marks the result
    ``partial``, and returns the verdicts it has — it never runs unbounded.
"""

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from loguru import logger
from pydantic import Field

from crosscheck.config import Settings
from crosscheck.detection.taxonomy import ContradictionType
from crosscheck.ids import content_hash
from crosscheck.llm import CostCeilingError, LLMClient
from crosscheck.models import Claim, CrossCheckModel, Pair, Verdict
from crosscheck.prompts import load_prompt


class JudgeError(RuntimeError):
    """Raised when a pair references a claim id absent from the provided claims."""


class JudgedVerdict(CrossCheckModel):
    """A verdict exactly as the LLM returns it, before code attaches the pair id.

    The judge is asked only for the ruling fields; ``pair_id`` is set in code from the
    pair being judged, and the evidence quotes are substring-validated against the two
    claims before a full :class:`~crosscheck.models.Verdict` is built — so the model can
    fabricate neither the id nor the evidence.
    """

    is_contradiction: bool
    contradiction_type: ContradictionType | None = None
    confidence: float = Field(ge=0.0, le=1.0, description="Judge confidence, 0.0-1.0.")
    rationale: str
    evidence_a: str
    evidence_b: str
    resolution_hint: str | None = None


class JudgeResult(CrossCheckModel):
    """The verdicts from one judging pass, plus observability counters."""

    verdicts: list[Verdict] = Field(default_factory=list)
    pair_count: int = 0
    llm_call_count: int = 0
    cache_hits: int = 0
    hallucination_count: int = Field(
        default=0, description="Contradiction verdicts dropped for un-quotable evidence."
    )
    partial: bool = Field(
        default=False, description="True if the cost ceiling stopped judging before all pairs."
    )

    @property
    def contradictions(self) -> list[Verdict]:
        """The subset of verdicts that assert a contradiction."""
        return [verdict for verdict in self.verdicts if verdict.is_contradiction]

    @property
    def hallucination_rate(self) -> float:
        """Fraction of asserted contradictions dropped for failing evidence validation.

        Denominator is the contradictions the model *asserted* (kept + dropped), since only
        those carry evidence to validate; 0.0 when it asserted none (spec §9.2).
        """
        asserted = len(self.contradictions) + self.hallucination_count
        return self.hallucination_count / asserted if asserted else 0.0


class VerdictCache(Protocol):
    """A cache of raw judge outputs, keyed by a hash of the two claims + judge model (§4)."""

    def get(self, key: str) -> JudgedVerdict | None:
        """Return the cached verdict for this key, or None on a miss."""
        ...

    def put(self, key: str, verdict: JudgedVerdict) -> None:
        """Store the raw verdict for this key."""
        ...


class InMemoryVerdictCache:
    """A process-local verdict cache (the default; used by tests and single runs)."""

    def __init__(self) -> None:
        self._store: dict[str, JudgedVerdict] = {}

    def get(self, key: str) -> JudgedVerdict | None:
        """Return the cached verdict for this key, or None on a miss."""
        return self._store.get(key)

    def put(self, key: str, verdict: JudgedVerdict) -> None:
        """Store the raw verdict for this key."""
        self._store[key] = verdict


class DiskVerdictCache:
    """A persistent verdict cache: one JSON file per pair hash.

    Survives across processes, so a re-run — or an audit resumed after the cost ceiling
    stopped it (spec §4) — skips pairs it has already judged instead of re-spending tokens.
    """

    def __init__(self, cache_dir: Path) -> None:
        """Create (if needed) and use ``cache_dir`` to store per-pair verdicts."""
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> JudgedVerdict | None:
        """Return the cached verdict for this key, or None on a miss."""
        path = self._dir / f"{key}.json"
        if not path.exists():
            return None
        return JudgedVerdict.model_validate_json(path.read_text(encoding="utf-8"))

    def put(self, key: str, verdict: JudgedVerdict) -> None:
        """Store the raw verdict for this key."""
        (self._dir / f"{key}.json").write_text(verdict.model_dump_json(), encoding="utf-8")


def _quote_present(haystack: str, quote: str) -> bool:
    """Return True if ``quote`` appears in ``haystack``, tolerating whitespace differences.

    Mirrors the extractor's verbatim check (D20): an exact substring match first, then a
    whitespace-flexible match (each run of whitespace in the quote matches any run of
    whitespace in the text), because the model often normalizes a source's line-wrap
    newlines to spaces while otherwise copying a span verbatim. A genuine fabrication — a
    changed or invented word — still fails.
    """
    if not quote.strip():
        return False
    if quote in haystack:
        return True
    pattern = re.compile(r"\s+".join(re.escape(word) for word in quote.split()))
    return pattern.search(haystack) is not None


def _claim_material(claim: Claim) -> str:
    """The text the judge is shown for a claim, and thus the haystack its quote must be in.

    Both the decontextualized assertion and the verbatim source span are shown in the
    prompt, so either is a legitimate place for the judge to quote from.
    """
    return f"{claim.text}\n{claim.evidence_quote}"


def _render_claim(claim: Claim, label: str) -> str:
    """Render a claim into the ``{{claim_a}}`` / ``{{claim_b}}`` block of the judge prompt."""
    return (
        f"Claim {label} (document {claim.doc_id}, section {claim.section_id}):\n"
        f"  Assertion: {claim.text}\n"
        f'  Source quote: "{claim.evidence_quote}"'
    )


class LLMJudge:
    """Adjudicates candidate pairs into verdicts via the LLM (spec v2 §7.4).

    Construct one per audit. Judges one pair per LLM call so the cost ceiling and the
    resume cache are per-pair; prompts are loaded once at construction and the cache is
    injectable so tests run with no network and a process-local cache.
    """

    def __init__(
        self,
        llm: LLMClient,
        settings: Settings,
        *,
        cache: VerdictCache | None = None,
    ) -> None:
        """Build a judge.

        Args:
            llm: The shared cost-tracked LLM wrapper (its ceiling stops judging).
            settings: Runtime configuration (judge model).
            cache: Where to cache raw verdicts; a process-local cache if None.
        """
        self._llm = llm
        self._settings = settings
        self._cache: VerdictCache = cache if cache is not None else InMemoryVerdictCache()
        self._system_prompt = load_prompt("contradiction_judge_system")
        self._user_prompt = load_prompt("contradiction_judge_user")

    def judge(self, pairs: Sequence[Pair], claims: Sequence[Claim]) -> JudgeResult:
        """Judge each pair, serving from cache and stopping cleanly at the cost ceiling.

        Args:
            pairs: The candidate pairs that survived the NLI filter.
            claims: The corpus claims (used to resolve each pair's claim ids to text).

        Returns:
            The verdicts (contradictions and non-contradictions), plus observability
            counters. Contradiction verdicts whose evidence is not verbatim in the claims
            are dropped and counted; if the cost ceiling is reached, ``partial`` is True and
            the verdicts judged so far are returned.

        Raises:
            JudgeError: If a pair references a claim id not present in ``claims``.
        """
        if not pairs:
            return JudgeResult()
        claims_by_id = {claim.claim_id: claim for claim in claims}

        verdicts: list[Verdict] = []
        llm_calls = 0
        cache_hits = 0
        hallucinations = 0
        partial = False
        for pair in pairs:
            try:
                claim_a = claims_by_id[pair.claim_a_id]
                claim_b = claims_by_id[pair.claim_b_id]
            except KeyError as exc:
                raise JudgeError(f"pair references unknown claim id {exc.args[0]!r}") from exc

            key = self._cache_key(claim_a, claim_b)
            raw = self._cache.get(key)
            if raw is None:
                try:
                    raw = self._call(claim_a, claim_b)
                except CostCeilingError as exc:
                    logger.warning("judge stopped at cost ceiling: {}", exc)
                    partial = True
                    break
                llm_calls += 1
                self._cache.put(key, raw)
            else:
                cache_hits += 1

            verdict = self._finalize(pair, raw, claim_a, claim_b)
            if verdict is None:
                hallucinations += 1
                continue
            verdicts.append(verdict)

        result = JudgeResult(
            verdicts=verdicts,
            pair_count=len(pairs),
            llm_call_count=llm_calls,
            cache_hits=cache_hits,
            hallucination_count=hallucinations,
            partial=partial,
        )
        logger.info(
            "judged {} pair(s): {} contradiction(s), {} llm call(s), {} cache hit(s), "
            "{} hallucination(s){}",
            result.pair_count,
            len(result.contradictions),
            llm_calls,
            cache_hits,
            hallucinations,
            " [partial: ceiling reached]" if partial else "",
        )
        return result

    def _call(self, claim_a: Claim, claim_b: Claim) -> JudgedVerdict:
        """Render the pair into the prompt and get one raw verdict from the LLM."""
        rendered = self._user_prompt.render(
            claim_a=_render_claim(claim_a, "A"),
            claim_b=_render_claim(claim_b, "B"),
        )
        return self._llm.structured(
            model=self._settings.judge_model,
            system=self._system_prompt.text,
            user=rendered,
            schema=JudgedVerdict,
        )

    def _finalize(
        self, pair: Pair, raw: JudgedVerdict, claim_a: Claim, claim_b: Claim
    ) -> Verdict | None:
        """Build a full :class:`Verdict`, or None if a claimed contradiction can't be quoted.

        A non-contradiction is passed through as-is (there is no evidence to validate). A
        contradiction must have both evidence quotes present in the respective claims;
        otherwise it is treated as a hallucination and dropped. The reserved
        ``CONDITIONAL_TRIPLET`` and a missing type both resolve to ``UNCLEAR`` (spec §6).
        """
        if not raw.is_contradiction:
            return Verdict(
                pair_id=pair.pair_id,
                is_contradiction=False,
                contradiction_type=None,
                confidence=raw.confidence,
                rationale=raw.rationale,
                evidence_a=raw.evidence_a,
                evidence_b=raw.evidence_b,
                resolution_hint=raw.resolution_hint,
            )
        if not (
            _quote_present(_claim_material(claim_a), raw.evidence_a)
            and _quote_present(_claim_material(claim_b), raw.evidence_b)
        ):
            logger.warning(
                "judge: evidence not found in claims for pair {} — dropping as hallucination "
                "(a={!r}, b={!r})",
                pair.pair_id,
                raw.evidence_a,
                raw.evidence_b,
            )
            return None
        contradiction_type = raw.contradiction_type
        if contradiction_type == ContradictionType.CONDITIONAL_TRIPLET:
            logger.warning(
                "judge: returned reserved CONDITIONAL_TRIPLET for pair {}; coercing to UNCLEAR",
                pair.pair_id,
            )
            contradiction_type = ContradictionType.UNCLEAR
        return Verdict(
            pair_id=pair.pair_id,
            is_contradiction=True,
            contradiction_type=contradiction_type or ContradictionType.UNCLEAR,
            confidence=raw.confidence,
            rationale=raw.rationale,
            evidence_a=raw.evidence_a,
            evidence_b=raw.evidence_b,
            resolution_hint=raw.resolution_hint,
        )

    def _cache_key(self, claim_a: Claim, claim_b: Claim) -> str:
        """Content hash of the judge model + both claim texts (in canonical pair order).

        The model is folded in so a cross-model eval run (Claude vs GPT-4o, §9.3) never
        serves one model's verdicts for the other — unlike the extractor cache, which is
        single-model. Pair order is already canonical (``claim_a_id < claim_b_id``, D24).
        """
        return content_hash(f"{self._settings.judge_model}\n{claim_a.text}\n{claim_b.text}")
