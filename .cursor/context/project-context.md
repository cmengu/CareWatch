# CareWatch / PillReminder — Project Context

> **Purpose:** High-level project state for AI tools. What exists, what patterns to follow, what constraints to respect.  
> **For AI:** Reference with `@.cursor/context/project-context.md` to avoid reimplementing features or violating patterns.  
> **Last Updated:** 2026-02-26

---

## Project Overview

**Name:** CareWatch (PillReminder)  
**Type:** AI-powered elderly monitoring system (CV + ML pipeline + dashboard)  
**Stack:** Python 3.12, PyTorch, YOLO, Streamlit, SQLite  
**Stage:** MVP / Demo (Singapore Innovation Challenge 2026)

**Purpose:** Detect behavioural decline in elderly individuals living alone by comparing their daily routine (eating, walking, pill-taking, etc.) against a personal baseline. Family gets alerted when deviations occur (e.g. pill not taken, unusual inactivity).

**Current State:**
- ✅ YOLO pose + Angle LSTM activity classification pipeline
- ✅ SQLite logging, baseline builder, deviation detector
- ✅ Streamlit dashboard with React-style UI (risk gauge, timeline, activity feed, 7-day calendar)
- ✅ Demo mode (Normal / Crisis toggle) and medication schedule
- ✅ Telegram alert system (requires `CAREWATCH_BOT_TOKEN`, `CAREWATCH_CHAT_ID`)
- 🔄 Real-time inference runs live but **does not log to DB** — dashboard uses `inject_demo_data()` when no logs exist
- 📋 Data collection for model training (videos not yet filmed)

---

## Architecture

### System Pattern

```
Webcam/Video → YOLO Pose → Keypoints → Angle Extractor → LSTM → Activity Label
                                                                    ↓
SQLite ← ActivityLogger ← (future: realtime_inference logs)
                                                                    ↓
Dashboard ← DeviationDetector ← BaselineBuilder ← activity_log table
```

**Key Decisions:**
- **Single camera, no wearables** — passive observation only
- **Personal baseline** — each resident gets a 7-day routine profile; no generic thresholds
- **Z-score anomaly detection** — activity timing compared to mean ± 2 std dev
- **Weighted risk score** — pill_taking (40), eating (25), walking (20) most critical

### Tech Stack

| Layer | Technology |
|-------|------------|
| Computer Vision | YOLO11x-pose (Ultralytics), COCO 17 keypoints |
| ML Model | PyTorch — AngleLSTMNet (LSTM, 12 input features, 30-frame sequences) |
| Feature Engineering | AngleFeatureExtractor (12 joint angles from 17 keypoints) |
| Database | SQLite via `data/carewatch.db` |
| Dashboard | Streamlit + Plotly (dark theme, IBM Plex Mono) |
| Alerts | Telegram Bot API |
| Language | Python 3.12 |

**Critical Dependencies:**
- `ultralytics` — YOLO pose
- `torch` — LSTM model
- `streamlit`, `plotly` — dashboard
- `opencv-python` — video capture
- `scikit-learn`, `pandas` — training / data

---

## Implemented Features

> **AI Rule:** Don't reimplement what's listed here.

### Pose + Activity Classification
**Status:** ✅  
**What:** YOLO11x-pose extracts 17 keypoints; AngleFeatureExtractor → 12 angles; AngleLSTMNet classifies activity from 30-frame sequences.  
**Location:** `src/classification_keypoint.py`, `src/detection_keypoint.py`, `app/realtime_inference.py`  
**Pattern:** Keypoints (34 floats) → angles (12 floats) → LSTM → softmax → label  
**Integration:** `realtime_inference.py` runs live; `train.py` trains on CSV from `extract_keypoints.py`

### Activity Logging
**Status:** ✅  
**What:** SQLite table `activity_log` (person_id, timestamp, date, hour, minute, activity, confidence).  
**Location:** `src/logger.py`  
**APIs:** `log()`, `get_today()`, `get_last_n_days()`, `get_last_activity()`  
**Integration:** Logger used by baseline_builder, deviation_detector, dashboard. **Note:** realtime_inference does NOT call `logger.log()` yet; dashboard uses `inject_demo_data()` when empty.

### Baseline Builder
**Status:** ✅  
**What:** Builds personal routine profile from 7 days of logs. Per-activity: mean_hour, std_hour, mean_count, occurs_daily.  
**Location:** `src/baseline_builder.py`  
**Output:** `data/baselines/{person_id}.json`  
**Integration:** DeviationDetector loads baseline; dashboard has "Build baseline" button

### Deviation Detector
**Status:** ✅  
**What:** Compares today’s activity vs baseline. Z-score anomaly detection. Returns risk_score (0–100), risk_level (GREEN/YELLOW/RED), anomalies list.  
**Location:** `src/deviation_detector.py`  
**Weights:** pill_taking 40, eating 25, walking 20, sitting 5, lying_down 10  
**Integration:** Dashboard displays risk; AlertSystem sends on YELLOW/RED

