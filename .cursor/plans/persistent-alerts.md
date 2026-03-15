# Persistent RED Alerts + Telegram `/clear` Plan

**Overall Progress:** `100%`

## TLDR
Adds persistent alert state to CareWatch. A fall detected on Tuesday stays RED on Wednesday until a caregiver sends `/clear resident_0042` in Telegram. Three changes: new `AlertStore` class (new file), two-line modification to `DeviationDetector.__init__` and `check()`, new `TelegramListener` (new file).

---

## Critical Decisions

- `active_alerts` lives in `data/carewatch.db` — same DB as `activity_log`, same relative path `"data/carewatch.db"` matching `ActivityLogger.DB_PATH`
- Soft delete — `cleared_at` timestamp, never hard delete — audit trail required for elder care
- One uncleared alert per resident max — enforced by partial unique index
- Polling not webhooks — no server required, consistent with existing script-based architecture
- `TelegramListener` reuses token/chat_id from env vars with same dotenv load pattern as `AlertSystem`

---

## Clarification Gate

| Unknown | Required | Source | Resolved |
|---------|----------|--------|----------|
| `RiskResult` field names | Confirmed: `risk_score`, `risk_level`, `anomalies`, `summary`, `checked_at` | models.py | ✅ |
| `anomalies` type | Confirmed: `List[Union[AnomalyItem, str]]` — must use `AnomalyItem(...)` not raw dicts | models.py | ✅ |
| `AlertSystem` dotenv loading | Confirmed: loads at module level via `dotenv` | alert_system.py | ✅ |
| `ActivityLogger.DB_PATH` | Confirmed: `"data/carewatch.db"` — relative string, not `__file__`-based | logger.py | ✅ |
| Fall detection block end line | Confirmed: ends at `return RiskResult(risk_score=100, risk_level="RED"...` first occurrence in `check()` | deviation_detector.py | ✅ |

---

## Agent Failure Protocol

1. A verification command fails → read the full error output.
2. Cause is unambiguous → make ONE targeted fix → re-run the same verification command.
3. If still failing after one fix → **STOP**. Output full contents of every file modified. Report: (a) command run, (b) full error verbatim, (c) fix attempted, (d) current state of each modified file, (e) why you cannot proceed.
4. Never attempt a second fix without human instruction.
5. Never modify files not named in the current step.

---

## Pre-Flight

```bash
grep -n "def check\|def __init__\|from src" src/deviation_detector.py
grep -n "active_alerts" src/*.py 2>/dev/null || echo "active_alerts does not exist yet"
sqlite3 data/carewatch.db ".tables"
wc -l src/alert_store.py 2>/dev/null || echo "alert_store.py does not exist yet"
wc -l src/telegram_listener.py 2>/dev/null || echo "telegram_listener.py does not exist yet"
```

**Baseline Snapshot (fill before Step 1):**
```
Tables in carewatch.db:         ____
active_alerts exists:           no
alert_store.py exists:          no
telegram_listener.py exists:    no
DeviationDetector.__init__ imports: ____
```

---

## Phase 1 — Persistent Alert State

**Goal:** `DeviationDetector.check("resident_0042")` returns RED on any day after a fall until a human clears it.

---

- [x] 🟩 **Step 1: Create `src/alert_store.py`** — *Critical: Steps 2 and 3 both depend on this*

  **Idempotent:** Yes — `CREATE TABLE IF NOT EXISTS` and `CREATE UNIQUE INDEX IF NOT EXISTS`

  **Context:** New file. No existing file to modify. Creates the `active_alerts` table and exposes three methods: `raise_alert`, `clear_alert`, `has_active_alert`.

  **DB_PATH must match `ActivityLogger` exactly.** `logger.py` uses `DB_PATH = "data/carewatch.db"` as a relative string. `AlertStore` must use the identical string — not a `__file__`-relative `os.path.join` — or they connect to different files depending on working directory.

  ```python
  # src/alert_store.py
  import sqlite3
  import os
  from datetime import datetime

  DB_PATH = "data/carewatch.db"  # must match ActivityLogger.DB_PATH exactly


  class AlertStore:
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
  ```

  **✓ Verification:**
  ```python
  # Save as verify_step1.py, run python verify_step1.py, then delete it
  from src.alert_store import AlertStore
  store = AlertStore()

  store.clear_alert("_test_resident")  # clean slate if leftover from prior run

  assert store.has_active_alert("_test_resident") is None, "should be empty"
  result1 = store.raise_alert("_test_resident", "FALLEN")
  assert result1 is True, "first raise should return True"
  assert store.has_active_alert("_test_resident") is not None, "alert should exist"
  result2 = store.raise_alert("_test_resident", "FALLEN")
  assert result2 is False, "duplicate raise should return False"
  cleared = store.clear_alert("_test_resident")
  assert cleared is True, "clear should return True"
  assert store.has_active_alert("_test_resident") is None, "should be empty after clear"
  print("PASS — AlertStore Step 1 verified")
  ```

  **Pass:** Prints `PASS — AlertStore Step 1 verified`
  **Fail:**
  - `IntegrityError` on table creation → partial index syntax unsupported on SQLite < 3.8 → run `sqlite3 --version` and upgrade if needed
  - Second `raise_alert` returns `True` → unique index not created → check `_ensure_table` ran

