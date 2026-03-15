# CareWatch — Phase 1 Close-the-Loop Plan

**Overall Progress:** `85%` ▓▓▓▓▓▓▓▓░░░

---

## TLDR

Nothing produced this session has been placed in the repo yet. This plan writes
`data/drug_interactions.txt` and `run_pipeline.py` directly into the repo using
embedded code blocks — no `cp` commands. It fixes three confirmed bugs before the
first run: the CUSUM `.label` crash, a silent date-mismatch GREEN result for `--all`
mode, and a suppression-cooldown silent failure for Telegram. After this plan
executes, `python run_pipeline.py --find-red` completes and a RED Telegram alert
arrives in the configured chat.

---

## CTO Review — Decisions Log

> All flaws found during pre-refinement review. Every item is resolved in the steps
> below. Carried here as a permanent record.

| # | Flaw | Severity | File confirmed by | Resolution |
|---|------|----------|-------------------|------------|
| 1 | `run_pipeline.py` calls `cusum.get('label', '?')` — `.label` does not exist on `CUSUMCheckResult` | **Blocker** | `src/cusum_monitor.py` | Fixed in embedded `run_pipeline.py` in Step 1.2 — uses `.summary` only |
| 2 | `get_today()` filters by `datetime.now().date()` — mock data is 7 days old, so `today_logs` is always empty → all non-alert residents silently return GREEN | **Blocker for `--all`** | `src/logger.py` | `--find-red` unaffected (persistent alert check fires before `get_today()` is called). `--all` mode noted as unreliable until data is refreshed. Step 1.5A uses `--find-red` only. |
| 3 | `AlertSuppressionLayer` has 5-minute RED cooldown. Phase B exits 0, logs success, but no Telegram fires if a previous run happened within the window | **Blocker for Phase B** | `src/suppression.py` | Step 1.5 Phase A includes a suppression state check before Phase B is authorised |
| 4 | Comment lines with `:` in drug_interactions.txt loaded as ChromaDB docs — count 48 vs 47 | **Blocker** | `src/knowledge_base.py` | Step 1.2.5: add `if line.startswith("#"): continue` before `":"` check |
| 5 | `alert_suppression` table never created — `.send()` raises `OperationalError` | **Blocker** | `src/suppression.py` | Step 1.3.5: add `_ensure_table()` to `AlertSuppressionLayer.__init__` |
| 6 | `audit_logger.compute_trend()` return shape assumed — not confirmed | Resolved | `src/audit_logger.py` | Returns `{"label": str, "history": str, "count": int}` — both keys agent.py uses exist |
| 7 | `CUSUMCheckResult` serialised keys — full dict shape not confirmed | Resolved | `src/cusum_monitor.py` | Keys confirmed: `person_id, checked_at, any_signal_detected, signals, skipped_signals, summary` |

---

## Critical Decisions

- **No `cp` commands** — every file is written verbatim using the code blocks in each step.
- **CUSUM bug fixed inside the embedded file** — `run_pipeline.py` is written with the fix already applied. No post-placement edit required.
- **`--find-red` only for E2E test** — `--all` mode silently returns GREEN for all residents because mock data dates don't match today. This is a known architectural limitation, not a bug to fix in this plan. Document it, do not fix it here.
- **Suppression state check before Phase B** — if suppression state is in-memory, restarting the process resets it. If it is persisted (SQLite/file), it must be checked. Step 1.5 handles both cases.

---

## Clarification Gate

| Unknown | Required | Source | Blocking | Resolved |
|---------|----------|--------|----------|----------|
| `CUSUMCheckResult` fields | Confirmed: `summary` yes, `label` no | `src/cusum_monitor.py` | Step 1.2 | ✅ |
| `AlertSuppressionLayer.send()` signature | `(risk_result: dict, person_name: str, resident_id: str)` | Human | Step 1.4 verify | ✅ |
| `audit_logger` return shape | `{"label": str, "history": str, "count": int}` | `src/audit_logger.py` | Step 1.4 verify | ✅ |
| `get_today()` date filter | Filters by `datetime.now().date()` — mock data excluded | `src/logger.py` | Step 1.5 scope | ✅ |
| Suppression cooldown | 5-min RED window, `{"fired": False, "suppressed": True}` on second call | `src/suppression.py` | Step 1.5B | ✅ |
| Suppression state storage | In-memory vs persisted — **not confirmed** | Not provided | Step 1.5 check | ⚠️ UNVERIFIABLE — handled by check in Step 1.5A |

---

## Agent Failure Protocol

1. A verification command fails → read the full error output.
2. Cause is unambiguous → make ONE targeted fix → re-run the same verification command.
3. If still failing after one fix → **STOP**. Output full contents of every file modified in this step. Report: (a) command run, (b) full error verbatim, (c) fix attempted, (d) current state of each modified file, (e) why you cannot proceed.
4. Never attempt a second fix without human instruction.
5. Never modify files not named in the current step.

---

## Pre-Flight — Run Before Any Code Changes

```bash
# 1. Confirm mock data and baselines exist
sqlite3 data/carewatch.db \
  "SELECT COUNT(DISTINCT person_id), COUNT(*) FROM activity_log;"
# Expected: 1000|~188000

sqlite3 data/carewatch.db "SELECT COUNT(*) FROM baselines;"
# Expected: 1000

# 2. Confirm at least one uncleared fall alert exists (required for --find-red)
sqlite3 data/carewatch.db \
  "SELECT person_id, alert_type, triggered_at \
   FROM active_alerts WHERE cleared_at IS NULL LIMIT 3;"
# Expected: 1-3 rows with alert_type=FALLEN
# If 0 rows: STOP. Re-run generate_mock_data.py --reset then build_baselines_bulk.py

# 3. Confirm chroma_db exists (stale data is fine — Step 1.3 rebuilds it)
ls data/chroma_db/
# Expected: UUID subdirectories + chroma.sqlite3

# 4. Confirm env vars
python -c "
import os
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv(Path('.env'))
except ImportError:
    pass
for k in ['GROQ_API_KEY', 'CAREWATCH_BOT_TOKEN', 'CAREWATCH_CHAT_ID']:
    v = os.environ.get(k, '')
    print(k, '✅' if v else '❌ MISSING')
"
# Expected: all three ✅

# 5. Confirm neither target file exists (will be written fresh in Steps 1.1-1.2)
ls run_pipeline.py 2>/dev/null \
  && echo "EXISTS — will overwrite" || echo "NOT PRESENT — expected"
ls data/drug_interactions.txt 2>/dev/null \
  && echo "EXISTS — will overwrite" || echo "NOT PRESENT — expected"

# 6. Confirm alert_suppression table (created by Step 1.3.5 — run after that step)
sqlite3 data/carewatch.db \
  "SELECT name FROM sqlite_master WHERE type='table' AND name='alert_suppression';"
# Expected after Step 1.3.5: alert_suppression
# Before Step 1.3.5: empty — expected
```

