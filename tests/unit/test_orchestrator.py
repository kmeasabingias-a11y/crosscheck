"""Unit tests for the audit orchestrator (hermetic — no network, no Qdrant service).

The pipeline is wired with its *real* stages wherever the stage is cheap and deterministic:
a real ``ClaimExtractor`` and ``LLMJudge`` over a mocked Anthropic SDK client (so cost
tracking, the ceiling, and the on-disk caches are exercised for real), a real ``ClaimRepo``
and hybrid strategy over an in-process ``:memory:`` Qdrant with fake embedders, and fakes
only for the two heavyweight models (reranker, NLI). Every call is priced at a round $0.30
so the cost-ceiling assertions read as arithmetic rather than as magic numbers.
"""

import hashlib
import re
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from anthropic import Anthropic
from anthropic.types import Usage
from qdrant_client import QdrantClient

from crosscheck.config import Settings
from crosscheck.detection.llm_judge import DiskVerdictCache, JudgedVerdict, LLMJudge
from crosscheck.detection.nli_filter import NLIResult
from crosscheck.detection.taxonomy import ContradictionType
from crosscheck.ingestion.claim_extractor import (
    ClaimExtractor,
    DiskClaimCache,
    ExtractedClaim,
    _ExtractionBatch,
)
from crosscheck.llm import LLMClient
from crosscheck.orchestrator import AuditComponents, audit, audit_id, load_audit_state
from crosscheck.retrieval.candidate_gen import HybridStrategy
from crosscheck.storage.claim_repo import ClaimRepo
from crosscheck.storage.embeddings import SparseVector
from crosscheck.storage.qdrant_client import ensure_collection

# Local (:memory:) Qdrant warns that payload indexes are server-only; the calls are correct
# for the real server, so silence just that one message here.
pytestmark = pytest.mark.filterwarnings(
    "ignore:Payload indexes have no effect in the local Qdrant:UserWarning"
)

# 100k input tokens at Sonnet's $3.00/Mtok = exactly $0.30 per LLM call.
_COST_PER_CALL = 0.30

_DOC_A = "Employees receive 20 PTO days per year."
_DOC_B = "Employees are not entitled to PTO days."
_DOC_C = "Contractors receive 10 PTO days per year."
# A quote present in all three, so one canned verdict validates against any pair.
_SHARED_EVIDENCE = "PTO days"

_CHUNK_RE = re.compile(r"\[chunk_id: ([^\]]+)\]\n([^\n]+)")


# --- fakes -------------------------------------------------------------------------------


def _vector_seed(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


class _FakeDense:
    """Deterministic 4-d vectors derived from the text, so any claim text embeds."""

    dim = 4

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        seed = _vector_seed(text)
        return [(seed[i] / 255.0) + 0.1 for i in range(4)]


class _FakeSparse:
    """Two-term sparse vectors derived from the text (indices kept distinct)."""

    def embed_passages(self, texts: Sequence[str]) -> list[SparseVector]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> SparseVector:
        seed = _vector_seed(text)
        return SparseVector([seed[0] % 50, (seed[1] % 50) + 50], [1.0, 1.0])


class _FakeReranker:
    def score_pairs(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        return [1.0 for _ in pairs]


class _FakeNLIScorer:
    """Says every pair is (or is not) a contradiction, uniformly."""

    def __init__(self, *, keep: bool = True) -> None:
        self._keep = keep

    def score(self, pairs: Sequence[tuple[str, str]]) -> list[NLIResult]:
        prob = 0.99 if self._keep else 0.01
        return [NLIResult(contradiction_prob=prob, is_contradiction=self._keep) for _ in pairs]


def _usage() -> Usage:
    return Usage(
        input_tokens=100_000,
        output_tokens=0,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )


def _response(parsed: object) -> SimpleNamespace:
    return SimpleNamespace(usage=_usage(), parsed_output=parsed, stop_reason="end_turn")


class _FakeAnthropic:
    """Extraction returns one claim per chunk; judging returns a canned verdict."""

    def __init__(self, verdict: JudgedVerdict) -> None:
        self._verdict = verdict
        self.extraction_calls = 0
        self.judge_calls = 0
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs: Any) -> SimpleNamespace:
        prompt = str(kwargs["messages"][0]["content"])
        if kwargs["output_format"] is _ExtractionBatch:
            self.extraction_calls += 1
            claims = [
                ExtractedClaim(
                    chunk_id=chunk_id,
                    text=text,
                    evidence_quote=text,
                    subject="pto",
                    predicate="entitlement",
                    polarity="positive",
                )
                for chunk_id, text in _CHUNK_RE.findall(prompt)
            ]
            return _response(_ExtractionBatch(claims=claims))
        self.judge_calls += 1
        return _response(self._verdict)


def _verdict(*, is_contradiction: bool = True) -> JudgedVerdict:
    return JudgedVerdict(
        is_contradiction=is_contradiction,
        contradiction_type=ContradictionType.DIRECT_NEGATION if is_contradiction else None,
        confidence=0.9,
        rationale="one grants PTO, the other denies it",
        evidence_a=_SHARED_EVIDENCE,
        evidence_b=_SHARED_EVIDENCE,
        resolution_hint=None,
    )


# --- harness -----------------------------------------------------------------------------


def _corpus(tmp_path: Path, *docs: str) -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for index, text in enumerate(docs):
        (corpus / f"doc_{index}.txt").write_text(text, encoding="utf-8")
    return corpus


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "anthropic_api_key": "test-key",
        "qdrant_collection": "claims_test",
        "dense_vector_size": 4,
        "audit_state_dir": tmp_path / "state",
        "max_audit_cost_usd": 100.0,
        "max_document_cost_usd": 0.0,  # per-document cap disabled unless a test sets one
    }
    base.update(overrides)
    return Settings(**base)


