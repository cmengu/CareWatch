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
    confidence is "high" by default — set to "low" when score and concern_level contradict.
    cusum_result is Optional — CUSUMCheckResult serialized as dict from ResidentCUSUMMonitor.check().
    """
    ai_explanation:   AIExplanation
    rag_context_used: bool
    error:            Optional[str] = None
    confidence:       str           = Field("high", pattern="^(high|low)$")
    cusum_result:     Optional[dict] = None