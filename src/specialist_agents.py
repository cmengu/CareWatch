"""
specialist_agents.py
====================
Specialist agents for CareWatch multi-agent pipeline.

MERGE ADDITIONS (from PillReminder):
  - ChronicAgent  — infers chronic illness conditions from 30-day medication history
  - MedScanAgent  — enriches a fresh label scan with illness context
  - CHRONIC_AGENT and MED_SCAN_AGENT constants
  - route() updated: CHRONIC_AGENT co-fires whenever MED_AGENT fires

Original agents unchanged:
    FallAgent, MedAgent, RoutineAgent, SummaryAgent
"""

import logging
from typing import Dict, List, Optional
from src.models import SpecialistResult, AgentResult, AIExplanation, RiskResult
from src.rag_retriever import RAGRetriever
from src.llm_explainer import explain_risk

logger = logging.getLogger(__name__)

CONCERN_PRIORITY = {"normal": 0, "watch": 1, "urgent": 2}

FALL_AGENT     = "FallAgent"
MED_AGENT      = "MedAgent"
ROUTINE_AGENT  = "RoutineAgent"
CHRONIC_AGENT  = "ChronicAgent"
MED_SCAN_AGENT = "MedScanAgent"


def _normalise_anomaly(a) -> dict:
    if isinstance(a, dict):
        return a
    try:
        return {"activity": a.activity, "type": a.type, "message": a.message, "severity": a.severity}
    except AttributeError:
        logger.warning("_normalise_anomaly: unrecognised anomaly shape %s — skipping", type(a))
        return {}


def route(anomalies: list) -> list[str]:
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
        if atype == "MED_SCAN":
            agents.add(MED_SCAN_AGENT)
            agents.add(MED_AGENT)

    if not agents:
        agents.add(ROUTINE_AGENT)

    if MED_AGENT in agents or MED_SCAN_AGENT in agents:
        agents.add(CHRONIC_AGENT)

    return list(agents)


class _BaseSpecialist:
    agent_name:  str   = "BaseAgent"
    rag_queries: tuple = ()

    def __init__(self, rag: RAGRetriever):
        self.rag = rag

    def _get_rag_context(self, anomalies: list[dict]) -> str:
        try:
            return self.rag.get_context_v2(anomalies)
        except Exception as e:
            logger.warning("%s: RAG retrieval failed (%s) — continuing without context", self.agent_name, e)
            return ""

    def _explain(self, person_id, risk_score, risk_level, anomalies, rag_context) -> dict:
        try:
            return explain_risk(
                person_id=person_id, risk_score=risk_score, risk_level=risk_level,
                anomalies=anomalies, rag_context=rag_context, memory_context="",
            )
        except Exception as e:
            logger.error("%s: LLM explain failed (%s) — using fallback", self.agent_name, e)
            return {"summary": f"{self.agent_name} could not generate explanation.",
                    "concern_level": "watch", "action": "Check the CareWatch system.", "positive": ""}

    def run(self, person_id, risk_result, my_anomalies) -> SpecialistResult:
        raise NotImplementedError


class FallAgent(_BaseSpecialist):
    agent_name  = FALL_AGENT
    rag_queries = ["fall detection emergency response", "hip fracture elderly", "fallen assessment"]

    def run(self, person_id, risk_result, my_anomalies):
        logger.info("FallAgent running for %s (%d anomalies)", person_id, len(my_anomalies))
        rag_context = self._get_rag_context(my_anomalies)
        explanation = self._explain(person_id, risk_result.risk_score, risk_result.risk_level,
                                    my_anomalies, rag_context)
        concern = explanation.get("concern_level", "urgent")
        if risk_result.risk_level == "RED" and concern != "urgent":
            logger.warning("FallAgent: LLM returned concern=%s for RED — overriding to urgent", concern)
            concern = "urgent"
        return SpecialistResult(
            agent_name=self.agent_name, concern_level=concern,
            summary=explanation.get("summary", "Fall event detected."),
            action=explanation.get("action", "Contact emergency services immediately."),
            rag_used=bool(rag_context), anomalies=my_anomalies,
        )