**Baseline Snapshot (agent fills during pre-flight):**
```
activity_log rows:            ____
baselines table rows:         ____
active RED alerts:            ____
chroma_db exists:             ____
GROQ_API_KEY:                 ____
CAREWATCH_BOT_TOKEN:          ____
CAREWATCH_CHAT_ID:            ____
run_pipeline.py exists:       ____
drug_interactions.txt exists: ____
```

**All must be confirmed before Step 1.1:**
- [ ] `activity_log` ~188k rows, 1000 residents
- [ ] `baselines` table has 1000 rows
- [ ] At least 1 uncleared active alert — if 0, STOP and re-seed
- [ ] All 3 env vars ✅
- [ ] `data/chroma_db/` exists

---

## Tasks

### Phase 1 — Close the Loop

**Goal:** `python run_pipeline.py --find-red` completes exit 0 and a RED Telegram alert arrives.

---

- [ ] 🟥 **Step 1.1: Write `data/drug_interactions.txt`** — *Non-critical: new file, no existing code touched*

  **Idempotent:** Yes — writing a text file is always safe to repeat.

  **Context:** `knowledge_base.py` reads `data/drug_interactions.txt` line by line,
  skipping blank lines and `#` comments, and loads every `topic: detail` line as a
  ChromaDB document. This file merges your original medication facts with the broader
  care protocols. Must exist before Step 1.3 rebuilds ChromaDB.

  **Pre-Read Gate:**
  ```bash
  ls data/
  # Must show carewatch.db — confirms data/ exists.
  sqlite3 data/carewatch.db "SELECT COUNT(*) FROM baselines;"
  # Must return 1000 — run build_baselines_bulk.py first if 0.
  ```

  Write the following content to `data/drug_interactions.txt`:

  ```text
  # CareWatch Knowledge Base
  # Format: topic: detail
  # Blank lines and # lines are skipped by knowledge_base.py

  metformin: Take with food. Missing a dose for a diabetic elderly patient increases risk of hyperglycemia. Critical to take consistently.
  warfarin: Blood thinner. Missing doses causes stroke risk. Must be taken at the same time daily. Interaction with aspirin increases bleeding risk.
  lisinopril: Blood pressure medication. Missing doses can cause dangerous blood pressure spikes in elderly patients.
  amlodipine: Calcium channel blocker for blood pressure. Dizziness and falls are common side effects especially in elderly.
  atorvastatin: Cholesterol medication. Evening dose preferred. Missing occasional doses less critical than blood pressure meds.
  aspirin: Daily low-dose aspirin for heart patients. Do not combine with warfarin without doctor approval.
  omeprazole: Stomach acid reducer. Take 30 minutes before breakfast. Missing doses causes acid reflux discomfort.
  general_missed_doses: Elderly patients missing more than 2 doses of any critical medication should be flagged for family follow-up.
  general_inactivity: Inactivity exceeding 4 hours during waking hours 7am to 9pm is a fall risk indicator in elderly patients.
  general_routine_change: Sudden change in routine such as eating or walking patterns in elderly can indicate onset of infection or depression.
  fallen_assessment: Any fall in elderly patient requires immediate medical assessment even if patient appears uninjured.
  pill_taking_missed_critical: Missed pill-taking activity combined with risk score above 60 requires family notification within 1 hour.
  fall_response_immediate: If a fall is detected, do not attempt to move the resident. Call emergency services (995 in Singapore) if the resident is unresponsive, bleeding, or complaining of head or hip pain.
  fall_response_conscious: If resident is conscious and alert after a fall, keep them calm and warm. Do not leave them alone. Check for pain in hip, wrist, or head before assisting them to stand.
  fall_risk_hip_fracture: Hip fracture is the most dangerous fall complication in elderly patients. Risk increases significantly after age 75. Signs include inability to bear weight, shortened or rotated leg, severe groin pain.
  fall_risk_head_injury: Head injury after a fall can be silent. Watch for confusion, vomiting, unequal pupils, or drowsiness in the 24 hours following any fall. Seek immediate medical attention if observed.
  fall_risk_medication: Medications that increase fall risk include sedatives, antihypertensives, diuretics, antidepressants, and antipsychotics. A pharmacist review is recommended after any fall event.
  fall_risk_dehydration: Dehydration causes dizziness and orthostatic hypotension in elderly patients, significantly increasing fall risk. Encourage 6-8 glasses of water daily.
  fall_risk_lying_down_extended: Prolonged lying down more than 2 consecutive hours outside sleep hours may indicate post-fall inability to rise, acute illness, or extreme fatigue. Check on resident immediately.
  fall_post_event_monitoring: After a confirmed fall, increase monitoring frequency to every 30 minutes for the first 4 hours. Document time, location, and activity at time of fall.
  fall_detection_confidence: A fall classification with confidence above 0.85 is considered a confirmed fall event. Confidence 0.70 to 0.85 is a probable fall and warrants visual confirmation.
  fall_prevention_footwear: Inappropriate footwear such as socks on smooth floors or loose slippers contributes to approximately 40% of falls in elderly residents. Recommend non-slip footwear at all times.
  pill_taking_missed_dose: A missed medication dose should be flagged to the caregiver within 1 hour of the expected administration window. Do not double-dose without consulting a pharmacist or doctor.
  pill_taking_timing_critical: For anticoagulants, antiepileptics, and Parkinson medications, timing is critical. Doses more than 2 hours late require immediate caregiver notification.
  pill_taking_morning_window: Most critical medications for elderly patients are prescribed in the morning 7 to 9am. If pill_taking activity is absent after 10am, treat as a missed dose event.
  pill_taking_interaction_warfarin_aspirin: Warfarin combined with aspirin significantly increases bleeding risk. Any fall event in a resident on anticoagulants should be treated as HIGH severity regardless of apparent injury.
  pill_taking_interaction_diuretic_fall: Diuretics increase urination frequency, causing residents to rush to the bathroom, elevating fall risk especially at night. Night-time walking combined with diuretic use warrants close monitoring.
  pill_taking_interaction_sedative_fall: Benzodiazepines and sedating antihistamines significantly impair balance in elderly patients. Walking or standing within 2 hours of sedative administration should be monitored.
  pill_taking_adherence: Medication non-adherence in elderly patients is associated with significant preventable hospitalisation. Monitoring pill-taking activity is among the highest-priority functions of CareWatch.
  eating_missed_meal: A missed meal should be flagged if eating activity is absent more than 2 hours past the resident usual mealtime. Skipping meals contributes to malnutrition, hypoglycaemia, and medication side effects.
  eating_hypoglycaemia_risk: Residents on insulin or sulfonylureas who miss meals are at serious risk of hypoglycaemia. Symptoms include confusion, sweating, shakiness, and loss of consciousness. Treat as medical emergency.
  eating_appetite_loss: Reduced appetite in elderly patients can signal depression, infection, medication side effects, or dental pain. If eating drops below 50% of baseline frequency for 3 or more consecutive days, notify caregiver.
  eating_timing_diabetic: For diabetic residents, meal timing is as important as meal content. Delays of more than 1 hour from usual mealtime combined with insulin doses can cause dangerous blood sugar fluctuations.
  walking_reduced_activity: A significant reduction in walking activity below 50% of baseline may indicate pain, fatigue, illness, or post-fall fear. Persistent reduction warrants a physiotherapy assessment.
  walking_night_fall_risk: Walking activity at night carries significantly higher fall risk than daytime walking due to reduced visibility, disorientation, and lower muscle readiness.
  sitting_prolonged_risk: Sitting for more than 4 consecutive hours increases risk of deep vein thrombosis, pressure sores, and muscle deconditioning in elderly patients. Encourage standing or brief walks hourly.
  night_wandering_definition: Night wandering is defined as walking activity detected between 10pm and 5am outside the resident normal sleep pattern. This is a common early indicator of dementia or sundowning syndrome.
  night_wandering_dementia: Night wandering is present in up to 66% of dementia patients. Increased frequency may indicate disease progression.
  night_wandering_safety: Unsupervised night wandering carries fall risk, especially in low-light conditions. Ensure pathways are clear, night lights are installed, and stairways are secured.
  night_wandering_pain: Unexplained night waking and wandering can indicate unmanaged pain such as arthritis or neuropathy. Review analgesic timing if wandering coincides with pain medication schedule.
  monitoring_anomaly_high: HIGH severity anomalies such as missed medication or confirmed fall require caregiver notification within 15 minutes.
  monitoring_anomaly_medium: MEDIUM severity anomalies such as unusual meal timing or reduced walking require caregiver notification within 1 hour.
  monitoring_trend_escalating: An escalating trend with risk score increasing over 3 or more consecutive days is a stronger concern indicator than any single day score.
  caregiver_clear_protocol: After a caregiver sends the clear command for a fall alert, a follow-up physical check must be documented within 2 hours. Digital acknowledgement alone is insufficient.
  emergency_contacts_singapore: Singapore emergency services: 995 for ambulance and fire, 999 for police. Agency for Integrated Care helpline: 1800-650-6060.
  ```

  **Git Checkpoint:**
  ```bash
  git add data/drug_interactions.txt
  git commit -m "step 1.1: add knowledge base (47 facts)"
  ```

  **✓ Verification Test:**

  **Type:** Unit

  **Action:**
  ```bash
  grep -c "^[^#].*:" data/drug_interactions.txt
  ```

  **Expected:** `47`

  **Pass:** Returns `47`

  **Fail:**
  - If `0` → file write failed or wrong path → re-write
  - If `< 47` → partial write → re-write from scratch

