# CareWatch AI Agent — Integration Plan

**Overall Progress:** `0%` (0/9 steps complete)

---

## TLDR

This plan integrates a full AI agent loop into the existing CareWatch codebase. The agent sits between `deviation_detector.py` (which already produces a risk score) and `alert_system.py` (which already sends Telegram messages). It adds three new capabilities: a ChromaDB RAG layer that retrieves relevant medical context for detected anomalies, a Groq LLM layer that turns the risk score into plain-English family-readable explanations, and an orchestrator (`agent.py`) that sequences these steps and produces a unified result dict. A new FastAPI endpoint `/api/agent/explain` exposes the full result to the Next.js dashboard. After this plan executes, every Telegram alert contains an AI-generated explanation, every dashboard risk call returns structured reasoning, and the codebase demonstrates LLM integration + RAG + agent orchestration — all three requirements for the target job application.

---

## Critical Decisions

- **Decision 1: Groq over Anthropic** — Free tier, no credit card, identical call pattern. Key validity checked at call time not import time (see Flaw 1 fix).
- **Decision 2: ChromaDB persistent local store** — No external service required. Stored at `data/chroma_db/`. Run `knowledge_base.py` once; RAG persists across restarts.
- **Decision 3: Agent does NOT replace `deviation_detector.py`** — Agent wraps it. `detector.check()` is called unchanged inside `agent.run()`. Zero risk of breaking existing risk logic.
- **Decision 4: `alert_system.py` fixed before `agent.py` created** — Prevents the crash window where agent calls a broken `send()`. Steps 1 and 2 execute before Step 6.
- **Decision 5: Fallback at every AI layer** — If Groq key missing, if ChromaDB empty, if JSON parse fails — each layer returns a safe default and the agent continues. System never crashes due to AI unavailability.

---

## Clarification Gate

All unknowns resolved. No human input required before Step 1.

| Unknown | Resolution | Source |
|---------|-----------|--------|
| `get_last_activity()` return shape | `{id, person_id, timestamp, date, hour, minute, activity, confidence}` or `None` | `logger.py` confirmed |
| `load_baseline()` return shape | `{"person_id", "built_at", "days_of_data", "activities": {act: {"mean_hour"\|None, "std_hour"\|None, "mean_count", "occurs_daily"}}}` or `None` | `baseline_builder.py` confirmed |
| `fastAPI` import bug | Line 1 of `api.py`: `from fastAPI import FastAPI` — must be `from fastapi import FastAPI` | `api.py` confirmed |
| `summary` variable bug in `alert_system.py` | Line ~63: `f"_{summary}_"` — `summary` not in scope, crashes on YELLOW/RED | `alert_system.py` confirmed |
| ChromaDB empty collection crash | `query(n_results=0)` raises `ValueError` — guard required before query | Flaw 3 analysis |

---

## Agent Failure Protocol

1. A verification command fails → read the full error output.
2. Cause is unambiguous → make ONE targeted fix → re-run the same verification command.
3. If still failing after one fix → **STOP**. Before stopping, output the full current contents of every file modified in this step. Report: (a) command run, (b) full error verbatim, (c) fix attempted, (d) current state of each modified file, (e) why you cannot proceed.
4. Never attempt a second fix without human instruction.
5. Never modify files not named in the current step.

---

## Pre-Flight — Run Before Any Code Changes

```bash
# 1. Confirm file structure
find . -name "*.py" -not -path "./.venv/*" -not -path "*/node_modules/*" -not -path "*/__pycache__/*" | sort

# 2. Confirm known bugs exist (both must return matches)
grep -n "from fastAPI import" app/api.py
grep -n "_summary_" src/alert_system.py

# 3. Confirm venv is active and core imports work
python -c "from src.deviation_detector import DeviationDetector; print('OK')"
python -c "from src.alert_system import AlertSystem; print('OK')"

# 4. Line counts (record for post-plan diff)
wc -l src/alert_system.py src/deviation_detector.py app/api.py

# 5. Confirm new files do NOT exist yet
ls src/llm_explainer.py src/rag_retriever.py src/knowledge_base.py src/agent.py 2>&1
# Expected: "No such file or directory" for all four
```

**Baseline Snapshot (agent fills during pre-flight):**
```
Line count src/alert_system.py:    ____
Line count src/deviation_detector.py: ____
Line count app/api.py:              ____
fastAPI import bug confirmed:       ____
summary bug confirmed:              ____
New files absent:                   ____
```

---

## Steps Analysis

```
Step 1 (Install dependencies)            — Non-critical — verification only        — Idempotent: Yes
Step 2 (Fix alert_system.py)             — Critical (shared by agent + API)        — Idempotent: Yes
Step 3 (Create data/drug_interactions.txt) — Non-critical                          — Idempotent: Yes
Step 4 (Create src/knowledge_base.py)    — Critical (RAG depends on it)            — Idempotent: Yes
Step 5 (Create src/rag_retriever.py)     — Critical (agent depends on it)          — Idempotent: Yes
Step 6 (Create src/llm_explainer.py)     — Critical (agent depends on it)          — Idempotent: Yes
Step 7 (Create src/agent.py)             — Critical (orchestrator, ties all steps)  — Idempotent: Yes
Step 8 (Fix api.py + add endpoint)       — Critical (API contract change)           — Idempotent: Yes
Step 9 (End-to-end test + git push)      — Non-critical                             — Idempotent: Yes
```

