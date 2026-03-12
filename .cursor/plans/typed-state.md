# CareWatch — Typed State: Pydantic Models

**Overall Progress:** `0%` (0/5 steps complete)

## TLDR

Adds Pydantic models for `RiskResult` and `AgentResult` at the three boundaries that matter:
`deviation_detector.check()` → `agent.run()` → `/api/agent/explain`. Creates `src/models.py`
as the single source of truth for data contracts, types both return signatures, adds
`response_model` to the API endpoint, and fixes the `alert_system.py` anomaly iteration
bug discovered during the audit. After this plan, every boundary has an explicit contract
and shape violations crash loudly at the source instead of silently corrupting downstream.

---

## Critical Decisions

- **Decision 1: One models file, not per-module** — `src/models.py` is the single source of truth. Avoids circular imports and makes contracts visible in one place.
- **Decision 2: `checked_at` is `Optional[str]`** — Cursor confirmed it only appears on some paths. Making it required would break the no-baseline path.
- **Decision 3: Anomalies typed as `List[Union[AnomalyItem, str]]`** — Cursor confirmed the no-baseline path returns `[str]`. Union preserves existing behaviour while making both shapes explicit.
- **Decision 4: Don't type internals** — YOLO keypoints, LSTM, SQLite reads are internal implementation detail. Only type what crosses a module boundary another module depends on.
- **Decision 5: Fix alert_system anomaly loop in same plan** — Cursor confirmed `a["severity"]` and `a["message"]` are accessed without `isinstance` guard. This is the known crash bug. Fix it here since models.py makes `AnomalyItem` available to import.

---

## Clarification Gate

All unknowns resolved from Cursor output. No human input required before Step 1.

| Unknown | Resolution | Source |
|---------|-----------|--------|
| `check()` return shape | `risk_score, risk_level, anomalies, summary, checked_at(optional)` | Cursor read |
| `run()` return shape | spread of RiskResult + `ai_explanation`, `rag_context_used`, optional `error` | Cursor read |
| Pydantic installed? | Yes — `src/detection_keypoint.py` already imports `BaseModel` | Cursor grep |
| Existing `RiskResult`/`AgentResult`? | None — grep returned 0 matches | Cursor grep |
| `alert_system` anomaly access | `a["severity"]`, `a["message"]` — no isinstance guard | Cursor read |
| Consumers of `deviation_detector` | `app/api.py`, `app/realtime_inference.py`, `app/dashboard.py` | Cursor grep |
| Consumers of `agent` | `app/api.py` only | Cursor grep |

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
# 1. Confirm Pydantic is installed
python -c "from pydantic import BaseModel; print('pydantic OK')"

# 2. Confirm models.py does NOT exist yet
ls src/models.py 2>&1
# Expected: No such file or directory

# 3. Confirm no existing RiskResult or AgentResult anywhere
grep -rn "RiskResult\|AgentResult" src/ app/
# Expected: no output

# 4. Confirm checked_at is optional — at least one path returns without it
grep -n "checked_at" src/deviation_detector.py
# Expected: 1-2 matches, confirming it exists but not on all return paths

# 5. Confirm anomaly loop bug exists in alert_system
grep -n 'a\["severity"\]\|a\["message"\]' src/alert_system.py
# Expected: 2 matches without isinstance guard nearby

