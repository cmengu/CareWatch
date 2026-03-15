"""
alert_store.py
===============
Persistent alert state for CareWatch. A fall detected on Tuesday stays RED on Wednesday
until a caregiver sends /clear <person_id> in Telegram. Uses same DB as ActivityLogger.

DB_PATH must match ActivityLogger.DB_PATH exactly ("data/carewatch.db") — relative string,
not __file__-relative — so both connect to the same file regardless of working directory.

USAGE:
    from src.alert_store import AlertStore
    store = AlertStore()
    store.raise_alert("resident_0042", "FALLEN")
    if store.has_active_alert("resident_0042"):
        ...
    store.clear_alert("resident_0042")
"""

import sqlite3
from datetime import datetime

DB_PATH = "data/carewatch.db"  # must match ActivityLogger.DB_PATH exactly


class AlertStore:
    """Stores uncleared alerts. One per resident max — enforced by partial unique index."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._ensure_table()

    def _ensure_table(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS active_alerts (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id    TEXT    NOT NULL,
                alert_type   TEXT    NOT NULL,
                triggered_at TEXT    NOT NULL,
                cleared_at   TEXT,
                cleared_by   TEXT
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_alert
            ON active_alerts (person_id)
            WHERE cleared_at IS NULL
        """)
        conn.commit()
        conn.close()

    def raise_alert(self, person_id: str, alert_type: str = "FALLEN") -> bool:
        """Insert uncleared alert. Returns False (no-op) if one already exists."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                INSERT INTO active_alerts (person_id, alert_type, triggered_at)
                VALUES (?, ?, ?)
            """, (person_id, alert_type, datetime.now().isoformat()))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def clear_alert(self, person_id: str, cleared_by: str = "caregiver") -> bool:
        """Mark uncleared alert resolved. Returns False if no uncleared alert existed."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            UPDATE active_alerts
            SET cleared_at = ?, cleared_by = ?
            WHERE person_id = ? AND cleared_at IS NULL
        """, (datetime.now().isoformat(), cleared_by, person_id))
        conn.commit()
        affected = cur.rowcount
        conn.close()
        return affected > 0

    def has_active_alert(self, person_id: str) -> dict | None:
        """Returns the uncleared alert row, or None."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("""
            SELECT * FROM active_alerts
            WHERE person_id = ? AND cleared_at IS NULL
        """, (person_id,)).fetchone()
        conn.close()
        return dict(row) if row else None
