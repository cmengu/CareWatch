"""
privacy.py
==========
Data privacy utilities for CareWatch (PDPA-aligned).

Implements obligations from data_privacy_plan.md:
  - Pseudonymous ID generation  (§5.1)
  - PII stripping before external transmission  (§5, §8)
  - Server-side consent logging  (§4)
  - Data retention enforcement  (§6)

Called by:
  - src/alert_system.py     — strip_pii() before Telegram send
  - app/ API endpoints      — has_active_consent() gate, record_consent()
  - Background monitor      — enforce_retention()
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent / "data" / "carewatch.db"

_PII_FIELDS = frozenset({"real_name", "name", "email", "phone", "address", "next_of_kin"})

_PII_PATTERNS = [
    re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b"),
    re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b[STFG]\d{7}[A-Z]\b"),
]


def _init_privacy_tables(db_path: Path = _DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS resident_id_map (
                pseudonymous_id  TEXT PRIMARY KEY,
                display_label    TEXT NOT NULL,
                created_at       TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS consent_log (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                pseudonymous_id  TEXT    NOT NULL,
                consented        INTEGER NOT NULL,
                consented_at     TEXT    NOT NULL,
                consented_by     TEXT
            )
        """)
        conn.commit()


def generate_pseudonymous_id(display_label: str, db_path: Path = _DB_PATH) -> str:
    _init_privacy_tables(db_path)
    hash_hex = hashlib.sha256(display_label.encode("utf-8")).hexdigest()[:6]
    pseudo_id = f"resident_{hash_hex}"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO resident_id_map (pseudonymous_id, display_label, created_at) VALUES (?, ?, ?)",
            (pseudo_id, display_label, datetime.utcnow().isoformat()),
        )
        conn.commit()
    logger.debug("privacy: generated pseudonymous_id %s", pseudo_id)
    return pseudo_id


def get_display_label(pseudonymous_id: str, db_path: Path = _DB_PATH) -> str:
    _init_privacy_tables(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT display_label FROM resident_id_map WHERE pseudonymous_id = ?",
            (pseudonymous_id,),
        ).fetchone()
    return row["display_label"] if row else pseudonymous_id


def strip_pii(data: Dict[str, Any]) -> Dict[str, Any]:
    cleaned: Dict[str, Any] = {}
    for k, v in data.items():
        if k.lower() in _PII_FIELDS:
            cleaned[k] = "[REDACTED]"
        elif isinstance(v, str) and _contains_pii(v):
            cleaned[k] = _redact_text(v)
        elif isinstance(v, dict):
            cleaned[k] = strip_pii(v)
        elif isinstance(v, list):
            cleaned[k] = [strip_pii(i) if isinstance(i, dict) else i for i in v]
        else:
            cleaned[k] = v
    return cleaned


def _contains_pii(text: str) -> bool:
    return any(p.search(text) for p in _PII_PATTERNS)


def _redact_text(text: str) -> str:
    for pattern in _PII_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def record_consent(pseudonymous_id: str, consented: bool,
                   consented_by: str = "resident", db_path: Path = _DB_PATH) -> None:
    _init_privacy_tables(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO consent_log (pseudonymous_id, consented, consented_at, consented_by) VALUES (?, ?, ?, ?)",
            (pseudonymous_id, int(consented), datetime.utcnow().isoformat(), consented_by),
        )
        conn.commit()
    logger.info("privacy: consent %s for %s", "granted" if consented else "withdrawn", pseudonymous_id)


def has_active_consent(pseudonymous_id: str, db_path: Path = _DB_PATH) -> bool:
    _init_privacy_tables(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT consented FROM consent_log WHERE pseudonymous_id = ? ORDER BY consented_at DESC LIMIT 1",
            (pseudonymous_id,),
        ).fetchone()
    return bool(row["consented"]) if row else False


def enforce_retention(db_path: Path = _DB_PATH, days: int = 30) -> Dict[str, int]:
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    deleted: Dict[str, int] = {}
    with sqlite3.connect(db_path) as conn:
        for table in ("activity_log", "medication_event"):
            try:
                cur = conn.execute(f"DELETE FROM {table} WHERE timestamp < ?", (cutoff,))
                deleted[table] = cur.rowcount
            except sqlite3.OperationalError:
                deleted[table] = 0
        conn.commit()
    if any(deleted.values()):
        logger.info("privacy: retention sweep deleted %s", deleted)
    return deleted
