"""
cusum_monitor.py
================
ResidentCUSUMMonitor — manages four CUSUMDetector instances per resident.
Fitted from data/baselines/{person_id}.json, reads activity_log for observations.
Signals: movement_frequency, pill_taking_timing, eating_timing, inactivity_duration.

USAGE:
    from src.cusum_monitor import ResidentCUSUMMonitor
    monitor = ResidentCUSUMMonitor()
    result = monitor.check("resident")
"""

import json
import sqlite3
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from src.cusum_detector import CUSUMDetector, CUSUMResult

logger = logging.getLogger(__name__)

# Minimum std floor — prevents hyper-sensitive detectors on very regular residents
MIN_STD = 0.5

# Inactivity signal parameters — fixed, not from baseline
INACTIVITY_BASELINE_MEAN = 0.5    # expect activity at least every 30 minutes
INACTIVITY_BASELINE_STD  = 0.25   # tight — sustained inactivity is abnormal


@dataclass
class CUSUMCheckResult:
    """
    Output of ResidentCUSUMMonitor.check().
    Contains one CUSUMResult per monitored signal.
    any_signal_detected is True if ANY detector fired.
    """
    person_id:           str
    checked_at:          str
    any_signal_detected: bool
    signals:             dict[str, CUSUMResult]  # signal_name → CUSUMResult
    skipped_signals:     list[str]               # signals with no data this check
    summary:             str                     # human-readable one-liner


