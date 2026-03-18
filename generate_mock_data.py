import argparse
import logging
import random
import sqlite3
from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

ACTIVITIES = ["sitting", "eating", "walking", "pill_taking", "lying_down"]

ACTIVITY_HOURS = {
    "pill_taking":  [8, 9, 21],
    "eating":       [8, 12, 19],
    "walking":      [10, 15, 17],
    "sitting":      [11, 14, 16],
    "lying_down":   [13, 20, 22],
}


def get_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def reset_tables(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM activity_log")
    conn.execute("DELETE FROM active_alerts")
    conn.commit()
    logger.info("Tables reset.")


def seed_resident(
    conn: sqlite3.Connection,
    person_id: str,
    days: int,
    include_today: bool,
    ref_date: datetime,
) -> int:
    rows = []
    start_offset = 0 if include_today else 1

    for day_offset in range(start_offset, days + start_offset):
        date = ref_date - timedelta(days=day_offset)
        date_str = date.strftime("%Y-%m-%d")

        for activity, base_hours in ACTIVITY_HOURS.items():
            for base_hour in base_hours:
                jitter_min = random.randint(-10, 10)
                actual_minute = max(0, min(59, 0 + jitter_min + random.randint(0, 20)))
                actual_hour = base_hour
                if actual_minute < 0:
                    actual_minute += 60
                    actual_hour = max(0, actual_hour - 1)

                ts = date.replace(
                    hour=actual_hour,
                    minute=actual_minute,
                    second=0,
                    microsecond=0,
                )
                rows.append((
                    person_id,
                    ts.strftime("%Y-%m-%dT%H:%M:%S"),
                    date_str,
                    actual_hour,
                    actual_minute,
                    activity,
                    round(random.uniform(0.78, 0.99), 3),
                ))

    conn.executemany(
        "INSERT INTO activity_log "
        "(person_id, timestamp, date, hour, minute, activity, confidence) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)


def seed_active_alert(conn: sqlite3.Connection, person_id: str, ref_date: datetime) -> None:
    date_str = ref_date.strftime("%Y-%m-%d")
    ts_fall = ref_date.replace(hour=10, minute=23, second=0, microsecond=0)

    conn.execute(
        "INSERT INTO activity_log "
        "(person_id, timestamp, date, hour, minute, activity, confidence) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            person_id,
            ts_fall.strftime("%Y-%m-%dT%H:%M:%S"),
            date_str,
            10,
            23,
            "fallen",
            0.951,
        ),
    )

    conn.execute(
        "INSERT OR REPLACE INTO active_alerts (person_id, alert_type, triggered_at) "
        "VALUES (?, ?, ?)",
        (person_id, "FALLEN", ts_fall.strftime("%Y-%m-%dT%H:%M:%S")),
    )
    logger.info("Active alert seeded for %s (fallen at 10:23, confidence=0.951)", person_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed CareWatch demo DB")
    parser.add_argument("--num-residents", type=int, default=1000)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--include-today", action="store_true")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--db-path", default="data/carewatch.db")
    parser.add_argument("--seed-active-alert", type=str, default="resident_0042",
                        metavar="PERSON_ID")
    args = parser.parse_args()

    conn = get_db(args.db_path)

    if args.reset:
        reset_tables(conn)

    ref_date = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    total_rows = 0
    for i in range(1, args.num_residents + 1):
        person_id = f"resident_{i:04d}"
        count = seed_resident(conn, person_id, args.days, args.include_today, ref_date)
        total_rows += count
        if i % 100 == 0:
            conn.commit()
            logger.info("  %d / %d residents seeded...", i, args.num_residents)

    conn.commit()
    logger.info("activity_log: %d rows inserted across %d residents.", total_rows, args.num_residents)

    if args.seed_active_alert:
        alert_date = ref_date if args.include_today else ref_date - timedelta(days=1)
        seed_resident(conn, args.seed_active_alert, args.days, args.include_today, ref_date)
        seed_active_alert(conn, args.seed_active_alert, alert_date)
        conn.commit()

    conn.close()

    logger.info("")
    logger.info("Done. Next steps:")
    logger.info("  python build_baselines_bulk.py")
    logger.info("  python run_pipeline.py --find-red --no-alert")


if __name__ == "__main__":
    main()