"""
llm_explainer.py
=================
Calls Groq (free tier) to produce a plain-English explanation of a risk result.
Falls back to a structured default if Groq is unavailable or key is invalid.

Public interface:
    explain_risk(person_id, risk_score, risk_level, anomalies, rag_context) -> dict

Return shape (always present, even on fallback):
    {
        "summary":       str,   # 2 sentences for family, no markdown
        "concern_level": str,   # "normal" | "watch" | "urgent"
        "action":        str,   # one specific thing family should do now
        "positive":      str,   # one positive observation about today
    }

Requires env var: GROQ_API_KEY
Set in .env file or: export GROQ_API_KEY="gsk_..."
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Load .env from repo root if present
_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        pass  # dotenv not installed; key must be set via export

try:
    from groq import Groq
    _groq_available = True
except ImportError:
    logger.warning("groq not installed. Run: pip install groq")
    _groq_available = False

# concern_level map used by _fallback
_LEVEL_TO_CONCERN = {
    "GREEN":   "normal",
    "YELLOW":  "watch",
    "RED":     "urgent",
    "UNKNOWN": "watch",
}


def explain_risk(
    person_id: str,
    risk_score: int,
    risk_level: str,
    anomalies: list,
    rag_context: str = "",
    memory_context: str = "",
) -> dict:
    """
    Call Groq to explain a risk result in plain English for a family member.
    Always returns a dict with keys: summary, concern_level, action, positive.
    Never raises — returns _fallback() on any failure.

    anomalies: list of dicts from deviation_detector.check() — strings are tolerated
    rag_context: plain string from RAGRetriever.get_context() — empty string is fine
    memory_context: formatted history from AuditLogger.compute_trend() — empty omits memory block
    """
    # Check key at call time (not import time) so missing key → fallback, not crash
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not _groq_available or not api_key:
        return _fallback(risk_score, risk_level, anomalies)

    # Filter anomalies to dicts only for clean JSON serialisation
    clean_anomalies = [a for a in anomalies if isinstance(a, dict)]

    context_block = (
        f"\nMedical context from knowledge base:\n{rag_context}"
        if rag_context else ""
    )
    memory_block = (
        f"\nPatient history (last 7 days, oldest to newest):\n{memory_context}"
        f"\nUse this trend as context. If ESCALATING, lean toward higher concern."
        f" If IMPROVING, note the positive trend."
        if memory_context else ""
    )

    prompt = f"""You are CareWatch, a caring elderly monitoring assistant.
A family member is checking on their loved one. Be warm, clear, and concise.
Do not use markdown, asterisks, or underscores anywhere in your response.

Return ONLY valid JSON with exactly these four keys:
{{
  "summary": "2 sentences explaining what happened today in plain English",
  "concern_level": "normal or watch or urgent",
  "action": "one specific thing the family should do right now",
  "positive": "one positive observation about today"
}}

DECISION TABLE for concern_level — apply top-to-bottom, stop at first match:
IF fall detected in anomalies                    → urgent
IF any anomaly has severity=HIGH               → urgent
IF all anomalies have severity=LOW              → watch (score is irrelevant)
IF anomalies empty AND risk_score < 40         → normal
IF anomalies empty AND risk_score >= 40        → watch (score is the signal)
DEFAULT                                         → watch

Examples you must match exactly:
- risk_score=15, risk_level=RED, anomalies empty → normal
- risk_score=75, risk_level=GREEN, anomalies empty → watch (high score overrides clean level)
- risk_score=75, risk_level=RED, all LOW severity → watch
- risk_score=90, risk_level=RED, all LOW severity → watch
- risk_score=30, risk_level=GREEN, one HIGH severity → urgent
- risk_score=50, risk_level=YELLOW, one HIGH + three LOW → urgent
- risk_score=85, risk_level=UNKNOWN, one HIGH severity → urgent

{memory_block}
Data:
- Person: {person_id}
- Risk Score: {risk_score}/100
- Risk Level: {risk_level}
- Issues detected: {json.dumps(clean_anomalies)}{context_block}

JSON only. No markdown. No extra text. No explanation outside the JSON."""

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",  # better instruction following than 8b-instant
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.3,
        )
        raw = response.choices[0].message.content.strip()
        print("DEBUG RAW BEFORE CLEAN:", repr(raw)) 
        # Strip markdown code fences if model wraps response anyway
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        # Find the JSON object if model added prose around it
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            raw = raw[start:end]

        parsed = json.loads(raw)

        # Confirm all 4 keys present — if any missing, use fallback
        required = {"summary", "concern_level", "action", "positive"}
        if not required.issubset(parsed.keys()):
            logger.warning("LLM response missing keys: %s. Using fallback.", required - parsed.keys())
            return _fallback(risk_score, risk_level, anomalies)

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
                    model="llama-3.3-70b-versatile",
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
                # Find the JSON object if model added prose around it
                start = raw_retry.find("{")
                end = raw_retry.rfind("}") + 1
                if start != -1 and end > start:
                    raw_retry = raw_retry[start:end]
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

    except json.JSONDecodeError as e:
        logger.warning("LLM returned non-JSON: %s. Using fallback.", e)
        return _fallback(risk_score, risk_level, anomalies)
    except Exception as e:
        logger.warning("LLM call failed: %s. Using fallback.", e)
        return _fallback(risk_score, risk_level, anomalies)


def _fallback(risk_score: int, risk_level: str, anomalies: list) -> dict:
    """
    Returns a valid explanation dict when Groq is unavailable.
    Always has all 4 keys. Never raises.
    """
    n = len([a for a in anomalies if isinstance(a, dict)])
    return {
        "summary": (
            f"Risk score is {risk_score}/100 ({risk_level}). "
            f"{n} issue(s) detected today."
        ),
        "concern_level": _LEVEL_TO_CONCERN.get(risk_level, "watch"),
        "action": (
            "Call or visit immediately."
            if risk_level == "RED"
            else "Check the CareWatch dashboard for details."
        ),
        "positive": "Monitoring is active and working normally.",
    }


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
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.0,
        )
        raw = response.choices[0].message.content.strip()

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        # LLM sometimes returns Python None instead of JSON null
        raw = raw.replace(": None", ": null").replace(":None", ": null")

        # Find the JSON object if model added prose around it
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            raw = raw[start:end]

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
