"""
graph.py
========
LangGraph multi-agent pipeline for CareWatch.

MERGE ADDITIONS:
  - AgentState: image_bytes, scan_result, voice_alert fields
  - scan_node: new entry point — no-op if image_bytes is None
  - med_scan_node: runs MedScanAgent on scan_result
  - chronic_node: runs ChronicAgent — co-fires with med_node

Graph structure:
    scan_node → detect_node → route_node
             → fall_node → med_node → med_scan_node → chronic_node → routine_node
             → summary_node
             → (RED) human_gate_node → alert_node → END
             → (non-RED) ────────────→ alert_node → END

USAGE:
    from src.graph import build_graph
    graph = build_graph()
    result = graph.invoke({"person_id": "resident_001", "send_alert": True})

    # With scan:
    with open("photo.jpg", "rb") as f:
        result = graph.invoke({"person_id": "resident_001", "send_alert": True,
                               "image_bytes": f.read()})
"""

import dataclasses
import logging
import operator
from datetime import datetime
from typing import Any, Annotated, Optional, TypedDict

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from src.deviation_detector import DeviationDetector
from src.cusum_monitor import ResidentCUSUMMonitor
from src.rag_retriever import RAGRetriever
from src.suppression import AlertSuppressionLayer
from src.audit_logger import AuditLogger
from src.models import RiskResult, AgentResult, AIExplanation
from src.specialist_agents import (
    FallAgent, MedAgent, RoutineAgent, ChronicAgent, MedScanAgent,
    SummaryAgent, route, _normalise_anomaly,
    FALL_AGENT, MED_AGENT, ROUTINE_AGENT, CHRONIC_AGENT, MED_SCAN_AGENT,
)

logger = logging.getLogger(__name__)
DB_PATH = "data/carewatch.db"


class AgentState(TypedDict):
    person_id:    str
    send_alert:   bool
    voice_alert:  Optional[bool]
    _current_hour: Optional[float]
    _today:        Optional[str]
    _variant:      Optional[Any]
    image_bytes:  Optional[bytes]
    scan_result:  Optional[dict]
    risk_result:   Optional[RiskResult]
    cusum_result:  Optional[dict]
    normalised_anomalies: Optional[list]
    agents_to_run: Optional[list]
    specialist_outputs: Annotated[list, operator.add]
    final_result:  Optional[AgentResult]
    alert_sent:    Optional[bool]
    human_approved: Optional[bool]
    error: Optional[str]


def _make_scan_node(db_path: str):
    def scan_node(state: AgentState) -> dict:
        image_bytes = state.get("image_bytes")
        if not image_bytes:
            return {"scan_result": None}

        person_id = state["person_id"]
        logger.info("scan_node: processing image scan for %s", person_id)

        try:
            from src.label_detector import MedicationLabelDetector
            from src.medication import MedicationRepo

            detector = MedicationLabelDetector()
            scan_result = detector.extract_from_image(image_bytes)

            repo = MedicationRepo(db_path=db_path)
            repo.record_event(
                person_id=person_id,
                med_name=scan_result["medication_name"],
                ts=datetime.utcnow(),
                source="ai",
            )
            logger.info("scan_node: recorded %s intake for %s (confidence=%.2f)",
                        scan_result["medication_name"], person_id, scan_result.get("confidence", 0))

            scan_anomaly = {
                "activity": "pill_taking", "type": "MED_SCAN",
                "message": (f"Label scan: {scan_result['medication_name']} "
                            f"{scan_result.get('dose', '')} "
                            f"detected (confidence={scan_result.get('confidence', 0):.0%})"),
                "severity": "LOW",
            }
            return {"scan_result": scan_result, "normalised_anomalies": [scan_anomaly]}

        except Exception as e:
            logger.error("scan_node: failed for %s — %s", person_id, e)
            return {"scan_result": None, "error": f"scan_node: {e}"}
    return scan_node


def detect_node(state: AgentState, detector: DeviationDetector,
                cusum: ResidentCUSUMMonitor) -> dict:
    person_id = state["person_id"]
    try:
        risk_result = detector.check(
            person_id,
            _current_hour=state.get("_current_hour"),
            _today=state.get("_today"),
        )
    except Exception as e:
        logger.error("detect_node: detector.check failed: %s", e)
        return {"error": str(e), "risk_result": None, "cusum_result": None,
                "normalised_anomalies": state.get("normalised_anomalies") or []}

    cusum_dict = None
    try:
        cusum_result = cusum.check(person_id)
        cusum_dict = dataclasses.asdict(cusum_result)
    except Exception as e:
        logger.warning("detect_node: CUSUM failed (non-fatal): %s", e)

    new_normalised = [n for n in [_normalise_anomaly(a) for a in risk_result.anomalies] if n]
    existing = state.get("normalised_anomalies") or []
    # Preserve any scan anomaly already in state; don't duplicate MED_SCAN entries
    merged = existing + [a for a in new_normalised if a.get("type") != "MED_SCAN"]

    return {"risk_result": risk_result, "cusum_result": cusum_dict,
            "normalised_anomalies": merged, "error": None}


def route_node(state: AgentState) -> dict:
    anomalies = state.get("normalised_anomalies") or []
    agents = route(anomalies)
    logger.info("route_node: routing to %s", agents)
    return {"agents_to_run": agents}


def _make_fall_node(rag):
    def fall_node(state):
        if FALL_AGENT not in (state.get("agents_to_run") or []):
            return {"specialist_outputs": []}
        my_anomalies = [a for a in (state.get("normalised_anomalies") or [])
                        if a.get("type") in ("FALLEN", "UNCLEARED")]
        return {"specialist_outputs": [FallAgent(rag).run(state["person_id"], state["risk_result"], my_anomalies)]}
    return fall_node


