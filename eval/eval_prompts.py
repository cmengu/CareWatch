"""
eval_prompts.py
===============
Evaluates 5 prompt variants across 20 scenarios × 3 runs each.
Reports LLM alignment rate, latency, and FNR per variant.

RAG context is always injected. All variants receive identical RAG input —
comparison is prompt-style only.

Why 3 runs per scenario:
  LLM output is non-deterministic (temperature=0.3). A single run can be
  lucky or unlucky. Mean ± std across 3 runs gives a stable comparison.

Why FNR is reported per variant:
  A prompt that improves alignment but returns "normal" for a RED/HIGH scenario
  is worse than the baseline. Safety must not regress.

USAGE:
  python eval/eval_prompts.py                  # all 5 variants, 3 runs each
  python eval/eval_prompts.py --variant A1C1   # single variant
  python eval/eval_prompts.py --runs 1         # fast pass (1 run per scenario)

OUTPUT:
  Prints per-variant summary table.
  Writes full results to eval/results/prompt_eval_<timestamp>.json
"""

import sys
from pathlib import Path

# Ensure project root is on path when run as script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import json
import logging
import statistics
import time
from datetime import datetime

logging.basicConfig(level=logging.WARNING, format="%(name)s — %(message)s")
logger = logging.getLogger("eval_prompts")

from eval.eval_helpers import (
    EvalScenario,
    TEST_DB_PATH,
    init_test_db,
    setup_scenario,
    teardown_scenario,
)
from eval.scenarios import ALL_SCENARIOS
from src.prompt_registry import PromptVariant, load_variant, list_variants

EVAL_CURRENT_HOUR = 23.0
EVAL_TODAY = "2026-03-08"
DEFAULT_RUNS = 3


def run_variant_scenario(
    scenario: EvalScenario,
    agent,
    variant: PromptVariant,
    n_runs: int = DEFAULT_RUNS,
) -> dict:
    """
    Run one scenario with one variant n_runs times.
    Returns dict with: scenario_id, variant_id, runs (list), mean_concern_match,
    std_concern_match, mean_latency_ms, level_match, passed_safety.
    """
    setup_scenario(scenario)
    if hasattr(agent, "cusum_monitor") and hasattr(agent.cusum_monitor, "_detectors"):
        agent.cusum_monitor._detectors.clear()

    pid = (
        scenario.active_alert["person_id"]
        if scenario.active_alert
        else scenario.activity_rows[0]["person_id"]
        if scenario.activity_rows
        else f"eval_{scenario.scenario_id.lower()}"
    )

    runs = []
    for run_idx in range(n_runs):
        t0 = time.perf_counter() * 1000
        try:
            result = agent.run(
                pid,
                send_alert=False,
                _current_hour=EVAL_CURRENT_HOUR,
                _today=EVAL_TODAY,
                _variant=variant,
            )
            latency_ms = time.perf_counter() * 1000 - t0
            actual_level = result.risk_level
            actual_concern = (
                result.ai_explanation.concern_level
                if result.ai_explanation
                else "unknown"
            )
            error = getattr(result, "error", None)
        except Exception as e:
            latency_ms = time.perf_counter() * 1000 - t0
            actual_level = "ERROR"
            actual_concern = "unknown"
            error = str(e)

        level_match = actual_level == scenario.expected_level
        concern_match = actual_concern == scenario.expected_concern

        runs.append({
            "run": run_idx + 1,
            "actual_level": actual_level,
            "actual_concern": actual_concern,
            "level_match": level_match,
            "concern_match": concern_match,
            "latency_ms": round(latency_ms, 1),
            "error": error,
        })

    teardown_scenario(scenario)

    concern_matches = [r["concern_match"] for r in runs]
    latencies = [r["latency_ms"] for r in runs if not r["error"]]
    level_matches = [r["level_match"] for r in runs]

    # Safety: RED level must always match — if any run missed a RED, flag it
    passed_safety = all(level_matches) if scenario.expected_level == "RED" else True

    return {
        "scenario_id": scenario.scenario_id,
        "category": scenario.category,
        "variant_id": variant.variant_id,
        "expected_level": scenario.expected_level,
        "expected_concern": scenario.expected_concern,
        "runs": runs,
        "mean_concern_match": round(sum(concern_matches) / len(concern_matches), 3),
        "std_concern_match": round(
            statistics.stdev(concern_matches) if len(concern_matches) > 1 else 0.0,
            3,
        ),
        "mean_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
        "level_match_rate": round(sum(level_matches) / len(level_matches), 3),
        "passed_safety": passed_safety,
    }


