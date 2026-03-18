# CareWatch – Data Handling & Privacy Plan

**Version:** 1.0  
**Date:** 2026-03-17  
**System:** CareWatch – AI-Powered Medication & Activity Monitor  

---

## 1. Overview

CareWatch is an AI-powered health monitoring system designed to support elderly residents by tracking medication adherence and daily activities via webcam inference. This document outlines how personal and health-related data is collected, used, protected, and deleted, in alignment with Singapore's **Personal Data Protection Act (PDPA)** and general health data best practices.

---

## 2. Data Collected

| Data Type | Description | Sensitivity |
|---|---|---|
| **Video frames** | Raw webcam frames processed in real-time | Very High |
| **Body keypoints** | Joint coordinates extracted per frame | Medium |
| **Activity logs** | Classified activity (e.g. sitting, eating, pill\_taking) with timestamp | High |
| **Medication schedules** | Planned dose times and medicine names | High |
| **Medication events** | Detected or manually recorded intake events | High |
| **Risk scores** | Computed adherence risk metric | High |
| **Meal schedules** | Planned mealtimes and tolerance windows | Medium |

---

## 3. Purpose Limitation

Data is collected **only** for the following purposes:
- Detecting if medication has been taken at the scheduled time
- Identifying potential falls or unusual inactivity
- Generating alerts to caregivers when health risk is elevated
- Providing dietary and lifestyle recommendations based on detected health patterns

Data is **not** used for advertising, profiling for commercial purposes, or shared with third parties.

---

## 4. Consent

### 4.1 How Consent is Obtained
- A **consent modal** is displayed on the CareWatch dashboard on first launch
- The modal clearly explains: what data is collected, how it is used, and how it is protected
- The system **does not activate data collection or display any health data** until the user (resident or authorised caregiver) clicks **"I Agree"**
- Consent is logged with a timestamp in `localStorage` on the user's device

### 4.2 Withdrawal of Consent
- A user may withdraw consent at any time by clearing the browser's `localStorage`
- Upon withdrawal, the dashboard returns to the consent screen and no further API calls are made

### 4.3 Who May Give Consent
- The resident themselves, or
- An authorised caregiver or family member acting on the resident's behalf

---

## 5. Anonymisation & Pseudonymisation

### 5.1 Pseudonymous Identifiers
- Residents are identified in the database and API by a **pseudonymous ID** (e.g. `resident_001`)
- Real names (e.g. "Mrs Tan") are **never stored in the database** and appear only as display labels in the UI, which can be changed without affecting data integrity
- The mapping between a pseudonymous ID and a real name is maintained separately and access-controlled

### 5.2 No Raw Video Storage
- Webcam frames are processed **entirely in memory** using the YOLO pose model
- Frames are **discarded immediately** after keypoint extraction — no video or images are written to disk
- Only the derived, numerical **joint angles** and the **classified activity label** are stored

### 5.3 Keypoint Data
- Raw keypoint coordinates `[x, y]` per joint are only used transiently during angle calculation
- What is persisted is the **activity label** (e.g. `eating`), **confidence score**, and **timestamp** — not the keypoints themselves

---

## 6. Data Retention & Deletion

| Data | Retention Period | Deletion Method |
|---|---|---|
| Activity logs | **30 days** rolling | Auto-deleted by background process |
| Medication events | **30 days** rolling | Auto-deleted by `purge_old_logs()` |
| Medication schedules | Until manually removed by caregiver | User-initiated delete via UI |
| Risk scores | Overwritten on each update | In-place update, no history stored |

The background monitoring thread calls `purge_old_logs()` every time it runs the reminder check (every 60 seconds), ensuring no stale data accumulates.

---

## 7. Demo & Synthetic Data

- CareWatch includes a **demo mode** clearly labelled "DEMO" in the UI
- Demo mode uses **entirely synthetic data** — no real person's information is involved
- The `/api/demo/inject` endpoint inserts randomly generated activity logs with no connection to any real individual
- All hackathon demonstrations are conducted using this synthetic dataset

---

## 8. Data Security

| Control | Implementation |
|---|---|
| **No video stored** | Frames discarded after inference (in-memory only) |
| **Local database** | SQLite stored locally; not transmitted to external servers |
| **CORS restriction** | API only accepts requests from `localhost:3000` by default |
| **Pseudonymous IDs** | Real names decoupled from stored health data |

---

## 9. PDPA Alignment Summary

| PDPA Obligation | How CareWatch Addresses It |
|---|---|
| **Consent** | Explicit consent modal before any data collection |
| **Purpose Limitation** | Data used only for health monitoring and alerts |
| **Notification** | Consent modal describes all data collected |
| **Access & Correction** | Caregiver can view and delete schedules via the dashboard |
| **Retention Limitation** | 30-day auto-purge for activity and medication event logs |
| **Protection** | Local storage, no raw video, CORS-restricted API |
| **Transfer Limitation** | No data transferred to third parties |

---

*This document should be reviewed and signed off by the resident or their authorised representative before system activation.*
