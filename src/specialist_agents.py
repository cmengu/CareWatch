"""
specialist_agents.py
====================
Specialist agents for CareWatch multi-agent pipeline.

Four classes:
    FallAgent     — handles FALLEN and UNCLEARED anomaly types
    MedAgent      — handles pill_taking MISSING/TIMING anomalies
    RoutineAgent  — handles eating/walking/sitting/lying_down deviations + CUSUM signals
    SummaryAgent  — synthesises list[SpecialistResult] into a single AgentResult

One helper:
    _normalise_anomaly(a) — converts AnomalyItem or dict to dict, safely

One routing function:
    route(anomalies) -> list[str]  — returns agent names that should run

USAGE (called by graph nodes in graph.py — not called directly by user code):
    from src.specialist_agents import FallAgent, MedAgent, RoutineAgent, SummaryAgent, route
"""

import logging
from typing import Optional
from src.models import SpecialistResult, AgentResult, AIExplanation, RiskResult
from src.rag_retriever import RAGRetriever
from src.llm_explainer import explain_risk

logger = logging.getLogger(__name__)

CONCERN_PRIORITY = {"normal": 0, "watch": 1, "urgent": 2}

FALL_AGENT    = "FallAgent"
MED_AGENT     = "MedAgent"
ROUTINE_AGENT = "RoutineAgent"


# ─────────────────────────────────────────────
# Anomaly shape normaliser
# ─────────────────────────────────────────────

def _normalise_anomaly(a) -> dict:
    """
    DeviationDetector returns anomalies in two shapes:
      - AnomalyItem objects (persistent_alert path)
      - raw dicts (fallen path + normal deviation path)

    Converts both to plain dicts with keys: activity, type, message, severity.
    Never raises. Returns empty dict if shape is unrecognised.
    """
    if isinstance(a, dict):
        return a
    try:
        return {
            "activity": a.activity,
            "type":     a.type,
            "message":  a.message,
            "severity": a.severity,
        }
    except AttributeError:
        logger.warning("_normalise_anomaly: unrecognised anomaly shape %s — skipping", type(a))
        return {}


# ─────────────────────────────────────────────
# Routing function
# ─────────────────────────────────────────────

def route(anomalies: list) -> list[str]:
    """
    Inspect anomaly list and return which specialist agents should run.
    Always returns at least one agent name (falls back to ROUTINE_AGENT).

    Routing rules:
      FALL_AGENT:    any anomaly with type FALLEN or UNCLEARED
      MED_AGENT:     any anomaly with activity == pill_taking
      ROUTINE_AGENT: any anomaly with activity in eating/walking/sitting/lying_down
                     OR anomaly type TIMING
                     OR no other agent was selected (fallback)
    """
    agents = set()
    normalised = [_normalise_anomaly(a) for a in anomalies]
    normalised = [a for a in normalised if a]

    for a in normalised:
        atype     = a.get("type", "")
        aactivity = a.get("activity", "")

        if atype in ("FALLEN", "UNCLEARED"):
            agents.add(FALL_AGENT)

        if aactivity == "pill_taking":
            agents.add(MED_AGENT)

        if aactivity in ("eating", "walking", "sitting", "lying_down"):
            agents.add(ROUTINE_AGENT)

        if atype == "TIMING":
            agents.add(ROUTINE_AGENT)

    if not agents:
        agents.add(ROUTINE_AGENT)

    return list(agents)


# ─────────────────────────────────────────────
# Base specialist (shared RAG + LLM logic)
# ─────────────────────────────────────────────

