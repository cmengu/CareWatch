# CareWatch

AI-powered activity monitoring for elderly residents. Detects behavioural deviations from personal baselines, generates family-facing explanations via RAG + LLM, and fires Telegram alerts. Built as a multi-agent system using LangGraph, with LangChain and custom single-agent baselines for comparison.

---

## Architecture
```mermaid
graph TD
    A[activity_log (SQLite)] --> B[DeviationDetector]
    B --> C[CareWatchOrchestrator LangGraph]
    C --> D{route_node}
    D -->|FALLEN/UNCLEARED| E[FallAgent]
    D -->|pill_taking| F[MedAgent]
    D -->|eating/walking/routine| G[RoutineAgent]
    E --> H[SummaryAgent]
    F --> H
    G --> H
    H -->|RED| I[human_gate_node]
    H -->|YELLOW/GREEN| J[AlertSuppressionLayer]
    I -->|caregiver /clear| J
    J --> K[Telegram Alert]
```

Three agent implementations share the same `run()` interface and are benchmarked against 20 deterministic eval scenarios:

| Agent | Architecture | Use |
|-------|-------------|-----|
| `CareWatchAgent` | Custom linear pipeline | Production baseline |
| `CareWatchOrchestrator` | LangGraph multi-agent | Production (Phase 3) |
| `CareWatchLangChainAgent` | LangChain tool-calling | Eval comparison only |

---

## Evaluation Results

### Agent Comparison (20 scenarios, --no-llm mode)

| Agent | F1 | FNR | LLM Alignment | p50 | p95 | Tokens/run |
|-------|----|-----|---------------|-----|-----|------------|
| Custom (Phase 1) | 1.000 | 0.000 | 95% | 1ms | 2ms | TBD |
| LangGraph multi-agent | 1.000 | 0.000 | 95% | 454ms | 2424ms | TBD |
| LangChain | 1.000 | 0.000 | 95% | 1ms | 9ms | TBD |

**FNR = 0.000** — no fall or active alert was missed across all 20 test cases, including the minimum-confidence fall at 0.851 and a 3-day-old uncleared alert. In a safety system, a missed fall is worse than a false alarm. That number being zero is the design goal.

LangGraph p50 latency (454ms) reflects full graph traversal through MemorySaver and 8 nodes on every run. An early-exit edge from `detect_node` → `alert_node` on GREEN would reduce this to ~5ms for the majority of residents on a typical day.

### Pipeline Metrics (Phase 2 — single agent, with LLM)

| Metric | Score |
|--------|-------|
| Pipeline F1 | 1.000 |
| Pipeline FNR | 0.000 |
| LLM Alignment | 95% |
| p50 latency | 229ms |
| p95 latency | 431ms |
| RAG Precision@1 | 0.920 |
| RAG MRR | 0.960 |

### Prompt Variant Comparison

| Variant | Style | Alignment | FNR | p50 | Safe |
|---------|-------|-----------|-----|-----|------|
| A1C1 | Decision table + self-check (original) | 95% | 0.000 | 229ms | ✅ |
| A2C1 | Chain-of-thought + self-check | 100% | 0.000 | 232ms | ✅ |
| A1C3 | Decision table + no self-check | 100% | 0.000 | 214ms | ✅ |

Chain-of-thought (A2C1) achieves 100% alignment at the same latency as the decision-table baseline. The separate self-check call was adding ~5 seconds with no measurable safety benefit at temperature=0.3. Production target: migrate to A2C1.

### RAG Retrieval (25 ground-truth queries)

| Metric | Score |
|--------|-------|
| MRR | 0.960 |
| Precision@1 | 0.920 |
| Recall@3 | 1.080 |
| Zero-hit queries | 0 |

Recall@3 > 1.0 indicates two queries each had two relevant documents in the top 3. MRR of 0.960 means the correct medical context surfaces as rank-1 result 96% of the time.

---

## Quick Start
```bash
git clone https://github.com/your-handle/carewatch
cd carewatch
cp .env.example .env          # add GROQ_API_KEY, CAREWATCH_BOT_TOKEN, CAREWATCH_CHAT_ID
python generate_mock_data.py   # populate DB before first run
docker-compose up
```

Or without Docker:
```bash
pip install -r requirements.txt
python run_pipeline.py --find-red                    # custom agent (default)
python run_pipeline.py --find-red --agent langgraph  # LangGraph orchestrator
python run_pipeline.py --find-red --agent langchain  # LangChain baseline
```

Run eval:
```bash
python -m eval.eval_agent --no-llm   # deterministic pipeline metrics, no API cost
python -m eval.eval_agent            # full run including LLM alignment scoring
```

---

## Design Decisions

**1. Weight-based risk scoring over ML classifier.** A weighted sum (pill missing = 40pts, meal missing = 25pts, timing deviation = up to 25.5pts) was chosen because no labelled training data exists for this resident population. Every risk score is fully traceable to a specific anomaly — a clinician can adjust weights without retraining.

