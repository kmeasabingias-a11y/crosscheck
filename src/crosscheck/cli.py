"""CrossCheck command-line interface (Typer)."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from loguru import logger

from crosscheck import __version__, orchestrator
from crosscheck.aggregation.html_renderer import write_html
from crosscheck.aggregation.report import build_report, write_json
from crosscheck.config import get_settings
from crosscheck.evaluation.metrics import DEFAULT_OVERLAP_THRESHOLD
from crosscheck.evaluation.runner import BenchmarkSpec, evaluate, load_suite, write_run
from crosscheck.llm import LLMError
from crosscheck.logging_config import configure_logging

app = typer.Typer(
    name="crosscheck",
    help="Cross-document contradiction detection.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    """Print the version and exit when ``--version`` is given."""
    if value:
        typer.echo(f"crosscheck {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Audit a corpus for cross-document contradictions."""
    configure_logging(get_settings())


@app.command()
def audit(
    corpus: Annotated[Path, typer.Argument(help="Corpus directory (or single file) to audit.")],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the full audit result as JSON to this path."),
    ] = None,
    max_cost: Annotated[
        float | None,
        typer.Option("--max-cost", help="Override the audit cost ceiling, in USD."),
    ] = None,
    report: Annotated[
        Path | None,
        typer.Option("--report", help="Write the grouped contradiction report as JSON here."),
    ] = None,
    html: Annotated[
        Path | None,
        typer.Option("--html", help="Write the human-readable HTML report here."),
    ] = None,
    reset_store: Annotated[
        bool,
        typer.Option(
            "--reset-store",
            help="Drop and rebuild the claim collection first. Destroys claims from earlier "
            "audits (and any resume that depended on them).",
        ),
    ] = False,
) -> None:
    """Audit a corpus for cross-document contradictions.

    Needs a running Qdrant (docker compose up -d qdrant) and an ANTHROPIC_API_KEY.
    Re-running the same corpus resumes: cached claim extractions and verdicts are
    reused, so an interrupted audit never re-spends tokens on work already paid for.
    """
    settings = get_settings()
    if max_cost is not None:
        settings = settings.model_copy(update={"max_audit_cost_usd": max_cost})
    try:
        result = orchestrator.audit(corpus, settings, reset_store=reset_store)
    except FileNotFoundError:
        typer.secho(f"corpus not found: {corpus}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None
    except LLMError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        logger.info("wrote audit result to {}", output)

    if report is not None or html is not None:
        # A real timestamp is right for a CLI run; build_report defaults it to None so the
        # regression snapshot over a frozen fixture stays byte-stable (D35).
        built = build_report(result, generated_at=datetime.now(UTC))
        if report is not None:
            write_json(built, report)
            logger.info("wrote contradiction report to {}", report)
        if html is not None:
            write_html(built, html)
            logger.info("wrote HTML report to {}", html)

    _summarize(result)


def _summarize(result: "orchestrator.AuditResult") -> None:
    """Print the human-facing summary, including the designed empty state (spec §7.5)."""
    stats = result.stats
    contradictions = result.contradictions
    if contradictions:
        typer.secho(
            f"Found {len(contradictions)} contradiction(s) across {stats.document_count} "
            f"document(s) / {stats.nli_kept_count} claim pair(s) evaluated.",
            fg=typer.colors.YELLOW,
        )
        for verdict in contradictions:
            label = verdict.contradiction_type.value if verdict.contradiction_type else "UNCLEAR"
            typer.echo(f"  [{label}] confidence {verdict.confidence:.2f} — {verdict.rationale}")
    else:
        typer.secho(
            f"No contradictions detected across {stats.document_count} document(s) / "
            f"{stats.nli_kept_count} claim pair(s) evaluated.",
            fg=typer.colors.GREEN,
        )
    typer.echo(
        f"{stats.claim_count} claim(s) · {stats.candidate_pair_count} candidate pair(s) · "
        f"cost ${result.cost.total_usd:.4f} over {result.cost.call_count} LLM call(s)"
    )
    if result.partial:
        typer.secho(f"Audit is PARTIAL: {result.partial_reason}", fg=typer.colors.RED, err=True)


@app.command()
def eval(  # noqa: A001 - `eval` is the natural command name; it shadows the builtin only here
    gold: Annotated[Path | None, typer.Argument(help="Gold-label JSON for the benchmark.")] = None,
    report: Annotated[
        Path | None, typer.Argument(help="Contradiction report JSON to score.")
    ] = None,
    suite: Annotated[
        Path | None,
        typer.Option(
            "--suite",
            help="Suite manifest listing several benchmarks to score into one report. "
            "Use instead of the GOLD and REPORT arguments.",
        ),
    ] = None,
    name: Annotated[
        str, typer.Option("--name", help="Label for this benchmark in the report.")
    ] = "benchmark",
    out: Annotated[
        Path, typer.Option("--out", help="Results root; a timestamped subdirectory is created.")
    ] = Path("benchmarks/results"),
    overlap_threshold: Annotated[
        float, typer.Option("--overlap-threshold", help="Lexical-overlap cut for the strata.")
    ] = DEFAULT_OVERLAP_THRESHOLD,
) -> None:
    """Score contradiction reports against their gold sets and write an evaluation report.

    Scoring is free and instant - it reads a report `crosscheck audit` already produced
    rather than re-running the pipeline, so iterating on the numbers costs nothing.

    Pass one benchmark as GOLD and REPORT, or several with --suite. Several is the
    interesting case: the synthetic and hand-written sets belong in one document, because
    the gap between them is the result.
    """
    if suite is not None and (gold is not None or report is not None):
        typer.secho(
            "pass either --suite or the GOLD and REPORT arguments, not both",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    if suite is None and (gold is None or report is None):
        typer.secho(
            "give a benchmark to score: GOLD and REPORT, or --suite MANIFEST",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    try:
        specs = (
            load_suite(suite)
            if suite is not None
            # Narrowed by the guards above; mypy cannot see it through the Optionals.
            else [BenchmarkSpec(name=name, gold_path=gold, report_path=report)]  # type: ignore[arg-type]
        )
        run = evaluate(
            specs,
            get_settings(),
            overlap_threshold=overlap_threshold,
            generated_at=datetime.now(UTC),
        )
    except FileNotFoundError as exc:
        typer.secho(f"not found: {exc.filename}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None
    except ValueError as exc:
        typer.secho(f"invalid suite manifest: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None

    destination = write_run(run, out)
    for result in run.benchmarks:
        scored = result.metrics.grouped.overall
        typer.echo(
            f"{result.name}: precision {scored.precision:.3f} - recall {scored.recall:.3f} - "
            f"F1 {scored.f1:.3f}"
        )
        for warning in result.warnings:
            typer.secho(f"warning: [{result.name}] {warning}", fg=typer.colors.YELLOW, err=True)
    typer.echo(f"wrote {destination}")