class _BaseSpecialist:
    """
    Shared logic for FallAgent, MedAgent, RoutineAgent.
    Subclasses define agent_name and rag_queries.
    """
    agent_name:  str = "BaseAgent"
    rag_queries: tuple = ()

    def __init__(self, rag: RAGRetriever):
        self.rag = rag

    def _get_rag_context(self, anomalies: list[dict]) -> str:
        """
        Retrieve RAG context via get_context_v2():
        query decomposition + hybrid dense/sparse retrieval + RRF merge + reranking.
        Relevance filtering is handled inside get_context_v2() — no separate
        _score_relevance() call needed in this path.
        CareWatchAgent continues to use get_context() + _score_relevance() unchanged.
        """
        try:
            return self.rag.get_context_v2(anomalies)
        except Exception as e:
            logger.warning(
                "%s: RAG retrieval failed (%s) — continuing without context",
                self.agent_name, e,
            )
            return ""

    def _explain(
        self,
        person_id: str,
        risk_score: int,
        risk_level: str,
        anomalies: list,
        rag_context: str,
    ) -> dict:
        """Call explain_risk with this specialist's anomaly subset."""
        try:
            return explain_risk(
                person_id=person_id,
                risk_score=risk_score,
                risk_level=risk_level,
                anomalies=anomalies,
                rag_context=rag_context,
                memory_context="",
            )
        except Exception as e:
            logger.error("%s: LLM explain failed (%s) — using fallback", self.agent_name, e)
            return {
                "summary":       f"{self.agent_name} could not generate explanation.",
                "concern_level": "watch",
                "action":        "Check the CareWatch system.",
                "positive":      "",
            }

    def run(
        self,
        person_id: str,
        risk_result: RiskResult,
        my_anomalies: list[dict],
    ) -> SpecialistResult:
        """Run this specialist on its subset of anomalies. Returns SpecialistResult. Never raises."""
        raise NotImplementedError


# ─────────────────────────────────────────────
# FallAgent
# ─────────────────────────────────────────────

class FallAgent(_BaseSpecialist):
    """Handles FALLEN and UNCLEARED anomaly types. Always urgent for RED."""
    agent_name  = FALL_AGENT
    rag_queries = ["fall detection emergency response", "hip fracture elderly", "fallen assessment"]

    def run(self, person_id, risk_result, my_anomalies):
        logger.info("FallAgent running for %s (%d anomalies)", person_id, len(my_anomalies))
        rag_context = self._get_rag_context(my_anomalies)
        explanation = self._explain(
            person_id=person_id,
            risk_score=risk_result.risk_score,
            risk_level=risk_result.risk_level,
            anomalies=my_anomalies,
            rag_context=rag_context,
        )
        concern = explanation.get("concern_level", "urgent")
        if risk_result.risk_level == "RED" and concern != "urgent":
            logger.warning("FallAgent: LLM returned concern=%s for RED — overriding to urgent", concern)
            concern = "urgent"

        return SpecialistResult(
            agent_name    = self.agent_name,
            concern_level = concern,
            summary       = explanation.get("summary", "Fall event detected."),
            action        = explanation.get("action", "Contact emergency services immediately."),
            rag_used      = bool(rag_context),
            anomalies     = my_anomalies,
        )


# ─────────────────────────────────────────────
# MedAgent
# ─────────────────────────────────────────────

class MedAgent(_BaseSpecialist):
    """Handles pill_taking MISSING and TIMING anomalies."""
    agent_name  = MED_AGENT
    rag_queries = [
        "missed medication elderly morning dosing window",
        "pill taking adherence",
        "drug interaction elderly",
    ]

    def run(self, person_id, risk_result, my_anomalies):
        logger.info("MedAgent running for %s (%d anomalies)", person_id, len(my_anomalies))
        rag_context = self._get_rag_context(my_anomalies)
        explanation = self._explain(
            person_id=person_id,
            risk_score=risk_result.risk_score,
            risk_level=risk_result.risk_level,
            anomalies=my_anomalies,
            rag_context=rag_context,
        )
        return SpecialistResult(
            agent_name    = self.agent_name,
            concern_level = explanation.get("concern_level", "watch"),
            summary       = explanation.get("summary", "Medication deviation detected."),
            action        = explanation.get("action", "Check whether medication was taken."),
            rag_used      = bool(rag_context),
            anomalies     = my_anomalies,
        )


