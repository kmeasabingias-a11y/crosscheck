"""Unit tests for the synthetic benchmark generator (§9.1, decisions D37/D38)."""

from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest

from crosscheck.config import Settings
from crosscheck.detection.taxonomy import V1_TYPES, ContradictionType
from crosscheck.evaluation.gold import duplicate_section_keys, load_gold_set
from crosscheck.evaluation.synthetic_gen import (
    GeneratedInjection,
    GenerationResult,
    generate_benchmark,
    plan_injections,
    related_sections,
    section_candidates,
)
from crosscheck.ingestion.parsers import parse
from crosscheck.llm import CostTracker, LLMError, SchemaT
from crosscheck.models import Document
from crosscheck.storage.embeddings import DenseEmbedder

_SORTED_V1_TYPES: list[ContradictionType] = sorted(V1_TYPES, key=lambda t: t.value)

# Three topics, repeated across documents. The fake embedder keys on these words, so which
# sections count as "related" is explicit in the fixture rather than an accident of a model.
_PTO_A = (
    "All full-time employees receive 20 paid time off days per calendar year. Part-time "
    "employees accrue paid time off pro rata according to contracted hours. Paid time off "
    "accrues monthly and becomes available after 90 days of continuous service."
    "Unused paid time off does not carry over into the following calendar year."
)
_PTO_B = (
    "Paid time off must be requested at least 14 days in advance through the People Operations "
    "portal. Managers may decline a paid time off request only where the absence would leave a "
    "team without adequate coverage during the period requested."
    "Paid time off is paid out on termination at the employee's final base rate."
)
_INSURANCE_A = (
    "Vendors must carry commercial general liability insurance of at least two million US "
    "dollars for each occurrence. The vendor must maintain that insurance cover for the "
    "duration of the engagement and for two years after it ends."
    "A certificate of insurance must be supplied to the company on request."
)
_INSURANCE_B = (
    "Evidence of insurance cover must be provided before services begin and on each renewal. "
    "Failure to maintain the required insurance is a material breach of this agreement and "
    "entitles the company to terminate the engagement immediately."
    "The insurance requirement applies to every engagement without exception."
)
_EXPENSE_A = (
    "Expense claims must be submitted within 30 days of the date the expense was incurred. "
    "Receipts are required for every expense claim above 25 US dollars. Late claims require "
    "written approval from a vice president before they will be reimbursed."
    "An expense claim without a receipt is rejected and returned to the claimant."
)
_EXPENSE_B = (
    "Travel expense claims are reimbursed at the published mileage rate. Every expense claim "
    "must identify the business purpose and the people present. Alcohol is not a reimbursable "
    "expense under any circumstances."
    "Every expense claim is reviewed by the finance team before reimbursement."
)

_TOPICS = ("paid time off", "insurance", "expense")


class _FakeEmbedder:
    """Deterministic topic-keyed embedder: same topic → cosine 1.0, different topic → 0.0."""

    @property
    def dim(self) -> int:
        return len(_TOPICS)

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    @staticmethod
    def _vector(text: str) -> list[float]:
        lowered = text.lower()
        counts = [float(lowered.count(topic)) for topic in _TOPICS]
        return counts if any(counts) else [0.0, 0.0, 1e-6]


class _FakeLLM:
    """A StructuredLLM returning canned injections.

    With ``source_claim=None`` it echoes the first sentence of the excerpt it was actually
    shown, so the verbatim check runs against real prompt content; passing a string overrides
    that, which is how the rejection paths are tested.
    """

    def __init__(
        self,
        *,
        source_claim: str | None = None,
        injected_claim: str = "Full-time staff are granted 32 days of annual leave each year.",
        error: Exception | None = None,
    ) -> None:
        self.cost = CostTracker()
        self.calls = 0
        self.prompts: list[str] = []
        self._source_claim = source_claim
        self._injected_claim = injected_claim
        self._error = error

    def structured(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[SchemaT],
        max_tokens: int | None = None,
    ) -> SchemaT:
        self.calls += 1
        self.prompts.append(user)
        if self._error is not None:
            raise self._error
        self.cost.record_tokens(model, input_tokens=500, output_tokens=100)
        claim = self._source_claim
        if claim is None:
            claim = _first_sentence_of_source_excerpt(user)
        injection = GeneratedInjection(
            source_claim=claim,
            injected_claim=f"{self._injected_claim} (call {self.calls})",
            rationale="They cannot both hold.",
        )
        return cast(SchemaT, injection)


def _first_sentence_of_source_excerpt(user_prompt: str) -> str:
    """Pull the first sentence of the source excerpt out of the rendered user prompt."""
    body = user_prompt.split("## Source document", 1)[1].split("## Target document", 1)[0]
    blocks = [block.strip() for block in body.split("\n\n") if block.strip()]
    excerpt = blocks[-1] if blocks else ""
    head, _, _ = excerpt.partition(". ")
    return f"{head}." if head else ""


def _document(title: str, *sections: tuple[str, str]) -> str:
    parts = [f"# {title}\n"]
    for heading, body in sections:
        parts.append(f"## {heading}\n")
        parts.append(f"{body}\n")
    return "\n".join(parts)


