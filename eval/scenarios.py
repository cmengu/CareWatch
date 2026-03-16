"""
scenarios.py
============
20 deterministic eval scenarios.

Categories and counts:
  FN_RISK    (4) — must return RED — exit code 1 if failed
  TRUE_RED   (4) — should return RED
  TRUE_YELLOW (2) — should return YELLOW (pill-only MISSING = 40pts)
  TRUE_GREEN (5) — should return GREEN
  FP_RISK    (5) — must NOT over-alarm — all expected GREEN

All rows use REF_DATE = "2026-03-08".
Eval runner passes _today="2026-03-08" and _current_hour=23.0.
"""

from eval.eval_helpers import EvalScenario
from datetime import datetime, timedelta

REF_DATE = "2026-03-08"


def _row(person_id, hour, minute, activity, confidence, date=REF_DATE):
    return {
        "person_id": person_id,
        "timestamp": f"{date}T{hour:02d}:{minute:02d}:00",
        "date": date,
        "hour": hour,
        "minute": minute,
        "activity": activity,
        "confidence": confidence,
    }


def _alert(person_id, alert_type="FALLEN", days_ago=0):
    ts = (datetime(2026, 3, 8) - timedelta(days=days_ago)).isoformat()
    return {"person_id": person_id, "alert_type": alert_type, "triggered_at": ts}


# ── FN_RISK (4) — must return RED — exit code 1 if any fail ──────────────

TC001 = EvalScenario(
    scenario_id="TC001",
    description="Fall at exactly 0.851 confidence — minimum floor",
    category="FN_RISK",
    activity_rows=[
        _row("eval_tc001", 9, 0, "walking", 0.92),
        _row("eval_tc001", 10, 0, "fallen", 0.851),  # > 0.85 strict
    ],
    expected_level="RED",
    expected_concern="urgent",
    tolerance="LEVEL_ONLY",
    notes="DeviationDetector uses confidence > 0.85 (strict). 0.851 passes, 0.850 does not.",
)

TC002 = EvalScenario(
    scenario_id="TC002",
    description="Persistent alert 3 days old — must not expire",
    category="FN_RISK",
    activity_rows=[],
    active_alert=_alert("eval_tc002", days_ago=3),
    expected_level="RED",
    expected_concern="urgent",
    tolerance="LEVEL_ONLY",
    notes="AlertStore never expires. 3-day-old uncleared alert = RED immediately.",
)

TC003 = EvalScenario(
    scenario_id="TC003",
    description="Active alert + otherwise normal day — alert path dominates",
    category="FN_RISK",
    activity_rows=[
        _row("eval_tc003", 8, 0, "pill_taking", 0.91),
        _row("eval_tc003", 12, 0, "eating", 0.92),
        _row("eval_tc003", 9, 0, "walking", 0.90),
        _row("eval_tc003", 21, 0, "lying_down", 0.91),
    ],
    active_alert=_alert("eval_tc003", days_ago=1),
    expected_level="RED",
    expected_concern="urgent",
    tolerance="LEVEL_ONLY",
    notes="has_active_alert() fires before deviation check. Normal day does not clear RED.",
)

TC004 = EvalScenario(
    scenario_id="TC004",
    description="Alert from yesterday + new fall today — alert path dominates",
    category="FN_RISK",
    activity_rows=[
        _row("eval_tc004", 10, 0, "fallen", 0.88),
    ],
    active_alert=_alert("eval_tc004", days_ago=1),
    expected_level="RED",
    expected_concern="urgent",
    tolerance="LEVEL_ONLY",
    notes="has_active_alert() fires first. Fall row is irrelevant to outcome.",
)

# ── TRUE_RED (4) — should return RED ─────────────────────────────────────

TC005 = EvalScenario(
    scenario_id="TC005",
    description="Fresh uncleared alert — basic persistent RED path",
    category="TRUE_RED",
    activity_rows=[],
    active_alert=_alert("eval_tc005"),
    expected_level="RED",
    expected_concern="urgent",
    tolerance="LEVEL_ONLY",
    notes="score=100, summary=uncleared alert message.",
)

TC006 = EvalScenario(
    scenario_id="TC006",
    description="Pill + eating MISSING — compounding = 65 pts → RED",
    category="TRUE_RED",
    activity_rows=[
        _row("eval_tc006", 8, 0, "pill_taking", 0.91, date="2026-03-05"),
        _row("eval_tc006", 12, 0, "eating", 0.92, date="2026-03-05"),
        _row("eval_tc006", 8, 5, "pill_taking", 0.90, date="2026-03-06"),
        _row("eval_tc006", 12, 5, "eating", 0.91, date="2026-03-06"),
        _row("eval_tc006", 7, 55, "pill_taking", 0.92, date="2026-03-07"),
        _row("eval_tc006", 11, 55, "eating", 0.90, date="2026-03-07"),
        _row("eval_tc006", 9, 0, "walking", 0.90),
        _row("eval_tc006", 14, 0, "walking", 0.89),
    ],
    expected_level="RED",
    expected_concern="urgent",
    tolerance="LEVEL_ONLY",
    notes="pill(40) + eating(25) = 65 > 60 → RED. concern_level LLM-dependent.",
)

