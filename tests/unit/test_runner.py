"""Unit tests for the evaluation runner (§7.6, §13)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crosscheck.aggregation.report import (
    ContradictionReport,
    DocumentPairGroup,
    Finding,
    FindingSide,
    write_json,
)
from crosscheck.config import Settings
from crosscheck.detection.taxonomy import ContradictionType
from crosscheck.evaluation.gold import GoldPair, GoldSet, GoldSide, gold_id, write_gold_set
from crosscheck.evaluation.runner import (
    BenchmarkSpec,
    EvalRun,
    GoldSummary,
    RunConfig,
    evaluate,
    load_suite,
    render_markdown,
    write_run,
)
from crosscheck.orchestrator import AuditStats

_A = "Vendors must carry liability insurance."
_B = "Vendors are not required to carry liability insurance."


def _gold_pair() -> GoldPair:
    a = GoldSide(document="a.md", section_id="s1", text=_A, evidence_quote=_A, char_span=(0, 1))
    b = GoldSide(document="b.md", section_id="s2", text=_B, evidence_quote=_B, char_span=(0, 1))
    return GoldPair(
        pair_id=gold_id(a, b),
        contradiction_type=ContradictionType.OBLIGATION_REVERSAL,
        a=a,
        b=b,
        origin="injected",
        generator_model="gpt-4.1",
    )


def _finding() -> Finding:
    def side(document: str, section: str, text: str) -> FindingSide:
        return FindingSide(
            claim_id=f"{document}:{section}",
            doc_id=document,
            filename=document,
            section_id=section,
            claim_text=text,
            evidence_quote=text,
            highlight=text,
            polarity="positive",
        )

    return Finding(
        pair_id="p1",
        contradiction_type=ContradictionType.OBLIGATION_REVERSAL,
        confidence=0.9,
        subject="insurance",
        rationale="one mandates, the other exempts",
        a=side("a.md", "s1", _A),
        b=side("b.md", "s2", _B),
    )


def _report(*, partial: bool = False, findings: list[Finding] | None = None) -> ContradictionReport:
    findings = [_finding()] if findings is None else findings
    return ContradictionReport(
        audit_id="aid",
        corpus_path=Path("/corpus"),
        document_count=2,
        claim_count=10,
        contradiction_count=len(findings),
        groups=[
            DocumentPairGroup(
                doc_a_id="d1", doc_b_id="d2", doc_a="a.md", doc_b="b.md", findings=findings
            )
        ]
        if findings
        else [],
        stats=AuditStats(
            claim_count=10, decontextualization_flags=1, judge_llm_calls=10, hallucination_count=1
        ),
        partial=partial,
        partial_reason="audit cost ceiling reached while judging" if partial else None,
    )


@pytest.fixture
def bench(tmp_path: Path) -> BenchmarkSpec:
    """A gold set and a matching report on disk."""
    gold_path = tmp_path / "gold.json"
    report_path = tmp_path / "report.json"
    write_gold_set(
        GoldSet(
            name="tiny",
            corpus_dir="corpus",
            seed=7,
            generator_model="gpt-4.1",
            judge_model_at_authoring="claude-haiku-4-5",
            pairs=[_gold_pair()],
        ),
        gold_path,
    )
    write_json(_report(), report_path)
    return BenchmarkSpec(name="tiny", gold_path=gold_path, report_path=report_path)


@pytest.fixture
def settings() -> Settings:
    return Settings()


class TestRunConfig:
    def test_captures_the_knobs_a_number_depends_on(self, settings: Settings) -> None:
        config = RunConfig.from_settings(settings)
        assert config.judge_model == settings.judge_model
        assert config.nli_default_threshold == settings.nli_default_threshold
        assert config.rerank_top_k == settings.rerank_top_k
        assert config.crosscheck_version

    def test_per_type_thresholds_are_serializable_strings(self, settings: Settings) -> None:
        with_types = settings.model_copy(
            update={"nli_thresholds": {ContradictionType.TEMPORAL_CONFLICT: 0.2}}
        )
        assert RunConfig.from_settings(with_types).nli_thresholds == {"temporal_conflict": 0.2}


class TestEvaluate:
    def test_scores_a_benchmark(self, bench: BenchmarkSpec, settings: Settings) -> None:
        run = evaluate([bench], settings)
        assert len(run.benchmarks) == 1
        result = run.benchmarks[0]
        assert result.name == "tiny"
        assert result.metrics.grouped.overall.true_positives == 1
        assert result.metrics.grouped.overall.f1 == pytest.approx(1.0)

    def test_captures_gold_provenance(self, bench: BenchmarkSpec, settings: Settings) -> None:
        gold = evaluate([bench], settings).benchmarks[0].gold
        assert gold.seed == 7
        assert gold.generator_model == "gpt-4.1"
        assert gold.cross_model is True  # gpt-4.1 vs claude-haiku-4-5
        assert gold.type_counts == {"obligation_reversal": 1}

    def test_scores_several_benchmarks_in_order(
        self, bench: BenchmarkSpec, settings: Settings
    ) -> None:
        second = bench.model_copy(update={"name": "second"})
        run = evaluate([bench, second], settings)
        assert [b.name for b in run.benchmarks] == ["tiny", "second"]

    def test_missing_file_raises(self, bench: BenchmarkSpec, settings: Settings) -> None:
        broken = bench.model_copy(update={"report_path": Path("/nope/missing.json")})
        with pytest.raises(FileNotFoundError):
            evaluate([broken], settings)


class TestWarnings:
    def test_partial_audit_is_flagged(self, tmp_path: Path, settings: Settings) -> None:
        gold_path, report_path = tmp_path / "g.json", tmp_path / "r.json"
        write_gold_set(GoldSet(name="t", corpus_dir="c", pairs=[_gold_pair()]), gold_path)
        write_json(_report(partial=True), report_path)
        run = evaluate(
            [BenchmarkSpec(name="t", gold_path=gold_path, report_path=report_path)], settings
        )
        assert any("partial" in w for w in run.benchmarks[0].warnings)

    def test_unknown_cross_model_status_is_flagged(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        gold_path, report_path = tmp_path / "g.json", tmp_path / "r.json"
        # No generator/judge recorded -> cross_model is None, which is not the same as fine.
        write_gold_set(GoldSet(name="t", corpus_dir="c", pairs=[_gold_pair()]), gold_path)
        write_json(_report(), report_path)
        run = evaluate(
            [BenchmarkSpec(name="t", gold_path=gold_path, report_path=report_path)], settings
        )
        assert any("unknown" in w for w in run.benchmarks[0].warnings)

    def test_a_clean_run_has_no_warnings(self, bench: BenchmarkSpec, settings: Settings) -> None:
        assert evaluate([bench], settings).benchmarks[0].warnings == []

    def test_hand_written_set_is_not_asked_for_a_generator(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        """A hand-authored set has no generator, so cross-model status is not a caveat (D44)."""
        gold_path, report_path = tmp_path / "g.json", tmp_path / "r.json"
        write_gold_set(
            GoldSet(name="t", corpus_dir="c", origin="handwritten", pairs=[_gold_pair()]),
            gold_path,
        )
        write_json(_report(), report_path)
        run = evaluate(
            [BenchmarkSpec(name="t", gold_path=gold_path, report_path=report_path)], settings
        )
        assert not any("cross-model" in w.lower() for w in run.benchmarks[0].warnings)


class TestLoadSuite:
    def _manifest(self, tmp_path: Path, body: dict[str, object]) -> Path:
        path = tmp_path / "suite.json"
        path.write_text(json.dumps(body), encoding="utf-8")
        return path

    def test_resolves_paths_relative_to_the_manifest(self, tmp_path: Path) -> None:
        """A committed manifest has to work from any working directory."""
        path = self._manifest(
            tmp_path,
            {"benchmarks": [{"name": "a", "gold_path": "x/gold.json", "report_path": "y/r.json"}]},
        )
        specs = load_suite(path)
        assert specs[0].gold_path == (tmp_path / "x" / "gold.json").resolve()
        assert specs[0].report_path == (tmp_path / "y" / "r.json").resolve()

    def test_keeps_benchmark_order(self, tmp_path: Path) -> None:
        path = self._manifest(
            tmp_path,
            {
                "benchmarks": [
                    {"name": "first", "gold_path": "g1", "report_path": "r1"},
                    {"name": "second", "gold_path": "g2", "report_path": "r2"},
                ]
            },
        )
        assert [spec.name for spec in load_suite(path)] == ["first", "second"]

    def test_empty_manifest_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="no benchmarks"):
            load_suite(self._manifest(tmp_path, {"benchmarks": []}))

    def test_malformed_manifest_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            load_suite(self._manifest(tmp_path, {"benchmarks": [{"name": "a"}]}))


class TestRenderMarkdown:
    def test_contains_the_headline_and_the_caveats(
        self, bench: BenchmarkSpec, settings: Settings
    ) -> None:
        markdown = render_markdown(evaluate([bench], settings))
        assert "# CrossCheck evaluation report" in markdown
        assert "## tiny" in markdown
        assert "Precision" in markdown
        assert "By lexical overlap" in markdown
        assert "Confidence calibration" in markdown
        assert "How to read these numbers" in markdown
        # The provenance caveat must travel with the tables.
        assert "at evaluation time" in markdown

    def test_warnings_are_rendered_into_the_section(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        gold_path, report_path = tmp_path / "g.json", tmp_path / "r.json"
        write_gold_set(GoldSet(name="t", corpus_dir="c", pairs=[_gold_pair()]), gold_path)
        write_json(_report(partial=True), report_path)
        run = evaluate(
            [BenchmarkSpec(name="t", gold_path=gold_path, report_path=report_path)], settings
        )
        assert "Read these numbers with care" in render_markdown(run)

    def test_unstamped_run_renders(self, bench: BenchmarkSpec, settings: Settings) -> None:
        assert "unstamped" in render_markdown(evaluate([bench], settings))

    def test_is_byte_stable_without_a_timestamp(
        self, bench: BenchmarkSpec, settings: Settings
    ) -> None:
        first = render_markdown(evaluate([bench], settings))
        second = render_markdown(evaluate([bench], settings))
        assert first == second

    def test_empty_run_renders(self, settings: Settings) -> None:
        markdown = render_markdown(EvalRun(config=RunConfig.from_settings(settings)))
        assert "# CrossCheck evaluation report" in markdown


class TestWriteRun:
    def test_writes_both_artifacts(
        self, bench: BenchmarkSpec, settings: Settings, tmp_path: Path
    ) -> None:
        run = evaluate([bench], settings, generated_at=datetime(2026, 8, 3, 9, 30, tzinfo=UTC))
        destination = write_run(run, tmp_path / "results")
        assert destination.name == "20260803T093000Z"
        assert (destination / "report.md").exists()
        payload = json.loads((destination / "eval.json").read_text(encoding="utf-8"))
        assert payload["benchmarks"][0]["name"] == "tiny"
        assert payload["config"]["judge_model"] == settings.judge_model

    def test_directory_name_can_be_overridden(
        self, bench: BenchmarkSpec, settings: Settings, tmp_path: Path
    ) -> None:
        run = evaluate([bench], settings)
        destination = write_run(run, tmp_path / "results", directory_name="fixed")
        assert destination.name == "fixed"

    def test_creates_missing_parents(
        self, bench: BenchmarkSpec, settings: Settings, tmp_path: Path
    ) -> None:
        run = evaluate([bench], settings)
        destination = write_run(run, tmp_path / "deep" / "nested", directory_name="x")
        assert destination.exists()

    def test_json_keeps_empty_calibration_bins(
        self, bench: BenchmarkSpec, settings: Settings, tmp_path: Path
    ) -> None:
        # The markdown drops empty bins; eval.json must keep them for a stable plot axis.
        run = evaluate([bench], settings)
        destination = write_run(run, tmp_path, directory_name="x")
        payload = json.loads((destination / "eval.json").read_text(encoding="utf-8"))
        assert len(payload["benchmarks"][0]["metrics"]["grouped"]["calibration"]["bins"]) == 10


class TestGoldSummary:
    def test_same_family_generation_is_reported_as_not_cross_model(self) -> None:
        gold = GoldSet(
            name="t",
            corpus_dir="c",
            generator_model="claude-sonnet-4-6",
            judge_model_at_authoring="claude-haiku-4-5",
            pairs=[_gold_pair()],
        )
        assert GoldSummary.of(gold).cross_model is False


class TestComparisonSection:
    """The head-to-head table and gap statement §13 requires."""

    def _two(self, tmp_path: Path, settings: Settings) -> EvalRun:
        """One injected benchmark and one hand-authored one, both scored."""
        specs = []
        for name, origin in (("synthetic", "injected"), ("handwritten", "handwritten")):
            gold_path, report_path = tmp_path / f"{name}-g.json", tmp_path / f"{name}-r.json"
            write_gold_set(
                GoldSet(
                    name=name,
                    corpus_dir="c",
                    origin=origin,  # type: ignore[arg-type]
                    generator_model="gpt-4.1" if origin == "injected" else None,
                    judge_model_at_authoring="claude-haiku-4-5",
                    pairs=[_gold_pair()],
                ),
                gold_path,
            )
            write_json(_report(), report_path)
            specs.append(BenchmarkSpec(name=name, gold_path=gold_path, report_path=report_path))
        return evaluate(specs, settings)

    def test_absent_for_a_single_benchmark(self, bench: BenchmarkSpec, settings: Settings) -> None:
        assert "Benchmarks side by side" not in render_markdown(evaluate([bench], settings))

    def test_renders_a_row_per_benchmark(self, tmp_path: Path, settings: Settings) -> None:
        markdown = render_markdown(self._two(tmp_path, settings))
        assert "Benchmarks side by side" in markdown
        assert "| synthetic | injected |" in markdown
        assert "| handwritten | handwritten |" in markdown

    def test_states_the_gap_between_injected_and_authored(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        markdown = render_markdown(self._two(tmp_path, settings))
        assert "**The gap.**" in markdown
        # Names the authored set first, since that is the number to quote.
        assert markdown.index("`handwritten`") < markdown.index(
            "`synthetic`", markdown.index("**The gap.**")
        )

    def test_median_gold_overlap_is_recorded(
        self, bench: BenchmarkSpec, settings: Settings
    ) -> None:
        overlap = evaluate([bench], settings).benchmarks[0].metrics.median_gold_overlap
        assert overlap is not None
        assert 0.0 <= overlap <= 1.0
