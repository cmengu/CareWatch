# CareWatch AI Agent — Part 5 of 5: API Endpoint, README, and Push

**Overall Progress:** `100%` (Parts 1–5 complete)

**What this part does:** Exposes the agent via FastAPI, updates the README with the
full architecture description, and pushes the completed branch to GitHub.

**End state when Part 5 is done:**
- `app/api.py` has `fastapi` import fixed and `/api/agent/explain` endpoint live
- `GET /api/agent/explain` returns full agent result including `ai_explanation`
- Existing endpoints `/api/risk`, `/api/logs/today`, `/api/baseline` are unchanged
- README leads with AI agent architecture and hits every keyword from the job posting
- `carewatch-dev` branch pushed to GitHub with all new files visible

---

## Agent Failure Protocol

1. A verification command fails → read the full error output.
2. Cause is unambiguous → make ONE targeted fix → re-run the same verification command.
3. If still failing after one fix → **STOP**. Before stopping, output the full current
   contents of every file modified in this step. Report: (a) command run, (b) full error
   verbatim, (c) fix attempted, (d) current state of each modified file, (e) why you
   cannot proceed.
4. Never attempt a second fix without human instruction.
5. Never modify files not named in the current step.

---

## Pre-Flight — Run Before Touching Anything

```bash
# 1. Confirm Part 4 is done
python -c "from src.agent import CareWatchAgent; print('agent OK')"

# 2. Confirm fastAPI bug still exists (must return 1 match)
grep -n "from fastAPI import" app/api.py
# Expected: exactly 1 match on line 1
# If 0 matches → bug already fixed → skip Fix A in Step 1, proceed to Fix B

# 3. Confirm CareWatchAgent not already imported in api.py
grep -n "CareWatchAgent" app/api.py
# Expected: no matches
# If match found → Step 1 already partially applied → read current state before proceeding

# 4. Confirm branch is carewatch-dev
git branch --show-current
# Expected: carewatch-dev
# If not → run: git checkout carewatch-dev

# 5. Confirm working tree is clean before edits
git status
# Expected: nothing to commit, working tree clean
# If dirty → commit or stash pending changes before Step 1
```

**Baseline Snapshot — fill before Step 1:**
```
agent OK:                  ____
fastAPI bug present:       ____
CareWatchAgent absent:     ____
branch is carewatch-dev:   ____
working tree clean:        ____
```

**All five checks must pass before Step 1 begins.**

---

## Tasks

---