TC007 = EvalScenario(
    scenario_id="TC007",
    description="All activities MISSING today — complete inactivity = 85 pts → RED",
    category="TRUE_RED",
    activity_rows=[
        _row("eval_tc007", 8, 0, "pill_taking", 0.91, date="2026-03-05"),
        _row("eval_tc007", 12, 0, "eating", 0.92, date="2026-03-05"),
        _row("eval_tc007", 9, 0, "walking", 0.90, date="2026-03-05"),
        _row("eval_tc007", 8, 0, "pill_taking", 0.90, date="2026-03-06"),
        _row("eval_tc007", 12, 0, "eating", 0.91, date="2026-03-06"),
        _row("eval_tc007", 9, 0, "walking", 0.89, date="2026-03-06"),
        _row("eval_tc007", 8, 0, "pill_taking", 0.91, date="2026-03-07"),
        _row("eval_tc007", 12, 0, "eating", 0.90, date="2026-03-07"),
        _row("eval_tc007", 9, 0, "walking", 0.90, date="2026-03-07"),
    ],
    expected_level="RED",
    expected_concern="urgent",
    tolerance="LEVEL_ONLY",
    notes="pill(40) + eating(25) + walking(20) = 85 > 60 → RED. All three has ≥3 days history.",
)

TC008 = EvalScenario(
    scenario_id="TC008",
    description="Fall 0.90 confidence — well above floor",
    category="TRUE_RED",
    activity_rows=[
        _row("eval_tc008", 9, 0, "walking", 0.91),
        _row("eval_tc008", 10, 30, "fallen", 0.90),
    ],
    expected_level="RED",
    expected_concern="urgent",
    tolerance="LEVEL_ONLY",
    notes="Clean fall detection path — no active alert. 0.90 > 0.85.",
)

# ── TRUE_YELLOW (2) — should return YELLOW ────────────────────────────────

TC009 = EvalScenario(
    scenario_id="TC009",
    description="Pill MISSING only — 40 pts → YELLOW (not RED)",
    category="TRUE_YELLOW",
    activity_rows=[
        _row("eval_tc009", 8, 0, "pill_taking", 0.91, date="2026-03-05"),
        _row("eval_tc009", 8, 5, "pill_taking", 0.90, date="2026-03-06"),
        _row("eval_tc009", 7, 55, "pill_taking", 0.92, date="2026-03-07"),
        _row("eval_tc009", 9, 0, "walking", 0.90),
        _row("eval_tc009", 12, 0, "eating", 0.92),
        _row("eval_tc009", 21, 0, "lying_down", 0.91),
    ],
    expected_level="YELLOW",
    expected_concern="watch",
    tolerance="LEVEL_ONLY",
    notes="pill(40) only = 40 pts → 31-60 = YELLOW.",
)

TC010 = EvalScenario(
    scenario_id="TC010",
    description="Strong 5-day adherence + missed pill today — still YELLOW",
    category="TRUE_YELLOW",
    activity_rows=[
        _row("eval_tc010", 8, 0, "pill_taking", 0.91, date="2026-03-03"),
        _row("eval_tc010", 8, 0, "pill_taking", 0.90, date="2026-03-04"),
        _row("eval_tc010", 8, 0, "pill_taking", 0.92, date="2026-03-05"),
        _row("eval_tc010", 8, 0, "pill_taking", 0.91, date="2026-03-06"),
        _row("eval_tc010", 8, 0, "pill_taking", 0.90, date="2026-03-07"),
        _row("eval_tc010", 9, 0, "walking", 0.90),
        _row("eval_tc010", 12, 0, "eating", 0.92),
    ],
    expected_level="YELLOW",
    expected_concern="watch",
    tolerance="LEVEL_ONLY",
    notes="Strong occurs_daily=True. pill(40) = 40 → YELLOW.",
)

# ── TRUE_GREEN (5) — should return GREEN ─────────────────────────────────

