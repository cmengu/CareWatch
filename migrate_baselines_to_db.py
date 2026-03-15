"""
migrate_baselines_to_db.py
==========================
Run once: python migrate_baselines_to_db.py

Reads all existing JSON baseline files from data/baselines/, inserts into the
baselines table in data/carewatch.db, deletes JSON files after verification.
"""

import json
import os
import sqlite3
from pathlib import Path

BASELINE_DIR = "data/baselines"
DB_PATH      = "data/carewatch.db"


def migrate():
    files  = list(Path(BASELINE_DIR).glob("*.json"))
    print(f"[MIGRATE] Found {len(files)} JSON baseline files")

    conn = sqlite3.connect(DB_PATH)
    inserted = 0
    failed   = []

    for path in files:
        try:
            with open(path) as f:
                profile = json.load(f)
            person_id = profile["person_id"]
            conn.execute("""
                INSERT OR REPLACE INTO baselines (person_id, built_at, profile)
                VALUES (?, ?, ?)
            """, (person_id, profile["built_at"], json.dumps(profile)))
            inserted += 1
        except Exception as e:
            failed.append((str(path), str(e)))

    conn.commit()

    # Verify count before deleting files
    count = conn.execute("SELECT COUNT(*) FROM baselines").fetchone()[0]
    conn.close()

    print(f"[MIGRATE] {inserted} files inserted. DB now has {count} baseline rows.")

    if failed:
        print(f"[WARN] {len(failed)} failed — NOT deleting any files")
        for path, err in failed[:5]:
            print(f"  {path}: {err}")
        return

    # Delete JSON files only after DB count verified
    assert count >= inserted, "DB count less than inserted — aborting file deletion"
    for path in files:
        os.remove(path)
    print(f"[MIGRATE] {len(files)} JSON files deleted. data/baselines/ can be removed.")


if __name__ == "__main__":
    migrate()
