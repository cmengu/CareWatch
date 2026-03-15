"""
build_baselines_bulk.py
======================
Builds a personalised baseline for every resident in activity_log (saves to SQLite).
Run from repo root: python build_baselines_bulk.py
"""

import sqlite3

from src.baseline_builder import BaselineBuilder

# 1. get all unique person_ids from the database
conn = sqlite3.connect("data/carewatch.db")
ids  = [r[0] for r in conn.execute(
    "SELECT DISTINCT person_id FROM activity_log"
).fetchall()]
conn.close()

# 2. build a personalised baseline for each resident (saves to baselines table)
builder = BaselineBuilder()
for pid in ids:
    builder.build_baseline(pid)
