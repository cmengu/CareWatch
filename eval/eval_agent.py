"""
eval_agent.py
=============
Runs 20 scenarios against CareWatchAgent. Reports F1, FNR, latency.

USAGE (from project root):
  python eval/eval_agent.py --no-llm    # ~30s — confirms detector logic only
  python eval/eval_agent.py             # ~15-60 min — full pipeline with Groq
  python eval/eval_agent.py --scenario TC001
  # Or: python -m eval.eval_agent --no-llm

Positive class for metrics = expected_level RED.
FNR = 0.000 is the safety target — a missed fall is worse than a false alarm.
"""

import sys
from pathlib import Path

# Ensure project root is on path when run as script (e.g. python eval/eval_agent.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import json
import logging
import time
from datetime import datetime

logging.basicConfig(level=logging.WARNING, format="%(name)s — %(message)s")
logger = logging.getLogger("eval_agent")

from eval.eval_helpers import (
    EvalScenario,
    EvalResult,
    TEST_DB_PATH,
    init_test_db,
    setup_scenario,
    teardown_scenario,
)
from eval.scenarios import ALL_SCENARIOS

EVAL_CURRENT_HOUR = 23.0  # pins clock so all deadlines are past
EVAL_TODAY = "2026-03-08"  # matches REF_DATE — today_logs returns seeded rows


def run_scenario(scenario: EvalScenario, agent, no_llm: bool = False) -> EvalResult:
    setup_scenario(scenario)

    # Reset CUSUM in-memory state — prevents accumulation across scenarios
    if hasattr(agent, "cusum_monitor") and hasattr(agent.cusum_monitor, "_detectors"):
        agent.cusum_monitor._detectors.clear()

    pid = (
        scenario.active_alert["person_id"]
        if scenario.active_alert
        else scenario.activity_rows[0]["person_id"]
        if scenario.activity_rows
        else f"eval_{scenario.scenario_id.lower()}"
    )

    current_hour = getattr(scenario, "_current_hour", None) or EVAL_CURRENT_HOUR
    today = getattr(scenario, "_today", EVAL_TODAY)

    t0 = time.perf_counter() * 1000
    try:
        if no_llm and hasattr(agent, "detector"):
            risk = agent.detector.check(
                pid, _current_hour=current_hour, _today=today
            )
            latency_ms = time.perf_counter() * 1000 - t0
            actual_level = risk.risk_level
            actual_concern = "skipped"
            rag_used, confidence, error = False, "high", None
        else:
            result = agent.run(
                pid,
                send_alert=False,
                _current_hour=current_hour,
                _today=today,
            )
            latency_ms = time.perf_counter() * 1000 - t0
            actual_level = result.risk_level
            actual_concern = (
                result.ai_explanation.concern_level
                if result.ai_explanation
                else "unknown"
            )
            rag_used = result.rag_context_used
            confidence = result.confidence
            error = getattr(result, "error", None)
    except Exception as e:
        latency_ms = time.perf_counter() * 1000 - t0
        actual_level = "ERROR"
        actual_concern = "unknown"
        rag_used, confidence, error = False, "low", str(e)

    teardown_scenario(scenario)

    level_match = actual_level == scenario.expected_level
    concern_match = actual_concern == scenario.expected_concern
    if no_llm:
        passed = level_match
    elif scenario.tolerance == "EXACT":
        passed = level_match and concern_match
    else:
        passed = level_match

    return EvalResult(
        scenario_id=scenario.scenario_id,
        expected_level=scenario.expected_level,
        actual_level=actual_level,
        expected_concern=scenario.expected_concern,
        actual_concern=actual_concern,
        tolerance=scenario.tolerance,
        level_match=level_match,
        concern_match=concern_match,
        passed=passed,
        latency_ms=round(latency_ms, 1),
        rag_used=rag_used,
        confidence=confidence,
        error=error,
    )