# 6. Line counts — record for post-plan diff
wc -l src/deviation_detector.py src/agent.py src/alert_system.py app/api.py
```

**Baseline Snapshot (agent fills during pre-flight):**
```
pydantic OK:                    ____
models.py absent:               ____
RiskResult/AgentResult absent:  ____
checked_at optional confirmed:  ____
anomaly bug confirmed:          ____
Line count deviation_detector:  ____
Line count agent:               ____
Line count alert_system:        ____
Line count api.py:              ____
```

**All checks must pass before Step 1 begins.**

---

## Steps Analysis

```
Step 1 (Create src/models.py)           — Critical (all other steps depend on it)     — Idempotent: Yes
Step 2 (Type deviation_detector.check)  — Critical (3 consumers, API contract)        — Idempotent: Yes
Step 3 (Type agent.run)                 — Critical (API endpoint depends on it)       — Idempotent: Yes
Step 4 (Add response_model to API)      — Critical (API contract, dashboard depends)  — Idempotent: Yes
Step 5 (Fix alert_system anomaly loop)  — Critical (crash bug on string anomalies)    — Idempotent: Yes
```

---

## Tasks

### Phase 1 — Define Contracts

**Goal:** `src/models.py` exists with all four models. Nothing imports it yet. Zero risk.

---

- [ ] 🟥 **Step 1: Create `src/models.py`** — *Critical: all other steps depend on this*

  **Idempotent:** Yes — file creation, no side effects.

  **Context:** Single source of truth for data contracts. Defines four models in dependency
  order: `AnomalyItem` (leaf) → `AIExplanation` → `RiskResult` → `AgentResult`.
  Nothing imports this file yet — this step has zero regression risk.

  Create file at exactly: `src/models.py`

  ```python
  """
  models.py
  ==========
  Pydantic data contracts for CareWatch boundaries.

  Import these in deviation_detector.py, agent.py, and app/api.py.
  Do NOT import from alert_system.py — it receives dicts, not models.

  Models (dependency order):
      AnomalyItem     — one detected anomaly from deviation_detector
      AIExplanation   — LLM output from llm_explainer
      RiskResult      — output of deviation_detector.check()
      AgentResult     — output of agent.run()
  """

  from __future__ import annotations
  from typing import List, Optional, Union
  from pydantic import BaseModel, Field


  class AnomalyItem(BaseModel):
      """One anomaly dict from deviation_detector.check()."""
      activity: str
      type:     str           # e.g. MISSING | UNUSUAL_TIME | LOW_CONFIDENCE
      message:  str
      severity: str           # HIGH | MEDIUM | LOW


  class AIExplanation(BaseModel):
      """Output of llm_explainer.explain_risk() — always present, even on fallback."""
      summary:       str
      concern_level: str      # normal | watch | urgent
      action:        str
      positive:      str


  class RiskResult(BaseModel):
      """
      Output of DeviationDetector.check().
      checked_at is Optional — absent on the no-baseline path.
      anomalies is List[Union[AnomalyItem, str]] — str on the no-baseline path.
      """
      risk_score:  int        = Field(..., ge=0, le=100)
      risk_level:  str        = Field(..., pattern="^(GREEN|YELLOW|RED|UNKNOWN)$")
      anomalies:   List[Union[AnomalyItem, str]] = Field(default_factory=list)
      summary:     str
      checked_at:  Optional[str] = None


  class AgentResult(RiskResult):
      """
      Output of CareWatchAgent.run().
      Extends RiskResult with AI layer fields.
      error is Optional — only present when detector.check() raised.
      """
      ai_explanation:   AIExplanation
      rag_context_used: bool
      error:            Optional[str] = None
  ```

  **What it does:** Defines all four contracts in one file. `AgentResult` extends `RiskResult`
  so the spread `{**risk_result, "ai_explanation": ..., "rag_context_used": ...}` in `agent.py`
  maps cleanly to the model.

  **Why this approach:** Single file avoids circular imports. `from __future__ import annotations`
  prevents forward reference errors. `Union[AnomalyItem, str]` preserves the no-baseline
  string path without breaking existing behaviour.

  **Assumptions:**
  - Pydantic v2 is installed (confirmed — already used in `detection_keypoint.py`)
  - `risk_level` values are exactly `GREEN | YELLOW | RED | UNKNOWN` (confirmed by Cursor)
  - `checked_at` is absent on the no-baseline path (confirmed by Cursor grep)

  **Risks:**
  - Pydantic v1 vs v2 `pattern` syntax differs → mitigation: verify with `python -c "import pydantic; print(pydantic.VERSION)"` in verification test
  - `AnomalyItem` fields don't match actual dict keys → mitigation: verification test constructs one from real data shape

  **Git Checkpoint:**
  ```bash
  git add src/models.py
  git commit -m "step 1: add Pydantic models for RiskResult and AgentResult"
  ```

  **Subtasks:**
  - [ ] 🟥 File created at `src/models.py`
  - [ ] 🟥 Verification passes

  **✓ Verification Test:**

  **Type:** Unit

  **Action:**
  ```bash
  python -c "
  import pydantic
  print('Pydantic version:', pydantic.VERSION)

  from src.models import AnomalyItem, AIExplanation, RiskResult, AgentResult

  # Test 1: AnomalyItem from real dict shape
  a = AnomalyItem(activity='pill_taking', type='MISSING', message='Not detected', severity='HIGH')
  assert a.activity == 'pill_taking'
  print('PASS 1: AnomalyItem constructs from real shape')

  # Test 2: RiskResult with optional checked_at absent (no-baseline path)
  r1 = RiskResult(risk_score=0, risk_level='UNKNOWN', anomalies=['No baseline built yet'], summary='No baseline')
  assert r1.checked_at is None
  print('PASS 2: RiskResult works without checked_at')

  # Test 3: RiskResult with checked_at present (normal path)
  r2 = RiskResult(risk_score=75, risk_level='RED', anomalies=[a], summary='Test', checked_at='2024-01-01T00:00:00')
  assert r2.checked_at is not None
  print('PASS 3: RiskResult works with checked_at')

  # Test 4: AgentResult full shape
  ai = AIExplanation(summary='Test', concern_level='urgent', action='Call now', positive='Good')
  result = AgentResult(
      risk_score=75, risk_level='RED', anomalies=[a],
      summary='Test', checked_at='2024-01-01T00:00:00',
      ai_explanation=ai, rag_context_used=True
  )
  assert result.ai_explanation.concern_level == 'urgent'
  assert result.rag_context_used is True
  print('PASS 4: AgentResult full shape constructs cleanly')

  # Test 5: RiskResult rejects invalid risk_level
  try:
      RiskResult(risk_score=50, risk_level='INVALID', anomalies=[], summary='Test')
      print('FAIL 5: should have raised ValidationError')
  except Exception:
      print('PASS 5: invalid risk_level rejected')

  # Test 6: RiskResult rejects out-of-range risk_score
  try:
      RiskResult(risk_score=150, risk_level='GREEN', anomalies=[], summary='Test')
      print('FAIL 6: should have raised ValidationError')
  except Exception:
      print('PASS 6: risk_score > 100 rejected')

  print()
  print('All 6 tests passed.')
  "
  ```

  **Pass:** `All 6 tests passed.` printed

  **Fail:**
  - If `ImportError: cannot import name 'BaseModel'` → pydantic not installed → `pip install pydantic`
  - If `FAIL 5` or `FAIL 6` → pattern/ge/le validation not working → check Pydantic version; v1 uses `regex=` not `pattern=`
  - If `ValidationError` on Test 2 → `checked_at` marked required → confirm `Optional[str] = None` in model
  - If `ValidationError` on Test 4 → `AgentResult` field mismatch → print full error to see which field

---

### Phase 2 — Apply Contracts at Boundaries

**Goal:** All three boundaries typed. API endpoint validates output. Alert bug fixed.

---

- [ ] 🟥 **Step 2: Type `deviation_detector.check()` return** — *Critical: 3 consumers*

  **Idempotent:** Yes — return type hint change only, no logic change.

  **Context:** `check()` currently returns `-> dict`. Changing to `-> RiskResult` makes
  the contract explicit and means Pydantic validates the shape on every call.
  Three consumers: `app/api.py`, `app/realtime_inference.py`, `app/dashboard.py`.
  None of them need to change — they access keys by string, which Pydantic models support
  via `.model_dump()` or dict-style access when passed to functions expecting dicts.

  **Pre-Read Gate:**
  ```bash
  # Confirm exact signature line — must return 1 match
  grep -n "def check(self" src/deviation_detector.py
  # Expected: 1 match like: def check(self, person_id: str = "resident") -> dict:

  # Confirm import block at top of file — where to add models import
  head -10 src/deviation_detector.py
  ```

  **Fix A** — add import at top of file, after existing imports:
  ```python
  # FIND (last line of existing imports — confirm with head -10 output):
  # [whatever the last import line is]
  # ADD after it:
  from src.models import RiskResult
  ```

  **Fix B** — update return type hint:
  ```python
  # FIND:
  def check(self, person_id: str = "resident") -> dict:
  # REPLACE WITH:
  def check(self, person_id: str = "resident") -> RiskResult:
  ```

  **Fix C** — wrap each return dict in RiskResult. There are 3 return paths confirmed by Cursor.
  Each `return {...}` becomes `return RiskResult(**{...})`.

  Before applying, run:
  ```bash
  grep -n "return {" src/deviation_detector.py
  # Record exact line numbers — apply Fix C to each one
  ```

  For each `return {` line, wrap:
  ```python
  # FIND (example — use actual line content):
  return {
      "risk_score": ...,
      "risk_level": ...,
      ...
  }
  # REPLACE WITH:
  return RiskResult(
      risk_score=...,
      risk_level=...,
      ...
  )
  ```

  **Git Checkpoint:**
  ```bash
  git add src/deviation_detector.py
  git commit -m "step 2: type deviation_detector.check() return as RiskResult"
  ```

  **Subtasks:**
  - [ ] 🟥 Pre-read gate greps pass
  - [ ] 🟥 Import added
  - [ ] 🟥 Return type hint updated
  - [ ] 🟥 All 3 return dicts wrapped in RiskResult
  - [ ] 🟥 Verification passes

  **✓ Verification Test:**

  **Type:** Integration

  **Action:**
  ```bash
  python -c "
  from src.deviation_detector import DeviationDetector
  from src.models import RiskResult

  d = DeviationDetector()
  result = d.check('resident')

  # Test 1: return type is RiskResult
  assert isinstance(result, RiskResult), f'Expected RiskResult, got {type(result)}'
  print('PASS 1: check() returns RiskResult')

  # Test 2: all required fields present
  assert hasattr(result, 'risk_score')
  assert hasattr(result, 'risk_level')
  assert hasattr(result, 'anomalies')
  assert hasattr(result, 'summary')
  print('PASS 2: all required fields present')

  # Test 3: risk_score is int in valid range
  assert isinstance(result.risk_score, int), f'risk_score not int: {type(result.risk_score)}'
  assert 0 <= result.risk_score <= 100, f'risk_score out of range: {result.risk_score}'
  print('PASS 3: risk_score is valid int')

  # Test 4: risk_level is valid value
  assert result.risk_level in ('GREEN', 'YELLOW', 'RED', 'UNKNOWN'), f'Bad risk_level: {result.risk_level}'
  print('PASS 4: risk_level is valid')

  # Test 5: model_dump() works (consumers can still get a dict)
  d_dict = result.model_dump()
  assert 'risk_score' in d_dict
  print('PASS 5: model_dump() works for dict consumers')

  print()
  print('All 5 tests passed.')
  "
  ```

  **Pass:** `All 5 tests passed.`

  **Fail:**
  - If `ValidationError` on `return RiskResult(...)` → a return path has a field that doesn't match model → print the full ValidationError, compare against `src/models.py` field names
  - If `AttributeError` on `result.risk_score` → still returning plain dict → Fix B or Fix C not applied
  - If `ImportError` → `from src.models import RiskResult` not added → apply Fix A

---

- [ ] 🟥 **Step 3: Type `agent.run()` return** — *Critical: API endpoint depends on this*

  **Idempotent:** Yes — return type hint + wrapping only, no logic change.

  **Context:** `run()` currently returns `-> dict`. Two return paths: success (spread of
  `risk_result` + AI fields) and error (hardcoded dict). Both must return `AgentResult`.
  The success path uses `{**risk_result, ...}` — since `risk_result` is now a `RiskResult`
  model, use `risk_result.model_dump()` to spread it.

  **Pre-Read Gate:**
  ```bash
  # Confirm return type hint line
  grep -n "def run(self" src/agent.py
  # Expected: 1 match

  # Confirm both return paths
  grep -n "return {" src/agent.py
  grep -n "return full_result" src/agent.py
  # Expected: 1 match each
  ```

  **Fix A** — add import:
  ```python
  # FIND (existing models import line or last import):
  from src.llm_explainer import explain_risk
  # REPLACE WITH:
  from src.llm_explainer import explain_risk
  from src.models import AgentResult, AIExplanation
  ```

  **Fix B** — update return type hint:
  ```python
  # FIND:
  def run(self, person_id: str = "resident", send_alert: bool = True) -> dict:
  # REPLACE WITH:
  def run(self, person_id: str = "resident", send_alert: bool = True) -> AgentResult:
  ```

  **Fix C** — wrap error return path:
  ```python
  # FIND:
  return {
      "error":       str(e),
      "risk_score":  0,
      "risk_level":  "UNKNOWN",
      "anomalies":   [],
      "ai_explanation": {
          "summary":       "Monitoring system encountered an error.",
          "concern_level": "watch",
          "action":        "Check the CareWatch system status.",
          "positive":      "Alert has been logged for review.",
      },
      "rag_context_used": False,
  }
  # REPLACE WITH:
  return AgentResult(
      error=str(e),
      risk_score=0,
      risk_level="UNKNOWN",
      anomalies=[],
      summary="Detector error.",
      ai_explanation=AIExplanation(
          summary="Monitoring system encountered an error.",
          concern_level="watch",
          action="Check the CareWatch system status.",
          positive="Alert has been logged for review.",
      ),
      rag_context_used=False,
  )
  ```

  **Fix D** — wrap success return path:
  ```python
  # FIND:
  full_result = {
      **risk_result,
      "ai_explanation":   explanation,
      "rag_context_used": bool(rag_context),
  }
  # REPLACE WITH:
  full_result = AgentResult(
      **risk_result.model_dump(),
      ai_explanation=AIExplanation(**explanation) if isinstance(explanation, dict) else explanation,
      rag_context_used=bool(rag_context),
  )
  ```

  **Git Checkpoint:**
  ```bash
  git add src/agent.py
  git commit -m "step 3: type agent.run() return as AgentResult"
  ```

  **Subtasks:**
  - [ ] 🟥 Pre-read gate greps pass
  - [ ] 🟥 Import added
  - [ ] 🟥 Return type hint updated
  - [ ] 🟥 Error path wrapped in AgentResult
  - [ ] 🟥 Success path wrapped in AgentResult
  - [ ] 🟥 Verification passes

  **✓ Verification Test:**

  **Type:** Integration

  **Action:**
  ```bash
  python -c "
  from src.agent import CareWatchAgent
  from src.models import AgentResult, AIExplanation

  agent = CareWatchAgent()
  result = agent.run('resident', send_alert=False)

  # Test 1: return type is AgentResult
  assert isinstance(result, AgentResult), f'Expected AgentResult, got {type(result)}'
  print('PASS 1: run() returns AgentResult')

  # Test 2: ai_explanation is AIExplanation not dict
  assert isinstance(result.ai_explanation, AIExplanation), f'Expected AIExplanation, got {type(result.ai_explanation)}'
  print('PASS 2: ai_explanation is AIExplanation model')

  # Test 3: concern_level is valid
  assert result.ai_explanation.concern_level in ('normal', 'watch', 'urgent')
  print('PASS 3: concern_level is valid')

  # Test 4: model_dump() works for API serialisation
  d = result.model_dump()
  assert 'ai_explanation' in d
  assert 'risk_score' in d
  print('PASS 4: model_dump() serialises cleanly')

  # Test 5: rag_context_used is bool
  assert isinstance(result.rag_context_used, bool)
  print('PASS 5: rag_context_used is bool')

  print()
  print('All 5 tests passed.')
  "
  ```

  **Pass:** `All 5 tests passed.`

  **Fail:**
  - If `ValidationError` → a field from `risk_result.model_dump()` doesn't match `AgentResult` → print full error
  - If `AIExplanation` is still a dict → `isinstance(explanation, dict)` branch not reached → check Fix D applied correctly
  - If `AttributeError: model_dump` → `risk_result` is still a plain dict → Step 2 verification did not pass → fix Step 2 first

---

- [ ] 🟥 **Step 4: Add `response_model` to `/api/agent/explain`** — *Critical: API contract*

  **Idempotent:** Yes — additive change to decorator only.

  **Context:** FastAPI's `response_model` does two things: validates the response shape
  before it leaves the server (crashes loudly if agent returns wrong shape), and
  auto-generates OpenAPI docs at `/docs`. Currently the endpoint returns raw dict with
  no validation. Since `agent.run()` now returns `AgentResult`, wiring `response_model`
  closes the loop.

  **Pre-Read Gate:**
  ```bash
  # Confirm endpoint decorator — must return 1 match
  grep -n '"/api/agent/explain"' app/api.py
  # Expected: exactly 1 match

  # Confirm AgentResult not already imported in api.py
  grep -n "AgentResult" app/api.py
  # Expected: no matches
  ```

  **Fix A** — add AgentResult to import:
  ```python
  # FIND:
  from src.agent import CareWatchAgent
  # REPLACE WITH:
  from src.agent import CareWatchAgent
  from src.models import AgentResult
  ```

  **Fix B** — add response_model to decorator:
  ```python
  # FIND:
  @app.get("/api/agent/explain")
  # REPLACE WITH:
  @app.get("/api/agent/explain", response_model=AgentResult)
  ```

  **Git Checkpoint:**
  ```bash
  git add app/api.py
  git commit -m "step 4: add response_model=AgentResult to /api/agent/explain"
  ```

  **Subtasks:**
  - [ ] 🟥 Pre-read gate greps pass
  - [ ] 🟥 Import added
  - [ ] 🟥 response_model added to decorator
  - [ ] 🟥 Verification passes

  **✓ Verification Test:**

  **Type:** E2E

  ```bash
  # Terminal 1:
  uvicorn app.api:app --port 8000

  # Terminal 2:
  python -c "
  import urllib.request, json, time

  def fetch(path):
      for _ in range(10):
          try:
              r = urllib.request.urlopen('http://localhost:8000' + path, timeout=5)
              return json.loads(r.read())
          except:
              time.sleep(1)
      raise RuntimeError(f'Could not reach {path}')

  # Test 1: endpoint still returns valid shape
  d = fetch('/api/agent/explain')
  assert 'ai_explanation' in d, f'Missing ai_explanation: {d.keys()}'
  assert 'risk_score' in d, f'Missing risk_score: {d.keys()}'
  print('PASS 1: /api/agent/explain returns valid shape')

  # Test 2: OpenAPI docs include AgentResult schema
  docs = fetch('/openapi.json')
  schemas = docs.get('components', {}).get('schemas', {})
  assert 'AgentResult' in schemas, f'AgentResult not in OpenAPI schema: {list(schemas.keys())}'
  print('PASS 2: AgentResult appears in OpenAPI schema')

  # Test 3: existing /api/risk still works
  r = fetch('/api/risk')
  assert 'risk_score' in r
  print('PASS 3: /api/risk unaffected')

  print()
  print('All 3 tests passed.')
  "
  ```

  **Pass:** `All 3 tests passed.`

  **Fail:**
  - If uvicorn fails to start → check import error in terminal 1
  - If `PASS 2` fails → `response_model` not wired → confirm Fix B applied
  - If 500 on endpoint → `AgentResult` serialisation failed → run Step 3 verification again

---

- [ ] 🟥 **Step 5: Fix `alert_system.py` anomaly iteration** — *Critical: crash bug*

  **Idempotent:** Yes — targeted replacement, no logic change to alert firing.

  **Context:** Cursor confirmed `alert_system.send()` does `a["severity"]` and `a["message"]`
  inside the anomaly loop without an `isinstance(a, dict)` guard. When
  `deviation_detector` returns `anomalies: ["No baseline built yet — need 7 days of data"]`,
  this crashes with `TypeError: string indices must be integers`. This is the audit finding.
  Fix is a one-line guard addition.

  **Pre-Read Gate:**
  ```bash
  # Confirm the anomaly loop — must return 1 match
  grep -n "for a in" src/alert_system.py
  # Expected: 1 match — the anomaly iteration loop

  # Confirm the crash lines exist
  grep -n 'a\["severity"\]' src/alert_system.py
  grep -n 'a\["message"\]' src/alert_system.py
  # Expected: 1 match each

  # Confirm no isinstance guard already present
  grep -n "isinstance(a" src/alert_system.py
  # Expected: no matches
  ```

  Find the anomaly loop. It looks like:
  ```python
  for a in anomalies:
  ```

  Add `isinstance` guard:
  ```python
  # FIND:
  for a in anomalies:
  # REPLACE WITH:
  for a in anomalies:
      if not isinstance(a, dict):
          continue
  ```

  **What it does:** Skips string anomalies (no-baseline path) silently.
  Dict anomalies proceed unchanged.

  **Git Checkpoint:**
  ```bash
  git add src/alert_system.py
  git commit -m "step 5: fix alert_system anomaly loop — skip non-dict anomalies"
  ```

  **Subtasks:**
  - [ ] 🟥 Pre-read gate greps pass
  - [ ] 🟥 isinstance guard added
  - [ ] 🟥 Verification passes

  **✓ Verification Test:**

  **Type:** Unit

  ```bash
  python -c "
  from src.alert_system import AlertSystem

  a = AlertSystem()

  # Test 1: string anomaly (no-baseline path) does not crash
  a.send({
      'risk_level': 'YELLOW',
      'risk_score': 45,
      'anomalies': ['No baseline built yet — need 7 days of data'],
      'summary': 'No baseline'
  }, 'Test Person')
  print('PASS 1: string anomaly does not crash')

  # Test 2: dict anomaly still processed correctly
  a.send({
      'risk_level': 'YELLOW',
      'risk_score': 45,
      'anomalies': [{'activity': 'pill_taking', 'type': 'MISSING', 'message': 'Not detected', 'severity': 'HIGH'}],
      'summary': 'Test summary'
  }, 'Test Person')
  print('PASS 2: dict anomaly processed correctly')

  # Test 3: mixed list (both str and dict) does not crash
  a.send({
      'risk_level': 'YELLOW',
      'risk_score': 45,
      'anomalies': [
          'No baseline built yet',
          {'activity': 'walking', 'type': 'MISSING', 'message': 'No walk', 'severity': 'MEDIUM'}
      ],
      'summary': 'Mixed anomalies'
  }, 'Test Person')
  print('PASS 3: mixed anomaly list handled cleanly')

  print()
  print('All 3 tests passed.')
  "
  ```

  **Pass:** `All 3 tests passed.` — no `TypeError: string indices must be integers`

  **Fail:**
  - If `TypeError: string indices must be integers` → isinstance guard not applied → re-check grep and retry
  - If `KeyError` on dict anomaly → wrong indentation of guard — `continue` must be inside `for` loop, before `a["severity"]` access

---

## Part Complete — State Manifest

Run after all 5 steps pass:

```bash
python -c "
from src.models import RiskResult, AgentResult, AIExplanation, AnomalyItem
from src.deviation_detector import DeviationDetector
from src.agent import CareWatchAgent

# Confirm full typed pipeline
d = DeviationDetector()
risk = d.check('resident')
assert type(risk).__name__ == 'RiskResult', f'Got {type(risk)}'

agent = CareWatchAgent()
result = agent.run('resident', send_alert=False)
assert type(result).__name__ == 'AgentResult', f'Got {type(result)}'
assert type(result.ai_explanation).__name__ == 'AIExplanation', f'Got {type(result.ai_explanation)}'

print('risk_score:    ', result.risk_score)
print('risk_level:    ', result.risk_level)
print('concern_level: ', result.ai_explanation.concern_level)
print('rag_used:      ', result.rag_context_used)
print('types:          RiskResult ✅  AgentResult ✅  AIExplanation ✅')
print()
print('Typed state DONE')
"
```

**Pass condition:** `Typed state DONE` printed, all three type assertions pass.

---

## Regression Guard

| System | Pre-change behaviour | Post-change verification |
|--------|---------------------|--------------------------|
| `deviation_detector.check()` | Returns dict | Now returns `RiskResult` — `model_dump()` gives same dict for consumers |
| `agent.run()` | Returns dict | Now returns `AgentResult` — `model_dump()` gives same dict |
| `/api/risk` endpoint | Returns risk dict | Unchanged — does not use agent, hit after Step 4 to confirm |
| `alert_system.send()` | Crashes on string anomalies | Now skips them — Test 1 in Step 5 verification |

---

## Rollback

```bash
git revert HEAD      # step 5: alert_system fix
git revert HEAD~1    # step 4: api.py response_model
git revert HEAD~2    # step 3: agent.py types
git revert HEAD~3    # step 2: deviation_detector types
git revert HEAD~4    # step 1: models.py

# Confirm clean
ls src/models.py 2>&1   # must say No such file or directory
grep -n "RiskResult" src/deviation_detector.py   # must return no matches
```

---

⚠️ **Do not mark a step 🟩 Done until its verification test passes.**
⚠️ **Do not batch multiple steps into one git commit.**
⚠️ **Do not touch any file not named in the current step.**
⚠️ **Step 2 Fix C: wrap ALL return paths — missing one causes runtime crash on that path.**
⚠️ **send_alert=False in all verification tests — never fire Telegram during testing.**