---

## Tasks

### Phase 1 — Fix Existing Bugs (must complete before any new code)

**Goal:** Both known bugs eliminated. `alert_system.py` and `api.py` are crash-free before the agent touches them.

---

- [ ] 🟥 **Step 1: Install dependencies** — *Non-critical: no existing code touched*

  **Idempotent:** Yes — pip install is a no-op if already installed.

  ```bash
  pip install groq chromadb python-dotenv
  ```

  **✓ Verification Test:**

  **Type:** Unit

  **Action:**
  ```bash
  python -c "import groq; import chromadb; print('OK')"
  ```

  **Expected:** prints `OK`

  **Pass:** `OK` printed, no ImportError

  **Fail:**
  - If `ModuleNotFoundError: groq` → pip install did not run inside venv → confirm venv is active: `which python`
  - If `ModuleNotFoundError: chromadb` → same cause

  **Git Checkpoint:**
  ```bash
  git add requirements.txt
  git commit -m "step 1: add groq and chromadb to dependencies"
  ```

---

- [ ] 🟥 **Step 2: Fix `src/alert_system.py`** — *Critical: shared by agent and existing Telegram alerts*

  **Idempotent:** Yes — both fixes are targeted replacements; re-running produces identical file.

  **Context:** Two bugs exist. Bug A: `summary` variable used on line ~63 is not defined in `send()` scope — crashes every YELLOW/RED alert. Bug B: alert message does not include AI explanation even after agent adds it. This step fixes both. Must complete before `agent.py` is created.

  **Pre-Read Gate:**
  ```bash
  # Confirm Bug A target — must return exactly 1 match
  grep -n "_{summary}_" src/alert_system.py
  # Expected: exactly 1 line like:  63:            f"_{summary}_",

  # Confirm Bug B target — must return exactly 1 match
  grep -n "Please check in with them" src/alert_system.py
  # Expected: exactly 1 line

  # Confirm insertion anchor exists once
  grep -n "lines +=" src/alert_system.py
  # Note the line numbers — there are 2 occurrences; target is the one containing "Please check in"
  ```
  If grep for Bug A returns 0 or 2+ matches → STOP and report.

  **Fix A** — replace the undefined `summary` variable.

  Find this exact line in `send()` (the one inside the `lines = [` block):
  ```python
            f"_{summary}_",
  ```
  Replace with:
  ```python
            f"_{risk_result.get('summary', 'No summary available.')}_",
  ```

  **Fix B** — replace the static closing lines with AI-aware block.

  Find this exact block (must appear exactly once in `send()`):
  ```python
        lines += [
            "",
            "Please check in with them or review the CareWatch dashboard.",
        ]
  ```
  Replace with:
  ```python
        ai = risk_result.get("ai_explanation")
        if ai:
            lines += [
                "",
                f"🤖 *AI Assessment:* {ai.get('summary', '')}",
                f"📋 *Recommended action:* {ai.get('action', '')}",
                f"✅ *Today\'s positive:* {ai.get('positive', '')}",
            ]
        else:
            lines += [
                "",
                "Please check in with them or review the CareWatch dashboard.",
            ]
  ```

  **What it does:** Fixes the crash on YELLOW/RED alerts. Adds AI explanation block to Telegram message when present; falls back to original text when not.

  **Why this approach:** Backward-compatible — if agent has not run yet, `ai_explanation` key is absent, old message text is used unchanged.

  **Assumptions:**
  - `risk_result` is a dict (confirmed — `deviation_detector.check()` always returns dict)
  - `send()` is the only method containing `_{summary}_` (confirmed by grep)

  **Risks:**
  - Markdown formatting in AI text could break Telegram parse_mode → mitigation: Groq prompt instructs plain text output, no asterisks or underscores in AI fields

  **Git Checkpoint:**
  ```bash
  git add src/alert_system.py
  git commit -m "step 2: fix summary NameError and add AI explanation block to Telegram alert"
  ```

  **Subtasks:**
  - [ ] 🟥 Grep confirms Bug A target exists exactly once
  - [ ] 🟥 Fix A applied — `summary` replaced with `risk_result.get('summary', ...)`
  - [ ] 🟥 Fix B applied — static closing lines replaced with AI-aware block
  - [ ] 🟥 Verification passes

  **✓ Verification Test:**

  **Type:** Unit

  **Action:**
  ```bash
  python -c "
  from src.alert_system import AlertSystem
  a = AlertSystem()
  # Simulate YELLOW result without ai_explanation (old behaviour)
  a.send({'risk_level': 'YELLOW', 'risk_score': 45, 'anomalies': [], 'summary': 'Test summary'}, 'Test Person')
  print('PASS: no crash')
  "
  ```

  **Expected:** Prints alert to console ending with `PASS: no crash`. No `NameError`.

  **Pass:** `PASS: no crash` printed

  **Fail:**
  - If `NameError: name 'summary' is not defined` → Fix A was not applied → re-check grep anchor and retry
  - If `KeyError` → wrong dict key used → re-read `deviation_detector.check()` return shape

---

### Phase 2 — Build AI Layers (bottom-up: data → retrieval → LLM → orchestrator)