---

- [ ] 🟥 **Step 1.2: Write `run_pipeline.py`** — *Critical: pipeline entry point, CUSUM bug pre-fixed*

  **Idempotent:** Yes — file write is safe to repeat.

  **Context:** This is the entry point for the entire risk pipeline. The file produced
  earlier in this session contained one confirmed bug: `cusum.get('label', '?')` where
  `.label` does not exist on `CUSUMCheckResult`. The file below has this fixed before
  being written — the CUSUM print block uses `.summary` only, which is confirmed present.

  **Pre-Read Gate:**
  ```bash
  # Confirm repo root is the working directory
  ls src/agent.py
  # Must return the file. If missing: wrong directory — cd to repo root first.
  ```

  Write the following content to `run_pipeline.py` at the repo root:

  ```python
  """
  run_pipeline.py
  ================
  CareWatch pipeline entry point. Runs the full risk pipeline for one or more
  residents and fires Telegram alerts for any RED results.

  Pipeline sequence:
      1. (Once) Verify ChromaDB is initialised — rebuild if empty
      2. Resolve target resident(s) from args or active_alerts table
      3. CareWatchAgent.run(person_id) per resident
         -> DeviationDetector.check()     (deviation + persistent alert check)
         -> ResidentCUSUMMonitor.check()  (trend detection)
         -> RAGRetriever.get_context()    (ChromaDB knowledge retrieval)
         -> explain_risk()               (Groq LLM explanation + self-check)
         -> AlertSuppressionLayer.send() (Telegram, YELLOW/RED only)
      4. Print structured summary to stdout

  KNOWN LIMITATION:
      --all mode runs DeviationDetector.check() for every resident, but
      get_today() filters activity_log by datetime.now().date(). Mock data
      was generated for past dates, so today_logs is always empty and all
      non-alert residents return GREEN. Use --find-red for reliable E2E testing.
      To use --all with real results, re-run generate_mock_data.py without --reset
      so it writes rows dated today, or run the live camera pipeline.

  USAGE:
      # Find first resident with active RED alert and fire Telegram:
      python run_pipeline.py --find-red

      # Dry run — no Telegram:
      python run_pipeline.py --find-red --no-alert

      # Specific resident:
      python run_pipeline.py --resident resident_0042 --no-alert

      # Batch (GREEN for all unless active alert exists — see KNOWN LIMITATION):
      python run_pipeline.py --all --no-alert

  REQUIRES:
      .env: GROQ_API_KEY, CAREWATCH_BOT_TOKEN, CAREWATCH_CHAT_ID
      data/carewatch.db       (run generate_mock_data.py first)
      baselines table         (run build_baselines_bulk.py first — 1000 rows)
      data/chroma_db/         (auto-rebuilt if missing)
  """

  import argparse
  import logging
  import sqlite3
  import sys
  from datetime import datetime
  from pathlib import Path

  # Logging setup before any src imports
  logging.basicConfig(
      level=logging.INFO,
      format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
      datefmt="%H:%M:%S",
  )
  logger = logging.getLogger("run_pipeline")

  # Load .env from repo root
  _env_path = Path(__file__).resolve().parent / ".env"
  if _env_path.exists():
      try:
          from dotenv import load_dotenv
          load_dotenv(_env_path)
          logger.info(".env loaded from %s", _env_path)
      except ImportError:
          logger.warning("python-dotenv not installed — set env vars manually")

  DB_PATH     = "data/carewatch.db"
  CHROMA_PATH = Path("data/chroma_db")
  FACTS_PATH  = Path("data/drug_interactions.txt")


  # ── ChromaDB bootstrap ──────────────────────────────────────────────────────

  def _ensure_chroma() -> bool:
      """
      Check ChromaDB collection exists and has documents.
      Rebuilds from data/drug_interactions.txt if empty or missing.
      Returns True if RAG available, False if it should be skipped.
      """
      try:
          import chromadb
      except ImportError:
          logger.warning("chromadb not installed — RAG skipped. pip install chromadb")
          return False

      try:
          client = chromadb.PersistentClient(path=str(CHROMA_PATH))
          try:
              col   = client.get_collection("carewatch_knowledge")
              count = col.count()
              if count > 0:
                  logger.info("ChromaDB ready: %d documents", count)
                  return True
              logger.warning("ChromaDB empty — rebuilding from %s", FACTS_PATH)
          except Exception:
              logger.warning("ChromaDB collection missing — building from %s", FACTS_PATH)

          if not FACTS_PATH.exists():
              logger.error(
                  "Cannot build ChromaDB: %s not found. "
                  "Complete Step 1.1 first.",
                  FACTS_PATH,
              )
              return False

          from src.knowledge_base import build_knowledge_base
          build_knowledge_base()
          logger.info("ChromaDB rebuilt successfully")
          return True

      except Exception as e:
          logger.warning("ChromaDB init failed (%s) — continuing without RAG", e)
          return False


  # ── Resident resolution ─────────────────────────────────────────────────────

  def _find_red_resident() -> str | None:
      """Return person_id of first resident with an uncleared active alert."""
      try:
          conn = sqlite3.connect(DB_PATH)
          row  = conn.execute(
              "SELECT person_id FROM active_alerts "
              "WHERE cleared_at IS NULL ORDER BY triggered_at ASC LIMIT 1"
          ).fetchone()
          conn.close()
          return row[0] if row else None
      except Exception as e:
          logger.error("Could not query active_alerts: %s", e)
          return None


  def _all_residents() -> list[str]:
      """Return all distinct person_ids from activity_log."""
      try:
          conn = sqlite3.connect(DB_PATH)
          rows = conn.execute(
              "SELECT DISTINCT person_id FROM activity_log ORDER BY person_id"
          ).fetchall()
          conn.close()
          return [r[0] for r in rows]
      except Exception as e:
          logger.error("Could not query activity_log: %s", e)
          return []


  # ── Result printing ─────────────────────────────────────────────────────────

  _LEVEL_COLOR = {
      "GREEN":   "\033[92m",
      "YELLOW":  "\033[93m",
      "RED":     "\033[91m",
      "UNKNOWN": "\033[90m",
  }
  _RESET    = "\033[0m"
  _SEV_ICON = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🔵"}


  def _print_result(result, person_id: str) -> None:
      """Pretty-print an AgentResult to stdout."""
      level = result.risk_level
      score = result.risk_score
      color = _LEVEL_COLOR.get(level, "")
      rag   = "✅ yes" if result.rag_context_used else "❌ no"
      conf  = result.confidence

      print()
      print("=" * 60)
      print(f"  CareWatch — {person_id.replace('_', ' ').title()}")
      print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
      print("=" * 60)
      print(f"  Risk:       {color}{level}{_RESET}  ({score}/100)")
      print(f"  RAG used:   {rag}")
      print(f"  Confidence: {conf}")
      print()

      if result.error:
          print(f"  ⚠  Pipeline error: {result.error}")
          print()

      print(f"  Summary: {result.summary}")
      print()

      if result.anomalies:
          print("  Anomalies detected:")
          for a in result.anomalies:
              if isinstance(a, dict):
                  icon = _SEV_ICON.get(a.get("severity", ""), "⚪")
                  print(f"    {icon}  [{a.get('type', '?')}] {a.get('message', '')}")
              else:
                  print(f"    ⚪  {a}")
          print()

      ai = result.ai_explanation
      if ai:
          print("  AI Explanation:")
          print(f"    {ai.summary}")
          print(f"    Concern : {ai.concern_level}")
          print(f"    Action  : {ai.action}")
          print(f"    Positive: {ai.positive}")
          print()

      # CUSUM: uses .summary only — .label does not exist on CUSUMCheckResult
      if result.cusum_result:
          cusum = result.cusum_result
          print(f"  CUSUM trend: {cusum.get('summary', 'no summary')}")
          print()

      print("=" * 60)
      print()


  # ── Args ────────────────────────────────────────────────────────────────────

  def _parse_args() -> argparse.Namespace:
      p = argparse.ArgumentParser(description="CareWatch risk pipeline")
      group = p.add_mutually_exclusive_group(required=True)
      group.add_argument("--resident",  metavar="ID",
                         help="Run for a specific person_id")
      group.add_argument("--find-red",  action="store_true",
                         help="Auto-find first resident with active RED alert")
      group.add_argument("--all",       action="store_true",
                         help="Run for every resident in the DB (see KNOWN LIMITATION)")
      p.add_argument("--no-alert",   action="store_true",
                     help="Dry run — skip Telegram alerts")
      p.add_argument("--skip-chroma", action="store_true",
                     help="Skip ChromaDB bootstrap check")
      return p.parse_args()


  # ── Main ────────────────────────────────────────────────────────────────────

  def main() -> int:
      args = _parse_args()

      # Step 0 — ChromaDB
      if not args.skip_chroma:
          logger.info("Step 0 — checking ChromaDB …")
          _ensure_chroma()
      else:
          logger.info("Step 0 — ChromaDB check skipped (--skip-chroma)")

      # Step 1 — Resolve targets
      logger.info("Step 1 — resolving target resident(s) …")

      if args.resident:
          targets = [args.resident]
          logger.info("Target: %s (explicit)", args.resident)

      elif args.find_red:
          pid = _find_red_resident()
          if not pid:
              logger.warning(
                  "No uncleared RED alerts found in active_alerts.\n"
                  "Tip: verify with: sqlite3 data/carewatch.db "
                  "\"SELECT * FROM active_alerts WHERE cleared_at IS NULL LIMIT 5;\""
              )
              return 1
          targets = [pid]
          logger.info("Target: %s (first active RED alert)", pid)

      else:  # --all
          targets = _all_residents()
          if not targets:
              logger.error(
                  "No residents found in activity_log. "
                  "Run generate_mock_data.py first."
              )
              return 1
          logger.warning(
              "--all mode: get_today() filters by today's date. "
              "Mock data is from past dates so today_logs is empty. "
              "All non-alert residents will return GREEN. "
              "See KNOWN LIMITATION in module docstring."
          )
          logger.info("Batch mode: %d residents", len(targets))

      # Step 2 — Import agent
      try:
          from src.agent import CareWatchAgent
      except Exception as e:
          logger.error("Failed to import CareWatchAgent: %s", e)
          return 1

      agent      = CareWatchAgent()
      send_alert = not args.no_alert

      if args.no_alert:
          logger.info("Dry run — Telegram alerts suppressed")

      # Step 3 — Run pipeline
      results = []
      errors  = 0

      for i, person_id in enumerate(targets, 1):
          if len(targets) > 1:
              logger.info(
                  "Step 3 [%d/%d] — running agent for %s …",
                  i, len(targets), person_id,
              )
          else:
              logger.info("Step 3 — running agent for %s …", person_id)

          try:
              result = agent.run(person_id, send_alert=send_alert)
              results.append((person_id, result))

              if result.error:
                  logger.warning(
                      "Agent returned error for %s: %s",
                      person_id, result.error,
                  )
                  errors += 1
              else:
                  logger.info(
                      "Done: %s → %s (%d/100) | concern=%s | rag=%s",
                      person_id,
                      result.risk_level,
                      result.risk_score,
                      result.ai_explanation.concern_level
                          if result.ai_explanation else "n/a",
                      result.rag_context_used,
                  )

          except Exception as e:
              logger.error(
                  "Unhandled exception for %s: %s",
                  person_id, e, exc_info=True,
              )
              errors += 1

      # Step 4 — Print results
      logger.info("Step 4 — printing results …")
      for person_id, result in results:
          _print_result(result, person_id)

      # Summary line for batch mode
      if len(results) > 1:
          reds     = sum(1 for _, r in results if r.risk_level == "RED")
          yellows  = sum(1 for _, r in results if r.risk_level == "YELLOW")
          greens   = sum(1 for _, r in results if r.risk_level == "GREEN")
          unknowns = sum(1 for _, r in results if r.risk_level == "UNKNOWN")
          print(f"Batch complete: {len(results)} residents processed")
          print(
              f"  🟢 GREEN={greens}  🟡 YELLOW={yellows}  "
              f"🔴 RED={reds}  ❓ UNKNOWN={unknowns}"
          )
          if errors:
              print(f"  ⚠  {errors} error(s) — check logs above")
          print()

      return 0 if errors == 0 else 1


  if __name__ == "__main__":
      sys.exit(main())
  ```

  **What it does:** Full pipeline entry point — ChromaDB bootstrap, resident
  resolution, agent orchestration, result printing. CUSUM block uses `.summary`
  only (`.label` removed). `--all` mode emits a warning about the date limitation.

  **Why this approach:** Single file at repo root mirrors the spec. All decisions
  (no-alert dry run, find-red auto-target, batch mode) are CLI flags so the same
  file serves testing and production.

  **Assumptions:**
  - `src/agent.py`, `src/knowledge_base.py` import cleanly (verified in Step 1.4)
  - `active_alerts` table exists in `data/carewatch.db` (created by `AlertStore._ensure_table()`)

  **Risks:**
  - `dataclasses.asdict(cusum_result)` returns nested dicts for `signals` field → `cusum.get('summary')` is a flat string access, not nested → safe
  - `result.ai_explanation` is an `AIExplanation` Pydantic model, not a dict → `.concern_level` attribute access is correct → safe

  **Git Checkpoint:**
  ```bash
  git add run_pipeline.py
  git commit -m "step 1.2: add run_pipeline.py with cusum label fix"
  ```

  **✓ Verification Test:**

  **Type:** Unit

  **Action:**
  ```bash
  python -m py_compile run_pipeline.py && echo "syntax ok"
  grep -n "label" run_pipeline.py
  ```

  **Expected:**
  - `syntax ok`
  - `grep` returns only the comment line `# CUSUM: uses .summary only — .label does not exist` — no live code reference to `.label`

  **Pass:** Syntax clean, no `.label` in CUSUM print block

  **Fail:**
  - If `SyntaxError` → paste the error line — likely an indentation issue in the embedded block
  - If `grep` returns a code line with `.label` → the fix was not applied correctly → re-write the file

