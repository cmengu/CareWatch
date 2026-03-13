"""
evals.py
=========
Adversarial eval suite for CareWatch LLM reasoning.
Tests cases where risk_score, risk_level, and anomaly severity contradict
each other — the failure modes a naive LLM gets wrong.

USAGE:
    python -m src.evals

OUTPUT:
    One row per case. Final score: X/10.
    Exit code 0 always — evals are measurement, not a gate.

COST:
    10 explain_risk() calls + up to 10 self-check calls = ~20 Groq requests.
    Each run costs roughly 0.001 USD on free tier.
"""

import os
import sys

# Ensure src/ is importable when run as python -m src.evals
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.llm_explainer import explain_risk

# ── 10 adversarial test cases ──────────────────────────────────────────────
EVAL_CASES = [
    # 1. Clean green — must not over-alarm
    {
        "id": 1,
        "risk_score": 10,
        "risk_level": "GREEN",
        "anomalies": [],
        "expected": "normal",
        "note": "clean green — must not over-alarm",
    },
    # 2. UNKNOWN is not dangerous — no baseline is not a crisis
    {
        "id": 2,
        "risk_score": 0,
        "risk_level": "UNKNOWN",
        "anomalies": ["No baseline built yet — need 7 days of data"],
        "expected": "normal",
        "note": "unknown is not dangerous — no data ≠ bad data",
    },
    # 3. Score high, severity all LOW — resist the score
    {
        "id": 3,
        "risk_score": 75,
        "risk_level": "RED",
        "anomalies": [
            {"activity": "walking", "type": "TIMING", "message": "Walk at unusual time", "severity": "LOW"},
            {"activity": "sitting", "type": "TIMING", "message": "Sitting at unusual time", "severity": "LOW"},
            {"activity": "eating", "type": "TIMING", "message": "Eating at unusual time", "severity": "LOW"},
        ],
        "expected": "watch",
        "note": "high score but trivial deviations — timing drift is not a crisis",
    },
    # 4. Score low, pill missing — severity overrides score
    {
        "id": 4,
        "risk_score": 30,
        "risk_level": "GREEN",
        "anomalies": [
            {"activity": "pill_taking", "type": "MISSING", "message": "Medication not taken", "severity": "HIGH"},
        ],
        "expected": "urgent",
        "note": "pill missing overrides green score — medication is critical",
    },
    # 5. Fall detected — always urgent regardless of score
    {
        "id": 5,
        "risk_score": 25,
        "risk_level": "GREEN",
        "anomalies": [
            {"activity": "fallen", "type": "FALLEN", "message": "FALL DETECTED — immediate attention required", "severity": "HIGH"},
        ],
        "expected": "urgent",
        "note": "fall is always urgent regardless of score or level",
    },
    # 6. Score contradicts level — high score, GREEN level — trust score
    {
        "id": 6,
        "risk_score": 70,
        "risk_level": "GREEN",
        "anomalies": [],
        "expected": "watch",
        "note": "score says danger, level says fine — must not blindly trust level",
    },
    # 7. Level contradicts score — RED level, low score — trust score
    {
        "id": 7,
        "risk_score": 15,
        "risk_level": "RED",
        "anomalies": [],
        "expected": "normal",
        "note": "level says danger, score says fine — must not blindly trust level",
    },
    # 8. Critical issue buried in LOW severity noise — must not average
    {
        "id": 8,
        "risk_score": 50,
        "risk_level": "YELLOW",
        "anomalies": [
            {"activity": "pill_taking", "type": "MISSING", "message": "Medication not taken", "severity": "HIGH"},
            {"activity": "walking", "type": "TIMING", "message": "Walk at unusual time", "severity": "LOW"},
            {"activity": "sitting", "type": "TIMING", "message": "Sitting at unusual time", "severity": "LOW"},
            {"activity": "eating", "type": "TIMING", "message": "Eating at unusual time", "severity": "LOW"},
        ],
        "expected": "urgent",
        "note": "one HIGH issue must not get averaged away by LOW noise",
    },
    # 9. Very high score, all LOW severity — timing drift not a crisis
    {
        "id": 9,
        "risk_score": 90,
        "risk_level": "RED",
        "anomalies": [
            {"activity": "walking", "type": "TIMING", "message": "Walk at unusual time", "severity": "LOW"},
            {"activity": "eating", "type": "TIMING", "message": "Eating at unusual time", "severity": "LOW"},
            {"activity": "sitting", "type": "TIMING", "message": "Sitting at unusual time", "severity": "LOW"},
            {"activity": "lying_down", "type": "TIMING", "message": "Lying down at unusual time", "severity": "LOW"},
        ],
        "expected": "watch",
        "note": "very high score but zero HIGH severity — timing drift not a crisis",
    },
    # 10. UNKNOWN level with clear HIGH anomaly — must not hide behind UNKNOWN
    {
        "id": 10,
        "risk_score": 85,
        "risk_level": "UNKNOWN",
        "anomalies": [
            {"activity": "pill_taking", "type": "MISSING", "message": "Medication not taken", "severity": "HIGH"},
        ],
        "expected": "urgent",
        "note": "must not hide behind UNKNOWN when anomaly is clear",
    },
]

# ── Runner ─────────────────────────────────────────────────────────────────

PASS = "✅"
FAIL = "❌"
WIDTH = 60


def run_case(case: dict) -> dict:
    """Run one eval case. Returns result dict with pass/fail and actual value."""
    try:
        result = explain_risk(
            person_id="eval_resident",
            risk_score=case["risk_score"],
            risk_level=case["risk_level"],
            anomalies=case["anomalies"],
            rag_context="",
        )
        actual = result.get("concern_level", "ERROR")
        passed = actual == case["expected"]
        return {
            "id": case["id"],
            "passed": passed,
            "expected": case["expected"],
            "actual": actual,
            "note": case["note"],
        }
    except Exception as e:
        return {
            "id": case["id"],
            "passed": False,
            "expected": case["expected"],
            "actual": f"EXCEPTION: {e}",
            "note": case["note"],
        }


def main():
    if not os.environ.get("GROQ_API_KEY"):
        print("ERROR: GROQ_API_KEY not set — evals require a live LLM call")
        print("Set it with: export GROQ_API_KEY='gsk_...'")
        sys.exit(1)

    print()
    print("CareWatch Evals — LLM Reasoning Quality")
    print("=" * WIDTH)

    results = []
    for case in EVAL_CASES:
        r = run_case(case)
        results.append(r)
        icon = PASS if r["passed"] else FAIL
        status = f"expected={r['expected']:<8} got={r['actual']:<8}"
        print(f"  {icon} Case {r['id']:>2}  {status}  {r['note']}")

    passed = sum(1 for r in results if r["passed"])
    total = len(results)

    print("=" * WIDTH)
    print(f"  Score: {passed}/{total}")
    print()

    if passed == total:
        print("  All cases passed. LLM reasoning is consistent.")
    else:
        failed = [r for r in results if not r["passed"]]
        print("  Failed cases:")
        for r in failed:
            print(f"    Case {r['id']}: expected {r['expected']}, got {r['actual']}")
            print(f"    → {r['note']}")
    print()


if __name__ == "__main__":
    main()