def _corpus(tmp_path: Path) -> Path:
    """Three documents covering overlapping topics, so every topic has a partner elsewhere."""
    corpus = tmp_path / "seed"
    corpus.mkdir()
    (corpus / "01_handbook.md").write_text(
        _document(
            "Employee Handbook",
            ("2. Paid Time Off", _PTO_A),
            ("6. Expenses", _EXPENSE_A),
        ),
        encoding="utf-8",
    )
    (corpus / "02_vendor.md").write_text(
        _document(
            "Vendor Agreement",
            ("3. Insurance", _INSURANCE_A),
            ("4. Evidence of Cover", _INSURANCE_B),
        ),
        encoding="utf-8",
    )
    (corpus / "03_policies.md").write_text(
        _document(
            "Staff Policies",
            ("2. Requesting Leave", _PTO_B),
            ("3. Travel", _EXPENSE_B),
        ),
        encoding="utf-8",
    )
    return corpus


def _documents(tmp_path: Path) -> list[Document]:
    return [parse(p) for p in sorted(_corpus(tmp_path).glob("*.md"))]


def _settings() -> Settings:
    return Settings(
        openai_api_key="sk-test",
        anthropic_api_key="sk-ant",
        generator_model="gpt-4.1",
        judge_model="claude-sonnet-4-6",
    )


def _generate(
    tmp_path: Path, llm: _FakeLLM, *, per_type: int = 1, seed: int = 7
) -> GenerationResult:
    return generate_benchmark(
        _corpus(tmp_path),
        tmp_path / "out",
        llm,
        _settings(),
        cast(DenseEmbedder, _FakeEmbedder()),
        seed=seed,
        per_type=per_type,
    )


# --- relatedness (D38) --------------------------------------------------------------------


def test_neighbours_are_never_in_the_same_document(tmp_path: Path) -> None:
    documents = _documents(tmp_path)
    neighbours = related_sections(documents, cast(DenseEmbedder, _FakeEmbedder()))
    assert neighbours
    for (doc_index, _), partners in neighbours.items():
        assert all(partner[0] != doc_index for partner in partners)


def test_neighbours_share_a_topic(tmp_path: Path) -> None:
    """The whole point of D38: a target must discuss what the source discusses."""
    documents = _documents(tmp_path)
    neighbours = related_sections(documents, cast(DenseEmbedder, _FakeEmbedder()))

    def topic(key: tuple[int, int]) -> str:
        text = documents[key[0]].sections[key[1]].text.lower()
        return next(t for t in _TOPICS if t in text)

    for source, partners in neighbours.items():
        assert all(topic(partner) == topic(source) for partner in partners)


def test_unrelated_sections_are_dropped_rather_than_padded(tmp_path: Path) -> None:
    """A source with no topical partner yields no injection at all."""
    corpus = tmp_path / "lonely"
    corpus.mkdir()
    (corpus / "a.md").write_text(_document("A", ("1. PTO", _PTO_A)), encoding="utf-8")
    (corpus / "b.md").write_text(_document("B", ("1. Insurance", _INSURANCE_A)), encoding="utf-8")
    documents = [parse(p) for p in sorted(corpus.glob("*.md"))]

    assert related_sections(documents, cast(DenseEmbedder, _FakeEmbedder())) == {}
    assert plan_injections(documents, {}, seed=1, per_type=2) == []


def test_section_candidates_skips_short_sections(tmp_path: Path) -> None:
    corpus = tmp_path / "short"
    corpus.mkdir()
    (corpus / "a.md").write_text(
        _document("A", ("1. Tiny", "Too short."), ("2. Real", _PTO_A)), encoding="utf-8"
    )
    assert section_candidates([parse(corpus / "a.md")]) == [(0, 1)]


# --- planning ----------------------------------------------------------------------------


def test_planning_is_deterministic_for_a_seed(tmp_path: Path) -> None:
    documents = _documents(tmp_path)
    neighbours = related_sections(documents, cast(DenseEmbedder, _FakeEmbedder()))
    assert plan_injections(documents, neighbours, seed=7, per_type=2) == plan_injections(
        documents, neighbours, seed=7, per_type=2
    )


def test_plans_only_pair_related_sections(tmp_path: Path) -> None:
    documents = _documents(tmp_path)
    neighbours = related_sections(documents, cast(DenseEmbedder, _FakeEmbedder()))
    plans = plan_injections(documents, neighbours, seed=3, per_type=3)
    assert plans
    for plan in plans:
        source = (plan.source_index, plan.source_section_index)
        target = (plan.target_index, plan.target_section_index)
        assert target in neighbours[source]


def test_plans_never_pair_a_document_with_itself(tmp_path: Path) -> None:
    documents = _documents(tmp_path)
    neighbours = related_sections(documents, cast(DenseEmbedder, _FakeEmbedder()))
    plans = plan_injections(documents, neighbours, seed=3, per_type=3)
    assert plans
    assert all(plan.source_index != plan.target_index for plan in plans)


