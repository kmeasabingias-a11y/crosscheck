"""§9.3 ablations on the hand-written benchmark. Run one arm at a time.

Must be run from the repo root: the audit id is a hash of the *resolved corpus path*, so this is
what lands on `.crosscheck/ba80362f7a824058/` and reuses the cached extraction rather than paying
to re-extract 173 claims.

The baseline arm exists to validate the harness: it must reproduce the published F1 of .578. If it
does not, no other arm's number means anything.

    uv run python scripts/ablate.py baseline
    uv run python scripts/ablate.py baseline 0.50    # override the arm's cost ceiling

Each arm writes three files under `../Crosscheck_Runs/ablations/`: the summary row `<arm>.json`,
the full metrics `<arm>_metrics.json`, and the full report `<arm>_report.json`. The latter two
exist because the first version of this script kept only `grouped.overall` and discarded the
lexical-overlap strata and the per-type counts — which are exactly what §9.3 asks the retrieval
ablation to be read on. Persisting the whole report also makes cross-arm questions (judge
agreement between two arms) answerable offline, without paying to run anything again.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from crosscheck.aggregation.report import build_report
from crosscheck.config import Settings, get_settings
from crosscheck.evaluation.gold import load_gold_set
from crosscheck.evaluation.metrics import BenchmarkMetrics, score_benchmark
from crosscheck.llm import LLMClient
from crosscheck.orchestrator import audit

CORPUS = Path("benchmarks/handwritten/corpus")
GOLD = Path("benchmarks/handwritten/gold.json")
OUT = Path("../Crosscheck_Runs/ablations")

HAIKU = "claude-haiku-4-5"
SONNET = "claude-sonnet-4-6"

ARMS: dict[str, tuple[dict[str, object], float]] = {
    # name: (settings overrides, cost ceiling for this arm)
    "baseline": ({"judge_model": HAIKU}, 1.00),
    "dense_only": ({"judge_model": HAIKU, "retrieval_strategy": "dense"}, 2.50),
    "judge_sonnet": ({"judge_model": SONNET}, 6.00),
    "nli_off": ({"judge_model": HAIKU, "nli_default_threshold": 0.0}, 4.50),
}


def metrics_fields(metrics: BenchmarkMetrics) -> dict[str, Any]:
    """Flatten the parts of a BenchmarkMetrics an arm is compared on.

    Kept separate from the audit so it can be exercised offline against a committed report,
    which is how the `by_type` field name was caught before it reached a paid run.
    """
    grouped = metrics.grouped
    overall = grouped.overall
    row: dict[str, Any] = {
        "precision": round(overall.precision, 4),
        "recall": round(overall.recall, 4),
        "f1": round(overall.f1, 4),
        "tp": overall.true_positives,
        "fp": overall.false_positives,
        "fn": overall.false_negatives,
    }
    for stratum in grouped.strata:
        counts = stratum.counts
        row[stratum.name] = {
            "threshold": stratum.threshold,
            "precision": round(counts.precision, 4),
            "recall": round(counts.recall, 4),
            "f1": round(counts.f1, 4),
            "tp": counts.true_positives,
            "fp": counts.false_positives,
            "fn": counts.false_negatives,
        }
    row["by_type"] = {
        name: {
            "precision": round(counts.precision, 4),
            "recall": round(counts.recall, 4),
            "f1": round(counts.f1, 4),
            "tp": counts.true_positives,
            "fp": counts.false_positives,
            "fn": counts.false_negatives,
        }
        for name, counts in sorted(grouped.by_type.items())
    }
    row["type_agreement"] = round(grouped.type_agreement, 4)
    row["median_gold_overlap"] = metrics.median_gold_overlap
    row["hallucination_rate"] = round(metrics.hallucination_rate, 4)
    return row


def main(arm: str, ceiling_override: float | None = None) -> None:
    """Run one ablation arm and write its row, metrics and report.

    Args:
        arm: Key into ``ARMS``.
        ceiling_override: Cost ceiling to use instead of the arm's default. Re-runs are
            served almost entirely from the verdict cache, so they are given a low ceiling:
            if drift makes one unexpectedly expensive, it should stop rather than quietly
            re-judge the whole corpus.
    """
    overrides, ceiling = ARMS[arm]
    if ceiling_override is not None:
        ceiling = ceiling_override
    base = get_settings()
    settings = Settings(**{**base.model_dump(), **overrides, "max_audit_cost_usd": ceiling})
    print(f"=== {arm} ===")
    print(
        f"  judge={settings.judge_model} retrieval={settings.retrieval_strategy} "
        f"nli>={settings.nli_default_threshold} ceiling=${ceiling:.2f}",
        flush=True,
    )

    llm = LLMClient(settings, cost_ceiling_usd=ceiling)
    result = audit(CORPUS, settings, llm=llm, reset_store=True)
    report = build_report(result)
    metrics = score_benchmark(report, load_gold_set(GOLD))

    row: dict[str, Any] = {
        "arm": arm,
        "judge_model": settings.judge_model,
        "retrieval": settings.retrieval_strategy,
        "nli_threshold": settings.nli_default_threshold,
        "claims": result.stats.claim_count,
        "candidates": result.stats.candidate_pair_count,
        "reranked": result.stats.reranked_pair_count,
        "judged": result.stats.nli_kept_count,
        "judge_llm_calls": result.stats.judge_llm_calls,
        "judge_cache_hits": result.stats.judge_cache_hits,
        "findings": report.contradiction_count,
    }
    row.update(metrics_fields(metrics))
    row["cost_usd"] = round(result.cost.total_usd, 4)
    row["partial"] = result.partial

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{arm}.json").write_text(json.dumps(row, indent=2))
    (OUT / f"{arm}_metrics.json").write_text(metrics.model_dump_json(indent=2))
    (OUT / f"{arm}_report.json").write_text(report.model_dump_json(indent=2))
    print(json.dumps(row, indent=2), flush=True)
    if result.partial:
        print("  !! stopped at the cost ceiling — numbers are partial", flush=True)


if __name__ == "__main__":
    arm_name = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    override = float(sys.argv[2]) if len(sys.argv) > 2 else None
    main(arm_name, override)
