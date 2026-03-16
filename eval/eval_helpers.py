"""
eval_helpers.py
===============
Eval infrastructure for CareWatch. TEST_DB_PATH is isolated from data/carewatch.db.

Why a separate test DB:
  DeviationDetector needs a baselines table to know each resident's normal routine.
  It needs an activity_log to read today's activity.
  It needs active_alerts for the persistent alert path.
  The eval seeds all of these into a test DB so scenarios are isolated and
  data/carewatch.db (with 1000 residents and resident_0042's live alert) is never touched.

Why baselines must be seeded:
  Without a baseline, DeviationDetector.load_baseline() returns None → UNKNOWN for every
  scenario. BaselineBuilder.build_baseline() reads the seeded activity_rows and computes
  mean_hour, std_hour, occurs_daily per activity — exactly like production but from 3-7
  synthetic rows instead of 7 days of camera footage.
"""

import sqlite3
import json
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

TEST_DB_PATH = "data/carewatch_test.db"


@dataclass
class EvalScenario:
    scenario_id: str
    description: str
    category: str  # TRUE_RED | TRUE_YELLOW | TRUE_GREEN | FP_RISK | FN_RISK
    activity_rows: list  # dicts seeded into activity_log
    expected_level: str  # GREEN | YELLOW | RED
    expected_concern: str  # normal | watch | urgent
    tolerance: str  # EXACT | LEVEL_ONLY
    active_alert: Optional[dict] = None
    notes: str = ""
    _current_hour: Optional[float] = 23.0
    _today: str = "2026-03-08"


@dataclass
class EvalResult:
    scenario_id: str
    expected_level: str
    actual_level: str
    expected_concern: str
    actual_concern: str
    tolerance: str
    level_match: bool
    concern_match: bool
    passed: bool
    latency_ms: float
    rag_used: bool
    confidence: str
    error: Optional[str] = None


def init_test_db() -> None:
    """
    Create all required tables in test DB. Idempotent — safe to call multiple times.
    Does NOT copy or touch data/carewatch.db.
    """
    from src.alert_store import AlertStore
    from src.audit_logger import AuditLogger
    from src.suppression import AlertSuppressionLayer

    AlertStore(db_path=TEST_DB_PATH)
    AuditLogger(db_path=TEST_DB_PATH)
    AlertSuppressionLayer(db_path=TEST_DB_PATH)

    with sqlite3.connect(TEST_DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id  TEXT NOT NULL,
                timestamp  TEXT NOT NULL,
                date       TEXT NOT NULL,
                hour       INTEGER NOT NULL,
                minute     INTEGER NOT NULL,
                activity   TEXT NOT NULL,
                confidence REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS baselines (
                person_id  TEXT PRIMARY KEY,
                built_at   TEXT NOT NULL,
                profile    TEXT NOT NULL
            )
        """)
        conn.commit()


def setup_scenario(scenario: "EvalScenario") -> None:
    """Seed test DB. Clears existing state for this person_id first."""
    if scenario.active_alert and scenario.activity_rows:
        assert scenario.active_alert["person_id"] == scenario.activity_rows[0]["person_id"], (
            f"{scenario.scenario_id}: active_alert and activity_rows person_ids must match"
        )

    pid = _get_person_id(scenario)

    with sqlite3.connect(TEST_DB_PATH) as conn:
        # table and col come from a hardcoded list below — no injection risk
        for table, col in [
            ("activity_log", "person_id"),
            ("baselines", "person_id"),
            ("active_alerts", "person_id"),
            ("alert_suppression", "resident_id"),
            ("agent_runs", "person_id"),
        ]:
            try:
                conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (pid,))
            except sqlite3.OperationalError:
                pass  # table may not exist yet
        conn.commit()

        for row in scenario.activity_rows:
            conn.execute(
                "INSERT INTO activity_log "
                "(person_id,timestamp,date,hour,minute,activity,confidence) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    row["person_id"],
                    row["timestamp"],
                    row["date"],
                    row["hour"],
                    row["minute"],
                    row["activity"],
                    row["confidence"],
                ),
            )

        if scenario.active_alert:
            conn.execute(
                "INSERT INTO active_alerts (person_id,alert_type,triggered_at) VALUES (?,?,?)",
                (
                    scenario.active_alert["person_id"],
                    scenario.active_alert["alert_type"],
                    scenario.active_alert["triggered_at"],
                ),
            )
        conn.commit()

    _seed_baseline(scenario, pid)


def teardown_scenario(scenario: "EvalScenario") -> None:
    pid = _get_person_id(scenario)
    with sqlite3.connect(TEST_DB_PATH) as conn:
        # table and col come from a hardcoded list below — no injection risk
        for table, col in [
            ("activity_log", "person_id"),
            ("baselines", "person_id"),
            ("active_alerts", "person_id"),
            ("alert_suppression", "resident_id"),
            ("agent_runs", "person_id"),
        ]:
            try:
                conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (pid,))
            except sqlite3.OperationalError:
                pass
        conn.commit()


def _get_person_id(scenario: "EvalScenario") -> str:
    if scenario.active_alert:
        return scenario.active_alert["person_id"]
    if scenario.activity_rows:
        return scenario.activity_rows[0]["person_id"]
    return f"eval_{scenario.scenario_id.lower()}"


def _seed_baseline(scenario: "EvalScenario", person_id: str) -> None:
    """
    Build baseline from seeded activity_rows, or seed a hardcoded default
    for scenarios that have only an active_alert and no activity_rows.

    Why this is necessary:
      DeviationDetector.load_baseline() reads from the baselines SQLite table.
      Without a row there, it returns None → UNKNOWN → scenario fails trivially.
      BaselineBuilder.build_baseline() reads activity_log rows we already seeded
      and computes mean_hour / std_hour / occurs_daily exactly as production does.
    """
    from src.baseline_builder import BaselineBuilder
    from src.logger import ActivityLogger

    test_logger = ActivityLogger(db_path=TEST_DB_PATH)
    builder = BaselineBuilder(logger=test_logger)

    if scenario.activity_rows:
        builder.build_baseline(person_id)
    else:
        # Active-alert-only scenarios: seed default so detector can check
        # occurs_daily=True with known deadlines
        default = {
            "person_id": person_id,
            "built_at": datetime.now().isoformat(),
            "days_of_data": 7,
            "activities": {
                "sitting": {"mean_hour": 9.5, "std_hour": 1.5, "mean_count": 12, "occurs_daily": True},
                "eating": {"mean_hour": 12.0, "std_hour": 0.5, "mean_count": 3, "occurs_daily": True},
                "walking": {"mean_hour": 11.0, "std_hour": 2.0, "mean_count": 8, "occurs_daily": True},
                "pill_taking": {"mean_hour": 8.0, "std_hour": 0.3, "mean_count": 2, "occurs_daily": True},
                "lying_down": {"mean_hour": 21.5, "std_hour": 1.0, "mean_count": 3, "occurs_daily": True},
            },
        }
        with sqlite3.connect(TEST_DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO baselines (person_id,built_at,profile) VALUES (?,?,?)",
                (person_id, default["built_at"], json.dumps(default)),
            )
            conn.commit()