---

- [ ] 🟥 **Step 1.2.5: Add `#` comment guard to `knowledge_base.py`** — *Critical: Flaw 3 Option B — prevents comment lines from loading as ChromaDB docs*

  **Idempotent:** Yes — adding a guard line only.

  **Context:** Lines starting with `#` contain colons (e.g. `# Format: topic: detail`). Without a guard, they are loaded as ChromaDB documents, inflating the count from 47 to 48. The docstring says "Blank lines and # lines are skipped" — the implementation must match.

  **Pre-Read Gate:**
  ```bash
  grep -n "if line and" src/knowledge_base.py
  # Must show the line before which to insert the guard
  ```

  **Edit** — in `src/knowledge_base.py`, inside the file-reading loop, add BEFORE `if line and ":" in line:`:
  ```python
  if line.startswith("#"):
      continue
  ```

  **Git Checkpoint:**
  ```bash
  git add src/knowledge_base.py
  git commit -m "step 1.2.5: skip # lines in knowledge_base loader"
  ```

  **✓ Verification Test:**

  **Type:** Unit

  **Action:**
  ```bash
  python -m src.knowledge_base
  python -c "
  import chromadb
  c = chromadb.PersistentClient(path='data/chroma_db')
  col = c.get_collection('carewatch_knowledge')
  print('count:', col.count())
  assert col.count() == 47, f'Expected 47, got {col.count()}'
  "
  ```

  **Expected:** `count: 47`

  **Pass:** ChromaDB has exactly 47 documents

  **Fail:** If count ≠ 47 → guard not applied correctly or wrong insertion point

