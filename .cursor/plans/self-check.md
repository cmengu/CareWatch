CareWatch — Day 2: LLM Self-Check Loop
Overall Progress: 100% (2/2 steps complete)
TLDR
After explain_risk() returns an explanation, a second LLM call asks "does this explanation actually match the risk data?" If the answer is no, the explanation is retried once with the failure reason injected into the prompt. This closes the one-shot gap: right now the LLM can return concern_level: "normal" when risk_score is 85 and three HIGH anomalies exist — nothing catches that. After this plan, the system catches and corrects it before the family sees it. All changes are confined to src/llm_explainer.py.

Critical Decisions

Decision 1: Self-check is a second Groq call, not a local heuristic — a heuristic (e.g. "if risk_score > 60 and concern_level == normal, fail") would only catch cases we anticipated. The LLM catches semantic mismatches we didn't anticipate.
Decision 2: One retry only — two retries risks an infinite correction loop and doubles latency. One retry is the minimum meaningful intervention.
Decision 3: Self-check failure on the retry path returns the retry result regardless — if the retry also fails the check, we return it anyway rather than falling back. A flawed explanation is better than a generic fallback for a real RED alert.
Decision 4: _self_check() is a private function in the same file — keeps the public interface (explain_risk) unchanged. No other file needs to know the check exists.


Clarification Gate
UnknownRequiredSourceBlockingResolvedGroq model to use for self-checkSame model as primary call (llama-3.1-8b-instant)llm_explainer.py line confirming model stringStep 1✅Should self-check run on fallback pathNo — fallback has no LLM output to checkLogic: fallback returns deterministic dict, no point checkingStep 2✅What counts as a self-check passLLM returns JSON with "pass": trueDecisionStep 1✅

Agent Failure Protocol

A verification command fails → read the full error output.
Cause is unambiguous → make ONE targeted fix → re-run the same verification command.
If still failing after one fix → STOP. Before stopping, output the full current contents of every file modified in this step. Report: (a) command run, (b) full error verbatim, (c) fix attempted, (d) current state of each modified file, (e) why you cannot proceed.
Never attempt a second fix without human instruction.
Never modify files not named in the current step.


Pre-Flight — Run Before Any Code Changes
```bash
# 1. Confirm llm_explainer.py exists and read its full structure
grep -n "^def \|^class " src/llm_explainer.py
# Expected: def explain_risk, def _fallback

# 2. Confirm exact signature of explain_risk
grep -n "def explain_risk" src/llm_explainer.py
# Expected: exactly 1 match

# 3. Confirm _self_check does NOT already exist
grep -n "_self_check" src/llm_explainer.py
# Expected: no output

# 4. Confirm Groq model string used
grep -n "model=" src/llm_explainer.py
# Expected: "llama-3.1-8b-instant"

# 5. Confirm the exact line where _fallback return happens in explain_risk
# (this is the anchor for where self-check gets inserted)
grep -n "return parsed" src/llm_explainer.py
# Expected: 1 match — the success return inside explain_risk

# 6. Line count
wc -l src/llm_explainer.py
```

**Baseline Snapshot (agent fills during pre-flight):**
```
_self_check absent:          ____
explain_risk signature:      ____
model string:                ____
return parsed line:          ____
line count llm_explainer:    ____
```

**All checks must pass before Step 1 begins.**

---

## Steps Analysis
```
Step 1 (Add _self_check function)     — Critical (Step 2 calls it)           — Idempotent: Yes
Step 2 (Wire self-check into explain_risk) — Critical (changes public output) — Idempotent: Yes

Tasks
Phase 1 — Add the checker


🟩 Step 1: Add _self_check() to src/llm_explainer.py — Critical: Step 2 depends on it
Idempotent: Yes — adding a new private function. Re-running creates no duplicate because the function name is unique and the Pre-Read Gate confirms absence before edit.
Context: _self_check() takes the original risk data and the explanation the LLM just produced, makes a second Groq call asking whether the explanation is consistent, and returns a simple {"pass": bool, "reason": str}. It must never raise — any failure returns {"pass": True, "reason": "check skipped"} so a Groq outage during the check doesn't block the primary explanation from being returned.
Pre-Read Gate:

```bash
# Confirm _self_check does not exist yet — must return no output
grep -n "_self_check" src/llm_explainer.py