def compute_variant_metrics(scenario_results: list[dict]) -> dict:
    """Aggregate per-scenario results into variant-level metrics."""
    concern_rates = [r["mean_concern_match"] for r in scenario_results]
    latencies = [r["mean_latency_ms"] for r in scenario_results]
    level_rates = [r["level_match_rate"] for r in scenario_results]

    # FNR for this variant: RED scenarios where level_match_rate < 1.0
    red_scenarios = [r for r in scenario_results if r["expected_level"] == "RED"]
    fn_count = sum(1 for r in red_scenarios if r["level_match_rate"] < 1.0)
    fnr = fn_count / len(red_scenarios) if red_scenarios else 0.0

    safety_failures = [
        r["scenario_id"] for r in scenario_results if not r["passed_safety"]
    ]

    # p50 = true median (handles even-length lists); p95 = index-based approximation
    sorted_lat = sorted(latencies)
    p95_idx = (
        min(int(len(latencies) * 0.95), len(latencies) - 1) if latencies else 0
    )

    return {
        "llm_alignment_rate": round(sum(concern_rates) / len(concern_rates), 3),
        "level_match_rate": round(sum(level_rates) / len(level_rates), 3),
        "fnr": round(fnr, 3),
        "p50_ms": round(statistics.median(latencies), 1) if latencies else 0,
        "p95_ms": round(sorted_lat[p95_idx], 1) if latencies else 0,
        "safety_failures": safety_failures,
        "total_scenarios": len(scenario_results),
    }