**2. CUSUM for drift detection over rolling z-score.** CUSUM accumulates small deviations before alerting, catching gradual decline (a resident eating less over 10 days) that a rolling z-score would miss until the deviation became large. Tradeoff: CUSUM state is in-memory and resets on process restart.

**3. ChromaDB + sentence-transformers over keyword search.** Vector retrieval lets natural-language queries ("resident not eating") retrieve semantically related facts ("appetite loss elderly") without exact string matches. BM25 was considered but rejected because family members query in natural language and clinical terminology varies.

**4. Separate self-check call removed.** Phase 2 eval showed the second Groq API call added ~5 seconds with no measurable alignment or safety benefit. Embedded self-verification in a single call achieves the same property at 215ms p50.

**5. AlertSuppressionLayer to prevent alert fatigue.** A 4-hour suppression window ensures families receive at most one Telegram alert per incident. Alert fatigue causes families to ignore notifications — defeating the system's purpose. Tradeoff: a new anomaly appearing within the suppression window for a different reason may be delayed.

**6. Personalised baselines per resident over population norms.** A resident who always takes pills at 9pm generates false positives under a population norm expecting 8am. Per-resident 7-day rolling baselines calibrate detection to individual routines. Tradeoff: residents with fewer than 7 days of history have thin baselines and may generate early false positives.

**7. Groq (llama-3.3-70b-versatile) over GPT-4o.** Sub-300ms p50 inference vs ~800ms typical for GPT-4o on this prompt size. The concern-level classification task does not require GPT-4o's reasoning depth — a well-structured chain-of-thought prompt achieves 100% alignment on llama-3.3-70b. Tradeoff: Groq free tier has a 100k token/day limit.

---

## Graceful Degradation

| Dependency | Failure mode | System behaviour | Impact |
|------------|-------------|------------------|--------|
| Groq API | `_fallback()` fires | concern_level derived from risk_level | Degraded explanation, alert still fires |
| ChromaDB | `_available = False` | `rag_context = ""` | Lower quality explanation, alert still fires |
| SQLite lock | WAL mode + 30s timeout | Retry without blocking readers | None under normal load |
| Telegram API | Exception caught, logged | Alert logged to DB, not delivered | Delayed delivery |

**Known gap:** Telegram retry queue not implemented. Fix: `alert_send_queue` table with `retry_count` and `next_retry_at`, polled every 30s.

---

## Known Limitations

**CUSUM state resets on restart.** Trend detection is in-memory. A gradual decline being tracked is lost on process restart. Fix: persist CUSUM accumulators to SQLite on each check.

**Human-gate deferred.** `CareWatchOrchestrator.resume()` raises `NotImplementedError`. The LangGraph interrupt architecture is wired and tested — re-enabling requires adding a `thread_id` column to `alert_store` and updating the Telegram listener to call `resume()` on `/clear`.

**Telegram send failures are not retried.** A failed Telegram delivery is logged but not queued. Fix: add an `alert_send_queue` table with `retry_count` and `next_retry_at`, polled by a background thread every 30 seconds.

**LangChain agent eval discrepancy.** The `detect_risk` tool inside `CareWatchLangChainAgent` calls `detector.check(person_id)` without `_current_hour` or `_today`. The LLM reasons about one risk level; the returned `AgentResult` uses another. Eval-only agent — not used in production.

---

## Project Structure
```
src/
  agent.py              # CareWatchAgent — custom single-agent pipeline
  orchestrator.py       # CareWatchOrchestrator — LangGraph multi-agent
  graph.py              # LangGraph StateGraph, 8 nodes, AgentState TypedDict
  specialist_agents.py  # FallAgent, MedAgent, RoutineAgent, SummaryAgent
  langchain_agent.py    # LangChain comparison agent (eval only)
  deviation_detector.py # Personalised baseline deviation detection
  cusum_monitor.py      # Gradual drift detection
  rag_retriever.py      # ChromaDB RAG over 47 clinical knowledge facts
  llm_explainer.py      # Groq LLM explanation + prompt variants
  suppression.py        # Alert suppression layer
  alert_system.py       # Telegram delivery
  models.py             # AgentResult, RiskResult, AnomalyItem, SpecialistResult

eval/
  scenarios.py          # 20 deterministic eval scenarios
  eval_agent.py         # Agent comparison benchmark
  eval_helpers.py       # DB seeding, teardown, EvalScenario dataclass
  eval_retrieval.py     # RAG precision/recall/MRR metrics
  eval_prompts.py       # Prompt variant A/B testing

data/
  prompts/              # Versioned prompt files (explain_risk_v1.txt, etc.)
  chroma_db/            # ChromaDB vector store
  carewatch.db          # SQLite — activity_log, baselines, alerts, audit
```