def _components(
    corpus: Path,
    settings: Settings,
    fake: _FakeAnthropic,
    *,
    nli_keep: bool = True,
) -> tuple[AuditComponents, LLMClient]:
    """Wire the real stages against fakes, with the caches where the orchestrator expects them."""
    llm = LLMClient(settings, client=cast(Anthropic, fake))
    client = QdrantClient(":memory:")
    ensure_collection(client, settings)
    dense, sparse = _FakeDense(), _FakeSparse()
    repo = ClaimRepo(client, settings, dense_embedder=dense, sparse_embedder=sparse)
    state_dir = settings.audit_state_dir / audit_id(corpus)
    components = AuditComponents(
        extractor=ClaimExtractor(llm, settings, cache=DiskClaimCache(state_dir / "claims")),
        repo=repo,
        strategy=HybridStrategy(repo, dense_embedder=dense, sparse_embedder=sparse),
        reranker=_FakeReranker(),
        nli_scorer=_FakeNLIScorer(keep=nli_keep),
        judge=LLMJudge(llm, settings, cache=DiskVerdictCache(state_dir / "verdicts")),
    )
    return components, llm


# --- tests -------------------------------------------------------------------------------


def test_audit_runs_all_stages_and_reports_a_contradiction(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path, _DOC_A, _DOC_B)
    settings = _settings(tmp_path)
    fake = _FakeAnthropic(_verdict())
    components, llm = _components(corpus, settings, fake)

    result = audit(corpus, settings, llm=llm, components=components)

    assert result.stats.document_count == 2
    assert result.stats.claim_count == 2
    assert result.stats.candidate_pair_count == 1  # one cross-document pair
    assert result.stats.nli_kept_count == 1
    assert len(result.contradictions) == 1
    assert result.contradictions[0].contradiction_type is ContradictionType.DIRECT_NEGATION
    assert not result.partial
    # 2 extraction calls (one per document) + 1 judge call, all through the shared client.
    assert (fake.extraction_calls, fake.judge_calls) == (2, 1)
    assert result.cost.total_usd == pytest.approx(3 * _COST_PER_CALL)
    # The pair and both claims travel with the result so aggregation can render them.
    assert len(result.judged_pairs) == 1
    assert {claim.claim_id for claim in result.claims} == {
        result.judged_pairs[0].claim_a_id,
        result.judged_pairs[0].claim_b_id,
    }


def test_no_contradiction_is_a_successful_empty_result(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path, _DOC_A, _DOC_B)
    settings = _settings(tmp_path)
    fake = _FakeAnthropic(_verdict(is_contradiction=False))
    components, llm = _components(corpus, settings, fake)

    result = audit(corpus, settings, llm=llm, components=components)

    assert result.contradictions == []
    assert len(result.verdicts) == 1  # the negative verdict is kept for the eval harness
    assert not result.partial