---

- [x] 🟩 **Step 2: Wire `AlertStore` into `DeviationDetector`** — *Critical: modifies existing production logic*

  **Idempotent:** Yes — adds new checks, does not restructure existing flow

  **Pre-Read Gate:**
  ```bash
  grep -n "from src\|import" src/deviation_detector.py | head -10
  # Must confirm: AnomalyItem and RiskResult are already imported
  # If not present, add: from src.models import AnomalyItem, RiskResult
  grep -n "def __init__" src/deviation_detector.py
  # Must return exactly 1 match
  grep -n "return RiskResult(risk_score=100" src/deviation_detector.py
  # Must return exactly 1 match — this is the insertion point anchor for raise_alert
  ```

  **Two edits. Both are additive — nothing is deleted or replaced.**

  **Edit A — add to `__init__` body** (after `self.builder = BaselineBuilder(self.logger)`):
  ```python
  from src.alert_store import AlertStore
  # Add this line inside __init__, after self.builder = BaselineBuilder(self.logger):
  self.alert_store = AlertStore()
  ```

  **Edit B — add persistent alert check as FIRST line of `check()` body**, before the existing `last = self.logger.get_last_activity(person_id)` line:
  ```python
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
  ```

  **Edit C — add `raise_alert` call immediately before the fall detection return.**
  The anchor is the line: `return RiskResult(risk_score=100, risk_level="RED"` — the first occurrence in `check()`.
  Explicit BEFORE/AFTER diff (insert new line above return; return unchanged):

  BEFORE:
  ```python
          if last and last["activity"] == "fallen" and last["confidence"] > 0.85:
              return RiskResult(...)
  ```

  AFTER:
  ```python
          if last and last["activity"] == "fallen" and last["confidence"] > 0.85:
              self.alert_store.raise_alert(person_id, "FALLEN")
              return RiskResult(...)
  ```

  **✓ Verification:**
  ```python
  # Save as verify_step2.py, run python verify_step2.py, then delete it
  from src.alert_store import AlertStore
  from src.deviation_detector import DeviationDetector

  store    = AlertStore()
  detector = DeviationDetector()

  store.clear_alert("_test_resident")  # clean slate
  store.raise_alert("_test_resident", "FALLEN")

  result = detector.check("_test_resident")
  assert result.risk_level == "RED", f"expected RED, got {result.risk_level}"
  assert result.risk_score == 100
  assert any(a.type == "UNCLEARED" for a in result.anomalies if hasattr(a, "type")), \
      "UNCLEARED anomaly not found"

  store.clear_alert("_test_resident")
  result2 = detector.check("_test_resident")
  assert result2.anomalies == [] or not any(
      hasattr(a, "type") and a.type == "UNCLEARED" for a in result2.anomalies
  ), "UNCLEARED still present after clear"

  print("PASS — DeviationDetector Step 2 verified")
  ```

  **Pass:** Prints `PASS`
  **Fail:**
  - `ValidationError` on `AnomalyItem` → confirm `AnomalyItem` is imported in `deviation_detector.py`
  - `AttributeError: alert_store` → Edit A not applied — check `__init__`

---

## Phase 2 — Telegram `/clear` Command

**Goal:** Caregiver sends `/clear resident_0042` in Telegram. Bot receives it, calls `clear_alert()`, confirms back.

---

