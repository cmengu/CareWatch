"""
baseline_builder.py
====================
Reads 7 days of activity logs and builds a personal routine profile.

For each activity, it learns:
- What time of day it typically happens (mean hour + std dev)
- How long it typically lasts (mean duration)
- How many times per day it occurs

Saves the profile to the baselines table in SQLite.

USAGE:
    from src.baseline_builder import BaselineBuilder
    builder = BaselineBuilder()
    builder.build_baseline("mrs_tan")
"""

import json
import sqlite3
import numpy as np
from collections import defaultdict
from datetime import datetime, timedelta
from src.logger import ActivityLogger

ACTIVITIES = ["sitting", "eating", "walking", "pill_taking", "lying_down"]


class BaselineBuilder:
    def __init__(self, logger: ActivityLogger = None):
        self.logger = logger or ActivityLogger()
        self._ensure_baselines_table()

    def _ensure_baselines_table(self):
        with sqlite3.connect(self.logger.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS baselines (
                    person_id  TEXT PRIMARY KEY,
                    built_at   TEXT NOT NULL,
                    profile    TEXT NOT NULL
                )
            """)
            conn.commit()

    def build_baseline(self, person_id: str = "resident") -> dict:
        """
        Read the last 7 days of logs for person_id.
        Compute per-activity statistics.
        Save to baselines table in SQLite
        """
        logs = self.logger.get_last_n_days(n=7, person_id=person_id)
        if not logs:
            print(f"⚠️  No logs found for {person_id}")
            return {}

        # Group logs by activity
        activity_hours  = defaultdict(list)  # activity → list of hours when it occurred
        activity_counts = defaultdict(list)  # activity → list of daily counts

        # Group by date first
        by_date = defaultdict(list)
        for row in logs:
            by_date[row["date"]].append(row)

        for date, day_logs in by_date.items():
            daily_counts = defaultdict(int)
            for row in day_logs:
                activity = row["activity"]
                activity_hours[activity].append(row["hour"] + row["minute"] / 60.0)
                daily_counts[activity] += 1
            for act in ACTIVITIES:
                activity_counts[act].append(daily_counts.get(act, 0))

        # Build profile
        profile = {
            "person_id":  person_id,
            "built_at":   datetime.now().isoformat(),
            "days_of_data": len(by_date),
            "activities": {}
        }

        for activity in ACTIVITIES:
            hours  = activity_hours[activity]
            counts = activity_counts[activity]

            if len(hours) < 3:
                # Not enough data for this activity
                profile["activities"][activity] = {
                    "mean_hour":    None,
                    "std_hour":     None,
                    "mean_count":   float(np.mean(counts)) if counts else 0,
                    "occurs_daily": False,
                }
                continue

            profile["activities"][activity] = {
                "mean_hour":    round(float(np.mean(hours)), 2),
                "std_hour":     round(float(np.std(hours)), 2),
                "mean_count":   round(float(np.mean(counts)), 2),
                "occurs_daily": float(np.mean([c > 0 for c in counts])) >= 0.7,
            }

        # Save
        with sqlite3.connect(self.logger.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO baselines (person_id, built_at, profile)
                VALUES (?, ?, ?)
            """, (person_id, profile["built_at"], json.dumps(profile)))
            conn.commit()

        print(f"✅ Baseline saved to DB for {person_id}")
        print(f"   Built from {len(by_date)} days of data")
        return profile

    def load_baseline(self, person_id: str = "resident") -> dict | None:
        with sqlite3.connect(self.logger.db_path) as conn:
            row = conn.execute(
                "SELECT profile FROM baselines WHERE person_id = ?",
                (person_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None