class MedAgent(_BaseSpecialist):
    agent_name  = MED_AGENT
    rag_queries = ["missed medication elderly morning dosing window",
                   "pill taking adherence", "drug interaction elderly"]

    def run(self, person_id, risk_result, my_anomalies):
        logger.info("MedAgent running for %s (%d anomalies)", person_id, len(my_anomalies))
        rag_context = self._get_rag_context(my_anomalies)
        explanation = self._explain(person_id, risk_result.risk_score, risk_result.risk_level,
                                    my_anomalies, rag_context)
        return SpecialistResult(
            agent_name=self.agent_name,
            concern_level=explanation.get("concern_level", "watch"),
            summary=explanation.get("summary", "Medication deviation detected."),
            action=explanation.get("action", "Check whether medication was taken."),
            rag_used=bool(rag_context), anomalies=my_anomalies,
        )


class RoutineAgent(_BaseSpecialist):
    agent_name  = ROUTINE_AGENT
    rag_queries = ["missed eating elderly nutrition", "activity routine deviation",
                   "walking reduced mobility"]

    def run(self, person_id, risk_result, my_anomalies):
        logger.info("RoutineAgent running for %s (%d anomalies)", person_id, len(my_anomalies))
        rag_context = self._get_rag_context(my_anomalies)
        explanation = self._explain(person_id, risk_result.risk_score, risk_result.risk_level,
                                    my_anomalies, rag_context)
        return SpecialistResult(
            agent_name=self.agent_name,
            concern_level=explanation.get("concern_level", "normal"),
            summary=explanation.get("summary", "Routine deviation detected."),
            action=explanation.get("action", "Monitor closely today."),
            rag_used=bool(rag_context), anomalies=my_anomalies,
        )


class ChronicAgent(_BaseSpecialist):
    """
    Infers chronic illness conditions from a resident's 30-day medication history.
    Co-fires with MedAgent whenever medication anomalies are present.
    """
    agent_name  = CHRONIC_AGENT
    rag_queries = ["chronic illness elderly medication management",
                   "polypharmacy elderly risk",
                   "diabetes hypertension comorbidity management"]

    def run(self, person_id, risk_result, my_anomalies,
            scan_result: Optional[Dict] = None, db_path: str = "data/carewatch.db") -> SpecialistResult:
        logger.info("ChronicAgent running for %s", person_id)
        from src.medication import MedicationRepo
        from src.chronic_detector import ChronicDetector

        try:
            repo = MedicationRepo(db_path=db_path)
            events = repo.get_recent_events(person_id, days=30)
        except Exception as e:
            logger.warning("ChronicAgent: could not fetch medication events: %s", e)
            events = []

        detector = ChronicDetector()
        chronic = detector.detect(events)

        scan_enrichment = ""
        if scan_result and scan_result.get("medication_name"):
            med_name = scan_result["medication_name"]
            inference = detector.infer_from_name(med_name)
            conditions = inference.get("conditions", [])
            if conditions:
                top = conditions[0]["name"]
                scan_enrichment = f" Scanned medication '{med_name}' is commonly used for {top}."

        if not chronic.top_illnesses:
            return SpecialistResult(
                agent_name=self.agent_name, concern_level="normal",
                summary="No chronic condition indicators found in recent medication history." + scan_enrichment,
                action="Continue monitoring medication adherence.",
                rag_used=False, anomalies=my_anomalies,
            )

        illness_anomalies = [{"activity": "pill_taking", "type": "CHRONIC",
                              "message": f"Chronic condition inferred: {ill}", "severity": "MEDIUM"}
                             for ill in chronic.top_illnesses]
        rag_context = self._get_rag_context(illness_anomalies)

        return SpecialistResult(
            agent_name=self.agent_name, concern_level=chronic.concern_level,
            summary=chronic.summary + scan_enrichment,
            action=("Ensure all medications for " + ", ".join(chronic.top_illnesses) +
                    " are taken consistently. Consider a medication review if adherence is low."),
            rag_used=bool(rag_context), anomalies=my_anomalies,
        )


