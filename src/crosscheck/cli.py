"""CrossCheck command-line interface (Typer)."""

from pathlib import Path
from typing import Annotated

import typer
from loguru import logger

from crosscheck import __version__, orchestrator
from crosscheck.config import get_settings
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
