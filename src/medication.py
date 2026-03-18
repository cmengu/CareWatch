import sqlite3
from datetime import datetime, date, time, timedelta
from typing import List, Dict, Optional

DB_PATH = "data/carewatch.db"


def _parse_hhmm(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(hour=int(h), minute=int(m))


class MedicationRepo:
    """
    Lightweight repository around SQLite for:
      - medication schedules (planned doses)
      - medication events (detected / manual intake or missed doses)
      - a small medication-specific risk component

    This is intentionally simple and hackathon-friendly.
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    # ── Schema ──────────────────────────────────────────────────────────────
    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS medication_schedule (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_id     TEXT    NOT NULL,
                    medication_name TEXT  NOT NULL,
                    dose          TEXT,
                    time_of_day   TEXT    NOT NULL,   -- "HH:MM"
                    tolerance_min INTEGER NOT NULL DEFAULT 30,
                    illness_hint  TEXT,
                    meal_relation TEXT    NOT NULL DEFAULT 'fixed',  -- 'before', 'after', 'fixed'
                    meal_name     TEXT                               -- 'Breakfast', 'Lunch', 'Dinner'
                )
                """
            )
            # Migrate existing databases that don't have the new columns
            for col, definition in [
                ("meal_relation", "TEXT NOT NULL DEFAULT 'fixed'"),
                ("meal_name",     "TEXT"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE medication_schedule ADD COLUMN {col} {definition}")
                except Exception:
                    pass  # column already exists

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meal_schedule (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_id     TEXT    NOT NULL,
                    meal_name     TEXT    NOT NULL,
                    time_of_day   TEXT    NOT NULL,   -- "HH:MM"
                    tolerance_min INTEGER NOT NULL DEFAULT 60
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS medication_event (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_id     TEXT    NOT NULL,
                    medication_name TEXT  NOT NULL,
                    timestamp     TEXT    NOT NULL,   -- ISO
                    scheduled_id  INTEGER,
                    on_time       INTEGER NOT NULL,   -- 1 = on time, 0 = late/missed
                    source        TEXT    NOT NULL    -- "ai", "manual", "missed"
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS medication_risk (
                    person_id  TEXT PRIMARY KEY,
                    risk_score INTEGER NOT NULL,
                    updated_at TEXT    NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meal_reminder_log (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_id        TEXT    NOT NULL,
                    schedule_id      INTEGER NOT NULL,
                    reminder_date    TEXT    NOT NULL,  -- "YYYY-MM-DD"
                    reminder_count   INTEGER NOT NULL DEFAULT 0,
                    last_reminded_at TEXT              -- ISO timestamp
                )
                """
            )
            conn.commit()

    # ── Schedules CRUD ─────────────────────────────────────────────────────
    def list_schedules(self, person_id: str) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM medication_schedule
                WHERE person_id = ?
                ORDER BY time_of_day ASC, id ASC
                """,
                (person_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def create_schedule(self, person_id: str, payload) -> Dict:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO medication_schedule
                    (person_id, medication_name, dose, time_of_day, tolerance_min, illness_hint, meal_relation, meal_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    person_id,
                    payload.medication_name,
                    payload.dose,
                    payload.time_of_day,
                    payload.tolerance_min,
                    payload.illness_hint,
                    getattr(payload, "meal_relation", "fixed"),
                    getattr(payload, "meal_name", None),
                ),
            )
            schedule_id = cur.lastrowid
            conn.commit()

            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM medication_schedule WHERE id = ?", (schedule_id,)
            ).fetchone()
        return dict(row) if row else {}

    def delete_schedule(self, person_id: str, schedule_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM medication_schedule WHERE person_id = ? AND id = ?",
                (person_id, schedule_id),
            )
            conn.commit()

    # ── Meal Schedules CRUD ────────────────────────────────────────────────
    def list_meal_schedules(self, person_id: str) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM meal_schedule
                WHERE person_id = ?
                ORDER BY time_of_day ASC, id ASC
                """,
                (person_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def create_meal_schedule(self, person_id: str, payload) -> Dict:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO meal_schedule
                    (person_id, meal_name, time_of_day, tolerance_min)
                VALUES (?, ?, ?, ?)
                """,
                (
                    person_id,
                    payload.meal_name,
                    payload.time_of_day,
                    payload.tolerance_min,
                ),
            )
            schedule_id = cur.lastrowid
            conn.commit()

            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM meal_schedule WHERE id = ?", (schedule_id,)
            ).fetchone()
        return dict(row) if row else {}

    def delete_meal_schedule(self, person_id: str, schedule_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM meal_schedule WHERE person_id = ? AND id = ?",
                (person_id, schedule_id),
            )
            conn.commit()

    # ── Events + Risk ──────────────────────────────────────────────────────
    def _get_or_init_risk(self, person_id: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT risk_score FROM medication_risk WHERE person_id = ?",
                (person_id,),
            ).fetchone()
            if row:
                return int(row["risk_score"])

            # Initialise with neutral risk 0
            now_iso = datetime.utcnow().isoformat()
            conn.execute(
                "INSERT INTO medication_risk (person_id, risk_score, updated_at) VALUES (?, ?, ?)",
                (person_id, 0, now_iso),
            )
            conn.commit()
            return 0

    def _set_risk(self, person_id: str, new_score: int) -> int:
        new_score = max(0, min(100, int(new_score)))
        now_iso = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO medication_risk (person_id, risk_score, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(person_id) DO UPDATE SET
                    risk_score = excluded.risk_score,
                    updated_at = excluded.updated_at
                """,
                (person_id, new_score, now_iso),
            )
            conn.commit()
        return new_score

    def get_medication_risk(self, person_id: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT risk_score FROM medication_risk WHERE person_id = ?",
                (person_id,),
            ).fetchone()
        return int(row["risk_score"]) if row else 0

    def get_recent_events(self, person_id: str, days: int = 30) -> List[Dict]:
        cutoff = datetime.utcnow() - timedelta(days=days)
        cutoff_iso = cutoff.isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM medication_event
                WHERE person_id = ? AND timestamp >= ?
                ORDER BY timestamp DESC
                """,
                (person_id, cutoff_iso),
            ).fetchall()
        return [dict(r) for r in rows]

    def _find_matching_schedule_for_event(
        self, person_id: str, med_name: str, ts: datetime
    ) -> Optional[Dict]:
        """
        Very small heuristic: same-day schedule with same name where the
        event time lies within the tolerance window and has not yet been
        matched by any other event.
        """
        today_str = ts.strftime("%Y-%m-%d")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            schedules = conn.execute(
                """
                SELECT *
                FROM medication_schedule
                WHERE person_id = ?
                  AND medication_name = ?
                """,
                (person_id, med_name),
            ).fetchall()

            for s in schedules:
                sched_time = _parse_hhmm(s["time_of_day"])
                sched_dt = datetime.combine(date.fromisoformat(today_str), sched_time)
                tol = timedelta(minutes=int(s["tolerance_min"]))
                window_start = sched_dt - tol
                window_end = sched_dt + tol
                if not (window_start <= ts <= window_end):
                    continue

                # Already matched?
                used = conn.execute(
                    """
                    SELECT 1
                    FROM medication_event
                    WHERE scheduled_id = ?
                    LIMIT 1
                    """,
                    (s["id"],),
                ).fetchone()
                if used:
                    continue
                return dict(s)
        return None

    def record_event(
        self,
        person_id: str,
        med_name: str,
        ts: datetime,
        source: str = "ai",
    ) -> Dict:
        ts_iso = ts.isoformat()
        schedule = self._find_matching_schedule_for_event(person_id, med_name, ts)
        scheduled_id = schedule["id"] if schedule else None

        on_time = 1
        if schedule:
            sched_time = _parse_hhmm(schedule["time_of_day"])
            sched_dt = datetime.combine(ts.date(), sched_time)
            tol = timedelta(minutes=int(schedule["tolerance_min"]))
            if ts > sched_dt + tol:
                on_time = 0

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO medication_event
                    (person_id, medication_name, timestamp, scheduled_id, on_time, source)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (person_id, med_name, ts_iso, scheduled_id, on_time, source),
            )
            conn.commit()

        # Simple risk-update heuristic
        current_risk = self._get_or_init_risk(person_id)
        if schedule:
            if on_time:
                new_risk = max(0, current_risk - 5)
            else:
                new_risk = min(100, current_risk + 10)
        else:
            new_risk = current_risk

        new_risk = self._set_risk(person_id, new_risk)

        return {
            "person_id": person_id,
            "medication_name": med_name,
            "timestamp": ts_iso,
            "scheduled_id": scheduled_id,
            "on_time": bool(on_time),
            "new_risk_score": new_risk,
        }

    # ── Data Retention ────────────────────────────────────────────────────────
    def purge_old_logs(self, person_id: str, days: int = 30) -> None:
        """
        Delete medication_event rows older than `days` days for the given person.
        Called automatically by check_and_trigger_reminders to enforce the
        30-day retention policy required by the data privacy plan.
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                DELETE FROM medication_event
                WHERE person_id = ? AND timestamp < ?
                """,
                (person_id, cutoff),
            )
            conn.commit()

    # ── Reminder / missed-dose detection ───────────────────────────────────
    def check_and_trigger_reminders(self, person_id: str, speaker=None) -> List[Dict]:
        """
        Check all schedules for today. For any schedule whose window has fully
        passed without a matching event, create a 'missed' event, bump risk,
        and (optionally) trigger a TTS reminder via `speaker(text)`.

        Also purges medication_event rows older than 30 days (data retention).

        Returns a list of dicts describing which schedules triggered.
        """
        self.purge_old_logs(person_id)  # enforce 30-day retention policy
        now = datetime.utcnow()
        today = date.today()
        triggered: List[Dict] = []

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            schedules = conn.execute(
                """
                SELECT *
                FROM medication_schedule
                WHERE person_id = ?
                """,
                (person_id,),
            ).fetchall()

            for s in schedules:
                sched_time = _parse_hhmm(s["time_of_day"])
                sched_dt = datetime.combine(today, sched_time)
                tol = timedelta(minutes=int(s["tolerance_min"]))
                window_end = sched_dt + tol

                # Only consider past schedules whose tolerance window has ended
                if now <= window_end:
                    continue

                # Already has any event (taken or missed)?
                existing = conn.execute(
                    """
                    SELECT 1
                    FROM medication_event
                    WHERE person_id = ?
                      AND scheduled_id = ?
                    LIMIT 1
                    """,
                    (person_id, s["id"]),
                ).fetchone()
                if existing:
                    continue

                # Mark as missed
                missed_ts = window_end
                conn.execute(
                    """
                    INSERT INTO medication_event
                        (person_id, medication_name, timestamp, scheduled_id, on_time, source)
                    VALUES (?, ?, ?, ?, 0, 'missed')
                    """,
                    (
                        person_id,
                        s["medication_name"],
                        missed_ts.isoformat(),
                        s["id"],
                    ),
                )
                conn.commit()

                # Risk bump for a fully missed dose
                current_risk = self._get_or_init_risk(person_id)
                new_risk = self._set_risk(person_id, min(100, current_risk + 15))

                message = (
                    f"It is time to take your medicine: {s['medication_name']}. "
                    "Please take your medication now."
                )
                if speaker is not None:
                    try:
                        speaker(message)
                    except Exception:
                        # Silently ignore TTS errors; this is best-effort.
                        pass

                triggered.append(
                    {
                        "schedule_id": s["id"],
                        "medication_name": s["medication_name"],
                        "new_risk_score": new_risk,
                    }
                )

        return triggered

    def check_and_trigger_meal_reminders(self, person_id: str, speaker=None, logger=None) -> List[Dict]:
        """
        Check meal schedules. If a meal window has passed and no eating
        activity was logged during that hour, trigger a TTS reminder.
        """
        now = datetime.utcnow()
        today = date.today()
        triggered: List[Dict] = []

        if logger is None:
            return triggered

        # Quick check for today's 'eating' logs
        # Since logger returns a list of dicts for `get_today`
        today_logs = logger.get_today(person_id) or []
        eating_logs = [log for log in today_logs if log.get('activity') == 'eating']

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            schedules = conn.execute(
                """
                SELECT *
                FROM meal_schedule
                WHERE person_id = ?
                """,
                (person_id,),
            ).fetchall()

            for s in schedules:
                sched_time = _parse_hhmm(s["time_of_day"])
                sched_dt = datetime.combine(today, sched_time)
                tol = timedelta(minutes=int(s["tolerance_min"]))
                window_end = sched_dt + tol

                if now <= window_end:
                    continue  # Window hasn't passed yet

                # Did they eat near this time? (Within hour block of the meal time)
                ate_during_meal = False
                for log in eating_logs:
                    try:
                        log_h = log.get('hour', 0)
                        log_m = log.get('minute', 0)
                        log_dt = datetime.combine(today, time(hour=int(log_h), minute=int(log_m)))
                        # If eating was detected any time between (sched_time - tolerance) and (window_end)
                        if (sched_dt - tol) <= log_dt <= window_end:
                            ate_during_meal = True
                            break
                    except Exception:
                        pass

                if ate_during_meal:
                    continue

                # Has this specific meal already been reminded today?
                # We reuse the `medication_event` table but use source="missed_meal" and medication_name=meal_name
                # Note: this is a hackathon shortcut instead of a dedicated reminder table.
                reminded_already = conn.execute(
                    """
                    SELECT 1
                    FROM medication_event
                    WHERE person_id = ? AND scheduled_id = ? AND source = 'missed_meal'
                      AND date(timestamp) = date('now')
                    LIMIT 1
                    """,
                    (person_id, s["id"]),
                ).fetchone()

                if reminded_already:
                    continue

                # It's late and they haven't eaten. Log the reminder so we don't spam.
                conn.execute(
                    """
                    INSERT INTO medication_event
                        (person_id, medication_name, timestamp, scheduled_id, on_time, source)
                    VALUES (?, ?, ?, ?, 0, 'missed_meal')
                    """,
                    (person_id, s["meal_name"], window_end.isoformat(), s["id"]),
                )
                conn.commit()

                message = (
                    f"It is time for your {s['meal_name']}. "
                    "Please have your meal now."
                )
                if speaker is not None:
                    try:
                        speaker(message)
                    except Exception:
                        pass

                triggered.append(
                    {
                        "meal_id": s["id"],
                        "meal_name": s["meal_name"]
                    }
                )

        return triggered

    # ── Meal-relative medication reminders ──────────────────────────────────
    def check_meal_relative_reminders(self, person_id: str, speaker=None) -> List[Dict]:
        """
        For each medication_schedule with meal_relation 'before' or 'after':

        - 'before': Fire TTS starting 15 min BEFORE the linked meal time.
          Repeat every 15 min if no pill_taking detected. Max 3 reminders.

        - 'after': Fire TTS starting AT the linked meal time (i.e. right after eating).
          Repeat every 15 min if no pill_taking detected. Max 3 reminders.

        Uses meal_reminder_log to track daily reminder counts per schedule.
        Returns list of triggered schedule dicts.
        """
        MAX_REMINDERS = 3
        INTERVAL_MIN  = 15
        now   = datetime.utcnow()
        today = date.today()
        today_str = today.isoformat()
        triggered: List[Dict] = []

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Load meal schedules so we know when each meal is
            meal_rows = conn.execute(
                "SELECT meal_name, time_of_day FROM meal_schedule WHERE person_id = ?",
                (person_id,),
            ).fetchall()
            meal_times: Dict[str, time] = {
                r["meal_name"]: _parse_hhmm(r["time_of_day"]) for r in meal_rows
            }

            # Load medication schedules that are meal-relative
            schedules = conn.execute(
                """
                SELECT * FROM medication_schedule
                WHERE person_id = ?
                  AND meal_relation IN ('before', 'after')
                  AND meal_name IS NOT NULL
                """,
                (person_id,),
            ).fetchall()

            # Check today's pill_taking events (to skip if already taken)
            pill_events = conn.execute(
                """
                SELECT scheduled_id FROM medication_event
                WHERE person_id = ?
                  AND date(timestamp) = ?
                  AND source IN ('ai', 'manual')
                """,
                (person_id, today_str),
            ).fetchall()
            taken_ids = {r["scheduled_id"] for r in pill_events}

            for s in schedules:
                sched_id = s["id"]

                # Skip if already taken today
                if sched_id in taken_ids:
                    continue

                meal_t = meal_times.get(s["meal_name"])
                if meal_t is None:
                    continue  # No meal schedule for this meal name

                meal_dt = datetime.combine(today, meal_t)

                if s["meal_relation"] == "before":
                    # First reminder fires 15 min BEFORE meal
                    first_trigger = meal_dt - timedelta(minutes=INTERVAL_MIN)
                else:  # "after"
                    # First reminder fires AT meal time
                    first_trigger = meal_dt

                # Haven't reached the first trigger yet — stay quiet
                if now < first_trigger:
                    continue

                # How far past the first trigger are we?
                minutes_elapsed = (now - first_trigger).total_seconds() / 60

                # Which reminder number should fire? (0-indexed)
                due_reminder_number = int(minutes_elapsed // INTERVAL_MIN)
                if due_reminder_number >= MAX_REMINDERS:
                    continue  # All reminders already exhausted

                # Check/update reminder log
                log_row = conn.execute(
                    """
                    SELECT id, reminder_count, last_reminded_at
                    FROM meal_reminder_log
                    WHERE person_id = ? AND schedule_id = ? AND reminder_date = ?
                    """,
                    (person_id, sched_id, today_str),
                ).fetchone()

                sent_count = log_row["reminder_count"] if log_row else 0

                # Already sent as many as are due (or more)
                if sent_count > due_reminder_number:
                    continue

                # Check that at least INTERVAL_MIN has passed since the last reminder
                if log_row and log_row["last_reminded_at"]:
                    try:
                        last_dt = datetime.fromisoformat(log_row["last_reminded_at"])
                        if (now - last_dt).total_seconds() < INTERVAL_MIN * 60 - 30:
                            continue  # too soon
                    except Exception:
                        pass

                # Fire the reminder
                relation_word = "before" if s["meal_relation"] == "before" else "after"
                reminder_num  = sent_count + 1
                message = (
                    f"Reminder {reminder_num} of {MAX_REMINDERS}: "
                    f"Please take your {s['medication_name']} {relation_word} your {s['meal_name']}."
                )
                if speaker is not None:
                    try:
                        speaker(message)
                    except Exception:
                        pass

                # Update the log
                now_iso = now.isoformat()
                if log_row:
                    conn.execute(
                        """
                        UPDATE meal_reminder_log
                        SET reminder_count = ?, last_reminded_at = ?
                        WHERE id = ?
                        """,
                        (sent_count + 1, now_iso, log_row["id"]),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO meal_reminder_log
                            (person_id, schedule_id, reminder_date, reminder_count, last_reminded_at)
                        VALUES (?, ?, ?, 1, ?)
                        """,
                        (person_id, sched_id, today_str, now_iso),
                    )
                conn.commit()

                triggered.append({
                    "schedule_id":   sched_id,
                    "medication_name": s["medication_name"],
                    "meal_name":     s["meal_name"],
                    "meal_relation": s["meal_relation"],
                    "reminder_number": sent_count + 1,
                })

        return triggered


