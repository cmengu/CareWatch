"""
agent.py
=========
CareWatch AI orchestrator.
Sequences: deviation detection → RAG context → LLM explanation → optional alert.

USAGE:
    from src.agent import CareWatchAgent
    agent = CareWatchAgent()
    result = agent.run("resident", send_alert=False)
    # result["ai_explanation"]["summary"] — plain-English family message
    # result["rag_context_used"]          — bool, True if medical context was retrieved
"""

import logging

from src.deviation_detector import DeviationDetector
from src.rag_retriever import RAGRetriever
from src.llm_explainer import explain_risk
from src.alert_system import AlertSystem
from src.models import AgentResult, AIExplanation

logger = logging.getLogger(__name__)


class CareWatchAgent:
    def __init__(self):
        self.detector = DeviationDetector()
        self.rag      = RAGRetriever()
        self.alerts   = AlertSystem()

    def run(self, person_id: str = "resident", send_alert: bool = True) -> AgentResult:
        """
        Full agent loop:
          1. Compute risk score  — DeviationDetector.check() (unchanged logic)
          2. Retrieve RAG context — RAGRetriever.get_context()
          3. LLM explanation     — explain_risk()
          4. Merge result dict
          5. Optional alert      — AlertSystem.send() (YELLOW/RED only)

        Returns unified dict. Never raises.

        Return shape:
          {
            # All keys from DeviationDetector.check():
            "risk_score":       int,
            "risk_level":       str,   # GREEN | YELLOW | RED
            "anomalies":        list,
            "summary":          str,
            # Added by agent:
            "ai_explanation": {
                "summary":       str,
                "concern_level": str,   # normal | watch | urgent
                "action":        str,
                "positive":      str,
            },
            "rag_context_used": bool,
          }
        """
        logger.info("CareWatch Agent running for: %s", person_id)

        # Step 1 — existing risk logic, zero changes to deviation_detector.py
        try:
            risk_result = self.detector.check(person_id)
        except Exception as e:
            logger.error("Detector failed: %s", e)
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

        logger.info(
            "Risk: %s/100 (%s)",
            risk_result.risk_score,
            risk_result.risk_level,
        )

        # Step 2 — RAG context for detected anomalies
        # anomalies shape: [{"activity", "type", "message", "severity"}, ...]
        # String anomalies (no-baseline path) are tolerated — get_context() filters them
        anomalies   = risk_result.anomalies
        rag_context = self.rag.get_context(anomalies)

        if rag_context:
            logger.info("RAG context retrieved (%d chars)", len(rag_context))
        else:
            logger.info("RAG: no context (unavailable or no dict anomalies)")

        # Step 3 — LLM explanation, fallback built into explain_risk()
        explanation = explain_risk(
            person_id=person_id,
            risk_score=risk_result.risk_score,
            risk_level=risk_result.risk_level,
            anomalies=anomalies,
            rag_context=rag_context,
        )
        logger.info("LLM concern_level: %s", explanation.get("concern_level"))

        # Step 4 — merge into unified result
        full_result = AgentResult(
            **risk_result.model_dump(),
            ai_explanation=AIExplanation(**explanation) if isinstance(explanation, dict) else explanation,
            rag_context_used=bool(rag_context),
        )

        # Step 5 — alert gate (alert_system only fires on YELLOW/RED)
        if send_alert:
            self.alerts.send(
                full_result,
                person_name=person_id.replace("_", " ").title(),
            )

        return full_result