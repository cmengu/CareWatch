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
from src.suppression import AlertSuppressionLayer
from src.audit_logger import AuditLogger
from src.models import AgentResult, AIExplanation

logger = logging.getLogger(__name__)


def _check_confidence(result: "AgentResult") -> str:
    """
    Inspect assembled AgentResult for internal contradictions.
    Returns "low" if score and concern_level point in opposite directions hard enough
    that no reasonable interpretation reconciles them. Returns "high" otherwise.
    Never raises.

    Contradiction cases:
        risk_score > 70 + concern_level = normal  → LLM under-alarmed despite high score
        risk_score < 20 + concern_level = urgent  → LLM over-alarmed despite clean score
    """
    try:
        score = result.risk_score
        concern = result.ai_explanation.concern_level

        if score > 70 and concern == "normal":
            logger.warning(
                "Low confidence: risk_score=%d but concern_level=normal — suppressing alert",
                score,
            )
            return "low"

        if score < 20 and concern == "urgent":
            logger.warning(
                "Low confidence: risk_score=%d but concern_level=urgent — suppressing alert",
                score,
            )
            return "low"

        return "high"

    except Exception as e:
        logger.error("Confidence check failed (non-blocking): %s", e)
        return "high"  # fail open — don't suppress alerts on check failure


class CareWatchAgent:
    def __init__(self):
        self.detector = DeviationDetector()
        self.rag      = RAGRetriever()
        self.alerts   = AlertSuppressionLayer()
        self.audit    = AuditLogger()

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
            relevance_score = self.rag._score_relevance(rag_context, anomalies)
            if relevance_score < 0.5:
                logger.info("RAG context scored %.2f — below threshold, skipping", relevance_score)
                rag_context = ""
            else:
                logger.info("RAG context retrieved (%d chars), relevance score: %.2f", len(rag_context), relevance_score)
        else:
            logger.info("RAG: no context (unavailable or no dict anomalies)")

        # Step 3 — LLM explanation, fallback built into explain_risk()
        trend = self.audit.compute_trend(person_id)
        memory_context = trend["history"] if trend["label"] != "INSUFFICIENT_DATA" else ""
        if memory_context:
            logger.info("Memory injected: trend=%s (%d rows)", trend["label"], trend["count"])
        explanation = explain_risk(
            person_id=person_id,
            risk_score=risk_result.risk_score,
            risk_level=risk_result.risk_level,
            anomalies=anomalies,
            rag_context=rag_context,
            memory_context=memory_context,
        )
        logger.info("LLM concern_level: %s", explanation.get("concern_level"))

        # Step 4 — merge into unified result
        full_result = AgentResult(
            **risk_result.model_dump(),
            ai_explanation=AIExplanation(**explanation) if isinstance(explanation, dict) else explanation,
            rag_context_used=bool(rag_context),
        )

        # Step 5 — confidence gate then alert gate
        full_result.confidence = _check_confidence(full_result)
        if send_alert and full_result.confidence == "high":
            self.alerts.send(
                full_result.model_dump(),
                person_name=person_id.replace("_", " ").title(),
            )

        self.audit.write(person_id, full_result)
        return full_result