class MedScanAgent(_BaseSpecialist):
    """
    Handles a fresh medication label scan from scan_node.
    Validates confidence, reports scan result to family.
    """
    agent_name  = MED_SCAN_AGENT
    rag_queries = ["medication intake confirmation", "pill taking verification elderly"]

    def run(self, person_id, risk_result, my_anomalies,
            scan_result: Optional[Dict] = None) -> SpecialistResult:
        logger.info("MedScanAgent running for %s", person_id)

        if not scan_result:
            logger.warning("MedScanAgent: no scan_result in state — skipping")
            return SpecialistResult(
                agent_name=self.agent_name, concern_level="normal",
                summary="No label scan result available.",
                action="Scan a medication label to record an intake.", skipped=True,
            )

        from src.label_detector import CONFIDENCE_THRESHOLD
        confidence = float(scan_result.get("confidence", 0.0))
        med_name   = scan_result.get("medication_name", "Unknown")
        dose       = scan_result.get("dose", "—")
        meal_rel   = scan_result.get("meal_relation", "fixed")

        if confidence < CONFIDENCE_THRESHOLD:
            return SpecialistResult(
                agent_name=self.agent_name, concern_level="watch",
                summary=(f"Low-confidence label scan (confidence={confidence:.0%}). "
                         "Could not reliably identify the medication. Please verify manually."),
                action="Ask the resident to confirm the medication name.",
                rag_used=False, anomalies=my_anomalies,
            )

        meal_note = {"before": "should be taken BEFORE food",
                     "after":  "should be taken WITH or AFTER food",
                     "fixed":  "can be taken at any time"}.get(meal_rel, "")

        rag_context = self._get_rag_context(my_anomalies)

        return SpecialistResult(
            agent_name=self.agent_name, concern_level="normal",
            summary=(f"Medication scan confirmed: {med_name} {dose} "
                     f"(confidence={confidence:.0%}). This medication {meal_note}."),
            action=f"Verify {med_name} was taken correctly. {meal_note.capitalize()}.",
            rag_used=bool(rag_context), anomalies=my_anomalies,
        )


class SummaryAgent:
    AGENT_PRIORITY = {FALL_AGENT: 4, MED_AGENT: 3, MED_SCAN_AGENT: 2, CHRONIC_AGENT: 1, ROUTINE_AGENT: 0}

    def synthesise(self, specialist_outputs, risk_result, cusum_result=None) -> AgentResult:
        try:
            active = [s for s in specialist_outputs if not s.skipped]
            if not active:
                logger.warning("SummaryAgent: no active specialist outputs — using fallback")
                return self._fallback(risk_result, cusum_result)

            active.sort(key=lambda s: (CONCERN_PRIORITY.get(s.concern_level, 0),
                                       self.AGENT_PRIORITY.get(s.agent_name, 0)), reverse=True)

            primary = active[0]
            summary_parts = [primary.summary]
            for s in active[1:]:
                if s.summary and s.summary != primary.summary:
                    summary_parts.append(s.summary)

            return AgentResult(
                **risk_result.model_dump(),
                ai_explanation=AIExplanation(
                    summary=" ".join(summary_parts), concern_level=primary.concern_level,
                    action=primary.action, positive="CareWatch multi-agent monitoring is active.",
                ),
                rag_context_used=any(s.rag_used for s in active),
                cusum_result=cusum_result,
            )
        except Exception as e:
            logger.error("SummaryAgent.synthesise failed: %s — using fallback", e)
            return self._fallback(risk_result, cusum_result)

    def _fallback(self, risk_result, cusum_result=None) -> AgentResult:
        concern = {"RED": "urgent", "YELLOW": "watch", "GREEN": "normal"}.get(risk_result.risk_level, "watch")
        return AgentResult(
            **risk_result.model_dump(),
            ai_explanation=AIExplanation(
                summary=risk_result.summary, concern_level=concern,
                action="Please check on your family member.",
                positive="CareWatch monitoring is active.",
            ),
            rag_context_used=False, cusum_result=cusum_result,
        )