TC011 = EvalScenario(
    scenario_id="TC011",
    description="Perfect routine — all activities present and on time",
    category="TRUE_GREEN",
    activity_rows=[
        _row("eval_tc011", 8, 0, "pill_taking", 0.92),
        _row("eval_tc011", 9, 0, "walking", 0.90),
        _row("eval_tc011", 10, 0, "sitting", 0.88),
        _row("eval_tc011", 12, 0, "eating", 0.93),
        _row("eval_tc011", 14, 0, "walking", 0.89),
        _row("eval_tc011", 21, 0, "lying_down", 0.91),
    ],
    expected_level="GREEN",
    expected_concern="normal",
    tolerance="LEVEL_ONLY",
    notes="0 anomalies → 0 pts → GREEN.",
)

TC012 = EvalScenario(
    scenario_id="TC012",
    description="Eating 25 minutes late — within 1 std dev (z=0.83 < 2.0)",
    category="TRUE_GREEN",
    activity_rows=[
        _row("eval_tc012", 8, 0, "pill_taking", 0.91),
        _row("eval_tc012", 9, 0, "walking", 0.90),
        _row("eval_tc012", 12, 25, "eating", 0.89),
        _row("eval_tc012", 14, 0, "walking", 0.88),
        _row("eval_tc012", 21, 0, "lying_down", 0.92),
    ],
    expected_level="GREEN",
    expected_concern="normal",
    tolerance="LEVEL_ONLY",
    notes="z < Z_THRESHOLD (2.0) → no TIMING anomaly → GREEN.",
)

TC013 = EvalScenario(
    scenario_id="TC013",
    description="New resident — 1 day of data, no baseline → returns GREEN (score=0)",
    category="TRUE_GREEN",
    activity_rows=[
        _row("eval_tc013", 8, 0, "pill_taking", 0.91),
        _row("eval_tc013", 12, 0, "eating", 0.92),
    ],
    expected_level="GREEN",
    expected_concern="normal",
    tolerance="LEVEL_ONLY",
    notes="1 day data → occurs_daily=False for all. No MISSING checks arm. score=0 → GREEN.",
)

TC014 = EvalScenario(
    scenario_id="TC014",
    description="Cleared alert — fall yesterday, cleared today, normal routine",
    category="TRUE_GREEN",
    activity_rows=[
        _row("eval_tc014", 8, 0, "pill_taking", 0.91),
        _row("eval_tc014", 12, 0, "eating", 0.92),
        _row("eval_tc014", 9, 0, "walking", 0.90),
        _row("eval_tc014", 21, 0, "lying_down", 0.91),
    ],
    active_alert=None,
    expected_level="GREEN",
    expected_concern="normal",
    tolerance="LEVEL_ONLY",
    notes="has_active_alert() returns None → normal deviation check runs → GREEN.",
)

TC015 = EvalScenario(
    scenario_id="TC015",
    description="Resident with naturally wide walking variance",
    category="TRUE_GREEN",
    activity_rows=[
        _row("eval_tc015", 8, 0, "pill_taking", 0.91),
        _row("eval_tc015", 7, 0, "walking", 0.90),
        _row("eval_tc015", 12, 0, "eating", 0.92),
        _row("eval_tc015", 17, 0, "walking", 0.88),
        _row("eval_tc015", 21, 0, "lying_down", 0.91),
        _row("eval_tc015", 7, 30, "walking", 0.89, date="2026-03-07"),
        _row("eval_tc015", 16, 0, "walking", 0.90, date="2026-03-07"),
        _row("eval_tc015", 8, 0, "walking", 0.91, date="2026-03-06"),
        _row("eval_tc015", 15, 0, "walking", 0.88, date="2026-03-06"),
    ],
    expected_level="GREEN",
    expected_concern="normal",
    tolerance="LEVEL_ONLY",
    notes="High std_hour → wide Z window → irregular walking within normal range.",
)

# ── FP_RISK (5) — must NOT over-alarm, all expected GREEN ─────────────────

TC016 = EvalScenario(
    scenario_id="TC016",
    description="Personalised late medication (9am not 7am)",
    category="FP_RISK",
    activity_rows=[
        _row("eval_tc016", 9, 0, "pill_taking", 0.91, date="2026-03-07"),
        _row("eval_tc016", 9, 5, "pill_taking", 0.90, date="2026-03-06"),
        _row("eval_tc016", 8, 55, "pill_taking", 0.92, date="2026-03-05"),
        _row("eval_tc016", 9, 0, "pill_taking", 0.89, date="2026-03-04"),
        _row("eval_tc016", 9, 0, "pill_taking", 0.91),
        _row("eval_tc016", 12, 0, "eating", 0.92),
    ],
    expected_level="GREEN",
    expected_concern="normal",
    tolerance="LEVEL_ONLY",
    notes="Personalised baseline mean_hour=9.0. Pill at 9am = on time.",
)