**Goal:** Four new files created. Each works independently. Agent ties them together.

---

- [ ] 🟥 **Step 3: Create `data/drug_interactions.txt`** — *Non-critical: plain text file, no code*

  **Idempotent:** Yes — file creation overwrites if exists.

  Create the file at exactly this path: `data/drug_interactions.txt`

  ```
  metformin: Take with food. Missing a dose for a diabetic elderly patient increases risk of hyperglycemia. Critical to take consistently.
  warfarin: Blood thinner. Missing doses causes stroke risk. Must be taken at the same time daily. Interaction with aspirin increases bleeding risk.
  lisinopril: Blood pressure medication. Missing doses can cause dangerous blood pressure spikes in elderly patients.
  amlodipine: Calcium channel blocker for blood pressure. Dizziness and falls are common side effects especially in elderly.
  atorvastatin: Cholesterol medication. Evening dose preferred. Missing occasional doses less critical than blood pressure meds.
  aspirin: Daily low-dose aspirin for heart patients. Do not combine with warfarin without doctor approval.
  omeprazole: Stomach acid reducer. Take 30 minutes before breakfast. Missing doses causes acid reflux discomfort.
  general: Elderly patients missing more than 2 doses of any critical medication should be flagged for family follow-up.
  general: Inactivity exceeding 4 hours during waking hours (7am-9pm) is a fall risk indicator in elderly patients.
  general: Sudden change in routine such as eating or walking patterns in elderly can indicate onset of infection or depression.
  fallen: Any fall in elderly patient requires immediate medical assessment even if patient appears uninjured.
  pill_taking: Missed pill-taking activity combined with risk score above 60 requires family notification within 1 hour.
  ```

  **Git Checkpoint:**
  ```bash
  git add data/drug_interactions.txt
  git commit -m "step 3: add drug interactions knowledge base for RAG"
  ```

  **✓ Verification Test:**

  **Type:** Unit

  **Action:**
  ```bash
  python -c "
  lines = open('data/drug_interactions.txt').readlines()
  assert len(lines) == 12, f'Expected 12 lines, got {len(lines)}'
  print('PASS:', len(lines), 'facts loaded')
  "
  ```

  **Pass:** `PASS: 12 facts loaded`

  **Fail:**
  - If `FileNotFoundError` → file not saved to correct path → confirm path is `data/drug_interactions.txt` not `src/` or project root

---

- [ ] 🟥 **Step 4: Create `src/knowledge_base.py`** — *Critical: RAG depends on this running once*

  **Idempotent:** Yes — deletes and recreates ChromaDB collection on every run.

  **Context:** Loads `data/drug_interactions.txt` into a persistent ChromaDB collection at `data/chroma_db/`. Must be run once before `rag_retriever.py` can query it. Safe to re-run — collection is dropped and rebuilt each time.

  Create file at exactly: `src/knowledge_base.py`

  ```python
  """
  knowledge_base.py
  ==================
  Run ONCE to load drug_interactions.txt into ChromaDB.
  After running, rag_retriever.py can query it.

  USAGE:
      python -m src.knowledge_base
  """

  import chromadb
  from pathlib import Path

  DB_PATH    = str(Path(__file__).parents[1] / "data" / "chroma_db")
  FACTS_PATH = Path(__file__).parents[1] / "data" / "drug_interactions.txt"


  def build_knowledge_base():
      client = chromadb.PersistentClient(path=DB_PATH)

      # Drop and recreate for clean idempotent build
      try:
          client.delete_collection("carewatch_knowledge")
      except Exception:
          pass

      collection = client.create_collection("carewatch_knowledge")

      facts = []
      ids   = []

      with open(FACTS_PATH, "r") as f:
          for i, line in enumerate(f):
              line = line.strip()
              if line and ":" in line:
                  facts.append(line)
                  ids.append(f"fact_{i}")

      if not facts:
          print("❌ No facts found. Check data/drug_interactions.txt exists and has content.")
          return

      collection.add(documents=facts, ids=ids)
      print(f"✅ Loaded {len(facts)} facts into ChromaDB at {DB_PATH}")

      # Verify write succeeded
      count = collection.count()
      assert count == len(facts), f"ChromaDB count mismatch: expected {len(facts)}, got {count}"
      print(f"✅ Verified: {count} documents queryable")


  if __name__ == "__main__":
      build_knowledge_base()
  ```

  Run it immediately after creating:
  ```bash
  python -m src.knowledge_base
  ```

  **Git Checkpoint:**
  ```bash
  git add src/knowledge_base.py
  git commit -m "step 4: add ChromaDB knowledge base builder for RAG pipeline"
  ```

  **Subtasks:**
  - [ ] 🟥 File created
  - [ ] 🟥 `python -m src.knowledge_base` runs without error
  - [ ] 🟥 Verification test passes

  **✓ Verification Test:**

  **Type:** Integration

  **Action:**
  ```bash
  python -c "
  import chromadb
  from pathlib import Path
  db_path = str(Path('data/chroma_db'))
  client = chromadb.PersistentClient(path=db_path)
  col = client.get_collection('carewatch_knowledge')
  count = col.count()
  assert count == 12, f'Expected 12, got {count}'
  results = col.query(query_texts=['pill_taking missed dose'], n_results=2)
  assert len(results['documents'][0]) == 2
  print('PASS: RAG queryable,', count, 'documents')
  "
  ```

  **Pass:** `PASS: RAG queryable, 12 documents`

  **Fail:**
  - If `CollectionNotFoundError` → `python -m src.knowledge_base` did not run or failed silently → check DB_PATH resolves correctly
  - If count != 12 → blank lines or lines without `:` were skipped → check `drug_interactions.txt` formatting