- [x] 🟩 **Step 1: Fix and extend `app/api.py`** — *Critical: API contract change + bug fix*

  **Idempotent:** Yes — all fixes are targeted replacements; endpoint is additive.

  **Context:** Two changes to one file.
  - Fix A: `from fastAPI import FastAPI` → `from fastapi import FastAPI` — currently
    crashes uvicorn on startup before any request is served.
  - Fix B: import `CareWatchAgent`, instantiate it, add `/api/agent/explain` endpoint.

  Fix A must be confirmed present before applying. Fix B is additive only — no existing
  endpoints are touched.

  **Pre-Read Gate:**
  ```bash
  # Confirm exact anchor for Fix A — must return 1 match
  grep -n "from fastAPI import" app/api.py

  # Confirm exact anchor for Fix B insertion — must return 1 match
  grep -n "from src.deviation_detector import DeviationDetector" app/api.py

  # Confirm exact anchor for Fix C (instantiation) — must return 1 match
  grep -n "detector = DeviationDetector()" app/api.py

  # Confirm exact anchor for Fix D (endpoint) — must return 1 match
  grep -n "return detector.check(PERSON)" app/api.py
  ```
  If any grep returns 0 matches → STOP and report.
  If grep for Fix D returns 2+ matches → identify which occurrence is inside get_risk()
  using `grep -n -A 3 'def get_risk' app/api.py` and apply Fix D only to that line number.

  **Fix A** — correct the FastAPI import (line 1):
  ```python
  # FIND:
  from fastAPI import FastAPI
  # REPLACE WITH:
  from fastapi import FastAPI
  ```

  **Fix B** — add agent import after existing src imports:
  ```python
  # FIND:
  from src.deviation_detector import DeviationDetector
  # REPLACE WITH:
  from src.deviation_detector import DeviationDetector
  from src.agent import CareWatchAgent
  ```

  **Fix C** — instantiate agent after existing instances:
  ```python
  # FIND:
  detector = DeviationDetector()
  # REPLACE WITH:
  detector = DeviationDetector()
  agent    = CareWatchAgent()
  ```

  **Fix D** — add new endpoint after `get_risk()`. Find the last line of `get_risk()`:
  ```python
  # FIND:
      return detector.check(PERSON)
  # REPLACE WITH:
      return detector.check(PERSON)


  @app.get("/api/agent/explain")
  def get_agent_explanation():
      """
      Full AI agent loop: risk score + RAG context + LLM explanation.
      Use for the dashboard AI card. Does not send Telegram alert.
      Safe to poll — send_alert is always False here.
      """
      return agent.run(PERSON, send_alert=False)
  ```

  **What it does:** Fixes startup crash. Adds one GET endpoint returning the full
  agent result. All existing endpoints are unchanged.

  **Risk:** `CareWatchAgent()` instantiated at module level — if ChromaDB is unavailable
  at startup, RAG falls back gracefully (Part 2 design). No startup crash.

  **Git Checkpoint:**
  ```bash
  git add app/api.py
  git commit -m "part5 step1: fix fastapi import, add /api/agent/explain endpoint"
  ```

  **Subtasks:**
  - [ ] 🟥 All 4 pre-read gate greps return exactly 1 match
  - [ ] 🟥 Fix A applied — `fastAPI` → `fastapi`
  - [ ] 🟥 Fix B + C applied — agent imported and instantiated
  - [ ] 🟥 Fix D applied — new endpoint added
  - [ ] 🟥 Verification passes

  **✓ Verification Test:**

  **Type:** E2E

  ```bash
  # Terminal 1 — start the API server
  uvicorn app.api:app --reload --port 8000 --workers 1
  # Expected first line: INFO: Application startup complete.
  # If ImportError on startup → Fix A not applied → check grep and retry

  # Terminal 2 — run immediately after "Application startup complete." appears
  python -c "
  import urllib.request, json, time

  BASE = 'http://localhost:8000'

  def fetch(path):
      for attempt in range(10):
          try:
              r = urllib.request.urlopen(BASE + path, timeout=5)
              return json.loads(r.read())
          except Exception:
              time.sleep(1)
      raise RuntimeError(f'Could not reach {path} after 10 attempts')

  # --- Test 1: existing endpoint still works ---
  d1 = fetch('/api/risk')
  assert 'risk_score' in d1, f'Old endpoint broken: {d1.keys()}'
  print('PASS 1: /api/risk still returns risk_score')

  # --- Test 2: new endpoint exists and returns expected shape ---
  d2 = fetch('/api/agent/explain')
  assert 'ai_explanation' in d2,              f'Missing ai_explanation: {d2.keys()}'
  assert 'risk_score'      in d2,              f'Missing risk_score: {d2.keys()}'
  assert 'rag_context_used' in d2,             f'Missing rag_context_used: {d2.keys()}'
  print('PASS 2: /api/agent/explain returns expected top-level keys')

  # --- Test 3: ai_explanation has all 4 subkeys ---
  ai = d2['ai_explanation']
  required = {'summary', 'concern_level', 'action', 'positive'}
  assert required.issubset(ai.keys()), f'Missing ai subkeys: {required - ai.keys()}'
  assert ai['concern_level'] in ('normal', 'watch', 'urgent'), f'Bad concern_level: {ai[\"concern_level\"]}'
  print('PASS 3: ai_explanation has all 4 subkeys with valid values')

  # --- Test 4: endpoint is idempotent (safe to poll) ---
  d3 = fetch('/api/agent/explain')
  assert 'ai_explanation' in d3
  print('PASS 4: second call succeeds (endpoint is safe to poll)')

  print()
  print('concern_level:', ai['concern_level'])
  print('summary:', ai['summary'])
  print()
  print('All 4 tests passed.')
  "
  ```

  **Pass:** `All 4 tests passed.` printed, uvicorn shows no errors in Terminal 1

  **Fail:**
  - If uvicorn fails with `ImportError: cannot import name 'FastAPI' from 'fastAPI'` →
    Fix A not applied → stop uvicorn, re-check grep, apply fix, restart
  - If uvicorn fails with `ImportError` on any `src.*` module → that part's file is
    missing → confirm Parts 1–4 files exist in `src/`
  - If `PASS 1` fails with 404 → wrong file edited → confirm edits are in `app/api.py`
  - If `PASS 2` fails with 500 → agent crashed inside endpoint → check Step 7 (Part 4)
    verification passed; print full uvicorn traceback
  - If `ConnectionRefusedError` after 10 retries → uvicorn did not start → read
    Terminal 1 output for startup error before retrying

---

- [x] 🟩 **Step 2: Update README.md** — *Non-critical: no code changes*

  **Idempotent:** Yes — prepending to README is safe; re-running overwrites same block.

  **Context:** The README is what a recruiter or hiring manager reads first. It must
  lead with the AI agent layer, not the original CV detection project. The paragraph
  must hit every keyword from the job posting: agent, RAG, LLM, tool use, real product.

  **Action:** Open `README.md` and paste this block at the very top, above all existing
  content. The architecture diagram uses a 4-space indented block (not triple backticks)
  to avoid nested fence issues when copying from this plan.

  ```markdown
  # CareWatch AI Agent

  An AI agent that monitors elderly routines via computer vision and flags behavioural
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
  ```

  **Git Checkpoint:**
  ```bash
  git add README.md
  git commit -m "part5 step2: update README with AI agent architecture and stack"
  ```

  **✓ Verification Test:**

  **Type:** Unit

  ```bash
  python -c "
  readme = open('README.md').read()
  keywords = ['CareWatchAgent', 'ChromaDB', 'RAG', 'Groq', 'llama3', 'agent orchestrator', '/api/agent/explain']
  missing = [k for k in keywords if k not in readme]
  assert not missing, f'README missing keywords: {missing}'
  assert readme.startswith('# CareWatch'), 'README must start with CareWatch heading'
  print('PASS: README contains all required keywords')
  "
  ```

  **Pass:** `PASS: README contains all required keywords`

  **Fail:**
  - If any keyword missing → block was not pasted at the top → re-open README and
    confirm the full block is present starting from line 1