---

- [ ] 🟥 **Step 1.3: Rebuild ChromaDB** — *Non-critical: data population, fully reversible*

  **Idempotent:** Yes — `knowledge_base.py` deletes and recreates the collection each run.

  **Context:** `chroma_db/` has stale data from a prior run with a smaller fact file.
  Step 1.1 replaced `drug_interactions.txt` with 47 facts. ChromaDB must be rebuilt
  to make those facts queryable. `rag_retriever.py` will silently return empty string
  if the collection has stale or mismatched data.

  **Pre-Read Gate:**
  ```bash
  grep -c "^[^#].*:" data/drug_interactions.txt
  # Must return 47. If not: Step 1.1 is incomplete — do not proceed.
  ```

  ```bash
  python -m src.knowledge_base 2>&1 | grep "Loaded\|Verified"
  # Expected: two lines, both containing "47"
  # The path after "at" is absolute and varies by machine — verify the number, not the path
  ```

  **`.gitignore` check — run once:**
  ```bash
  grep -q "chroma_db" .gitignore \
    && echo "already ignored" \
    || echo "data/chroma_db/" >> .gitignore
  ```

  **Git Checkpoint:**
  ```bash
  # Only commit .gitignore if it changed
  git diff --quiet .gitignore \
    || git add .gitignore && git commit -m "step 1.3: add chroma_db to gitignore"
  ```

  **✓ Verification Test:**

  **Type:** Integration

  **Action:**
  ```bash
  python -c "
  import chromadb
  c   = chromadb.PersistentClient(path='data/chroma_db')
  col = c.get_collection('carewatch_knowledge')
  print('count:', col.count())
  r = col.query(query_texts=['fallen elderly fall response'], n_results=2)
  print('sample:', r['documents'][0])
  "
  ```

  **Expected:** `count: 47` and 2 fall-related documents returned

  **Pass:** Count is `47`, documents contain fall-related text

  **Fail:**
  - If `Collection does not exist` → `knowledge_base.py` failed silently → re-run and read full output
  - If `count < 47` → malformed lines in `drug_interactions.txt` (missing `:`) or Step 1.2.5 guard not applied → `grep -v ":" data/drug_interactions.txt` to find them