---

- [ ] 🟥 **Step 5: Create `src/rag_retriever.py`** — *Critical: agent depends on this*

  **Idempotent:** Yes — stateless query class, no writes.

  **Context:** Wraps ChromaDB with a safe query interface. Key fix from Logic Check Flaw 3: guards against empty collection (would cause `ValueError` with `n_results=0`). Returns empty string on any failure — agent continues without RAG context rather than crashing.

  Create file at exactly: `src/rag_retriever.py`

  ```python
  """
  rag_retriever.py
  =================
  Queries the ChromaDB knowledge base built by knowledge_base.py.
  Given anomalies from deviation_detector, returns relevant medical context.
  Returns empty string on any failure — agent always continues.
  """

  import chromadb
  from pathlib import Path

  DB_PATH = str(Path(__file__).parents[1] / "data" / "chroma_db")


  class RAGRetriever:
      def __init__(self):
          try:
              client = chromadb.PersistentClient(path=DB_PATH)
              self.collection = client.get_collection("carewatch_knowledge")
              self._available = True
          except Exception as e:
              print(f"⚠️  RAG not available: {e}. Run: python -m src.knowledge_base")
              self.collection  = None
              self._available  = False

      def get_context(self, anomalies: list, n_results: int = 3) -> str:
          """
          Given anomaly dicts from deviation_detector.check(), return relevant facts.
          Returns empty string if RAG unavailable or collection empty.

          anomalies shape: [{"activity": str, "type": str, "message": str, "severity": str}, ...]
          """
          if not self._available or not anomalies:
              return ""

          # Guard: empty collection causes ValueError in ChromaDB query
          if self.collection.count() == 0:
              return ""

          # Build query from anomaly activities and types
          query_terms = " ".join([
              a.get("activity", "") + " " + a.get("type", "")
              for a in anomalies
              if isinstance(a, dict)
          ]).strip()

          if not query_terms:
              return ""

          try:
              results = self.collection.query(
                  query_texts=[query_terms],
                  n_results=min(n_results, self.collection.count()),
              )
              docs = results.get("documents", [[]])[0]
              return "\n".join(docs)
          except Exception as e:
              print(f"⚠️  RAG query failed: {e}")
              return ""
  ```

  **Git Checkpoint:**
  ```bash
  git add src/rag_retriever.py
  git commit -m "step 5: add RAG retriever with empty-collection guard"
  ```

  **✓ Verification Test:**

  **Type:** Integration

  **Action:**
  ```bash
  python -c "
  from src.rag_retriever import RAGRetriever
  rag = RAGRetriever()
  assert rag._available, 'RAG not available — run python -m src.knowledge_base first'

  # Test with real anomaly shape from deviation_detector
  anomalies = [{'activity': 'pill_taking', 'type': 'MISSING', 'message': 'test', 'severity': 'HIGH'}]
  context = rag.get_context(anomalies)
  assert len(context) > 0, 'Expected context, got empty string'
  print('PASS: context retrieved')
  print(context[:100])

  # Test empty anomalies returns empty string (not crash)
  empty = rag.get_context([])
  assert empty == '', f'Expected empty string, got: {empty}'
  print('PASS: empty anomalies handled')
  "
  ```

  **Pass:** Both `PASS` lines printed, context preview shown

  **Fail:**
  - If `_available = False` → Step 4 verification did not pass → re-run Step 4
  - If context is empty → query terms built incorrectly → print `query_terms` inside `get_context` to debug

---

