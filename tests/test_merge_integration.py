"""
tests/test_merge_integration.py
===============================
Integration tests for the PillReminder merge additions.
Tests graph nodes directly via build_graph().invoke() with an isolated SQLite DB.
Does NOT use the eval harness (eval/eval_agent.py) — that harness only calls
detector.check() and cannot exercise graph nodes above the detector.

Run:
    python -m pytest tests/test_merge_integration.py -v
    python -m pytest tests/test_merge_integration.py -v -k "scan"
"""

import sqlite3
import tempfile
import os
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock


# ── DB helpers ────────────────────────────────────────────────────────────────

def make_test_db() -> str:
    """Create an isolated temp SQLite DB with all required tables."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp.name
    tmp.close()
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                date TEXT NOT NULL,
                hour REAL NOT NULL,
                minute INTEGER NOT NULL,
                activity TEXT NOT NULL,
                confidence REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS baselines (
                person_id  TEXT PRIMARY KEY,
                built_at   TEXT NOT NULL DEFAULT '',
                profile    TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS active_alerts (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id    TEXT    NOT NULL,
                alert_type   TEXT    NOT NULL,
                triggered_at TEXT    NOT NULL,
                cleared_at   TEXT,
                cleared_by   TEXT
            );
            CREATE TABLE IF NOT EXISTS alert_suppression (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                resident_id        TEXT    NOT NULL,
                risk_level         TEXT    NOT NULL,
                prior_severity     TEXT,
                fired_at           TEXT    NOT NULL,
                suppressed         INTEGER NOT NULL DEFAULT 0,
                suppression_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS agent_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id TEXT,
                run_at TEXT,
                result_json TEXT
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id TEXT,
                run_at TEXT,
                result_json TEXT
            );
            CREATE TABLE IF NOT EXISTS medication_schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id TEXT NOT NULL,
                medication_name TEXT NOT NULL,
                dose TEXT,
                time_of_day TEXT,
                tolerance_min INTEGER DEFAULT 30,
                meal_relation TEXT DEFAULT 'fixed'
            );
            CREATE TABLE IF NOT EXISTS medication_event (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id       TEXT    NOT NULL,
                medication_name TEXT    NOT NULL,
                timestamp       TEXT    NOT NULL,
                scheduled_id    INTEGER,
                on_time         INTEGER NOT NULL DEFAULT 1,
                source          TEXT    NOT NULL DEFAULT 'manual'
            );
            CREATE TABLE IF NOT EXISTS resident_id_map (
                pseudonymous_id TEXT PRIMARY KEY,
                display_label TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS consent_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pseudonymous_id TEXT NOT NULL,
                consented INTEGER NOT NULL,
                consented_at TEXT NOT NULL,
                consented_by TEXT
            );
        """)
        conn.commit()
    return db_path


def seed_medication_events(db_path: str, person_id: str, events: list) -> None:
    """Seed medication_event rows directly."""
    with sqlite3.connect(db_path) as conn:
        for med_name, days_ago in events:
            ts = (datetime.now(tz=None) - timedelta(days=days_ago)).isoformat()
            conn.execute(
                "INSERT INTO medication_event "
                "(person_id, medication_name, timestamp, scheduled_id, on_time, source) "
                "VALUES (?, ?, ?, NULL, 1, 'manual')",
                (person_id, med_name, ts),
            )
        conn.commit()


def invoke_graph(state: dict, db_path: str) -> dict:
    """Build graph against test DB and invoke with state."""
    from src.graph import build_graph
    graph = build_graph(db_path=db_path)
    config = {"configurable": {"thread_id": f"test-{state.get('person_id', 'x')}"}}
    return graph.invoke(state, config=config)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    """Fresh isolated DB per test."""
    path = make_test_db()
    yield path
    os.unlink(path)


# ── TC21: scan_node no-op when image_bytes absent ─────────────────────────────