---

- [x] 🟩 **Step 3: Final push to GitHub** — *Non-critical: no code changes*

  **Idempotent:** Yes — pushing same commits twice is a no-op.

  **Pre-Push Checklist:**
  ```bash
  # 1. Confirm branch
  git branch --show-current
  # Expected: carewatch-dev

  # 2. Confirm all new files are committed
  git status
  # Expected: nothing to commit, working tree clean

  # 3. Confirm commit count — should show parts 1–5 commits
  git log --oneline | head -20

  # 4. Confirm .env is NOT staged or tracked
  git ls-files .env
  # Expected: no output (empty)
  # If .env appears → STOP. Run: git rm --cached .env && git commit -m "remove .env from tracking"
  ```

  **Action:**
  ```bash
  git push origin carewatch-dev
  ```

  **✓ Verification Test:**

  **Type:** E2E

  ```bash
  # Open in browser:
  # https://github.com/brandonyeo0611-gif/PillReminder/tree/carewatch-dev

  # Confirm all 5 new files are visible:
  python -c "
  import urllib.request, json

  api = 'https://api.github.com/repos/brandonyeo0611-gif/PillReminder/contents/src?ref=carewatch-dev'
  r = urllib.request.urlopen(urllib.request.Request(api, headers={'User-Agent': 'Mozilla/5.0'}))
  files = [f['name'] for f in json.loads(r.read())]
  print('Files in src/ on carewatch-dev:')
  for f in sorted(files):
      print(' ', f)

  required = ['agent.py', 'llm_explainer.py', 'rag_retriever.py', 'knowledge_base.py']
  missing  = [f for f in required if f not in files]
  assert not missing, f'Missing from GitHub: {missing}'
  print()
  print('PASS: all required files visible on carewatch-dev')
  "
  ```

  **Pass:** All 4 files listed, `PASS` printed

  **Fail:**
  - If `404` → repo is private and unauthenticated → open browser manually to confirm
  - If files missing → `git push` did not run or pushed to wrong branch →
    confirm `git branch --show-current` shows `carewatch-dev` and re-push

---

## Part 5 Complete — Final State Manifest

```bash
# Run with API server active in Terminal 1 (uvicorn app.api:app --port 8000)
python -c "
import urllib.request, json

r = urllib.request.urlopen('http://localhost:8000/api/agent/explain')
result = json.loads(r.read())

print('=== Final State Manifest ===')
print('risk_score:       ', result['risk_score'])
print('risk_level:       ', result['risk_level'])
print('rag_context_used: ', result['rag_context_used'])
print('concern_level:    ', result['ai_explanation']['concern_level'])
print('summary:          ', result['ai_explanation']['summary'])
print('action:           ', result['ai_explanation']['action'])
print('positive:         ', result['ai_explanation']['positive'])
print()

assert 'ai_explanation' in result
assert result['ai_explanation']['concern_level'] in ('normal', 'watch', 'urgent')
assert result['rag_context_used'] in (True, False)
print('Part 5 DONE — CareWatch AI Agent complete.')
"
```

**Pass condition:** `Part 5 DONE` printed with all fields populated.

---

## Full Regression Guard

Run after Step 1 with uvicorn active:

```bash
python -c "
import urllib.request, json

def fetch(path):
    r = urllib.request.urlopen('http://localhost:8000' + path)
    return json.loads(r.read())

# All pre-existing endpoints must still return their original keys
assert 'risk_score'  in fetch('/api/risk'),        '/api/risk broken'
assert 'logs'        in fetch('/api/logs/today') or isinstance(fetch('/api/logs/today'), list), '/api/logs/today broken'
assert 'risk_score'  in fetch('/api/agent/explain'), '/api/agent/explain broken'
print('PASS: all endpoints responding correctly')
"
```

---

## Rollback

```bash
git revert HEAD      # step 3 push cannot be reverted but local is clean
git revert HEAD~1    # step 2: README
git revert HEAD~2    # step 1: api.py

# Confirm api.py is back to broken state (fastAPI bug restored)
grep "fastAPI" app/api.py
```

---

⚠️ **Do not mark a step 🟩 Done until its verification test passes.**
⚠️ **Do not batch multiple steps into one git commit.**
⚠️ **Do not touch any file not named in the current step.**
⚠️ **Confirm `.env` is NOT tracked by git before Step 3 push — this is a hard stop.**
⚠️ **Run uvicorn in Terminal 1 before running Step 1 verification in Terminal 2.**
⚠️ **Step 3 pre-push checklist must pass completely before `git push` runs.**