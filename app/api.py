"""
api.py
======
FastAPI REST API for CareWatch. Exposes logger, baseline, and deviation detector
to the React frontend. Runs alongside realtime_inference.py (which writes to the
same SQLite DB). Use --workers 1 (SQLite does not handle concurrent writes).

USAGE:
  uvicorn app.api:app --reload --port 8000 --workers 1
"""

import os
import random
import sqlite3
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

from src.logger import ActivityLogger
from src.baseline_builder import BaselineBuilder
from src.deviation_detector import DeviationDetector
from src.agent import CareWatchAgent
from src.models import AgentResult

app = FastAPI(title="CareWatch API")

origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = ActivityLogger()
builder = BaselineBuilder(logger)
detector = DeviationDetector()
agent    = CareWatchAgent()
PERSON = "resident"


def _inject_demo_data():
    """Full implementation from dashboard.py — inserts 7 days of fake activity logs."""
    activities = [
        "sitting", "eating", "walking", "pill_taking",
        "lying_down", "sitting", "walking", "eating",
    ]
    base = datetime.now().replace(hour=7, minute=0, second=0, microsecond=0)
    with sqlite3.connect(logger.db_path) as conn:
        for day_offset in range(7):
            for i, act in enumerate(activities):
                t = base - timedelta(days=day_offset) + timedelta(hours=i * 1.5)
                t += timedelta(minutes=random.randint(-20, 20))
                conn.execute(
                    """
                    INSERT INTO activity_log
                        (person_id, timestamp, date, hour, minute, activity, confidence)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        PERSON,
                        t.strftime("%Y-%m-%dT%H:%M:%S"),
                        t.strftime("%Y-%m-%d"),
                        t.hour,
                        t.minute,
                        act,
                        round(random.uniform(0.75, 0.98), 2),
                    ),
                )
        conn.commit()


@app.get("/api/logs/today")
def get_today():
    """Return all logs for today. Used by timeline and medication schedule."""
    return logger.get_today(PERSON) or []


@app.get("/api/logs/latest")
def get_latest():
    """Return the most recent activity log. Used for current activity display."""
    return logger.get_last_activity(PERSON) or {}


@app.get("/api/logs/week")
def get_week():
    """Return logs for the last 7 days. Used for week history and buildWeekData."""
    return logger.get_last_n_days(7, PERSON) or []


@app.get("/api/risk")
def get_risk():
    """Return risk score and anomalies from deviation detector."""
    return detector.check(PERSON)


@app.get("/api/agent/explain", response_model=AgentResult)
def get_agent_explanation():
    """
    Full AI agent loop: risk score + RAG context + LLM explanation.
    Use for the dashboard AI card. Does not send Telegram alert.
    Safe to poll — send_alert is always False here.
    """
    return agent.run(PERSON, send_alert=False)


@app.get("/api/baseline")
def get_baseline():
    """Return baseline profile. baseline_risk is placeholder until risk history stored."""
    baseline = builder.load_baseline(PERSON) or {}
    baseline["baseline_risk"] = 15
    return baseline


@app.post("/api/baseline/build")
def build_baseline_endpoint():
    """Build baseline from existing logs. Call after inject or when new data available."""
    builder.build_baseline(PERSON)
    return {"ok": True}


@app.post("/api/demo/inject")
def inject_demo():
    """Inject 7 days of demo data and build baseline. For demos when no live data.
    Development only — disable before production."""
    if os.getenv("ENV") == "production":
        raise HTTPException(status_code=403, detail="Demo inject disabled in production")
    _inject_demo_data()
    builder.build_baseline(PERSON)
    return {"ok": True, "message": "Demo data injected and baseline built"}


# ── Medication schedule endpoints (from PillReminder) ─────────────────────
from src.medication import MedicationRepo
from src.label_detector import MedicationLabelDetector
from src.privacy import record_consent, has_active_consent
from pydantic import BaseModel as _BaseModel
from typing import Optional as _Optional


class MedicationSchedulePayload(_BaseModel):
    medication_name: str
    dose: _Optional[str] = None
    time_of_day: str
    tolerance_min: int = 30
    illness_hint: _Optional[str] = None
    meal_relation: str = "fixed"
    meal_name: _Optional[str] = None


class MealSchedulePayload(_BaseModel):
    meal_name: str
    time_of_day: str
    tolerance_min: int = 60


class ConsentPayload(_BaseModel):
    consented: bool
    consented_by: str = "resident"


_med_repo = MedicationRepo()
_label_detector = MedicationLabelDetector()


@app.get("/residents/{person_id}/medication-schedules")
def list_medication_schedules(person_id: str):
    return _med_repo.list_schedules(person_id)


@app.post("/residents/{person_id}/medication-schedules")
def create_medication_schedule(person_id: str, payload: MedicationSchedulePayload):
    return _med_repo.create_schedule(person_id, payload)


@app.delete("/residents/{person_id}/medication-schedules/{schedule_id}")
def delete_medication_schedule(person_id: str, schedule_id: int):
    _med_repo.delete_schedule(person_id, schedule_id)
    return {"deleted": schedule_id}


@app.get("/residents/{person_id}/meal-schedules")
def list_meal_schedules(person_id: str):
    return _med_repo.list_meal_schedules(person_id)


@app.post("/residents/{person_id}/meal-schedules")
def create_meal_schedule(person_id: str, payload: MealSchedulePayload):
    return _med_repo.create_meal_schedule(person_id, payload)


@app.delete("/residents/{person_id}/meal-schedules/{schedule_id}")
def delete_meal_schedule(person_id: str, schedule_id: int):
    _med_repo.delete_meal_schedule(person_id, schedule_id)
    return {"deleted": schedule_id}


@app.post("/residents/{person_id}/scan")
async def scan_medication_label(person_id: str, file: UploadFile = File(...)):
    """
    Upload a pill bottle image. Returns structured medication info.
    The result is also written to medication_event via graph scan_node when
    graph.invoke() is called with image_bytes.
    """
    file_bytes = await file.read()
    result = _label_detector.extract_from_image(file_bytes)
    return result


@app.post("/residents/{person_id}/consent")
def update_consent(person_id: str, payload: ConsentPayload):
    record_consent(person_id, payload.consented, payload.consented_by)
    return {"consented": payload.consented, "person_id": person_id}


@app.get("/residents/{person_id}/consent")
def get_consent_status(person_id: str):
    return {"has_active_consent": has_active_consent(person_id), "person_id": person_id}