# Confirm _fallback exists — insertion goes after it
grep -n "^def _fallback" src/llm_explainer.py
# Expected: exactly 1 match
```
Add this function at the bottom of the file, after _fallback:
```python
def _self_check(
    risk_score: int,
    risk_level: str,
    anomalies: list,
    explanation: dict,
    api_key: str,
) -> dict:
    """
    Second LLM call: does this explanation match the risk data?
    Returns {"pass": bool, "reason": str}.
    Never raises — returns pass=True on any failure so check never blocks output.
    """
    try:
        client = Groq(api_key=api_key)
        prompt = f"""You are a quality checker for a medical monitoring system.
You will be given a risk assessment and an AI-generated explanation.
Decide whether the explanation accurately reflects the risk data.

Return ONLY valid JSON with exactly these two keys:
{{
  "pass": true or false,
  "reason": "one sentence explaining your decision"
}}

Risk data:
- Risk Score: {risk_score}/100
- Risk Level: {risk_level}
- Anomalies: {json.dumps([a for a in anomalies if isinstance(a, dict)])}

Explanation to check:
- summary: {explanation.get("summary", "")}
- concern_level: {explanation.get("concern_level", "")}
- action: {explanation.get("action", "")}

A FAIL means: concern_level contradicts the risk score, or the summary ignores critical anomalies.
A PASS means: the explanation is a reasonable, consistent reflection of the data.

JSON only. No markdown. No extra text."""

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.0,
        )
        raw = response.choices[0].message.content.strip()

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        result = json.loads(raw)

        if "pass" not in result:
            return {"pass": True, "reason": "check skipped — missing key"}

        return {
            "pass": bool(result["pass"]),
            "reason": str(result.get("reason", "")),
        }

    except Exception as e:
        logger.warning("Self-check failed (non-blocking): %s", e)
        return {"pass": True, "reason": "check skipped — exception"}
```
What it does: Makes a focused second Groq call that only answers pass/fail + reason. temperature=0.0 because this is a judgment call, not a creative task. Returns pass=True on any exception so the self-check is never a point of failure.
Why this approach: Keeping it as a private function with a narrow return type means Step 2 can call it in one line and branch on result["pass"]. Putting the full prompt here (not in Step 2) keeps Step 2's diff minimal.
Assumptions:

- groq, json, logger are already imported at the top of the file (confirmed by existing code)
- Groq client accepts temperature=0.0 (confirmed by Groq docs — same param as OpenAI)

Risks:

- Groq rate limit hit on second call → mitigation: except Exception catches it, returns pass=True, primary explanation still returned
- LLM returns non-JSON → mitigation: same json.loads try/except pattern already used in explain_risk

Git Checkpoint:
```bash
git add src/llm_explainer.py
git commit -m "step 1: add _self_check() to llm_explainer"
```

Subtasks:

- 🟥 _self_check added after _fallback
- 🟥 Verification passes

✓ Verification Test:
Type: Unit
Action:
```bash
python -c "
import inspect
from src.llm_explainer import _self_check, _fallback

# Test 1: _self_check exists and is callable
assert callable(_self_check), '_self_check not callable'
print('PASS 1: _self_check exists and is callable')

# Test 2: _self_check is defined AFTER _fallback in the file
src_lines = inspect.getsourcefile(_self_check)
check_line = inspect.getsourcelines(_self_check)[1]
fallback_line = inspect.getsourcelines(_fallback)[1]
assert check_line > fallback_line, f'_self_check (line {check_line}) must come after _fallback (line {fallback_line})'
print('PASS 2: _self_check defined after _fallback')