---

- [ ] 🟥 **Step 1.3.5: Add `_ensure_table()` to `AlertSuppressionLayer`** — *Critical: B-1 — `alert_suppression` table must exist before `.send()` is called*

  **Idempotent:** Yes — `CREATE TABLE IF NOT EXISTS`.

  **Context:** `AlertSuppressionLayer.__init__` does not create the `alert_suppression` table. `_same_level_within_window` and `_log_decision` both access it. First `.send()` call raises `sqlite3.OperationalError: no such table: alert_suppression`. **Confirm this edit is applied before Step 1.5 runs** — verification below will fail if not.

  **Pre-Read Gate:**
  ```bash
  grep -En "def __init__|def _ensure_table" src/suppression.py
  # Must show __init__ — confirm _ensure_table does not exist yet (BSD grep requires -E)
  ```

  **Edit A** — in `__init__`, after `self.alert_system = AlertSystem()`:
  ```python
  self._ensure_table()
  ```

  **Edit B** — add new method immediately after `__init__`:
  ```python
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
  ```

  **Git Checkpoint:**
  ```bash
  git add src/suppression.py
  git commit -m "step 1.3.5: add _ensure_table to AlertSuppressionLayer"
  ```

  **✓ Verification Test:**

  **Type:** Integration

  **Action:**
  ```bash
  python -c "
  from src.suppression import AlertSuppressionLayer
  layer = AlertSuppressionLayer()
  import sqlite3
  conn = sqlite3.connect('data/carewatch.db')
  tables = [r[0] for r in conn.execute(
      \"SELECT name FROM sqlite_master WHERE type='table'\"
  ).fetchall()]
  assert 'alert_suppression' in tables, 'alert_suppression table not created'
  print('alert_suppression table: ok')
  conn.close()
  "
  ```

  **Expected:** `alert_suppression table: ok`

  **Pass:** Table exists after instantiating `AlertSuppressionLayer`

  **Fail:** `assert 'alert_suppression' in tables` → _ensure_table not called or DDL wrong

---

- [ ] 🟥 **Step 1.4: Verify all pipeline imports resolve** — *Critical: silent import errors cause confusing crashes in Step 1.5*

  **Idempotent:** Yes — read-only.

  **Context:** `run_pipeline.py` → `CareWatchAgent` → chains through six `src/` modules.
  Any missing pip package or broken import here surfaces as a confusing traceback during
  the E2E run rather than a clean error message. Catch it now.

  ```bash
  # Check requirements first
  pip install -r requirements.txt --quiet
  echo "requirements: $?"
  # Expected: 0

  # Pydantic version — v1 fails to coerce raw dicts to AnomalyItem in AgentResult
  python -c "
  import pydantic
  print('pydantic version:', pydantic.__version__)
  assert pydantic.__version__.startswith('2.'), 'Pydantic 2.x required — add pydantic>=2.0 to requirements.txt'
  "

  # requests — used by alert_system.py for Telegram (pip install requests if missing)
  python -c "import requests; print('requests:', requests.__version__)"

  # Test every import in the agent chain
  python -c "
  from src.agent             import CareWatchAgent
  from src.deviation_detector import DeviationDetector
  from src.cusum_monitor     import ResidentCUSUMMonitor
  from src.cusum_detector    import CUSUMResult
  from src.rag_retriever     import RAGRetriever
  from src.suppression       import AlertSuppressionLayer
  from src.audit_logger      import AuditLogger
  from src.models            import AgentResult, RiskResult, AIExplanation, AnomalyItem
  from src.alert_store       import AlertStore
  from src.llm_explainer     import explain_risk
  import dataclasses
  assert dataclasses.is_dataclass(CUSUMResult), 'CUSUMResult must be @dataclass for asdict()'
  print('all imports ok')
  "

  # Raw dict coercion — deviation_detector returns raw dict anomalies; Pydantic must accept them
  python -c "
  from src.models import AgentResult, AIExplanation
  test_result = AgentResult(
      risk_score=100, risk_level='RED',
      anomalies=[{'activity': 'fallen', 'type': 'FALLEN',
                  'message': 'test', 'severity': 'HIGH'}],
      summary='test',
      ai_explanation=AIExplanation(summary='s', concern_level='urgent',
                                   action='a', positive='p'),
      rag_context_used=False,
  )
  print('raw dict coercion ok:', type(test_result.anomalies[0]))
  "

  # RAGRetriever._score_relevance must exist — agent.py calls it
  python -c "
  from src.rag_retriever import RAGRetriever
  import inspect
  r = RAGRetriever()
  assert hasattr(r, '_score_relevance'), 'RAGRetriever missing _score_relevance'
  sig = inspect.signature(r._score_relevance)
  params = list(sig.parameters.keys())
  assert 'anomalies' in params, f\"_score_relevance must accept 'anomalies' param — got {params}\"
  print('_score_relevance: ok')
  "

  # Smoke-test AlertSuppressionLayer — creates alert_suppression table (Step 1.3.5)
  python -c "
  from src.suppression import AlertSuppressionLayer
  layer = AlertSuppressionLayer()
  import sqlite3
  conn = sqlite3.connect('data/carewatch.db')
  tables = [r[0] for r in conn.execute(
      \"SELECT name FROM sqlite_master WHERE type='table'\"
  ).fetchall()]
  assert 'alert_suppression' in tables, 'alert_suppression table not created'
  print('alert_suppression table: ok')
  conn.close()
  "

  # Agent.run smoke test — use explicit resident from DB (default 'resident' may not exist)
  python -c "
  from src.agent import CareWatchAgent
  import sqlite3
  conn = sqlite3.connect('data/carewatch.db')
  row = conn.execute('SELECT person_id FROM activity_log LIMIT 1').fetchone()
  conn.close()
  pid = row[0] if row else 'resident_0000'
  result = CareWatchAgent().run(pid, send_alert=False)
  assert result.risk_level != 'UNKNOWN', \
      f'Got UNKNOWN — baseline missing for {pid}. Run build_baselines_bulk.py first.'
  print('agent.run smoke test:', result.risk_level, result.risk_score)
  "

  # Confirm run_pipeline.py itself parses without error
  python -m py_compile run_pipeline.py && echo "syntax ok"
  ```

  **Git Checkpoint:** No file changes — no commit needed.

  **✓ Verification Test:**

  **Type:** Unit

  **Action:** Run all three commands above in sequence.

  **Expected:** `requirements: 0`, `requests: X.Y.Z`, `all imports ok`, `raw dict coercion ok: <class '...'>`, `_score_relevance: ok`, `alert_suppression table: ok`, `agent.run smoke test: ...`, `syntax ok`

  **Pass:** All three lines printed, no tracebacks

  **Fail:**
  - `ModuleNotFoundError: groq` → `pip install groq`
  - `ModuleNotFoundError: chromadb` → `pip install chromadb`
  - `ModuleNotFoundError: requests` → `pip install requests`
  - `ImportError` from `src.*` → paste the full traceback — likely a circular import or missing file
  - Any syntax error in `run_pipeline.py` → paste the error line

