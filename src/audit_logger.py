"""
audit_logger.py
================
Writes one row per agent.run() call to the agent_runs table in carewatch.db.
Answers: what did the AI decide, when, and why?

USAGE (called automatically by agent.py):
    from src.audit_logger import AuditLogger
    audit = AuditLogger()
    audit.write(person_id, result)   # result is AgentResult

Schema:
    id              — autoincrement primary key
    person_id       — who was monitored
    timestamp       — ISO format datetime of the run
    risk_score      — 0-100 from deviation_detector
    risk_level      — GREEN | YELLOW | RED | UNKNOWN
    concern_level   — normal | watch | urgent from LLM
    rag_context_used — 1 or 0 — whether RAG context was passed to LLM
    error           — error string if detector failed, NULL otherwise
"""

import sqlite3
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = "data/carewatch.db"


class AuditLogger:
    def __init__(self, db_path: str = DB_PATH):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Create agent_runs table if it does not exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_id        TEXT    NOT NULL,
                    timestamp        TEXT    NOT NULL,
                    risk_score       INTEGER NOT NULL,
                    risk_level       TEXT    NOT NULL,
                    concern_level    TEXT    NOT NULL,
                    rag_context_used INTEGER NOT NULL,
                    error            TEXT
                )
            """)
            conn.commit()

    def write(self, person_id: str, result) -> None:
        """
        Write one audit row from an AgentResult.
        Never raises — a logging failure must never crash the agent.
        result is AgentResult from src.models — accessed by attribute.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO agent_runs
                        (person_id, timestamp, risk_score, risk_level,
                         concern_level, rag_context_used, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    person_id,
                    datetime.now().isoformat(),
                    result.risk_score,
                    result.risk_level,
                    result.ai_explanation.concern_level,
                    int(result.rag_context_used),
                    result.error if hasattr(result, "error") else None,
                ))
                conn.commit()
            logger.info(
                "Audit written: %s risk=%s concern=%s rag=%s",
                person_id,
                result.risk_level,
                result.ai_explanation.concern_level,
                result.rag_context_used,
            )
        except Exception as e:
            logger.error("Audit write failed (non-blocking): %s", e)

    def get_last_n(self, n: int = 7, person_id: str = "resident") -> list:
        """Return last n audit rows for a person. Used by Day 6 memory."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT * FROM agent_runs
                    WHERE person_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (person_id, n)).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error("Audit read failed: %s", e)
            return []