def test_empty_corpus_returns_a_well_formed_result_without_building_anything(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    settings = _settings(tmp_path)

    # No llm and no components: an empty corpus must not need an API key or a vector store.
    result = audit(corpus, settings)

    assert result.stats.document_count == 0
    assert result.claims == []
    assert result.contradictions == []
    assert result.cost.total_usd == 0.0
    assert not result.partial


def test_unsupported_files_are_skipped_not_fatal(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "diagram.png").write_bytes(b"\x89PNG\r\n")
    settings = _settings(tmp_path)
    fake = _FakeAnthropic(_verdict())
    components, llm = _components(corpus, settings, fake)

    result = audit(corpus, settings, llm=llm, components=components)

    assert result.stats.document_count == 0
    assert result.claims == []
    assert fake.extraction_calls == 0


def test_missing_corpus_raises(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(FileNotFoundError):
        audit(tmp_path / "nope", settings)


def test_audit_cost_ceiling_stops_judging_and_marks_partial(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path, _DOC_A, _DOC_B, _DOC_C)
    # 3 extractions ($0.90) then judging: the 3rd judge call is refused at $1.50.
    settings = _settings(tmp_path, max_audit_cost_usd=1.50)
    fake = _FakeAnthropic(_verdict())
    components, llm = _components(corpus, settings, fake)

    result = audit(corpus, settings, llm=llm, components=components)

    assert result.stats.claim_count == 3
    assert result.stats.nli_kept_count == 3  # three cross-document pairs survived NLI
    assert fake.judge_calls == 2  # the third was never dispatched
    assert result.partial
    assert result.partial_reason is not None and "ceiling" in result.partial_reason
    assert result.cost.total_usd <= settings.max_audit_cost_usd


def test_per_document_cap_abandons_only_that_document(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    # Two sections => two extraction batches at batch_size=1, so the second one trips the cap.
    (corpus / "doc_0.txt").write_text(f"{_DOC_A}\n\n{_DOC_C}", encoding="utf-8")
    (corpus / "doc_1.txt").write_text(_DOC_B, encoding="utf-8")
    settings = _settings(
        tmp_path,
        chunk_max_tokens=12,  # forces doc_0's two sentences into two chunks
        chunk_overlap_tokens=0,
        extraction_batch_size=1,
        max_document_cost_usd=0.10,  # less than one $0.30 call: only the first is dispatched
        max_audit_cost_usd=100.0,
    )
    fake = _FakeAnthropic(_verdict())
    components, llm = _components(corpus, settings, fake)

    result = audit(corpus, settings, llm=llm, components=components)

    # doc_0 was abandoned mid-extraction; doc_1 still ingested normally.
    assert result.stats.document_count == 1
    assert [claim.text for claim in result.claims] == [_DOC_B]
    assert not result.partial  # a capped document degrades the audit, it does not end it


def test_resume_reuses_the_disk_caches_and_spends_nothing(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path, _DOC_A, _DOC_B)
    settings = _settings(tmp_path)
    fake = _FakeAnthropic(_verdict())
    components, llm = _components(corpus, settings, fake)

    first = audit(corpus, settings, llm=llm, components=components)
    calls_after_first = (fake.extraction_calls, fake.judge_calls)

    # A second run of the same corpus: fresh client and components, same state directory.
    fake_2 = _FakeAnthropic(_verdict())
    components_2, llm_2 = _components(corpus, settings, fake_2)
    second = audit(corpus, settings, llm=llm_2, components=components_2)

    assert calls_after_first == (2, 1)
    assert (fake_2.extraction_calls, fake_2.judge_calls) == (0, 0)  # everything served from disk
    assert second.cost.total_usd == 0.0
    assert second.stats.extraction_cache_hits == 2
    assert second.stats.judge_cache_hits == 1
    assert len(second.contradictions) == len(first.contradictions) == 1


def test_audit_state_file_records_the_final_stage(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path, _DOC_A, _DOC_B)
    settings = _settings(tmp_path)
    fake = _FakeAnthropic(_verdict())
    components, llm = _components(corpus, settings, fake)

    result = audit(corpus, settings, llm=llm, components=components)

    state = load_audit_state(settings, corpus)
    assert state is not None
    assert state.audit_id == result.audit_id == audit_id(corpus)
    assert state.stage == "judge"
    assert state.cost_usd == pytest.approx(result.cost.total_usd)
    assert not state.partial


def test_unreadable_audit_state_is_ignored(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path, _DOC_A)
    settings = _settings(tmp_path)
    state_dir = settings.audit_state_dir / audit_id(corpus)
    state_dir.mkdir(parents=True)
    (state_dir / "audit_state.json").write_text("{not json", encoding="utf-8")

    assert load_audit_state(settings, corpus) is None
