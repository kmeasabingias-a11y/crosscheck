"""Unit tests for the Typer CLI.

The orchestrator is stubbed out — these tests are about argument wiring, the export paths and
the exit codes, not about running a pipeline. `test_orchestrator.py` covers the audit itself.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from crosscheck import cli, orchestrator
from crosscheck.config import Settings
from crosscheck.detection.taxonomy import ContradictionType
from crosscheck.llm import LLMError
from crosscheck.models import Claim, DocumentRef, Pair, SectionRef, Verdict
from crosscheck.orchestrator import AuditResult, AuditStats, CostSummary
from crosscheck.warmup import WarmupResult

runner = CliRunner()

_TEXT_A = "Unused paid time off does not carry over into the following calendar year."
_TEXT_B = "Employees may carry over up to 5 unused paid time off days."


def _claim(claim_id: str, doc_id: str, section_id: str, text: str, polarity: str) -> Claim:
    return Claim(
        claim_id=claim_id,
        doc_id=doc_id,
        section_id=section_id,
        text=text,
        evidence_quote=text,
        evidence_offset=(0, len(text)),
        subject="paid time off",
        predicate="carries over",
        polarity="negative" if polarity == "negative" else "positive",
    )


def _result(*, with_contradiction: bool = True, partial: bool = False) -> AuditResult:
    return AuditResult(
        audit_id="aid",
        corpus_path=Path("/corpus"),
        documents=[
            DocumentRef(
                doc_id="d1",
                source_path=Path("/corpus/handbook.md"),
                sections=[SectionRef(section_id="s1", heading="2. Paid Time Off")],
            ),
            DocumentRef(
                doc_id="d2",
                source_path=Path("/corpus/pto_v2.md"),
                sections=[SectionRef(section_id="s2", heading="3. Carry-Over")],
            ),
        ],
        claims=[
            _claim("c1", "d1", "s1", _TEXT_A, "negative"),
            _claim("c2", "d2", "s2", _TEXT_B, "positive"),
        ],
        judged_pairs=[Pair(pair_id="p1", claim_a_id="c1", claim_b_id="c2")],
        verdicts=[
            Verdict(
                pair_id="p1",
                is_contradiction=with_contradiction,
                contradiction_type=ContradictionType.DIRECT_NEGATION,
                confidence=0.95,
                rationale="They cannot both hold.",
                evidence_a=_TEXT_A,
                evidence_b=_TEXT_B,
            )
        ],
        stats=AuditStats(document_count=2, claim_count=2, nli_kept_count=1),
        cost=CostSummary(total_usd=0.02, call_count=3),
        partial=partial,
        partial_reason="audit cost ceiling reached while judging" if partial else None,
    )


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    path = tmp_path / "corpus"
    path.mkdir()
    (path / "a.txt").write_text("text", encoding="utf-8")
    return path


def _stub(monkeypatch: pytest.MonkeyPatch, result: AuditResult) -> dict[str, object]:
    """Replace orchestrator.audit with a stub, capturing the kwargs it was called with."""
    seen: dict[str, object] = {}

    def fake_audit(corpus: Path, settings: object, **kwargs: object) -> AuditResult:
        seen["corpus"] = corpus
        seen["settings"] = settings
        seen.update(kwargs)
        return result

    monkeypatch.setattr(orchestrator, "audit", fake_audit)
    return seen


def test_version_flag() -> None:
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert "crosscheck" in result.stdout


def test_audit_reports_findings(monkeypatch: pytest.MonkeyPatch, corpus: Path) -> None:
    _stub(monkeypatch, _result())
    result = runner.invoke(cli.app, ["audit", str(corpus)])
    assert result.exit_code == 0
    assert "Found 1 contradiction" in result.stdout


def test_audit_reports_the_empty_state(monkeypatch: pytest.MonkeyPatch, corpus: Path) -> None:
    _stub(monkeypatch, _result(with_contradiction=False))
    result = runner.invoke(cli.app, ["audit", str(corpus)])
    assert result.exit_code == 0
    assert "No contradictions detected" in result.stdout


def test_missing_corpus_exits_nonzero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def raise_missing(corpus: Path, settings: object, **kwargs: object) -> AuditResult:
        raise FileNotFoundError(corpus)

    monkeypatch.setattr(orchestrator, "audit", raise_missing)
    result = runner.invoke(cli.app, ["audit", str(tmp_path / "nope")])
    assert result.exit_code == 1


def test_llm_error_exits_nonzero(monkeypatch: pytest.MonkeyPatch, corpus: Path) -> None:
    def raise_llm(corpus: Path, settings: object, **kwargs: object) -> AuditResult:
        raise LLMError("no API key configured")

    monkeypatch.setattr(orchestrator, "audit", raise_llm)
    result = runner.invoke(cli.app, ["audit", str(corpus)])
    assert result.exit_code == 1


def test_max_cost_overrides_the_ceiling(monkeypatch: pytest.MonkeyPatch, corpus: Path) -> None:
    seen = _stub(monkeypatch, _result())
    runner.invoke(cli.app, ["audit", str(corpus), "--max-cost", "2.50"])
    settings = seen["settings"]
    assert isinstance(settings, Settings)
    assert settings.max_audit_cost_usd == 2.50


def test_reset_store_flag_is_forwarded(monkeypatch: pytest.MonkeyPatch, corpus: Path) -> None:
    seen = _stub(monkeypatch, _result())
    runner.invoke(cli.app, ["audit", str(corpus), "--reset-store"])
    assert seen["reset_store"] is True


# --- exports -----------------------------------------------------------------------------


def test_output_writes_the_raw_audit_result(
    monkeypatch: pytest.MonkeyPatch, corpus: Path, tmp_path: Path
) -> None:
    _stub(monkeypatch, _result())
    path = tmp_path / "nested" / "audit.json"
    runner.invoke(cli.app, ["audit", str(corpus), "-o", str(path)])

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["audit_id"] == "aid"
    assert len(payload["verdicts"]) == 1
    assert "documents" in payload


def test_report_flag_writes_grouped_json(
    monkeypatch: pytest.MonkeyPatch, corpus: Path, tmp_path: Path
) -> None:
    _stub(monkeypatch, _result())
    path = tmp_path / "report.json"
    runner.invoke(cli.app, ["audit", str(corpus), "--report", str(path)])

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["contradiction_count"] == 1
    assert payload["groups"][0]["doc_a"] == "handbook.md"
    # A CLI run stamps a real time, unlike a snapshot build.
    assert payload["generated_at"] is not None


def test_html_flag_writes_a_standalone_page(
    monkeypatch: pytest.MonkeyPatch, corpus: Path, tmp_path: Path
) -> None:
    _stub(monkeypatch, _result())
    path = tmp_path / "report.html"
    runner.invoke(cli.app, ["audit", str(corpus), "--html", str(path)])

    page = path.read_text(encoding="utf-8")
    assert page.startswith("<!DOCTYPE html>")
    assert "handbook.md" in page
    assert "<style>" in page


def test_no_export_flags_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, corpus: Path, tmp_path: Path
) -> None:
    _stub(monkeypatch, _result())
    runner.invoke(cli.app, ["audit", str(corpus)])
    assert list(tmp_path.glob("*.json")) == []
    assert list(tmp_path.glob("*.html")) == []


def test_partial_audit_is_flagged_on_stderr(monkeypatch: pytest.MonkeyPatch, corpus: Path) -> None:
    _stub(monkeypatch, _result(partial=True))
    result = runner.invoke(cli.app, ["audit", str(corpus)])
    assert result.exit_code == 0  # a ceiling stop is a degraded success, not a failure
    assert "PARTIAL" in result.output


def test_eval_rejects_suite_together_with_positional_arguments(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        ["eval", str(tmp_path / "g.json"), str(tmp_path / "r.json"), "--suite", str(tmp_path)],
    )
    assert result.exit_code == 2
    assert "not both" in result.output


def test_eval_requires_a_benchmark() -> None:
    result = runner.invoke(cli.app, ["eval"])
    assert result.exit_code == 2
    assert "--suite" in result.output


def test_eval_reports_an_unusable_suite_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "suite.json"
    manifest.write_text(json.dumps({"benchmarks": []}), encoding="utf-8")
    result = runner.invoke(cli.app, ["eval", "--suite", str(manifest)])
    assert result.exit_code == 1
    assert "invalid suite manifest" in result.output


def _stub_warm(monkeypatch: pytest.MonkeyPatch, results: list[WarmupResult]) -> None:
    """Replace the warm-up so no model is loaded; `test_warmup.py` covers the stage itself."""
    monkeypatch.setattr(cli, "build_probes", lambda settings: [])
    monkeypatch.setattr(cli, "warm", lambda probes: results)


def test_warm_models_reports_each_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_warm(
        monkeypatch,
        [
            WarmupResult(stage="dense embedding", model_name="bge-large", seconds=12.5),
            WarmupResult(stage="reranking", model_name="bge-reranker", seconds=30.0),
        ],
    )
    result = runner.invoke(cli.app, ["warm-models"])
    assert result.exit_code == 0
    assert "bge-large" in result.output
    assert "All 2 model(s) cached and loadable." in result.output


def test_warm_models_exits_nonzero_when_a_model_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """The container gates the API on this exit code, so a failure must not exit 0."""
    _stub_warm(
        monkeypatch,
        [
            WarmupResult(stage="dense embedding", model_name="bge-large", seconds=1.0),
            WarmupResult(
                stage="NLI filtering",
                model_name="nli-deberta",
                seconds=0.2,
                error="OSError: connection reset",
            ),
        ],
    )
    result = runner.invoke(cli.app, ["warm-models"])
    assert result.exit_code == 1
    assert "1 of 2 model(s) failed to load: nli-deberta" in result.output