- [ ] 🟥 **Step 6: Create `src/llm_explainer.py`** — *Critical: agent depends on this*

  **Idempotent:** Yes — stateless function, no side effects.

  **Context:** Calls Groq API with risk data and RAG context. Key fix from Logic Check Warning 1: key validity checked at call time, not import time. `_available` flag only reflects whether `groq` package is installed. Empty or invalid key produces a graceful fallback dict, not a crash.

  Create file at exactly: `src/llm_explainer.py`

  ```python
  """
  llm_explainer.py
  =================
  Calls Groq (free tier) to produce a plain-English explanation of a risk result.
  Falls back to a structured default if Groq is unavailable or key is invalid.

  Requires env var: GROQ_API_KEY
  Set in .env file or: export GROQ_API_KEY="your_key_here"
  """

  import os
  import json
  from pathlib import Path

  # Load .env from repo root if present
  _env_path = Path(__file__).resolve().parents[1] / ".env"
  if _env_path.exists():
      try:
          from dotenv import load_dotenv
          load_dotenv(_env_path)
      except ImportError:
          pass

  try:
      from groq import Groq
      _groq_available = True
  except ImportError:
      print("⚠️  groq not installed. Run: pip install groq")
      _groq_available = False


  def explain_risk(
      person_id: str,
      risk_score: int,
      risk_level: str,
      anomalies: list,
      rag_context: str = "",
  ) -> dict:
      """
      Returns dict with keys:
        summary        — 2 sentences, plain English for family
        concern_level  — "normal" | "watch" | "urgent"
        action         — one specific thing family should do now
        positive       — one positive observation about today

      Never raises — returns fallback dict on any failure.
      """
      api_key = os.environ.get("GROQ_API_KEY", "").strip()

      # Check key at call time, not import time (fixes Logic Check Warning 1)
      if not _groq_available or not api_key:
          return _fallback(risk_score, risk_level, anomalies)

      context_block = f"\nMedical Context from knowledge base:\n{rag_context}" if rag_context else ""

      prompt = f"""You are CareWatch, a caring elderly monitoring assistant.
  A family member is checking on their loved one. Be warm, clear, and concise.
  Do not use markdown formatting, asterisks, or underscores in your response.

  Return ONLY valid JSON with exactly these keys:
  {{
    "summary": "2 sentences explaining what happened today in plain English",
    "concern_level": "normal or watch or urgent",
    "action": "one specific thing the family should do right now",
    "positive": "one positive observation about today"
  }}

  Data:
  - Person: {person_id}
  - Risk Score: {risk_score}/100
  - Risk Level: {risk_level}
  - Issues detected: {json.dumps(anomalies)}{context_block}

  JSON only. No markdown. No extra text."""

      try:
          client   = Groq(api_key=api_key)
          response = client.chat.completions.create(
              model="llama3-8b-8192",
              messages=[{"role": "user", "content": prompt}],
              max_tokens=300,
              temperature=0.3,
          )
          raw = response.choices[0].message.content.strip()
          return json.loads(raw)
      except json.JSONDecodeError:
          print(f"⚠️  LLM returned non-JSON. Using fallback.")
          return _fallback(risk_score, risk_level, anomalies)
      except Exception as e:
          print(f"⚠️  LLM call failed: {e}. Using fallback.")
          return _fallback(risk_score, risk_level, anomalies)


  def _fallback(risk_score: int, risk_level: str, anomalies: list) -> dict:
      """Safe default when Groq is unavailable."""
      n = len([a for a in anomalies if isinstance(a, dict)])
      return {
          "summary":       f"Risk score is {risk_score}/100 ({risk_level}). {n} issue(s) detected today.",
          "concern_level": {"GREEN": "normal", "YELLOW": "watch", "RED": "urgent"}.get(risk_level, "watch"),
          "action":        "Call or visit immediately." if risk_level == "RED" else "Check the dashboard for details.",
          "positive":      "Monitoring is active and working normally.",
      }
  ```

  **Git Checkpoint:**
  ```bash
  git add src/llm_explainer.py
  git commit -m "step 6: add Groq LLM explainer with fallback and key-at-call-time check"
  ```

  **Subtasks:**
  - [ ] 🟥 `GROQ_API_KEY` added to `.env` file
  - [ ] 🟥 File created
  - [ ] 🟥 Verification passes

  **✓ Verification Test:**

  **Type:** Integration

  **Action:**
  ```bash
  # Test 1: fallback works with no key — runs in its own subprocess.
  # GROQ_API_KEY= ensures empty env before import; load_dotenv does not override existing vars.
  GROQ_API_KEY= python -c "
  from src.llm_explainer import explain_risk
  fallback = explain_risk('resident', 50, 'YELLOW', [])
  assert all(k in fallback for k in ['summary', 'concern_level', 'action', 'positive']), f'Missing keys: {fallback.keys()}'
  assert fallback['concern_level'] == 'watch', f'Expected watch for YELLOW, got: {fallback[\"concern_level\"]}'
  print('PASS: fallback works without key')
  "

  # Tests 2–3 run in a completely separate process with key present (from .env)
  python -c "
  from src.llm_explainer import explain_risk

  # Test 2: with a real anomaly (uses Groq if key present)
  result = explain_risk(
      person_id='resident',
      risk_score=75,
      risk_level='RED',
      anomalies=[{'activity': 'pill_taking', 'type': 'MISSING', 'message': 'Pill Taking not detected', 'severity': 'HIGH'}],
      rag_context='pill_taking: Missed pill-taking activity combined with risk score above 60 requires family notification.',
  )
  assert all(k in result for k in ['summary', 'concern_level', 'action', 'positive']), f'Missing keys: {result.keys()}'
  assert result['concern_level'] in ('normal', 'watch', 'urgent'), f'Bad concern_level: {result[\"concern_level\"]}'
  print('PASS:', result['concern_level'])
  print('Summary:', result['summary'])
  "
  ```

  **Pass:** `PASS: fallback works without key` and `PASS: [concern_level]` both printed

  **Fail:**
  - If `ModuleNotFoundError: dotenv` → run `pip install python-dotenv` (Step 1 adds it; may have been skipped)
  - If `AuthenticationError` → key is set but invalid → check `.env` value
  - If `JSONDecodeError caught` → model returned text not JSON → prompt may need tightening, fallback will activate

---

