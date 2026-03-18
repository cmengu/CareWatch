"""
suppression.py
==============
Alert suppression layer. Wraps AlertSystem.send(), suppresses repeated
alerts of the same risk_level within configured windows, and overrides
suppression when severity escalates (e.g. YELLOW → RED).
"""

import sqlite3
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from src.alert_system import AlertSystem

_DEFAULT_DB_PATH = str(Path(__file__).resolve().parents[1] / "data" / "carewatch.db")

logger = logging.getLogger(__name__)

# Suppression windows per risk level — explicit config, not magic numbers
# Unit: minutes. 0 = never suppress.
SUPPRESSION_WINDOWS: dict[str, int] = {
    "RED":     5,
    "YELLOW":  30,
    "UNKNOWN": 0,
    "GREEN":   0,
}

# Severity rank — higher = more severe
# Used to detect cross-level escalation
SEVERITY_RANK: dict[str, int] = {
    "GREEN":   0,
    "UNKNOWN": 0,
    "YELLOW":  1,
    "RED":     2,
}


class AlertSuppressionLayer:
    """
    Wraps AlertSystem.send().
    Suppresses repeated alerts of the same risk_level within the configured window.
    Always fires if severity has escalated since the last fired alert.
    Logs every decision — fired or suppressed — to alert_suppression table.
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path if db_path is not None else _DEFAULT_DB_PATH
        self.alert_system = AlertSystem()
        self._ensure_table()

    def _ensure_table(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_suppression (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    resident_id        TEXT    NOT NULL,
                    risk_level         TEXT    NOT NULL,
                    prior_severity     TEXT,
                    fired_at           TEXT    NOT NULL,
                    suppressed         INTEGER NOT NULL DEFAULT 0,
                    suppression_reason TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_suppression_lookup
                ON alert_suppression (resident_id, risk_level, fired_at)
            """)
            conn.commit()

    def send(
        self,
        risk_result: dict,
        person_name: str = "Your family member",
        resident_id: str = "default",
        voice_alert: bool = False,
    ) -> dict:
        """
        Drop-in replacement for AlertSystem.send().
        Returns a dict describing what happened and why.
        """
        risk_level: str = risk_result.get("risk_level", "UNKNOWN").upper()

        if risk_level == "GREEN":
            return {
                "fired": False,
                "suppressed": False,
                "reason": "GREEN level — no alert required",
                "risk_level": risk_level,
            }

        window_minutes = SUPPRESSION_WINDOWS.get(risk_level, 0)
        now = datetime.now(timezone.utc)

        # Query 1 — should same-level alert be suppressed?
        within_window, suppression_reason = self._same_level_within_window(
            resident_id=resident_id,
            risk_level=risk_level,
            window_minutes=window_minutes,
            now=now,
        )

        # Query 2 — has severity escalated since last fired alert?
        # Runs regardless of Query 1 result — escalation always overrides
        escalated, prior_severity = self._severity_escalated(
            resident_id=resident_id,
            current_risk_level=risk_level,
            now=now,
        )

        if within_window and not escalated:
            logger.info(
                "Alert suppressed resident=%s risk_level=%s reason=%s",
                resident_id, risk_level, suppression_reason,
            )
            self._log_decision(
                resident_id=resident_id,
                risk_level=risk_level,
                prior_severity=prior_severity,
                fired_at=now.isoformat(),
                suppressed=True,
                suppression_reason=suppression_reason,
            )
            return {
                "fired": False,
                "suppressed": True,
                "reason": suppression_reason,
                "risk_level": risk_level,
            }

        if within_window and escalated:
            logger.info(
                "Suppression overridden — escalated from %s to %s resident=%s",
                prior_severity, risk_level, resident_id,
            )

        # Fire the alert
        self.alert_system.send(risk_result, person_name=person_name, voice_alert=voice_alert)

        self._log_decision(
            resident_id=resident_id,
            risk_level=risk_level,
            prior_severity=prior_severity,
            fired_at=now.isoformat(),
            suppressed=False,
            suppression_reason=None,
        )

        logger.info(
            "Alert fired resident=%s risk_level=%s escalated=%s",
            resident_id, risk_level, escalated,
        )
        return {
            "fired": True,
            "suppressed": False,
            "escalated": escalated,
            "prior_severity": prior_severity,
            "reason": (
                f"Escalated from {prior_severity}" if escalated
                else "No recent alert — fired normally"
            ),
            "risk_level": risk_level,
        }

    def _same_level_within_window(
        self,
        resident_id: str,
        risk_level: str,
        window_minutes: int,
        now: datetime,
    ) -> tuple[bool, str | None]:
        """
        Query 1.
        Returns (within_window, reason).
        Checks whether an alert of exactly this risk_level
        fired within window_minutes for this resident.
        """
        if window_minutes == 0:
            return False, None

        cutoff = (now - timedelta(minutes=window_minutes)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT fired_at
                FROM   alert_suppression
                WHERE  resident_id = ?
                  AND  risk_level  = ?
                  AND  suppressed  = 0
                  AND  fired_at   >= ?
                ORDER  BY fired_at DESC
                LIMIT  1
                """,
                (resident_id, risk_level, cutoff),
            ).fetchone()

        if row is None:
            return False, None

        parsed = datetime.fromisoformat(row[0])
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        minutes_ago = (now - parsed).total_seconds() / 60
        reason = (
            f"Same alert ({risk_level}) fired {minutes_ago:.1f} min ago. "
            f"Window: {window_minutes} min."
        )
        return True, reason

    def _severity_escalated(
        self,
        resident_id: str,
        current_risk_level: str,
        now: datetime,
    ) -> tuple[bool, str | None]:
        """
        Query 2.
        Returns (escalated, prior_severity).
        Fetches the most recent FIRED alert for this resident
        across ALL risk levels. Compares rank to current level.
        prior_severity is None if this is the first ever alert for this resident.
        """
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT risk_level
                FROM   alert_suppression
                WHERE  resident_id = ?
                  AND  suppressed  = 0
                ORDER  BY fired_at DESC
                LIMIT  1
                """,
                (resident_id,),
            ).fetchone()

        if row is None:
            # No prior fired alert — first alert ever for this resident
            return False, None

        prior_severity = row[0]
        current_rank = SEVERITY_RANK.get(current_risk_level, 0)
        prior_rank = SEVERITY_RANK.get(prior_severity, 0)
        escalated = current_rank > prior_rank

        return escalated, prior_severity

    def _log_decision(
        self,
        resident_id: str,
        risk_level: str,
        prior_severity: str | None,
        fired_at: str,
        suppressed: bool,
        suppression_reason: str | None,
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO alert_suppression
                    (resident_id, risk_level, prior_severity,
                     fired_at, suppressed, suppression_reason)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    resident_id,
                    risk_level,
                    prior_severity,
                    fired_at,
                    int(suppressed),
                    suppression_reason,
                ),
            )
            conn.commit()