def test_21_scan_node_noop_without_image(db):
    """scan_node must not set scan_result when image_bytes is absent."""
    state = {
        "person_id": "test_scan_noop",
        "send_alert": False,
        "image_bytes": None,
    }
    result = invoke_graph(state, db)
    assert result.get("scan_result") is None, (
        f"scan_result should be None when image_bytes absent, got: {result.get('scan_result')}"
    )
    print("TC21 PASS: scan_node is no-op without image_bytes")


# ── TC22: scan_node processes image_bytes ─────────────────────────────────────

def test_22_scan_node_processes_image(db):
    """scan_node must populate scan_result when image_bytes is non-empty."""
    state = {
        "person_id": "test_scan_active",
        "send_alert": False,
        "image_bytes": b"MOCK_IMAGE_BYTES",
    }
    result = invoke_graph(state, db)
    scan = result.get("scan_result")
    assert scan is not None, "scan_result must be set when image_bytes provided"
    assert "medication_name" in scan, f"scan_result missing medication_name: {scan}"
    assert "confidence" in scan, f"scan_result missing confidence: {scan}"
    assert "meal_relation" in scan, f"scan_result missing meal_relation: {scan}"
    assert 0.0 <= scan["confidence"] <= 1.0, f"confidence out of range: {scan['confidence']}"
    print(f"TC22 PASS: scan_result = {scan['medication_name']} {scan.get('dose')} "
          f"(confidence={scan['confidence']:.0%})")


# ── TC23: scan records medication_event in DB ─────────────────────────────────

def test_23_scan_records_medication_event(db):
    """scan_node must write a medication_event row for the scanned medication."""
    person_id = "test_scan_record"
    state = {
        "person_id": person_id,
        "send_alert": False,
        "image_bytes": b"MOCK_IMAGE_BYTES_RECORD",
    }
    invoke_graph(state, db)
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT medication_name FROM medication_event WHERE person_id = ?",
            (person_id,),
        ).fetchall()
    assert len(rows) == 1, f"Expected 1 medication_event row, got {len(rows)}"
    print(f"TC23 PASS: medication_event recorded — {rows[0][0]}")


# ── TC24: ChronicAgent infers T2DM from Metformin history ─────────────────────

def test_24_chronic_agent_infers_t2dm(db):
    """ChronicAgent must infer Type 2 Diabetes from 10 Metformin events."""
    person_id = "test_chronic_t2dm"
    seed_medication_events(
        db, person_id,
        [("Metformin", i) for i in range(1, 11)]
    )
    state = {
        "person_id": person_id,
        "send_alert": False,
        "image_bytes": None,
        "_inject_pill_missing": True,
    }
    from src.models import RiskResult
    mock_risk = RiskResult(
        risk_score=55, risk_level="YELLOW",
        summary="Metformin missed",
        anomalies=[{"activity": "pill_taking", "type": "MISSING",
                    "message": "Metformin not taken", "severity": "HIGH"}],
    )
    with patch("src.deviation_detector.DeviationDetector.check", return_value=mock_risk):
        result = invoke_graph(state, db)

    final = result.get("final_result")
    assert final is not None, "final_result must not be None"
    summary = final.ai_explanation.summary if final.ai_explanation else ""
    assert any(
        kw in summary.lower() for kw in ["diabetes", "metformin", "chronic", "medication history"]
    ), f"Expected T2DM/chronic reference in summary, got: {summary}"
    print(f"TC24 PASS: ChronicAgent summary = {summary[:100]}...")


# ── TC25: ChronicAgent — insufficient history returns normal ──────────────────

def test_25_chronic_agent_insufficient_history(db):
    """ChronicAgent must not raise and must return gracefully with 1 event."""
    person_id = "test_chronic_short"
    seed_medication_events(db, person_id, [("Omeprazole", 1)])
    state = {
        "person_id": person_id,
        "send_alert": False,
        "image_bytes": None,
    }
    from src.models import RiskResult
    mock_risk = RiskResult(
        risk_score=30, risk_level="YELLOW",
        summary="Omeprazole missed",
        anomalies=[{"activity": "pill_taking", "type": "MISSING",
                    "message": "Omeprazole not taken", "severity": "MEDIUM"}],
    )
    with patch("src.deviation_detector.DeviationDetector.check", return_value=mock_risk):
        result = invoke_graph(state, db)

    assert result.get("final_result") is not None, "final_result must not be None"
    print("TC25 PASS: ChronicAgent handled insufficient history without error")