- [ ] 🟥 **Step 7: Create `src/agent.py`** — *Critical: orchestrator, depends on Steps 2–6 all passing*

  **Idempotent:** Yes — `run()` is stateless, reads DB and calls APIs, no writes.

  **Context:** The orchestrator that sequences all AI layers. Calls `DeviationDetector.check()` (unchanged), feeds anomalies to `RAGRetriever.get_context()`, passes everything to `explain_risk()`, merges into one result dict, and optionally fires an alert. This is the function the new API endpoint will call.

  **Pre-Read Gate:**
  ```bash
  # Confirm all dependencies exist before creating this file
  python -c "from src.deviation_detector import DeviationDetector; print('detector OK')"
  python -c "from src.rag_retriever import RAGRetriever; print('rag OK')"
  python -c "from src.llm_explainer import explain_risk; print('llm OK')"
  python -c "from src.alert_system import AlertSystem; print('alert OK')"
  ```
  All four must print OK. If any fail → fix that step before proceeding.

  Create file at exactly: `src/agent.py`

  ```python
  """
  agent.py
  =========
  CareWatch AI orchestrator.
  Sequences: deviation detection → RAG context → LLM explanation → optional alert.

  USAGE:
      from src.agent import CareWatchAgent
      agent = CareWatchAgent()
      result = agent.run("resident")
      # result["ai_explanation"] contains plain-English summary for family
  """

  from src.deviation_detector import DeviationDetector
  from src.rag_retriever import RAGRetriever
  from src.llm_explainer import explain_risk
  from src.alert_system import AlertSystem


  class CareWatchAgent:
      def __init__(self):
          self.detector = DeviationDetector()
          self.rag      = RAGRetriever()
          self.alerts   = AlertSystem()

      def run(self, person_id: str = "resident", send_alert: bool = True) -> dict:
          """
          Full agent loop:
            1. Compute risk score using existing DeviationDetector (unchanged logic)
            2. Retrieve medical context from ChromaDB RAG for detected anomalies
            3. Call Groq LLM to produce plain-English explanation
            4. Merge into one complete result dict
            5. Optionally fire Telegram alert with explanation attached

          Returns the full result dict. Never raises.
          """
          print(f"🤖 CareWatch Agent running for: {person_id}")

          # Step 1: Existing risk logic — zero changes to deviation_detector.py
          try:
              risk_result = self.detector.check(person_id)
          except Exception as e:
              print(f"❌ Detector failed: {e}")
              return {"error": str(e), "risk_score": 0, "risk_level": "UNKNOWN", "anomalies": []}

          print(f"   Risk: {risk_result['risk_score']}/100 ({risk_result['risk_level']})")

          # Step 2: RAG — get medical context for detected anomalies
          # anomalies shape: [{"activity", "type", "message", "severity"}]
          anomalies   = risk_result.get("anomalies", [])
          rag_context = self.rag.get_context(anomalies)
          if rag_context:
              print(f"   RAG: context retrieved ({len(rag_context)} chars)")
          else:
              print(f"   RAG: no context (unavailable or no anomalies)")

          # Step 3: LLM explanation — graceful fallback built in
          explanation = explain_risk(
              person_id=person_id,
              risk_score=risk_result["risk_score"],
              risk_level=risk_result["risk_level"],
              anomalies=anomalies,
              rag_context=rag_context,
          )
          print(f"   LLM: concern_level={explanation.get('concern_level', 'unknown')}")

          # Step 4: Merge into unified result
          full_result = {
              **risk_result,
              "ai_explanation":   explanation,
              "rag_context_used": bool(rag_context),
          }

          # Step 5: Alert (only YELLOW/RED; alert_system.py handles the gate)
          if send_alert:
              self.alerts.send(full_result, person_name=person_id.replace("_", " ").title())

          return full_result
  ```

  **Git Checkpoint:**
  ```bash
  git add src/agent.py
  git commit -m "step 7: add CareWatch AI agent orchestrator (RAG + LLM + alert)"
  ```

  **Subtasks:**
  - [ ] 🟥 All four dependency imports confirmed OK
  - [ ] 🟥 File created
  - [ ] 🟥 Verification passes

  **✓ Verification Test:**

  **Type:** Integration

  **Action:**
  ```bash
  python -c "
  from src.agent import CareWatchAgent
  agent = CareWatchAgent()

  # Run without sending alert (safe for testing)
  result = agent.run('resident', send_alert=False)

  # Confirm structure
  assert 'risk_score' in result,      'Missing risk_score'
  assert 'risk_level' in result,      'Missing risk_level'
  assert 'ai_explanation' in result,  'Missing ai_explanation'
  assert 'rag_context_used' in result,'Missing rag_context_used'

  ai = result['ai_explanation']
  assert all(k in ai for k in ['summary', 'concern_level', 'action', 'positive']), f'Missing AI keys: {ai.keys()}'

  print('PASS: agent loop complete')
  print('Risk:', result['risk_score'], result['risk_level'])
  print('AI concern:', ai['concern_level'])
  print('Summary:', ai['summary'])
  "
  ```

  **Pass:** `PASS: agent loop complete` printed with valid risk and AI fields

  **Fail:**
  - If `ImportError` on any src module → that step's verification did not pass → fix before retrying
  - If `ai_explanation` missing → `explain_risk` raised and was not caught → check `llm_explainer.py` try/except

---

### Phase 3 — Expose via API

**Goal:** `/api/agent/explain` endpoint live. Dashboard can call it. `fastAPI` import bug fixed.

---

