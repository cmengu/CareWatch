"""
deviation_detector.py
======================
Runs every 15 minutes. Compares what's happened today against the personal baseline.
Returns a list of anomalies and an overall risk score (0–100).

Risk score:
  0–30   = GREEN  (normal day)
  31–60  = YELLOW (some deviation, worth monitoring)
  61–100 = RED    (significant deviation, alert family)

USAGE:
    from src.deviation_detector import DeviationDetector
    detector = DeviationDetector()
    result = detector.check("mrs_tan")
    # result.risk_score, result.anomalies
"""

import json
from datetime import datetime
from src.alert_store import AlertStore
from src.logger import ActivityLogger
from src.baseline_builder import BaselineBuilder
from src.models import AnomalyItem, RiskResult

DB_PATH = "data/carewatch.db"

# How many standard deviations off = anomaly
Z_THRESHOLD = 2.0

# Weight of each activity in the risk score (pill_taking is most critical)
ACTIVITY_WEIGHTS = {
    "pill_taking":  40,
    "eating":       25,
    "walking":      20,
    "sitting":       5,
    "lying_down":   10,
}


class DeviationDetector:
    def __init__(self, db_path: str | None = None):
        path = db_path if db_path is not None else DB_PATH
        self.logger      = ActivityLogger(db_path=path)
        self.builder     = BaselineBuilder(self.logger)
        self.alert_store = AlertStore(db_path=path)

    def check(
        self,
        person_id: str = "resident",
        _current_hour: float | None = None,
        _today: str | None = None,
    ) -> RiskResult:
        """
        Compare today's activity log vs stored baseline.
        Returns dict with: risk_score, risk_level, anomalies, summary
        """
        # Persistent alert check — RED stays RED until caregiver clears it.
        # Must come before get_last_activity so a cleared fall doesn't re-trigger.
        active = self.alert_store.has_active_alert(person_id)
        if active:
            return RiskResult(
                risk_score=100,
                risk_level="RED",
                anomalies=[AnomalyItem(
                    activity="persistent_alert",
                    type="UNCLEARED",
                    message=(f"Uncleared alert since {active['triggered_at']}. "
                             f"Send /clear {person_id} to acknowledge."),
                    severity="HIGH",
                )],
                summary=f"Uncleared RED alert since {active['triggered_at']}.",
                checked_at=datetime.now().isoformat(),
            )

        # Immediate override — fallen is always critical
        last = self.logger.get_last_activity(person_id)
        if last and last["activity"] == "fallen" and last["confidence"] > 0.85:
            self.alert_store.raise_alert(person_id, "FALLEN")
            return RiskResult(
                risk_score=100,
                risk_level="RED",
                anomalies=[{"activity": "fallen", "type": "FALLEN",
                            "message":  "FALL DETECTED — immediate attention required",
                            "severity": "HIGH"}],
                summary="Fall detected. Immediate alert sent.",
                checked_at=datetime.now().isoformat(),
            )

        baseline = self.builder.load_baseline(person_id)
        today_logs = self.logger.get_today(person_id, _today=_today)
        current_hour = (
            _current_hour if _current_hour is not None
            else datetime.now().hour + datetime.now().minute / 60.0
        )

        anomalies = []
        risk_points = 0

        if not baseline:
            return RiskResult(
                risk_score=0,
                risk_level="UNKNOWN",
                anomalies=["No baseline built yet — need 7 days of data"],
                summary="Insufficient data",
            )

        # Count today's occurrences per activity
        today_counts = {}
        today_hours  = {}
        for row in today_logs:
            act = row["activity"]
            today_counts[act] = today_counts.get(act, 0) + 1
            today_hours.setdefault(act, []).append(row["hour"] + row["minute"] / 60.0)

        # Check each activity
        for activity, stats in baseline["activities"].items():
            weight = ACTIVITY_WEIGHTS.get(activity, 10)

            # ── Check 1: Expected activity hasn't happened yet ──
            if stats["occurs_daily"] and stats["mean_hour"] is not None:
                expected_hour = stats["mean_hour"]
                std_hour      = max(stats["std_hour"] or 1.0, 0.5)  # min 30min std

                # Only flag if we're past the expected time + 2 std devs
                deadline = expected_hour + Z_THRESHOLD * std_hour
                if current_hour > deadline:
                    count_today = today_counts.get(activity, 0)
                    if count_today == 0:
                        label = activity.replace("_", " ").title()
                        expected_time = _hour_to_str(expected_hour)
                        anomalies.append({
                            "activity": activity,
                            "type":     "MISSING",
                            "message":  f"{label} not detected today (usually around {expected_time})",
                            "severity": "HIGH" if weight >= 30 else "MEDIUM",
                        })
                        risk_points += weight

            # ── Check 2: Activity happening at unusual time ──
            if activity in today_hours and stats["mean_hour"] is not None:
                std_hour = max(stats["std_hour"] or 1.0, 0.5)
                for t in today_hours[activity]:
                    z = abs(t - stats["mean_hour"]) / std_hour
                    if z > Z_THRESHOLD:
                        label = activity.replace("_", " ").title()
                        anomalies.append({
                            "activity": activity,
                            "type":     "TIMING",
                            "message":  f"{label} occurred at unusual time ({_hour_to_str(t)})",
                            "severity": "LOW",
                        })
                        risk_points += weight * 0.3

        # Cap risk score at 100
        risk_score = min(int(risk_points), 100)

        if risk_score <= 30:
            risk_level = "GREEN"
        elif risk_score <= 60:
            risk_level = "YELLOW"
        else:
            risk_level = "RED"

        # Build a human-readable summary
        if not anomalies:
            summary = f"{person_id.replace('_', ' ').title()} is following their normal routine."
        else:
            high = [a for a in anomalies if a["severity"] == "HIGH"]
            summary = f"{len(anomalies)} deviation(s) detected. " + \
                      (f"{len(high)} critical." if high else "No critical issues.")

        return RiskResult(
            risk_score=risk_score,
            risk_level=risk_level,
            anomalies=anomalies,
            summary=summary,
            checked_at=datetime.now().isoformat(),
        )


def _hour_to_str(hour_float: float) -> str:
    """Convert 8.5 → '8:30am'"""
    h = int(hour_float)
    m = int((hour_float - h) * 60)
    period = "am" if h < 12 else "pm"
    h12 = h if h <= 12 else h - 12
    return f"{h12}:{m:02d}{period}"