# Test 3: _self_check returns pass=True on missing api_key (exception path)
result = _self_check(
    risk_score=80,
    risk_level='RED',
    anomalies=[{'activity': 'pill_taking', 'type': 'MISSING', 'message': 'Not taken', 'severity': 'HIGH'}],
    explanation={'summary': 'test', 'concern_level': 'normal', 'action': 'test', 'positive': 'test'},
    api_key='',
)
assert isinstance(result, dict), f'Expected dict, got {type(result)}'
assert 'pass' in result, f'Missing pass key: {result}'
assert 'reason' in result, f'Missing reason key: {result}'
assert result['pass'] is True, f'Expected pass=True on exception path, got {result}'
print('PASS 3: _self_check returns pass=True on invalid api_key (exception path)')

# Test 4: return shape is always {pass: bool, reason: str}
assert isinstance(result['pass'], bool)
assert isinstance(result['reason'], str)
print('PASS 4: return shape is correct')

print()
print('All 4 tests passed.')
"
```
Pass: All 4 tests passed.
Fail:

- If ImportError: cannot import name '_self_check' → function not added or indented incorrectly → check bottom of llm_explainer.py
- If FAIL 3: pass=False → exception not caught → confirm outer except Exception wraps the entire try block


Phase 2 — Wire it in


🟩 Step 2: Call _self_check inside explain_risk, retry once if it fails — Critical: changes public output of explain_risk
Idempotent: Yes — replacing the single return parsed block with a self-check + conditional retry. Re-running produces the same code state.
Context: Currently explain_risk() returns parsed immediately after validating the JSON. This step replaces that single return block with: run _self_check, if pass → return as-is, if fail → rebuild the prompt with the failure reason injected and call Groq once more, then return whatever the second call gives. The public interface of explain_risk() is unchanged — it still returns the same 4-key dict. Callers in agent.py need no changes.
Pre-Read Gate:

```bash
# Confirm client and prompt are in scope — both must appear BEFORE the return parsed line (lower line number)
grep -n "client = Groq" src/llm_explainer.py
grep -n "^    prompt = " src/llm_explainer.py
# Both must exist. Record their line numbers.

# Confirm return parsed line — must be exactly 1 match
grep -n "return parsed" src/llm_explainer.py
# Expected: exactly 1 match inside explain_risk

# Verify client and prompt lines come before return parsed line
# If client_line >= return_line OR prompt_line >= return_line → STOP (out of scope)

# Confirm _self_check now exists (Step 1 must be complete)
grep -n "def _self_check" src/llm_explainer.py
# Expected: exactly 1 match

# Confirm the full success block exists — anchor for replacement (must match exactly)
grep -n "parsed\[.concern_level.\]" src/llm_explainer.py
# Expected: 2 matches — the assignment and the if-check
```

**Anchor:** The replacement target is the entire block from `# Normalise concern_level` through `return parsed` (inclusive). Use the full block as the search string — do not anchor on `return parsed` alone. If a future edit adds a second `return parsed`, anchoring on the full block keeps the replacement unique.