- [ ] 🟥 **Step 8: Fix and extend `app/api.py`** — *Critical: API contract change + existing bug fix*

  **Idempotent:** Yes — fixes are targeted replacements; new endpoint is additive.

  **Context:** Two changes. Fix A: `from fastAPI import FastAPI` → `from fastapi import FastAPI` (currently crashes uvicorn on startup). Fix B: add `CareWatchAgent` import and `/api/agent/explain` endpoint. Fix A must apply first.

  **Pre-Read Gate:**
  ```bash
  # Confirm Bug A — must return exactly 1 match
  grep -n "from fastAPI import" app/api.py
  # Expected: 1 match on line 1

  # Confirm insertion anchor for new endpoint — must return exactly 1 match
  grep -n "def get_risk" app/api.py
  # New endpoint goes AFTER this function

  # Confirm CareWatchAgent not already imported
  grep -n "CareWatchAgent" app/api.py
  # Expected: no matches
  ```

  **Fix A** — correct the FastAPI import.

  Find this exact line (line 1 of `api.py`):
  ```python
  from fastAPI import FastAPI
  ```
  Replace with:
  ```python
  from fastapi import FastAPI
  ```

  **Fix B** — add agent import after existing src imports.

  Find this exact line:
  ```python
  from src.deviation_detector import DeviationDetector
  ```
  Replace with:
  ```python
  from src.deviation_detector import DeviationDetector
  from src.agent import CareWatchAgent
  ```

  **Fix C** — instantiate agent after existing instances.

  Find this exact line:
  ```python
  detector = DeviationDetector()
  ```
  Replace with:
  ```python
  detector = DeviationDetector()
  agent    = CareWatchAgent()
  ```

  **Fix D** — add new endpoint. Find this exact function closing (the last line of `get_risk()`):
  ```python
      return detector.check(PERSON)
  ```
  Replace with:
  ```python
      return detector.check(PERSON)


  @app.get("/api/agent/explain")
  def get_agent_explanation():
      """Full AI agent loop: risk score + RAG context + LLM explanation.
      Use this endpoint for the dashboard AI card. Does not send Telegram alert."""
      return agent.run(PERSON, send_alert=False)
  ```

  **What it does:** Fixes startup crash. Adds one new GET endpoint that returns the full agent result including `ai_explanation`.

  **Why this approach:** Additive only. All existing endpoints unchanged. `send_alert=False` ensures hitting the endpoint never fires Telegram — safe for polling.

  **Risks:**
  - `CareWatchAgent()` instantiated at module level — if ChromaDB unavailable at startup, RAG falls back gracefully (Step 5 design) → no startup crash

  **Git Checkpoint:**
  ```bash
  git add app/api.py
  git commit -m "step 8: fix fastapi import, add /api/agent/explain endpoint"
  ```

  **Subtasks:**
  - [ ] 🟥 Fix A applied — `fastAPI` → `fastapi`
  - [ ] 🟥 Fix B + C applied — agent imported and instantiated
  - [ ] 🟥 Fix D applied — new endpoint added
  - [ ] 🟥 Verification passes

  **✓ Verification Test:**

  **Type:** E2E

  **Action:**
  ```bash
  # Terminal 1: start API
  uvicorn app.api:app --reload --port 8000 --workers 1

  # Terminal 2: hit both old and new endpoints
  python -c "
  import urllib.request, json, time
  time.sleep(2)  # wait for startup

  # Old endpoint must still work
  r1 = urllib.request.urlopen('http://localhost:8000/api/risk')
  d1 = json.loads(r1.read())
  assert 'risk_score' in d1, f'Old endpoint broken: {d1}'
  print('PASS: /api/risk still works')

  # New endpoint
  r2 = urllib.request.urlopen('http://localhost:8000/api/agent/explain')
  d2 = json.loads(r2.read())
  assert 'ai_explanation' in d2, f'Missing ai_explanation: {d2.keys()}'
  assert 'summary' in d2['ai_explanation'], f'Missing summary: {d2[\"ai_explanation\"].keys()}'
  print('PASS: /api/agent/explain works')
  print('Concern level:', d2['ai_explanation']['concern_level'])
  "
  ```

  **Pass:** Both `PASS` lines printed

  **Fail:**
  - If `uvicorn` fails to start → Fix A not applied → re-check grep and retry
  - If `/api/risk` returns 404 → wrong file edited → confirm changes are in `app/api.py`
  - If `/api/agent/explain` returns 500 → agent crash → check Step 7 verification passed

---

### Phase 4 — Final Verification and Push

---