# ── TC26: MedScanAgent low-confidence path ────────────────────────────────────

def test_26_med_scan_agent_low_confidence(db):
    """MedScanAgent must surface a watch concern when confidence < 0.75."""
    from src.label_detector import MedicationLabelDetector
    low_conf_result = {
        "medication_name": "Unknown",
        "dose": "—",
        "meal_relation": "fixed",
        "confidence": 0.52,
    }
    person_id = "test_scan_low_conf"
    state = {
        "person_id": person_id,
        "send_alert": False,
        "image_bytes": b"MOCK_LOW_CONF",
    }
    with patch.object(MedicationLabelDetector, "extract_from_image",
                      return_value=low_conf_result):
        result = invoke_graph(state, db)

    outputs = result.get("specialist_outputs") or []
    scan_outputs = [o for o in outputs
                    if hasattr(o, "agent_name") and o.agent_name == "MedScanAgent"]
    assert scan_outputs, "MedScanAgent must produce an output on low-confidence scan"
    assert scan_outputs[0].concern_level == "watch", (
        f"Expected concern=watch for low-confidence scan, got: {scan_outputs[0].concern_level}"
    )
    print(f"TC26 PASS: MedScanAgent concern={scan_outputs[0].concern_level} for confidence=52%")


# ── TC27: PII stripped from alert payload ─────────────────────────────────────

def test_27_pii_stripped_from_alert(db):
    """strip_pii must remove real names from the Telegram payload."""
    from src.privacy import strip_pii
    payload = {
        "risk_level": "YELLOW",
        "risk_score": 55,
        "summary": "Mrs Tan Ah Kow missed her morning Metformin.",
        "name": "Mrs Tan Ah Kow",
        "anomalies": [{"message": "Metformin missed", "severity": "HIGH"}],
        "ai_explanation": {
            "summary": "Resident Mrs Tan Ah Kow has not taken medication.",
            "concern_level": "watch",
            "action": "Check on Mrs Tan Ah Kow.",
            "positive": "",
        },
    }
    cleaned = strip_pii(payload)
    import json
    cleaned_str = json.dumps(cleaned)
    assert "Mrs Tan Ah Kow" not in cleaned_str, (
        f"PII found in stripped payload: {cleaned_str}"
    )
    assert "[REDACTED]" in cleaned_str or "REDACTED" in cleaned_str, (
        "Expected [REDACTED] markers in cleaned payload"
    )
    print("TC27 PASS: PII stripped from alert payload")


# ── TC28: TTS fires when voice_alert=True ─────────────────────────────────────

def test_28_tts_fires_on_voice_alert(db):
    """speak() must be called exactly once when voice_alert=True and level is YELLOW."""
    from src.models import RiskResult
    mock_risk = RiskResult(
        risk_score=55, risk_level="YELLOW",
        summary="Sertraline missed",
        anomalies=[{"activity": "pill_taking", "type": "MISSING",
                    "message": "Evening Sertraline missed", "severity": "HIGH"}],
    )
    person_id = "test_tts_fires"
    state = {
        "person_id": person_id,
        "send_alert": True,
        "voice_alert": True,
        "image_bytes": None,
    }
    speak_calls = []
    with patch("src.deviation_detector.DeviationDetector.check", return_value=mock_risk), \
         patch("src.tts.speak", side_effect=lambda msg: speak_calls.append(msg)):
        invoke_graph(state, db)

    assert len(speak_calls) == 1, (
        f"Expected speak() called once, got {len(speak_calls)} calls. "
        "Check voice_alert is passed from alert_node → AlertSuppressionLayer → AlertSystem."
    )
    assert "sertraline" in speak_calls[0].lower() or "carewatch" in speak_calls[0].lower(), (
        f"TTS message does not mention CareWatch or medication: {speak_calls[0]}"
    )
    print(f"TC28 PASS: speak() called once — '{speak_calls[0][:80]}...'")