def compute_metrics(results: list) -> dict:
    """Binary classification: positive class = RED."""
    TP = sum(1 for r in results if r.expected_level == "RED" and r.actual_level == "RED")
    FN = sum(1 for r in results if r.expected_level == "RED" and r.actual_level != "RED")
    FP = sum(1 for r in results if r.expected_level != "RED" and r.actual_level == "RED")
    TN = sum(
        1
        for r in results
        if r.expected_level != "RED" and r.actual_level != "RED"
    )

    prec = TP / (TP + FP) if (TP + FP) > 0 else 0.0
    rec = TP / (TP + FN) if (TP + FN) > 0 else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    fnr = FN / (FN + TP) if (FN + TP) > 0 else 0.0
    fpr = FP / (FP + TN) if (FP + TN) > 0 else 0.0

    lats = sorted(r.latency_ms for r in results if not r.error)
    n = len(lats)
    return {
        "TP": TP,
        "FN": FN,
        "FP": FP,
        "TN": TN,
        "precision": round(prec, 3),
        "recall": round(rec, 3),
        "f1": round(f1, 3),
        "fnr": round(fnr, 3),
        "fpr": round(fpr, 3),
        "p50_ms": round(lats[int(n * 0.50)], 1) if n else 0,
        "p95_ms": round(lats[int(n * 0.95)], 1) if n else 0,
        "p99_ms": round(lats[min(int(n * 0.99), n - 1)], 1) if n else 0,
        "llm_alignment_rate": (
            round(sum(1 for r in results if r.concern_match) / len(results), 3)
            if results
            else 0
        ),
        "overall_pass_rate": (
            round(sum(1 for r in results if r.passed) / len(results), 3) if results else 0
        ),
        "total_scenarios": len(results),
        "errors": sum(1 for r in results if r.error),
    }


def print_results(results, metrics):
    print()
    print("=" * 92)
    print("  CareWatch Eval — Agent Results")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  |  {len(results)} scenarios")
    print("=" * 92)
    print(
        f"  {'ID':<8} {'Cat':<14} {'Exp':<8} {'Got':<8} {'Tol':<12} {'Pass':<6} {'ms':>7}  {'Error'}"
    )
    print("-" * 92)
    for r in results:
        status = "✅" if r.passed else "❌"
        err = (r.error or "")[:30]
        cat = next(
            (s.category for s in ALL_SCENARIOS if s.scenario_id == r.scenario_id),
            "?",
        )
        print(
            f"  {r.scenario_id:<8} {cat:<14} {r.expected_level:<8} {r.actual_level:<8} "
            f"{r.tolerance:<12} {status:<6} {r.latency_ms:>7.0f}  {err}"
        )
    print("=" * 92)
    print()
    print("  METRICS")
    print(
        f"  F1:              {metrics['f1']:.3f}   "
        f"(precision={metrics['precision']:.3f}  recall={metrics['recall']:.3f})"
    )
    print(
        f"  FNR (miss rate): {metrics['fnr']:.3f}   "
        "← TARGET 0.000 — missed fall = safety failure"
    )
    print(f"  FPR (false pos): {metrics['fpr']:.3f}")
    print(f"  LLM alignment:   {metrics['llm_alignment_rate']:.1%}")
    print(
        f"  Pass rate:       {metrics['overall_pass_rate']:.1%}  "
        f"({sum(1 for r in results if r.passed)}/{len(results)})"
    )
    print(
        f"  Latency p50/p95/p99:  {metrics['p50_ms']:.0f}ms / "
        f"{metrics['p95_ms']:.0f}ms / {metrics['p99_ms']:.0f}ms"
    )
    print(f"  Errors: {metrics['errors']}")
    print("=" * 92)
    print()
    if metrics["fnr"] == 0.0:
        print("  ★ FNR = 0.000 — no falls or active alerts were missed.")
    if metrics["errors"]:
        print(f"  ⚠  {metrics['errors']} error(s) — check results JSON.")
    print()