- [ ] 🟥 **Step 9: End-to-end test, README update, git push** — *Non-critical*

  **Idempotent:** Yes.

  **Action — full pipeline smoke test:**
  ```bash
  python -c "
  from src.agent import CareWatchAgent
  from src.alert_system import AlertSystem

  agent = CareWatchAgent()

  # Simulate RED scenario
  result = agent.run('resident', send_alert=False)
  print('=== FULL AGENT RESULT ===')
  import json
  print(json.dumps(result, indent=2, default=str))
  "
  ```

  **README block to add** (paste at top of existing README, above current content):

  ```markdown
  ## AI Agent Layer

  CareWatch includes an AI agent that augments the computer vision pipeline with
  language-model reasoning and medical knowledge retrieval.

  **Architecture:**
  ```
  YOLO pose → LSTM classifier → DeviationDetector (risk score)
                                        ↓
                               [CareWatchAgent orchestrator]
                                ↙            ↓           ↘
                       RAG lookup      LLM reasoning    Alert gate
                      (ChromaDB)         (Groq)      (Telegram)
                                ↘            ↓           ↙
                                   Structured result dict
                                  ↙                    ↘
                         /api/agent/explain        Telegram alert
                         (Next.js dashboard)    (plain-English family message)
  ```

  **Stack:** YOLO11x-pose · PyTorch LSTM · ChromaDB · Groq (llama3-8b) · FastAPI · Next.js · Telegram Bot API

  **Run the agent:**
  ```bash
  python -c "from src.agent import CareWatchAgent; import json; print(json.dumps(CareWatchAgent().run('resident', send_alert=False), indent=2, default=str))"
  ```
  ```

  **Final push:**
  ```bash
  git add README.md
  git commit -m "step 9: update README with AI agent architecture"
  git push origin carewatch-dev
  ```

  **✓ Verification Test:**

  **Type:** E2E

  **Action:** Open `https://github.com/brandonyeo0611-gif/PillReminder/tree/carewatch-dev`

  **Expected:** 9 commits visible on `carewatch-dev` since this plan started. `src/agent.py`, `src/llm_explainer.py`, `src/rag_retriever.py`, `src/knowledge_base.py` all visible in `src/`.

  **Pass:** All 4 new files visible on GitHub

  **Fail:** If files missing → `git push` did not run → re-run push command

---

## Regression Guard

| System | Pre-change behaviour | Post-change verification |
|--------|---------------------|--------------------------|
| `/api/risk` endpoint | Returns `{risk_score, risk_level, anomalies, summary}` | Hit endpoint after Step 8 — same keys must be present |
| `AlertSystem.send()` on GREEN | Prints to console, no Telegram | Call `send({'risk_level': 'GREEN', 'risk_score': 10, 'anomalies': [], 'summary': 'test'})` — must not crash |
| `DeviationDetector.check()` | Returns risk dict | Call directly after Step 7 — result unchanged, no new keys added by detector |

**Test count:** No automated test suite detected for Python src files. Regression guard is manual only.

---

## Rollback Procedure

```bash
# Reverse order — one revert per step commit
git revert HEAD     # step 9 README
git revert HEAD~1   # step 8 api.py
git revert HEAD~2   # step 7 agent.py
git revert HEAD~3   # step 6 llm_explainer.py
git revert HEAD~4   # step 5 rag_retriever.py
git revert HEAD~5   # step 4 knowledge_base.py
git revert HEAD~6   # step 3 drug_interactions.txt
git revert HEAD~7   # step 2 alert_system.py fixes
git revert HEAD~8   # step 1 (no code changes, no revert needed)

# Confirm back to baseline
python -c "from src.alert_system import AlertSystem; print('OK')"
python -c "from app.api import app; print('OK')"
```

---

## Risk Heatmap

| Step | Risk | What Could Go Wrong | Early Detection | Idempotent |
|------|------|---------------------|-----------------|------------|
| 1 | 🟢 Low | pip install fails | ImportError on verify | Yes |
| 2 | 🟡 Medium | Wrong grep anchor — fix applied to wrong line | grep pre-read confirms 1 match | Yes |
| 3 | 🟢 Low | File saved to wrong path | FileNotFoundError on verify | Yes |
| 4 | 🟡 Medium | ChromaDB path resolves differently on Windows | Verify query returns 12 docs | Yes |
| 5 | 🟡 Medium | Empty collection guard missing (Flaw 3) | Fixed in this plan | Yes |
| 6 | 🟡 Medium | Groq key invalid — silently uses fallback | Fallback prints warning | Yes |
| 7 | 🔴 High | Any upstream import fails → agent won't load | Pre-read gate checks all 4 deps | Yes |
| 8 | 🔴 High | Wrong fastAPI→fastapi fix breaks other imports | grep confirms single match before replace | Yes |
| 9 | 🟢 Low | Push to wrong branch | Confirm `git branch` shows carewatch-dev | Yes |

---

## Success Criteria

| Feature | Target | Verification |
|---------|--------|--------------|
| Telegram alerts contain AI explanation | YELLOW/RED alerts include `summary`, `action`, `positive` fields | Trigger alert manually, read Telegram message |
| `/api/agent/explain` endpoint live | Returns `{risk_score, ai_explanation: {summary, concern_level, action, positive}, rag_context_used}` | `curl http://localhost:8000/api/agent/explain` |
| RAG retrieves drug context | Anomaly with `pill_taking` returns relevant fact from knowledge base | Step 5 verification test |
| Fallback on missing Groq key | `explain_risk()` returns valid dict even with no key set | Step 6 verification test 2 |
| Regression: existing endpoints unchanged | `/api/risk`, `/api/logs/today`, `/api/baseline` return same shapes as before | Hit all three after Step 8 |
| FastAPI startup fixed | `uvicorn app.api:app` starts without ImportError | Step 8 verification |

---

⚠️ **Do not mark a step 🟩 Done until its verification test passes.**
⚠️ **Do not proceed past a Human Gate without explicit human input.**
⚠️ **If blocked, mark 🟨 In Progress and output the State Manifest before stopping.**
⚠️ **Do not batch multiple steps into one git commit.**
⚠️ **If idempotent = No, confirm the step has not already run before executing.**