def test_plans_do_not_reuse_a_section_pair(tmp_path: Path) -> None:
    """Section-level gold matching cannot separate two conflicts in one section pair (D36)."""
    documents = _documents(tmp_path)
    neighbours = related_sections(documents, cast(DenseEmbedder, _FakeEmbedder()))
    plans = plan_injections(documents, neighbours, seed=5, per_type=3)
    keys = [
        frozenset(
            {(p.source_index, p.source_section_index), (p.target_index, p.target_section_index)}
        )
        for p in plans
    ]
    assert len(keys) == len(set(keys))


def test_a_single_document_cannot_be_planned(tmp_path: Path) -> None:
    corpus = tmp_path / "one"
    corpus.mkdir()
    (corpus / "a.md").write_text(_document("A", ("1. PTO", _PTO_A)), encoding="utf-8")
    assert plan_injections([parse(corpus / "a.md")], {}, seed=1, per_type=2) == []


# --- generation --------------------------------------------------------------------------


def test_generate_writes_corpus_and_gold(tmp_path: Path) -> None:
    result = _generate(tmp_path, _FakeLLM())
    assert result.generated > 0
    assert result.gold_path.exists()
    assert sorted(p.name for p in result.corpus_dir.glob("*.md")) == [
        "01_handbook.md",
        "02_vendor.md",
        "03_policies.md",
    ]
    assert result.cost_usd > 0


def test_gold_section_ids_match_a_fresh_parse_of_the_written_corpus(tmp_path: Path) -> None:
    """D38: injecting text changes every section id in that document."""
    result = _generate(tmp_path, _FakeLLM())
    reparsed = {p.name: parse(p) for p in result.corpus_dir.glob("*.md")}
    assert result.gold.pairs
    for pair in result.gold.pairs:
        for side in (pair.a, pair.b):
            ids = {section.section_id for section in reparsed[side.document].sections}
            assert side.section_id in ids, "gold cites a section the pipeline will never compute"


def test_injected_claims_are_actually_in_the_written_corpus(tmp_path: Path) -> None:
    result = _generate(tmp_path, _FakeLLM())
    assert result.gold.pairs
    for pair in result.gold.pairs:
        assert pair.b.text in (result.corpus_dir / pair.b.document).read_text(encoding="utf-8")


def test_the_prompt_shows_both_source_and_target_text(tmp_path: Path) -> None:
    """The generator must see the target section, or it cannot write in its register."""
    llm = _FakeLLM()
    _generate(tmp_path, llm)
    assert llm.prompts
    for prompt in llm.prompts:
        assert "## Source document" in prompt
        assert "## Target document" in prompt


def test_gold_records_provenance_and_is_cross_model(tmp_path: Path) -> None:
    result = _generate(tmp_path, _FakeLLM())
    assert result.gold.generator_model == "gpt-4.1"
    assert result.gold.judge_model_at_authoring == "claude-sonnet-4-6"
    assert result.gold.cross_model is True
    assert result.gold.seed == 7
    assert all(pair.origin == "injected" for pair in result.gold.pairs)


def test_gold_has_no_section_pair_collisions(tmp_path: Path) -> None:
    result = _generate(tmp_path, _FakeLLM(), per_type=2)
    assert duplicate_section_keys(result.gold.pairs) == []


def test_gold_round_trips_from_disk(tmp_path: Path) -> None:
    result = _generate(tmp_path, _FakeLLM())
    assert load_gold_set(result.gold_path).model_dump_json() == result.gold.model_dump_json()


# --- rejection paths ---------------------------------------------------------------------


def test_a_paraphrased_source_claim_is_rejected(tmp_path: Path) -> None:
    """A non-verbatim source claim points at text that does not exist — the span would be a lie."""
    result = _generate(tmp_path, _FakeLLM(source_claim="Employees get some holiday, roughly."))
    assert result.generated == 0
    assert result.skipped
    assert all("not verbatim" in reason for reason in result.skipped)


def test_an_empty_source_claim_is_rejected(tmp_path: Path) -> None:
    """The generator declining to find a contradictable assertion is a valid answer."""
    result = _generate(tmp_path, _FakeLLM(source_claim=""))
    assert result.generated == 0
    assert all("nothing concrete" in reason for reason in result.skipped)


def test_generation_errors_are_skipped_not_fatal(tmp_path: Path) -> None:
    result = _generate(tmp_path, _FakeLLM(error=LLMError("upstream is down")))
    assert result.generated == 0
    assert len(result.skipped) == result.planned
    # A failed run still writes a usable, empty benchmark rather than half a corpus.
    assert result.gold_path.exists()
    assert result.gold.pairs == []


def test_uninjected_documents_are_still_written(tmp_path: Path) -> None:
    """A document with no injection is still part of the benchmark corpus."""
    result = _generate(tmp_path, _FakeLLM(error=LLMError("nope")))
    assert len(list(result.corpus_dir.glob("*.md"))) == 3


@pytest.mark.parametrize("contradiction_type", _SORTED_V1_TYPES)
def test_each_type_has_a_definition(contradiction_type: ContradictionType) -> None:
    from crosscheck.evaluation.synthetic_gen import _TYPE_DEFINITIONS

    assert _TYPE_DEFINITIONS[contradiction_type].strip()