def save_results(results, metrics) -> Path:
    out = Path("eval/results")
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"eval_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(
        json.dumps(
            {
                "run_at": datetime.now().isoformat(),
                "eval_today": EVAL_TODAY,
                "eval_current_hour": EVAL_CURRENT_HOUR,
                "metrics": metrics,
                "results": [vars(r) for r in results],
            },
            indent=2,
        )
    )
    return path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", metavar="ID")
    p.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip Groq calls — test detector only (~30s total)",
    )
    args = p.parse_args()

    init_test_db()

    scenarios = ALL_SCENARIOS
    if args.scenario:
        scenarios = [
            s for s in ALL_SCENARIOS if s.scenario_id == args.scenario.upper()
        ]
        if not scenarios:
            print(f"Not found. Valid: {[s.scenario_id for s in ALL_SCENARIOS]}")
            return 1

    from src.agent import CareWatchAgent
    from src.orchestrator import CareWatchOrchestrator
    from src.langchain_agent import CareWatchLangChainAgent
    from src.deviation_detector import DeviationDetector
    from src.audit_logger import AuditLogger
    from src.suppression import AlertSuppressionLayer
    from src.alert_store import AlertStore
    from src.logger import ActivityLogger
    from src.baseline_builder import BaselineBuilder
    from src.cusum_monitor import ResidentCUSUMMonitor

    def _make_custom_agent():
        test_logger = ActivityLogger(db_path=TEST_DB_PATH)
        test_builder = BaselineBuilder(logger=test_logger)
        det = DeviationDetector(db_path=TEST_DB_PATH)
        cusum = ResidentCUSUMMonitor()
        audit = AuditLogger()
        agent = CareWatchAgent()
        agent.detector = det
        agent.cusum_monitor = cusum
        agent.alerts = AlertSuppressionLayer(db_path=TEST_DB_PATH)
        agent.audit = audit
        return agent

    AGENTS = [
        ("custom",    _make_custom_agent()),
        ("langgraph", CareWatchOrchestrator(db_path=TEST_DB_PATH)),
        ("langchain", CareWatchLangChainAgent(db_path=TEST_DB_PATH)),
    ]

    # Run each agent independently through all scenarios
    all_agent_results = {}
    comparison_rows = []

    for agent_name, agent in AGENTS:
        tp = tn = fp = fn_count = 0
        latencies = []
        llm_aligned = 0
        results = []

        total = len(scenarios)
        for i, sc in enumerate(scenarios, 1):
            print(
                f"  [{agent_name}] {sc.scenario_id} ({i}/{total}) {sc.description[:50]}...",
                end="\r",
            )
            results.append(run_scenario(sc, agent, no_llm=args.no_llm))

            result = results[-1]
            latencies.append(result.latency_ms)

            predicted = result.actual_level
            expected  = sc.expected_level

            if expected == "RED" and predicted == "RED":       tp += 1
            elif expected == "RED" and predicted != "RED":     fn_count += 1
            elif expected != "RED" and predicted == "RED":     fp += 1
            else:                                              tn += 1

            if sc.tolerance == "LEVEL_ONLY":
                llm_aligned += 1
            else:
                if result.concern_match:
                    llm_aligned += 1

        print(" " * 80, end="\r")

        n = len(scenarios)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall    = tp / (tp + fn_count) if (tp + fn_count) > 0 else 0.0
        f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        fnr       = fn_count / (fn_count + tp) if (fn_count + tp) > 0 else 0.0
        sorted_lats = sorted(latencies)
        p50       = sorted_lats[n // 2] if n else 0
        p95       = sorted_lats[int(n * 0.95)] if n else 0

        comparison_rows.append({
            "agent":         agent_name,
            "f1":            round(f1, 3),
            "fnr":           round(fnr, 3),
            "llm_alignment": round(llm_aligned / n, 3) if n else 0,
            "p50_ms":        round(p50),
            "p95_ms":        round(p95),
        })

        all_agent_results[agent_name] = results

        metrics = compute_metrics(results)
        print(f"\n  --- {agent_name} ---")
        print_results(results, metrics)
        out = save_results(results, metrics)
        print(f"  Results ({agent_name}): {out}")

    # Print comparison table
    print("\n=== Agent Comparison Table ===")
    print(f"{'Agent':<12} {'F1':>6} {'FNR':>6} {'LLM%':>6} {'p50ms':>7} {'p95ms':>7}")
    print("-" * 50)
    for row in comparison_rows:
        print(
            f"{row['agent']:<12} {row['f1']:>6.3f} {row['fnr']:>6.3f} "
            f"{row['llm_alignment']:>6.1%} {row['p50_ms']:>7} {row['p95_ms']:>7}"
        )

    # Safety check on custom agent (primary)
    custom_results = all_agent_results.get("custom", [])
    fn_fail = [
        r
        for r in custom_results
        if not r.passed
        and next(
            (s.category for s in ALL_SCENARIOS if s.scenario_id == r.scenario_id),
            "",
        )
        == "FN_RISK"
    ]
    if fn_fail:
        ids = [r.scenario_id for r in fn_fail]
        print(f"\n  ❌ SAFETY FAILURE: FN_RISK failed — {ids}")
        print("  These are missed falls or uncleared alerts. Fix before proceeding.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