Find the current success return block in explain_risk — it looks like this:
```python
        # Normalise concern_level to known values
        parsed["concern_level"] = parsed["concern_level"].lower().strip()
        if parsed["concern_level"] not in ("normal", "watch", "urgent"):
            parsed["concern_level"] = _LEVEL_TO_CONCERN.get(risk_level, "watch")

        return parsed
```
Replace it with:
```python
        # Normalise concern_level to known values
        parsed["concern_level"] = parsed["concern_level"].lower().strip()
        if parsed["concern_level"] not in ("normal", "watch", "urgent"):
            parsed["concern_level"] = _LEVEL_TO_CONCERN.get(risk_level, "watch")

        # Self-check — does this explanation actually match the risk data?
        check = _self_check(risk_score, risk_level, anomalies, parsed, api_key)
        if not check["pass"]:
            logger.info("Self-check failed (%s) — retrying once", check["reason"])
            retry_prompt = prompt + f"\n\nPrevious attempt was rejected because: {check['reason']}. Correct this in your response."
            try:
                retry_response = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[{"role": "user", "content": retry_prompt}],
                    max_tokens=300,
                    temperature=0.3,
                )
                raw_retry = retry_response.choices[0].message.content.strip()
                if raw_retry.startswith("```"):
                    raw_retry = raw_retry.split("```")[1]
                    if raw_retry.startswith("json"):
                        raw_retry = raw_retry[4:]
                    raw_retry = raw_retry.strip()
                retry_parsed = json.loads(raw_retry)
                if {"summary", "concern_level", "action", "positive"}.issubset(retry_parsed.keys()):
                    retry_parsed["concern_level"] = retry_parsed["concern_level"].lower().strip()
                    if retry_parsed["concern_level"] not in ("normal", "watch", "urgent"):
                        retry_parsed["concern_level"] = _LEVEL_TO_CONCERN.get(risk_level, "watch")
                    logger.info("Retry succeeded — returning corrected explanation")
                    return retry_parsed
            except Exception as e:
                logger.warning("Retry failed: %s — returning original explanation", e)

        return parsed
```
What it does: After the first explanation passes JSON validation and normalisation, runs _self_check. If the check passes (or errors), returns immediately — zero extra latency. If the check fails, appends the failure reason to the original prompt and makes one more Groq call. If the retry produces valid JSON with all 4 keys, returns the corrected explanation. If the retry fails for any reason, returns the original parsed — the check never prevents an explanation from being returned.
Why this approach: The retry uses retry_prompt = prompt + ... rather than building a new prompt from scratch, so the retry gets the full original context plus the correction instruction.
Assumptions:

- client and prompt are in scope at the point of replacement. prompt is assigned before client.chat.completions.create is called — it is always in scope at the retry point.
- _self_check is defined in the same file (confirmed by Step 1)

Risks:

- client out of scope at retry point → mitigation: Pre-Read Gate greps verify both client and prompt appear before return parsed in the same try block
- Retry also fails self-check → mitigation: by design we return retry result regardless — one correction attempt is the contract
- Total latency doubles on failure path → acceptable: self-check only fires when explanation is wrong, which is the case we want to catch

Git Checkpoint:
```bash
git add src/llm_explainer.py
git commit -m "step 2: wire _self_check into explain_risk with one retry on failure"
```

Subtasks:

- 🟥 Pre-read gate greps pass (including client/prompt line-number check)
- 🟥 Full block replaced with self-check + retry block
- 🟥 Verification passes

✓ Verification Test:
Type: Unit
Action:
```bash
python -c "
import json
from unittest.mock import patch, MagicMock
from src.llm_explainer import explain_risk

# Test 1: self-check pass path — first explanation returned directly
# patch('src.llm_explainer.Groq') patches the class globally — both explain_risk and _self_check use the same mock instance.
good_explanation = json.dumps({
    'summary': 'Resident has elevated risk today.',
    'concern_level': 'urgent',
    'action': 'Call immediately.',
    'positive': 'Monitoring is active.'
})
check_pass = json.dumps({'pass': True, 'reason': 'explanation matches risk data'})

call_count = {'n': 0}
def mock_create(**kwargs):
    call_count['n'] += 1
    m = MagicMock()
    if call_count['n'] == 1:
        m.choices[0].message.content = good_explanation
    else:
        m.choices[0].message.content = check_pass
    return m

with patch('src.llm_explainer.Groq') as MockGroq:
    with patch.dict('os.environ', {'GROQ_API_KEY': 'test-key'}):
        instance = MockGroq.return_value
        instance.chat.completions.create.side_effect = mock_create
        result = explain_risk('resident', 80, 'RED', [], '')

