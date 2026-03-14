"""
create_suppression_table.py
===========================
Creates the alert_suppression table in data/carewatch.db for Day 8.
Run once: python scripts/create_suppression_table.py

Table stores every suppression decision (fired or suppressed) for
AlertSuppressionLayer. prior_severity holds the risk level of the most
recently fired alert before the current one — used for cross-level
escalation detection.
"""

import sqlite3
from pathlib import Path

DB_PATH = str(Path(__file__).resolve().parents[1] / "data" / "carewatch.db")

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS alert_suppression (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id      TEXT    NOT NULL,
    risk_level       TEXT    NOT NULL,
    prior_severity   TEXT,
    fired_at         TEXT    NOT NULL,
    suppressed       INTEGER NOT NULL DEFAULT 0,
    suppression_reason TEXT
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_suppression_resident_time
ON alert_suppression (resident_id, fired_at DESC);
"""

if __name__ == "__main__":
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(CREATE_TABLE_SQL)
        conn.execute(CREATE_INDEX_SQL)
        conn.commit()
        print("alert_suppression table created.")
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        print("All tables:", [t[0] for t in tables])
        schema = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='alert_suppression'"
        ).fetchone()
        print("Schema:", schema[0])