# ─────────────────────────────────────────────
# RoutineAgent
# ─────────────────────────────────────────────

class RoutineAgent(_BaseSpecialist):
    """Handles eating/walking/sitting/lying_down deviations and TIMING anomalies. Fallback agent."""
    agent_name  = ROUTINE_AGENT
    rag_queries = [
        "missed eating elderly nutrition",
        "activity routine deviation",
        "walking reduced mobility",
    ]

    def run(self, person_id, risk_result, my_anomalies):
        logger.info("RoutineAgent running for %s (%d anomalies)", person_id, len(my_anomalies))
        rag_context = self._get_rag_context(my_anomalies)
        explanation = self._explain(
            person_id=person_id,
            risk_score=risk_result.risk_score,
            risk_level=risk_result.risk_level,
            anomalies=my_anomalies,
            rag_context=rag_context,
        )
        return SpecialistResult(
            agent_name    = self.agent_name,
            concern_level = explanation.get("concern_level", "normal"),
            summary       = explanation.get("summary", "Routine deviation detected."),
            action        = explanation.get("action", "Monitor closely today."),
            rag_used      = bool(rag_context),
            anomalies     = my_anomalies,
        )


# ─────────────────────────────────────────────
# SummaryAgent
# ─────────────────────────────────────────────

class SummaryAgent:
    """
    Synthesises a list of SpecialistResult into a single AgentResult.

    Priority ordering:
        urgent > watch > normal
        Within same concern_level, fall > medication > routine
    """

    AGENT_PRIORITY = {FALL_AGENT: 2, MED_AGENT: 1, ROUTINE_AGENT: 0}

    def synthesise(
        self,
        specialist_outputs: list[SpecialistResult],
        risk_result: RiskResult,
        cusum_result: Optional[dict] = None,
    ) -> AgentResult:
        """Combine specialist outputs into one AgentResult. Never raises."""
        try:
            active = [s for s in specialist_outputs if not s.skipped]
            if not active:
                logger.warning("SummaryAgent: no active specialist outputs — using fallback")
                return self._fallback(risk_result, cusum_result)

            active.sort(
                key=lambda s: (
                    CONCERN_PRIORITY.get(s.concern_level, 0),
                    self.AGENT_PRIORITY.get(s.agent_name, 0),
                ),
                reverse=True,
            )

            primary = active[0]
            final_concern = primary.concern_level

            summary_parts = [primary.summary]
            for s in active[1:]:
                if s.summary and s.summary != primary.summary:
                    summary_parts.append(s.summary)
            final_summary = " ".join(summary_parts)

            rag_used = any(s.rag_used for s in active)

            return AgentResult(
                **risk_result.model_dump(),
                ai_explanation=AIExplanation(
                    summary       = final_summary,
                    concern_level = final_concern,
                    action        = primary.action,
                    positive      = "CareWatch multi-agent monitoring is active.",
                ),
                rag_context_used = rag_used,
                cusum_result     = cusum_result,
            )

        except Exception as e:
            logger.error("SummaryAgent.synthesise failed: %s — using fallback", e)
            return self._fallback(risk_result, cusum_result)

    def _fallback(self, risk_result: RiskResult, cusum_result: Optional[dict] = None) -> AgentResult:
        concern = {
            "RED":     "urgent",
            "YELLOW":  "watch",
            "GREEN":   "normal",
        }.get(risk_result.risk_level, "watch")

        return AgentResult(
            **risk_result.model_dump(),
            ai_explanation=AIExplanation(
                summary       = risk_result.summary,
                concern_level = concern,
                action        = "Please check on your family member.",
                positive      = "CareWatch monitoring is active.",
            ),
            rag_context_used = False,
            cusum_result     = cusum_result,
        )