def _make_med_node(rag):
    def med_node(state):
        if MED_AGENT not in (state.get("agents_to_run") or []):
            return {"specialist_outputs": []}
        my_anomalies = [a for a in (state.get("normalised_anomalies") or [])
                        if a.get("activity") == "pill_taking"]
        return {"specialist_outputs": [MedAgent(rag).run(state["person_id"], state["risk_result"], my_anomalies)]}
    return med_node


def _make_routine_node(rag):
    def routine_node(state):
        if ROUTINE_AGENT not in (state.get("agents_to_run") or []):
            return {"specialist_outputs": []}
        routine_activities = ("eating", "walking", "sitting", "lying_down")
        my_anomalies = [a for a in (state.get("normalised_anomalies") or [])
                        if a.get("activity") in routine_activities or a.get("type") == "TIMING"]
        if not my_anomalies:
            my_anomalies = state.get("normalised_anomalies") or []
        return {"specialist_outputs": [RoutineAgent(rag).run(state["person_id"], state["risk_result"], my_anomalies)]}
    return routine_node


def _make_med_scan_node(rag):
    def med_scan_node(state):
        if MED_SCAN_AGENT not in (state.get("agents_to_run") or []):
            return {"specialist_outputs": []}
        scan_anomalies = [a for a in (state.get("normalised_anomalies") or [])
                          if a.get("type") == "MED_SCAN"]
        result = MedScanAgent(rag).run(
            person_id=state["person_id"], risk_result=state["risk_result"],
            my_anomalies=scan_anomalies, scan_result=state.get("scan_result"),
        )
        return {"specialist_outputs": [result]}
    return med_scan_node


def _make_chronic_node(rag, db_path: str):
    def chronic_node(state):
        if CHRONIC_AGENT not in (state.get("agents_to_run") or []):
            return {"specialist_outputs": []}
        med_anomalies = [a for a in (state.get("normalised_anomalies") or [])
                         if a.get("activity") == "pill_taking"]
        result = ChronicAgent(rag).run(
            person_id=state["person_id"], risk_result=state["risk_result"],
            my_anomalies=med_anomalies, scan_result=state.get("scan_result"),
            db_path=db_path,
        )
        return {"specialist_outputs": [result]}
    return chronic_node


def summary_node(state: AgentState) -> dict:
    if state.get("risk_result") is None:
        return {"final_result": AgentResult(
            error=state.get("error", "Detection failed"),
            risk_score=0, risk_level="UNKNOWN", anomalies=[], summary="",
            ai_explanation=AIExplanation(summary="", concern_level="watch", action="", positive=""),
            rag_context_used=False, cusum_result=None,
        )}
    sa = SummaryAgent()
    return {"final_result": sa.synthesise(
        state.get("specialist_outputs") or [], state["risk_result"],
        cusum_result=state.get("cusum_result"),
    )}


def human_gate_node(state: AgentState) -> dict:
    logger.info("human_gate_node: caregiver acknowledgement for %s", state["person_id"])
    return {"human_approved": True}


def _make_alert_node(alerts, audit):
    def alert_node(state):
        final = state.get("final_result")
        if final is None:
            logger.error("alert_node: final_result is None — skipping alert")
            return {"alert_sent": False}
        person_id  = state["person_id"]
        send_alert = state.get("send_alert", True)
        final.prompt_version = getattr(state.get("_variant"), "variant_id", "langgraph")
        if send_alert:
            alerts.send(
                final.model_dump(),
                person_name=person_id.replace("_", " ").title(),
                resident_id=person_id,
                voice_alert=state.get("voice_alert", False),
            )
        audit.write(person_id, final)
        return {"alert_sent": send_alert}
    return alert_node


def _route_after_summary(state: AgentState) -> str:
    risk_result = state.get("risk_result")
    if risk_result and risk_result.risk_level == "RED":
        return "human_gate_node"
    return "alert_node"


def build_graph(db_path: str = DB_PATH):
    detector = DeviationDetector(db_path=db_path)
    cusum    = ResidentCUSUMMonitor()
    rag      = RAGRetriever()
    alerts   = AlertSuppressionLayer(db_path=db_path)
    audit    = AuditLogger(db_path=db_path)

    graph = StateGraph(AgentState)

    graph.add_node("scan_node",       _make_scan_node(db_path))
    graph.add_node("detect_node",     lambda s: detect_node(s, detector, cusum))
    graph.add_node("route_node",      route_node)
    graph.add_node("fall_node",       _make_fall_node(rag))
    graph.add_node("med_node",        _make_med_node(rag))
    graph.add_node("med_scan_node",   _make_med_scan_node(rag))
    graph.add_node("chronic_node",    _make_chronic_node(rag, db_path))
    graph.add_node("routine_node",    _make_routine_node(rag))
    graph.add_node("summary_node",    summary_node)
    graph.add_node("human_gate_node", human_gate_node)
    graph.add_node("alert_node",      _make_alert_node(alerts, audit))

    graph.set_entry_point("scan_node")

    graph.add_edge("scan_node",     "detect_node")
    graph.add_edge("detect_node",   "route_node")
    graph.add_edge("route_node",    "fall_node")
    graph.add_edge("fall_node",     "med_node")
    graph.add_edge("med_node",      "med_scan_node")
    graph.add_edge("med_scan_node", "chronic_node")
    graph.add_edge("chronic_node",  "routine_node")
    graph.add_edge("routine_node",  "summary_node")

    graph.add_conditional_edges(
        "summary_node", _route_after_summary,
        {"human_gate_node": "human_gate_node", "alert_node": "alert_node"},
    )
    graph.add_edge("human_gate_node", "alert_node")
    graph.add_edge("alert_node", END)

    return graph.compile(checkpointer=MemorySaver())