---

- [ ] 🟥 **Step 1.5: Run end-to-end pipeline** — *Critical: first full E2E execution. Two phases — suppression check gates Phase B.*

  **Idempotent:** Phase A (dry run) yes. Phase B (live Telegram) no — fires a real message.

  **Context:** `AlertSuppressionLayer` has a 5-minute RED cooldown. If any previous
  pipeline run fired an alert for the same resident within the last 5 minutes, Phase B
  exits 0 but no Telegram message is sent — a silent failure. Phase A includes a
  suppression state check to confirm the alert path is clear before Phase B is authorised.

  ---

  **Phase A — Dry run and suppression state check**

  ```bash
  # 1. Dry run — no Telegram (capture output once — avoid second Groq run)
  PHASE_A_OUTPUT=$(python run_pipeline.py --find-red --no-alert 2>&1)
  EXIT_CODE=$?
  echo "$PHASE_A_OUTPUT"
  echo "Exit code: $EXIT_CODE"

  TARGET_RESIDENT=$(echo "$PHASE_A_OUTPUT" \
    | grep -oE 'resident_[0-9]+' | head -1)
  echo "TARGET_RESIDENT: $TARGET_RESIDENT"
  # Expected: resident_XXXX (4-digit number). If empty: grep the log manually for resident ID.
  ```

  After the dry run completes, check suppression state.
  `--no-alert` bypasses `AlertSuppressionLayer.send()` entirely — no rows are written to `alert_suppression` during Phase A. The table will be empty for this resident until Phase B fires.

  ```bash
  # Check alert_suppression table exists (Step 1.3.5)
  sqlite3 data/carewatch.db \
    "SELECT name FROM sqlite_master WHERE type='table' AND name='alert_suppression';"
  # Expected: alert_suppression

  # Check most recent suppression rows for this resident
  sqlite3 data/carewatch.db \
    "SELECT resident_id, risk_level, fired_at, suppressed, suppression_reason
     FROM alert_suppression
     WHERE resident_id = '${TARGET_RESIDENT}'
     ORDER BY fired_at DESC LIMIT 5;"
  # If any row shows: fired_at within last 5 minutes AND suppressed=0 → WAIT before Phase B
  # If empty or last fired_at > 5 minutes ago → suppression window clear, proceed to Phase B
  ```

  **State Manifest — Phase A:**
  ```
  Files modified:    none (dry run)
  Values produced:
    target resident_id: [from TARGET_RESIDENT]
    risk_level:         RED (expected)
    risk_score:         100 (expected)
    rag_context_used:   [true or false — note it]
  If rag_context_used=False → Groq may have rate-limited on relevance scoring.
  This is non-blocking for Phase B. The alert will still fire.
  Wait 60 seconds before Phase B if any Groq call shows rate-limit warning in logs.
  Suppression table written by Phase A: NO (--no-alert bypasses AlertSuppressionLayer entirely)
  Expected rows after Phase A: 0 for this resident
  Phase B suppression window: clear (first write occurs during Phase B)
  Verifications passed: Steps 1.1 – 1.4 ✅, Step 1.5A ✅
  Next: Step 1.5B — human must confirm dry run output and say "fire it"
  ```

  **Human Gate — Phase A:**

  STOP. Output exactly this line and nothing else:
  ```
  PHASE_A_GATE: <risk_level> <risk_score> <target_resident_id>
  ```
  Example: `PHASE_A_GATE: RED 100 resident_0042`

  Do not write any code, bash commands, or prose after this line.
  Human verifies the three values before saying "fire it".

  ---

  **Phase B — Live Telegram alert**

  > Only execute after human says "fire it".
  > If `alert_suppression` has a row for this resident with `fired_at` within the last
  > 5 minutes and `suppressed=0`, wait until the window passes before running.

  ```bash
  python run_pipeline.py --find-red
  # Expected log lines (both must appear — absence of either with exit 0 = silent gate):
  # INFO  src.suppression — Alert fired resident=... risk_level=RED escalated=...
  # INFO  src.alert_system — Telegram alert sent successfully.
  echo "Exit code: $?"
  # Expected: 0
  ```

  **Phase B confidence check** — if exit 0 but no Telegram, diagnose:
  ```bash
  # TARGET_RESIDENT from Phase A — must be set
  sqlite3 data/carewatch.db \
    "SELECT person_id, risk_level, concern_level, confidence, timestamp
     FROM agent_runs
     WHERE person_id = '${TARGET_RESIDENT}'
     ORDER BY timestamp DESC LIMIT 1;"
  # Expected: confidence=high, concern_level=urgent
  # If confidence=low → LLM returned normal for RED score → re-run Phase B (new LLM call may fix)
  # If confidence=high AND no Telegram → suppression window active → check alert_suppression fired_at
  ```

  **Git Checkpoint:**
  ```bash
  git add run_pipeline.py
  git commit -m "step 1.5: e2e pipeline verified, RED alert fires successfully"
  ```

  **Subtasks:**
  - [ ] 🟥 Phase A: dry run exits 0, RED result printed
  - [ ] 🟥 Suppression state confirmed clear
  - [ ] 🟥 Human gate passed
  - [ ] 🟥 Phase B: `Telegram alert sent successfully` in logs
  - [ ] 🟥 Telegram message arrives in chat

  **✓ Verification Test:**

  **Type:** E2E

  **Action:** Check Telegram chat for the alert message.

  **Expected:** Message contains `🚨 CareWatch Alert`, resident name, `Risk Level: RED`,
  at least one anomaly, AI summary paragraph, recommended action.

  **Pass:** Message received in Telegram with all expected fields.

  **Fail:**
  - `No uncleared RED alerts` in logs → `active_alerts` table is empty → re-run `generate_mock_data.py --reset` then `build_baselines_bulk.py`
  - Exit 0 but no Telegram message → run Phase B confidence check above: if `confidence=low`, re-run Phase B; if `confidence=high`, check `alert_suppression.fired_at` — wait 5 minutes if within window
  - `Telegram error: 400` → `chat_id` format wrong (group chats need `-` prefix) → verify with `https://api.telegram.org/bot<TOKEN>/getUpdates`
  - `Telegram credentials not set` → `.env` missing `CAREWATCH_BOT_TOKEN` or `CAREWATCH_CHAT_ID` → re-check pre-flight
  - `Detector failed` in logs → paste full traceback — likely a missing column in `activity_log`