- [x] 🟩 **Step 3: Create `src/telegram_listener.py`** — *Critical: new capability, touches network*

  **Idempotent:** Yes — polling loop is stateless, safe to restart

  **Context:** `AlertSystem` already sends outbound messages. This file adds inbound polling. Token/chat_id loaded identically to `AlertSystem` — same env vars, same dotenv path — so credentials are always consistent.

  ```python
  # src/telegram_listener.py
  import os
  import time
  import requests
  from pathlib import Path
  from src.alert_store import AlertStore

  # Load .env from repo root — identical pattern to alert_system.py
  _env_path = Path(__file__).resolve().parents[1] / ".env"
  if _env_path.exists():
      try:
          from dotenv import load_dotenv
          load_dotenv(_env_path)
      except ImportError:
          pass

  TELEGRAM_API = "https://api.telegram.org/bot{token}"


  class TelegramListener:
      def __init__(self):
          self.token   = os.environ.get("CAREWATCH_BOT_TOKEN", "")
          self.chat_id = os.environ.get("CAREWATCH_CHAT_ID", "")
          self.store   = AlertStore()
          self.offset  = 0

          if not self.token or not self.chat_id:
              raise EnvironmentError(
                  "CAREWATCH_BOT_TOKEN and CAREWATCH_CHAT_ID must be set. "
                  "Check your .env file or export them manually."
              )

      def _get_updates(self) -> list:
          url = f"{TELEGRAM_API.format(token=self.token)}/getUpdates"
          try:
              r = requests.get(url, params={"offset": self.offset, "timeout": 10})
              return r.json().get("result", [])
          except Exception as e:
              print(f"[TELEGRAM] Poll error: {e}")
              return []

      def _send(self, text: str):
          url = f"{TELEGRAM_API.format(token=self.token)}/sendMessage"
          requests.post(url, json={"chat_id": self.chat_id, "text": text})

      def _handle(self, message: dict):
          text = message.get("text", "").strip()
          if not text.startswith("/clear"):
              return
          parts = text.split()
          if len(parts) != 2:
              self._send("Usage: /clear <person_id>   e.g. /clear resident_0042")
              return
          person_id = parts[1]
          cleared   = self.store.clear_alert(person_id)
          if cleared:
              self._send(f"Alert cleared for {person_id}. Resuming normal monitoring.")
          else:
              self._send(f"No active alert found for {person_id}.")

      def poll(self, interval_seconds: int = 5):
          """Blocking loop. Run in a background thread or separate terminal."""
          print("[TELEGRAM] Listener started. Waiting for /clear commands...")
          while True:
              updates = self._get_updates()
              for update in updates:
                  self.offset = update["update_id"] + 1
                  msg = update.get("message", {})
                  if msg:
                      self._handle(msg)
              time.sleep(interval_seconds)
  ```

  **✓ Verification (two-terminal test):**

  Terminal 1 — start the listener:
  ```bash
  python -c "from src.telegram_listener import TelegramListener; TelegramListener().poll()"
  ```
  Confirm it prints: `[TELEGRAM] Listener started. Waiting for /clear commands...`
  If it throws `EnvironmentError` → env vars not set → check `.env` file.

  Terminal 2 — raise a test alert then send the clear command:
  ```bash
  python -c "from src.alert_store import AlertStore; AlertStore().raise_alert('_test_resident', 'FALLEN'); print('alert raised')"
  ```
  Send `/clear _test_resident` in the Telegram chat.

  Terminal 2 — verify DB:
  ```bash
  sqlite3 data/carewatch.db "SELECT person_id, cleared_at FROM active_alerts WHERE person_id='_test_resident';"
  ```

  **Pass:** `cleared_at` column is not null
  **Fail:**
  - `cleared_at` is null → listener running but `/clear` not received → confirm bot is in the correct chat
  - `EnvironmentError` on startup → credentials missing → check `.env` or `export` commands

---

## Regression Guard

| System | Pre-change behavior | Post-change verification |
|--------|---------------------|--------------------------|
| `DeviationDetector.check()` on GREEN day | Returns GREEN | After Step 2, run `detector.check("resident_0000")` with no active alert — must not return RED |
| `AlertSystem.send()` | Sends outbound Telegram | Unchanged — `alert_system.py` not touched in this plan |
| `activity_log` table | Unchanged | `sqlite3 data/carewatch.db ".tables"` — must still show `activity_log` |

---

## Rollback

```bash
sqlite3 data/carewatch.db "DROP TABLE IF EXISTS active_alerts;"
git checkout src/deviation_detector.py
rm -f src/alert_store.py src/telegram_listener.py
```

---

## Success Criteria

| Feature | Verification |
|---------|-------------|
| Fall persists as RED next day | `raise_alert("x")` → next day `check("x")` → `risk_level == RED` |
| Duplicate fall is no-op | `raise_alert("x")` twice → `SELECT COUNT(*) FROM active_alerts WHERE person_id='x' AND cleared_at IS NULL` = 1 |
| `/clear` resolves alert | Send in Telegram → `cleared_at` not null in DB |
| Post-clear returns to baseline comparison | After clear, `check()` runs normally — no UNCLEARED anomaly |
| Audit trail preserved | `SELECT * FROM active_alerts` — cleared rows remain with timestamp and cleared_by |
| Normal day unaffected | `check("resident_with_no_alert")` still returns GREEN on a normal day |