### Alert System
**Status:** ✅  
**What:** Sends Telegram message to family on YELLOW/RED risk. Requires `CAREWATCH_BOT_TOKEN` and `CAREWATCH_CHAT_ID`. Falls back to console print if not set.  
**Location:** `src/alert_system.py`  
**Integration:** Called externally (e.g. cron) with `DeviationDetector.check()` result

### Streamlit Dashboard
**Status:** ✅  
**What:** Family-facing UI: Current Activity, RiskGauge, Medication schedule, Timeline, Activity Log, 7-Day History. Normal/Crisis demo toggle.  
**Location:** `app/dashboard.py`  
**Pattern:** `logs_to_timeline()`, `build_week_data()`, `get_medication_schedule()` transform DB data for display; `render_risk_gauge()`, `render_activity_feed()`, `render_week_calendar()` for UI  
**Integration:** Reads from logger, baseline_builder, deviation_detector

### Keypoint Extraction Pipeline
**Status:** ✅  
**What:** Processes videos in `datasets/raw/{label}/`, runs YOLO pose, outputs `train_action_pose_keypoint.csv` and `test_action_pose_keypoint.csv` for training.  
**Location:** `scripts/extract_keypoints.py`  
**Labels:** sitting, eating, walking, pill_taking, lying_down, no_person

### Model Training
**Status:** ✅  
**What:** Trains AngleLSTMNet on CSV. Outputs `model/trained_carewatch.pt` and `model/label_classes.txt`.  
**Location:** `notebooks/train.py`  
**Integration:** realtime_inference and dashboard expect these files

---

## Data Models

### Activity Log (DB row)
```
{ id, person_id, timestamp (ISO), date (YYYY-MM-DD), hour, minute, activity, confidence }
```
**Used by:** Logger, BaselineBuilder, DeviationDetector, Dashboard  
**Flow:** Logged by inject_demo_data or (future) realtime_inference → read by all consumers

### Baseline Profile (JSON)
```
{ person_id, built_at, days_of_data, activities: { act: { mean_hour, std_hour, mean_count, occurs_daily } } }
```
**Used by:** DeviationDetector, Dashboard  
**Flow:** BaselineBuilder.build_baseline() → data/baselines/{id}.json → load_baseline()

### Risk Result (in-memory)
```
{ risk_score, risk_level, anomalies, summary, checked_at }
```
**Used by:** Dashboard, AlertSystem  
**Flow:** DeviationDetector.check() → display or Telegram

### Timeline Item (display)
```
{ time ("HH:MM"), activity, conf, note }
```
**Used by:** Dashboard Activity Log, Timeline  
**Flow:** logs_to_timeline(today_logs) → render_activity_feed()

### Week Data (display)
```
{ day, risk, pill, events }
```
**Used by:** Dashboard 7-Day History  
**Flow:** build_week_data(all_logs, risk_result) → render_week_calendar()

---

## Patterns

> **AI Rule:** Follow these for consistency.

### Activity Label Set
**Use when:** Adding activities, displaying labels, training.  
**How:** Exactly `sitting`, `eating`, `walking`, `pill_taking`, `lying_down`, `no_person` (plus `unknown` for low-confidence). Dashboard adds `fallen` for display only.  
**Location:** `src/classification_keypoint.py` LABELS, `app/dashboard.py` ACTIVITIES

### Keypoint Format
**Use when:** Passing keypoints between YOLO and AngleFeatureExtractor.  
**How:** Flat array `[x0,y0, x1,y1, ..., x16,y16]` (34 floats). COCO 17-keypoint order.  
**Location:** `src/classification_keypoint.py`, `app/realtime_inference.py` extract_keypoints()

### Person ID
**Use when:** Multi-resident support (future).  
**How:** Default `"resident"` everywhere. Change `PERSON_ID` in dashboard, or pass to logger/baseline/detector.

### Anomaly Handling
**Use when:** DeviationDetector can return string messages (e.g. "No baseline built yet") or dict anomalies.  
**How:** Check `isinstance(a, str)` before `a.get()` in display loops.  
**Location:** `app/dashboard.py` anomaly rendering

---

## Integration Points

> **AI Rule:** Use these, don't recreate.

### Logger
**What:** Central activity persistence.  
**APIs:**
- `log(activity, confidence, person_id)` — append one event
- `get_today(person_id)` — today’s logs
- `get_last_n_days(n, person_id)` — recent logs (LIMIT 10000)
- `get_last_activity(person_id)` — most recent log

### Baseline Builder
**What:** Personal routine profile.  
**APIs:**
- `build_baseline(person_id)` — compute and save JSON
- `load_baseline(person_id)` — load or None