def print_comparison_table(all_variant_metrics: dict[str, dict]) -> None:
    """Print the variant comparison table — the interview artifact."""
    print()
    print("=" * 88)
    print("  CareWatch Eval — Prompt Variant Comparison")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 88)
    print(f"  {'Variant':<8} {'Description':<45} {'Align':<8} {'FNR':<7} {'p50ms':<8} {'Safety'}")
    print("-" * 88)

    from src.prompt_registry import _VARIANT_META

    for vid, metrics in all_variant_metrics.items():
        desc = _VARIANT_META[vid]["description"][:44]
        align = f"{metrics['llm_alignment_rate']:.1%}"
        fnr = f"{metrics['fnr']:.3f}"
        p50 = f"{metrics['p50_ms']:.0f}"
        safety = (
            "✅"
            if not metrics["safety_failures"]
            else f"❌ {metrics['safety_failures']}"
        )
        print(f"  {vid:<8} {desc:<45} {align:<8} {fnr:<7} {p50:<8} {safety}")

    print("=" * 88)
    print()
    print("  INTERPRETATION")
    best_align = max(
        all_variant_metrics,
        key=lambda v: all_variant_metrics[v]["llm_alignment_rate"],
    )
    fastest = min(all_variant_metrics, key=lambda v: all_variant_metrics[v]["p50_ms"])
    safe_variants = [
        v
        for v, m in all_variant_metrics.items()
        if not m["safety_failures"]
    ]
    print(
        f"  Best alignment:    {best_align} ({all_variant_metrics[best_align]['llm_alignment_rate']:.1%})"
    )
    print(
        f"  Fastest (p50):     {fastest} ({all_variant_metrics[fastest]['p50_ms']:.0f}ms)"
    )
    print(f"  Safe variants:     {safe_variants}")

    # Cost tradeoff: A1C3 (no self-check) vs A1C1 (separate self-check)
    if "A1C1" in all_variant_metrics and "A1C3" in all_variant_metrics:
        baseline_align = all_variant_metrics["A1C1"]["llm_alignment_rate"]
        no_check_align = all_variant_metrics["A1C3"]["llm_alignment_rate"]
        baseline_p50 = all_variant_metrics["A1C1"]["p50_ms"]
        no_check_p50 = all_variant_metrics["A1C3"]["p50_ms"]
        latency_saving = baseline_p50 - no_check_p50
        align_delta = no_check_align - baseline_align
        print()
        print("  SELF-CHECK COST/QUALITY TRADEOFF (A1C1 vs A1C3):")
        print(f"    Latency saved by removing self-check: {latency_saving:.0f}ms p50")
        print(f"    Alignment change without self-check:  {align_delta:+.1%}")
        if align_delta >= -0.05:
            print("    → Self-check adds latency with minimal alignment benefit")
        else:
            print("    → Self-check improves alignment by more than 5% — worth the cost")
    print()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--variant",
        metavar="ID",
        help=f"Single variant ID. Options: {list_variants()}",
    )
    p.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUNS,
        help=f"Runs per scenario (default: {DEFAULT_RUNS})",
    )
    args = p.parse_args()

    init_test_db()

    variant_ids = [args.variant] if args.variant else list_variants()
    for vid in variant_ids:
        if vid not in list_variants():
            print(f"Unknown variant '{vid}'. Valid: {list_variants()}")
            return 1

    # Build agent — same wiring as eval_agent.py
    from src.agent import CareWatchAgent
    from src.deviation_detector import DeviationDetector
    from src.audit_logger import AuditLogger
    from src.suppression import AlertSuppressionLayer
    from src.alert_store import AlertStore
    from src.logger import ActivityLogger
    from src.baseline_builder import BaselineBuilder
    from src.cusum_monitor import ResidentCUSUMMonitor

    test_logger = ActivityLogger(db_path=TEST_DB_PATH)
    test_builder = BaselineBuilder(logger=test_logger)

    try:
        test_detector = DeviationDetector(db_path=TEST_DB_PATH)
    except TypeError:
        test_detector = DeviationDetector()
        test_detector.logger = test_logger
        test_detector.builder = test_builder
        test_detector.alert_store = AlertStore(db_path=TEST_DB_PATH)

    try:
        agent_cusum = ResidentCUSUMMonitor(
            db_path=TEST_DB_PATH,
            baseline_builder=test_builder,
        )
    except TypeError:
        agent_cusum = ResidentCUSUMMonitor(db_path=TEST_DB_PATH)

    agent = CareWatchAgent()
    agent.detector = test_detector
    agent.cusum_monitor = agent_cusum
    agent.alerts = AlertSuppressionLayer(db_path=TEST_DB_PATH)
    agent.audit = AuditLogger(db_path=TEST_DB_PATH)

    all_results = {}
    all_metrics = {}

    for vid in variant_ids:
        variant = load_variant(vid)
        print(f"\n  Running variant {vid}: {variant.description}")
        print(
            f"  {len(ALL_SCENARIOS)} scenarios × {args.runs} runs = "
            f"{len(ALL_SCENARIOS) * args.runs} Groq calls"
        )

        variant_results = []
        for i, sc in enumerate(ALL_SCENARIOS, 1):
            print(f"  {sc.scenario_id} ({i}/{len(ALL_SCENARIOS)})...", end="\r")
            result = run_variant_scenario(sc, agent, variant, n_runs=args.runs)
            variant_results.append(result)

        print(" " * 60, end="\r")
        all_results[vid] = variant_results
        all_metrics[vid] = compute_variant_metrics(variant_results)

        if all_metrics[vid]["fnr"] > 0:
            print(
                f"\n  ❌ SAFETY FAILURE: variant {vid} has "
                f"FNR={all_metrics[vid]['fnr']:.3f}"
            )
            print(f"     Failed scenarios: {all_metrics[vid]['safety_failures']}")
            print("     Do not use this variant in production.")

    print_comparison_table(all_metrics)

    out_dir = Path("eval/results")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"prompt_eval_{ts}.json"
    out_path.write_text(
        json.dumps(
            {
                "run_at": datetime.now().isoformat(),
                "n_runs": args.runs,
                "variants": variant_ids,
                "metrics": all_metrics,
                "results": all_results,
            },
            indent=2,
        )
    )
    print(f"  Full results: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
