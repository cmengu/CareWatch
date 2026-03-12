# CareWatch AI Agent

An AI agent orchestrator that monitors elderly routines via computer vision and flags behavioural
decline. Uses a YOLO + LSTM perception pipeline to classify activities, a ChromaDB RAG
system over medical knowledge to contextualise anomalies, and a Groq LLM reasoning
layer to generate plain-English risk explanations for family caregivers — delivered
via Telegram and a Next.js dashboard.

**Stack:** YOLO11x-pose · PyTorch LSTM · ChromaDB · Groq (llama3-8b) · FastAPI ·
Next.js · SQLite · Telegram Bot API

## Architecture

    Camera → YOLO pose → LSTM classifier → DeviationDetector (risk score 0–100)
                                                    ↓
                                         [CareWatchAgent orchestrator]
                                          ↙            ↓           ↘
                                 RAG lookup      LLM reasoning    Alert gate
                                (ChromaDB)    (Groq llama3-8b)  (Telegram)
                                          ↘            ↓           ↙
                                             Structured result dict
                                            ↙                    ↘
                                   /api/agent/explain        Telegram alert
                                   (Next.js dashboard)    (plain-English explanation)

## Run the Agent

```bash
# One-time: build ChromaDB knowledge base
python -m src.knowledge_base

# Run agent (no alert sent)
python -c "
from src.agent import CareWatchAgent
import json
result = CareWatchAgent().run('resident', send_alert=False)
print(json.dumps(result, indent=2, default=str))
"

# Start API
uvicorn app.api:app --reload --port 8000
# Then: GET http://localhost:8000/api/agent/explain
```

## What Was Built

| Component | File | What it does |
|-----------|------|--------------|
| Agent orchestrator | `src/agent.py` | Sequences all AI layers into one `run()` call |
| LLM explainer | `src/llm_explainer.py` | Groq API call with fallback — always returns 4-key dict |
| RAG retriever | `src/rag_retriever.py` | ChromaDB semantic search over medical knowledge |
| Knowledge base | `src/knowledge_base.py` | Loads `drug_interactions.txt` into ChromaDB |
| API endpoint | `app/api.py` | `GET /api/agent/explain` — full agent result for dashboard |

---

# CareWatch 👁️
> AI-powered elderly routine monitoring. 
> Detects behavioural decline before crisis happens.

## The Problem
1 in 3 elderly Singaporeans live alone. 
Families only find out something is wrong after a fall or hospitalisation.
Health decline shows up in behaviour days before a crisis.

## The Solution
CareWatch learns a resident's normal daily routine over 7 days.
It flags when something feels wrong — before the crisis.

## Architecture

### Perception → Intelligence → Action

| Layer | Component | What it does |
|-------|-----------|--------------|
| **Perception** | YOLO11x-pose + ByteTrack | 17 keypoints per frame, person tracking, confidence >0.6 |
| **Features** | AngleFeatureExtractor | 8 joint angles + velocity + left/right symmetry score |
| **Classifier** | AngleLSTMNet (30 frames) | sitting / eating / walking / pill_taking / lying / no_person |
| **Memory** | SQLite via ActivityLogger | Logs every prediction with timestamp, confidence, angles |
| **Baseline** | BaselineBuilder | 7-day routine profile per resident |
| **Anomaly** | DeviationDetector | Z-score deviation → risk score 0–100 |
| **AI Agent** | CareWatchAgent | RAG context + Groq LLM → plain-English explanation |
| **Alerts** | Telegram Bot | Fires on YELLOW/RED with AI-generated family message |
| **Dashboard** | Next.js + FastAPI | `/api/agent/explain` — live risk + AI explanation |

## What It Detects
- Missed medication
- Unusual inactivity (3+ hours)
- Routine deviation (eating/walking at wrong times)
- Falls (immediate alert)

## Alert Example
🚨 Mrs Tan has not taken her medication.
No movement detected since 9:10am.
Pill expected at 8:45am — now 2h 15m overdue.

## Tech Stack
- YOLO11x-pose — real-time pose estimation
- PyTorch LSTM — activity classification
- SQLite — activity logging
- Streamlit — family dashboard
- Telegram Bot — instant family alerts

## Setup
pip install -r requirements.txt
python3 app/realtime_inference.py   # live demo
streamlit run app/dashboard.py      # dashboard

## Team
Built for Singapore Innovation Challenge 2026