### Deviation Detector
**What:** Daily risk check.  
**APIs:**
- `check(person_id)` → `{ risk_score, risk_level, anomalies, summary }`

### Dashboard Helpers
**What:** Transform DB data for display.  
**Available:**
- `logs_to_timeline(logs)` — activity_log → `[{time, activity, conf, note}]`
- `build_week_data(all_logs, risk_result)` — 7-day `[{day, risk, pill, events}]`
- `get_medication_schedule(baseline, today_logs, demo_mode)` — morning/lunch/night doses
- `render_risk_gauge(score)` — Plotly gauge figure
- `render_activity_feed(timeline)` — Activity Log cards
- `render_week_calendar(week_data)` — 7-day risk + pill display

---

## File Structure

```
PillReminder/
├── app/
│   dashboard.py          # Streamlit dashboard (family view)
│   realtime_inference.py # Live webcam demo (pose + LSTM)
├── src/
│   classification_keypoint.py  # AngleFeatureExtractor, AngleLSTMNet
│   detection_keypoint.py       # (YOLO wrapper)
│   logger.py                   # ActivityLogger (SQLite)
│   baseline_builder.py         # Personal routine profile
│   deviation_detector.py      # Risk scorer, anomaly detection
│   alert_system.py            # Telegram alerts
├── scripts/
│   extract_keypoints.py       # Video → labeled CSV
├── notebooks/
│   train.py                   # LSTM training
├── model/
│   trained_carewatch.pt       # Saved weights
│   label_classes.txt          # Activity labels
├── data/
│   carewatch.db               # SQLite
│   baselines/                 # Per-person JSON
├── datasets/
│   raw/{label}/               # Training videos by label
│   train_action_pose_keypoint.csv
│   test_action_pose_keypoint.csv
├── requirements.txt
└── .cursor/
    context/
      project-context.md       # This file
    commands/                  # Cursor commands
    products/
      vision.md                # Product vision
```

**Key Files:**
- `app/dashboard.py` — main user-facing UI
- `app/realtime_inference.py` — live demo entrypoint
- `src/logger.py` — data foundation
- `src/classification_keypoint.py` — model + feature extraction

---

## Constraints

> **AI Rule:** Respect these, don't work around them.

### realtime_inference Does Not Log
**What:** Live demo shows predictions but does not persist to `activity_log`.  
**Handle:** Dashboard uses `inject_demo_data()` when no logs. To connect live data, add `logger.log()` calls in realtime_inference.  
**Affects:** Dashboard, baseline, deviation detection

### Label Classes Sync
**What:** `model/label_classes.txt` must match training labels.  
**Handle:** Training writes it; inference reads it. Don't change labels without retraining.  
**Affects:** realtime_inference, dashboard ACTIVITIES

### Model Quality Gate
**What:** .cursorrules: if val_acc drops below 85% after retraining, do not replace saved model.  
**Handle:** Manual check before deploying new weights.

### Branch Policy
**What:** Never commit to main directly; use carewatch-dev.  
**Handle:** All changes go to feature branch first.

---

## Not Implemented

> **AI Rule:** Don't assume these exist.

### realtime_inference → Logger
**Status:** 💡 Gap  
**What:** Wire realtime_inference to call `logger.log()` when confident prediction (e.g. > 0.85) so dashboard shows live data without demo injection.

### Scheduled Deviation Check
**Status:** 💡 Idea  
**What:** Cron/scheduler that runs DeviationDetector.check() every 15 min and calls AlertSystem.send() on YELLOW/RED.

### Multi-Resident
**Status:** 📋 Planned  
**What:** Support multiple person_ids; dashboard tabs or selector.

### Fallen Detection
**Status:** 💡 Display only  
**What:** Dashboard has `fallen` in ACTIVITIES; model does not classify it. Could add to training or treat as lying_down variant.

---

## Dev Commands

```bash
# Activate venv
source .venv/bin/activate

# Install
pip install -r requirements.txt

# Run live demo (webcam)
python3 app/realtime_inference.py

# Run dashboard
streamlit run app/dashboard.py

# Extract keypoints from videos
python3 scripts/extract_keypoints.py

# Train model
python3 notebooks/train.py
```

---

## Quick Checklist

Before prompting AI:
- [ ] Checked `.cursor/context/project-context.md` for existing implementation
- [ ] Reviewed patterns (activity labels, keypoint format, anomaly handling)
- [ ] Noted integration points (logger, baseline, detector)
- [ ] Identified constraints (logging gap, label sync, model gate)

---

## Related Docs

| File | Purpose |
|------|---------|
| `.cursor/products/vision.md` | Product vision, problem, value prop |
| `.cursorrules` | Tech stack, structure, dev commands, active rules |
| `.cursor/commands/CAREWATCH_DASHBOARD_INTEGRATION_PLAN.md` | Dashboard integration plan (completed) |

---

**Maintenance:** Update after major features; review when adding modules or changing data flow.