TC017 = EvalScenario(
    scenario_id="TC017",
    description="Night wandering — walking TIMING at 3am = 6 pts → GREEN",
    category="FP_RISK",
    activity_rows=[
        _row("eval_tc017", 11, 0, "walking", 0.90, date="2026-03-05"),
        _row("eval_tc017", 11, 0, "walking", 0.89, date="2026-03-06"),
        _row("eval_tc017", 11, 0, "walking", 0.91, date="2026-03-07"),
        _row("eval_tc017", 8, 0, "pill_taking", 0.90, date="2026-03-05"),
        _row("eval_tc017", 12, 0, "eating", 0.91, date="2026-03-05"),
        _row("eval_tc017", 8, 0, "pill_taking", 0.89, date="2026-03-06"),
        _row("eval_tc017", 12, 0, "eating", 0.92, date="2026-03-06"),
        _row("eval_tc017", 8, 0, "pill_taking", 0.91, date="2026-03-07"),
        _row("eval_tc017", 12, 0, "eating", 0.90, date="2026-03-07"),
        _row("eval_tc017", 8, 30, "pill_taking", 0.90),
        _row("eval_tc017", 12, 0, "eating", 0.91),
        _row("eval_tc017", 3, 15, "walking", 0.87),
    ],
    expected_level="GREEN",
    expected_concern="normal",
    tolerance="LEVEL_ONLY",
    notes="walking TIMING = 20 * 0.3 = 6 pts ≤ 30 → GREEN.",
)

TC018 = EvalScenario(
    scenario_id="TC018",
    description="All activities at wrong times — all TIMING = 25.5 pts → GREEN",
    category="FP_RISK",
    activity_rows=[
        _row("eval_tc018", 8, 0, "pill_taking", 0.91, date="2026-03-05"),
        _row("eval_tc018", 12, 0, "eating", 0.90, date="2026-03-05"),
        _row("eval_tc018", 11, 0, "walking", 0.89, date="2026-03-05"),
        _row("eval_tc018", 8, 0, "pill_taking", 0.90, date="2026-03-06"),
        _row("eval_tc018", 12, 0, "eating", 0.91, date="2026-03-06"),
        _row("eval_tc018", 11, 0, "walking", 0.88, date="2026-03-06"),
        _row("eval_tc018", 8, 0, "pill_taking", 0.92, date="2026-03-07"),
        _row("eval_tc018", 12, 0, "eating", 0.89, date="2026-03-07"),
        _row("eval_tc018", 11, 0, "walking", 0.90, date="2026-03-07"),
        _row("eval_tc018", 2, 0, "pill_taking", 0.91),
        _row("eval_tc018", 6, 0, "eating", 0.90),
        _row("eval_tc018", 20, 0, "walking", 0.89),
    ],
    expected_level="GREEN",
    expected_concern="normal",
    tolerance="LEVEL_ONLY",
    notes="All three TIMING = 12 + 7.5 + 6 = 25.5 ≤ 30 → GREEN.",
)

TC019 = EvalScenario(
    scenario_id="TC019",
    description="Walking MISSING only — 20 pts → GREEN",
    category="FP_RISK",
    activity_rows=[
        _row("eval_tc019", 9, 0, "walking", 0.90, date="2026-03-05"),
        _row("eval_tc019", 10, 0, "walking", 0.89, date="2026-03-06"),
        _row("eval_tc019", 9, 30, "walking", 0.91, date="2026-03-07"),
        _row("eval_tc019", 8, 0, "pill_taking", 0.91),
        _row("eval_tc019", 12, 0, "eating", 0.92),
        _row("eval_tc019", 10, 0, "sitting", 0.88),
        _row("eval_tc019", 21, 0, "lying_down", 0.91),
    ],
    expected_level="GREEN",
    expected_concern="normal",
    tolerance="LEVEL_ONLY",
    notes="walking MISSING = 20 pts ≤ 30 → GREEN.",
)

TC020 = EvalScenario(
    scenario_id="TC020",
    description="2 days data — insufficient baseline → GREEN (score=0)",
    category="FP_RISK",
    activity_rows=[
        _row("eval_tc020", 8, 0, "pill_taking", 0.91, date="2026-03-07"),
        _row("eval_tc020", 8, 0, "pill_taking", 0.90),
    ],
    expected_level="GREEN",
    expected_concern="normal",
    tolerance="LEVEL_ONLY",
    notes="len(hours) < 3 → occurs_daily=False → score=0 → GREEN.",
)

ALL_SCENARIOS = [
    TC001, TC002, TC003, TC004,
    TC005, TC006, TC007, TC008,
    TC009, TC010,
    TC011, TC012, TC013, TC014, TC015,
    TC016, TC017, TC018, TC019, TC020,
]