class ResidentCUSUMMonitor:
    """
    Manages four CUSUMDetector instances for one resident.
    Fitted from data/baselines/{person_id}.json on first check().
    CUSUM state is in-memory — resets on process restart.
    """

    def __init__(
        self,
        db_path:      str = "data/carewatch.db",
        baseline_dir: str = "data/baselines",
    ):
        self.db_path      = db_path
        self.baseline_dir = baseline_dir
        # Detectors keyed by person_id then signal_name
        # Built lazily on first check() call for each person_id
        self._detectors: dict[str, dict[str, CUSUMDetector]] = {}

    def check(self, person_id: str) -> CUSUMCheckResult:
        """
        Run all CUSUM detectors for this resident.
        Loads baseline and builds detectors on first call for this person_id.
        Returns CUSUMCheckResult with results for all four signals.
        """
        if person_id not in self._detectors:
            self._build_detectors(person_id)

        detectors = self._detectors[person_id]
        now       = datetime.now()
        results   = {}
        skipped   = []

        # ── Signal 1: movement_frequency ──────────────────────────────────
        if "movement_frequency" in detectors:
            hourly_count = self._get_hourly_activity_count(person_id, now)
            if hourly_count is not None:
                results["movement_frequency"] = detectors[
                    "movement_frequency"
                ].update(hourly_count)
        else:
            skipped.append("movement_frequency")  # detector skipped at build (no baseline data)

        # ── Signal 2: pill_taking_timing ───────────────────────────────────
        pill_hour = self._get_last_activity_hour(person_id, "pill_taking", now)
        if pill_hour is not None:
            results["pill_taking_timing"] = detectors[
                "pill_taking_timing"
            ].update(pill_hour)
        else:
            skipped.append("pill_taking_timing")
            logger.debug("pill_taking_timing skipped — no event today for %s", person_id)

        # ── Signal 3: eating_timing ────────────────────────────────────────
        eating_hour = self._get_last_activity_hour(person_id, "eating", now)
        if eating_hour is not None:
            results["eating_timing"] = detectors["eating_timing"].update(eating_hour)
        else:
            skipped.append("eating_timing")
            logger.debug("eating_timing skipped — no event today for %s", person_id)

        # ── Signal 4: inactivity_duration ─────────────────────────────────
        hours_since = self._get_hours_since_last_activity(person_id, now)
        if hours_since is not None:
            results["inactivity_duration"] = detectors[
                "inactivity_duration"
            ].update(hours_since)

        any_detected = any(r.signal_detected for r in results.values())

        # Build summary string
        fired = [
            f"{name}({r.statistic_upper:.1f}↑ / {r.statistic_lower:.1f}↓)"
            for name, r in results.items()
            if r.signal_detected
        ]
        if fired:
            summary = f"CUSUM signal(s) detected: {', '.join(fired)}"
        else:
            summary = "All CUSUM signals within normal bounds."

        return CUSUMCheckResult(
            person_id=person_id,
            checked_at=now.isoformat(),
            any_signal_detected=any_detected,
            signals=results,
            skipped_signals=skipped,
            summary=summary,
        )

    def reset_signal(self, person_id: str, signal_name: str) -> None:
        """
        Reset one detector after a confirmed caretaker intervention.
        """
        if person_id in self._detectors:
            if signal_name in self._detectors[person_id]:
                self._detectors[person_id][signal_name].reset()
                logger.info(
                    "CUSUM reset: person=%s signal=%s", person_id, signal_name
                )

    # ── Private: detector construction ────────────────────────────────────

    def _build_detectors(self, person_id: str) -> None:
        baseline_path = f"{self.baseline_dir}/{person_id}.json"
        try:
            with open(baseline_path) as f:
                baseline = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"ResidentCUSUMMonitor: baseline not found at {baseline_path}. "
                f"Run BaselineBuilder.build_baseline('{person_id}') first."
            )

        acts = baseline.get("activities", {})

        # movement_frequency — derive from mean_count across all activities
        # Baseline uses mean_count (mean daily count per activity)
        total_daily = sum(
            a.get("mean_count", a.get("mean_daily_count", 0)) for a in acts.values()
        )
        hourly_mean = total_daily / 24.0
        hourly_std  = max(hourly_mean * 0.3, MIN_STD)  # 30% of mean as proxy std

        # Zero-activity guard: baseline_mean=0 expects zero activity as normal.
        # Every observation would exceed baseline → detector fires immediately and continuously.
        detectors_dict = {}
        if hourly_mean <= 0:
            logger.warning(
                "No activity data for movement_frequency baseline — skipping detector (person=%s)",
                person_id,
            )
        else:
            detectors_dict["movement_frequency"] = CUSUMDetector(
                signal_name="movement_frequency",
                baseline_mean=hourly_mean,
                baseline_std=hourly_std,
            )

        # pill_taking parameters
        pill = acts.get("pill_taking", {})
        pill_mean = pill.get("mean_hour", 8.0)
        pill_std  = max(pill.get("std_hour") or MIN_STD, MIN_STD)

        # eating parameters
        eating = acts.get("eating", {})
        eating_mean = eating.get("mean_hour", 12.0)
        eating_std  = max(eating.get("std_hour") or MIN_STD, MIN_STD)

        detectors_dict.update({
            "pill_taking_timing": CUSUMDetector(
                signal_name="pill_taking_timing",
                baseline_mean=pill_mean,
                baseline_std=pill_std,
            ),
            "eating_timing": CUSUMDetector(
                signal_name="eating_timing",
                baseline_mean=eating_mean,
                baseline_std=eating_std,
            ),
            "inactivity_duration": CUSUMDetector(
                signal_name="inactivity_duration",
                baseline_mean=INACTIVITY_BASELINE_MEAN,
                baseline_std=INACTIVITY_BASELINE_STD,
            ),
        })
        self._detectors[person_id] = detectors_dict
        logger.info(
            "CUSUM detectors built for person=%s "
            "hourly_mean=%.2f pill_mean=%.1f eating_mean=%.1f",
            person_id, hourly_mean, pill_mean, eating_mean,
        )

    # ── Private: observation extraction from activity_log ─────────────────

    def _get_hourly_activity_count(
        self, person_id: str, now: datetime
    ) -> Optional[float]:
        cutoff = (now - timedelta(hours=1)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM   activity_log
                WHERE  person_id = ?
                  AND  timestamp >= ?
                """,
                (person_id, cutoff),
            ).fetchone()
        return float(row[0]) if row else None

    def _get_last_activity_hour(
        self, person_id: str, activity: str, now: datetime
    ) -> Optional[float]:
        today = now.strftime("%Y-%m-%d")
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT hour, minute
                FROM   activity_log
                WHERE  person_id = ?
                  AND  activity  = ?
                  AND  date      = ?
                ORDER  BY timestamp DESC
                LIMIT  1
                """,
                (person_id, activity, today),
            ).fetchone()
        if row is None:
            return None
        return row[0] + row[1] / 60.0

    def _get_hours_since_last_activity(
        self, person_id: str, now: datetime
    ) -> Optional[float]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT timestamp
                FROM   activity_log
                WHERE  person_id = ?
                ORDER  BY timestamp DESC
                LIMIT  1
                """,
                (person_id,),
            ).fetchone()
        if row is None:
            return None
        last_ts = datetime.fromisoformat(row[0])
        return (now - last_ts).total_seconds() / 3600.0