---

## Regression Guard

| System | Pre-change behaviour | Post-change verification |
|--------|----------------------|--------------------------|
| `DeviationDetector.check()` | Returns `RiskResult` without raising | `python -c "from src.deviation_detector import DeviationDetector; r = DeviationDetector().check('resident_0000'); print(r.risk_level)"` — must not raise |
| `AlertStore` | `has_active_alert()` returns `None` for unknown resident | `python -c "from src.alert_store import AlertStore; print(AlertStore().has_active_alert('nonexistent'))"` — must print `None` |
| ChromaDB collection | 47 documents queryable | `col.count()` returns `47` (Step 1.3 verification) |

---

## Rollback Procedure

```bash
# If run_pipeline.py causes a crash:
rm run_pipeline.py
# Nothing else was modified — system returns to pre-plan state

# If ChromaDB rebuild corrupts the collection:
rm -rf data/chroma_db/
python -m src.knowledge_base
# Rebuilds clean from data/drug_interactions.txt

# If Phase B fires alerts for wrong resident:
# First capture: TARGET_RESIDENT=$(python run_pipeline.py --find-red --no-alert 2>&1 | grep -oE 'resident_[0-9]+' | head -1)
# Then clear (replace $TARGET_RESIDENT with actual value if running manually):
python -c "
from src.alert_store import AlertStore
import os
store = AlertStore()
pid = os.environ.get('TARGET_RESIDENT', 'resident_0000')  # set TARGET_RESIDENT=resident_XXXX before running
store.clear_alert(pid, cleared_by='rollback')
print('alert cleared for', pid)
"
# Run as: TARGET_RESIDENT=resident_0042 python -c "..."
```

---

## Risk Heatmap

| Step | Risk | What Could Go Wrong | Early Detection | Idempotent |
|------|------|---------------------|-----------------|------------|
| 1.1 Write txt | 🟢 Low | Wrong content written | `grep -c "^[^#].*:" data/drug_interactions.txt` ≠ 47 | Yes |
| 1.2 Write pipeline | 🟡 Medium | Syntax error in embedded block | `python -m py_compile run_pipeline.py` | Yes |
| 1.3 Rebuild ChromaDB | 🟢 Low | Stale collection not dropped | `col.count()` ≠ 47 | Yes |
| 1.4 Import verify | 🟢 Low | Missing pip package | `ImportError` with package name | Yes |
| 1.5A Dry run | 🟡 Medium | Agent crashes on first real run | Exit code ≠ 0 | Yes |
| 1.5B Live alert | 🔴 High | Suppression window silently swallows alert | Check suppression table before firing | No — real Telegram message |

---

## Success Criteria

| Feature | Target | Verification |
|---------|--------|--------------|
| Knowledge base | 47 documents in ChromaDB | `col.count()` returns `47` |
| Pipeline syntax | Clean parse | `python -m py_compile run_pipeline.py` exits 0 |
| All imports | No errors | `all imports ok` printed |
| Dry run | Exit 0, RED result printed | `echo $?` returns `0` |
| Live Telegram | Message arrives | `🚨 CareWatch Alert` in chat |
| CUSUM bug fixed | No `.label` reference in code | `grep "cusum.get" run_pipeline.py` returns 1 line using `.summary` |

---

## Known Limitations (document, do not fix in this plan)

| Limitation | Impact | Future fix |
|------------|--------|------------|
| `get_today()` filters by today's date — mock data is from past dates | `--all` mode returns GREEN for all non-alert residents | Re-run `generate_mock_data.py` without `--reset` to append today's rows, or use live camera pipeline |
| `AlertSuppressionLayer` 5-min RED cooldown | Second E2E run within 5 min silently skips Telegram | Expected behaviour in production — document in README |

---

⚠️ **Do not mark a step 🟩 Done until its verification test passes.**
⚠️ **Do not proceed past the Human Gate in Step 1.5 without explicit human input.**
⚠️ **Do not fire Phase B if suppression window is not confirmed clear.**
⚠️ **Never modify files not named in the current step.**
⚠️ **`--all` mode will return GREEN for all non-alert residents — use `--find-red` for E2E testing.**