assert result['concern_level'] == 'urgent', f'Got: {result}'
assert call_count['n'] == 2, f'Expected 2 calls (explain + check), got {call_count[\"n\"]}'
print('PASS 1: self-check pass path — 2 calls total, first explanation returned')

# Test 2: self-check fail path — retry called, retry result returned
bad_explanation = json.dumps({
    'summary': 'Everything is fine today.',
    'concern_level': 'normal',
    'action': 'No action needed.',
    'positive': 'Great day.'
})
check_fail = json.dumps({'pass': False, 'reason': 'concern_level normal contradicts RED risk level'})
corrected = json.dumps({
    'summary': 'Resident has elevated risk. Pill not taken.',
    'concern_level': 'urgent',
    'action': 'Call immediately.',
    'positive': 'Monitoring caught this early.'
})

call_count2 = {'n': 0}
responses2 = [bad_explanation, check_fail, corrected]
def mock_create2(**kwargs):
    call_count2['n'] += 1
    if call_count2['n'] > 3:
        raise AssertionError(f'Expected at most 3 Groq calls, got {call_count2[\"n\"]}')
    m = MagicMock()
    m.choices[0].message.content = responses2[call_count2['n'] - 1]
    return m

with patch('src.llm_explainer.Groq') as MockGroq2:
    with patch.dict('os.environ', {'GROQ_API_KEY': 'test-key'}):
        instance2 = MockGroq2.return_value
        instance2.chat.completions.create.side_effect = mock_create2
        result2 = explain_risk('resident', 80, 'RED', [], '')

# Assert call count FIRST — fail loudly before content check if wrong
assert call_count2['n'] == 3, f'Expected 3 calls (explain + check + retry), got {call_count2[\"n\"]}'
assert result2['concern_level'] == 'urgent', f'Got: {result2}'
print('PASS 2: self-check fail path — 3 calls total, corrected explanation returned')

# Test 3: no GROQ_API_KEY — falls back, no self-check called
result3 = explain_risk('resident', 80, 'RED', [], '')
assert 'concern_level' in result3
print('PASS 3: fallback path unaffected — no api key still returns valid dict')

print()
print('All 3 tests passed.')
"
```
Pass: All 3 tests passed.
Fail:

- If FAIL 1: call_count != 2 → _self_check not being called → confirm replacement was applied to the correct block
- If FAIL 2: call_count2 != 3 (asserts first) → retry block not reached or extra calls made → confirm if not check["pass"] condition and that mock returns pass: false on second call
- If FAIL 2: concern_level == normal after call count passes → retry result not being returned → check that return retry_parsed is inside the if issubset block


Regression Guard
| System | Pre-change behaviour | Post-change verification |
|--------|----------------------|---------------------------|
| explain_risk() fallback | Returns 4-key dict when no API key | Test 3 above confirms — fallback path untouched |
| explain_risk() happy path | Returns 4-key dict | Test 1 above confirms — same return shape |
| agent.run() | Calls explain_risk, gets dict | agent.run() has no changes — regression confirmed by running Step 3 from Day 1 verification |

Rollback
```bash
git revert HEAD      # step 2: removes self-check wiring
git revert HEAD~1    # step 1: removes _self_check function

# Confirm clean
grep -n "_self_check" src/llm_explainer.py  # must return no output
grep -n "return parsed" src/llm_explainer.py  # must return exactly 1 match
```

⚠️ Do not mark a step 🟩 Done until its verification test passes.
⚠️ Do not batch Step 1 and Step 2 into one commit.
⚠️ Do not modify any file other than src/llm_explainer.py.
⚠️ Step 2 Pre-Read Gate must confirm client and prompt are in scope (line numbers < return parsed) before applying the replacement — if either is missing or out of order, STOP.
