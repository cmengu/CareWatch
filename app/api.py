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

from fastapi import FastAPI, HTTPException
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