"""
graph.py
========
LangGraph multi-agent pipeline for CareWatch.

Graph structure:
    detect_node → route_node → [fall_node?, med_node?, routine_node?]
                                                            ↓
                                                     summary_node
                                                            ↓
                                    (RED) → human_gate_node → alert_node → END
                                    (non-RED) ─────────────→ alert_node → END

State:
    AgentState TypedDict — single source of truth between nodes

Human gate:
    Deferred — graph runs end-to-end. human_gate_node is a pass-through.
    Re-add interrupt_before after alert_store.thread_id column exists.

USAGE:
    from src.graph import build_graph
    graph = build_graph()
    result = graph.invoke({"person_id": "mrs_tan", "send_alert": True})
"""

import dataclasses
import logging
import operator
from typing import TypedDict, Optional, Any, Annotated

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from src.deviation_detector import DeviationDetector
from src.cusum_monitor import ResidentCUSUMMonitor
from src.rag_retriever import RAGRetriever
from src.suppression import AlertSuppressionLayer
from src.audit_logger import AuditLogger
from src.models import RiskResult, AgentResult, AIExplanation
from src.specialist_agents import (
    FallAgent, MedAgent, RoutineAgent, SummaryAgent,
    route, _normalise_anomaly,
    FALL_AGENT, MED_AGENT, ROUTINE_AGENT,
)

logger = logging.getLogger(__name__)

DB_PATH = "data/carewatch.db"


# ─────────────────────────────────────────────
# State — single source of truth
# ─────────────────────────────────────────────

class AgentState(TypedDict):
    person_id:    str
    send_alert:   bool
    _current_hour: Optional[float]
    _today:        Optional[str]
    _variant:      Optional[Any]

    risk_result:   Optional[RiskResult]
    cusum_result:  Optional[dict]
    normalised_anomalies: Optional[list]

    agents_to_run: Optional[list]

    specialist_outputs: Annotated[list, operator.add]

    final_result:  Optional[AgentResult]

    alert_sent:    Optional[bool]

    human_approved: Optional[bool]

    error: Optional[str]


# ─────────────────────────────────────────────
# Node implementations
# ─────────────────────────────────────────────

def detect_node(state: AgentState, detector: DeviationDetector, cusum: ResidentCUSUMMonitor) -> dict:
    """Run DeviationDetector and CUSUM. Normalise anomaly shapes."""
    person_id = state["person_id"]
    try:
        risk_result = detector.check(
            person_id,
            _current_hour=state.get("_current_hour"),
            _today=state.get("_today"),
        )
    except Exception as e:
        logger.error("detect_node: detector.check failed: %s", e)
        return {"error": str(e), "risk_result": None, "cusum_result": None, "normalised_anomalies": []}

    cusum_dict = None
    try:
        cusum_result = cusum.check(person_id)
        cusum_dict = dataclasses.asdict(cusum_result)
    except Exception as e:
        logger.warning("detect_node: CUSUM failed (non-fatal): %s", e)

    normalised = [
        n for n in [_normalise_anomaly(a) for a in risk_result.anomalies]
        if n
    ]
    return {
        "risk_result":            risk_result,
        "cusum_result":           cusum_dict,
        "normalised_anomalies":   normalised,
        "error":                  None,
    }


def route_node(state: AgentState) -> dict:
    """Decide which specialist agents to run based on normalised anomalies."""
    anomalies = state.get("normalised_anomalies") or []
    agents = route(anomalies)
    logger.info("route_node: routing to %s", agents)
    return {"agents_to_run": agents}


def _make_fall_node(rag: RAGRetriever):
    def fall_node(state: AgentState) -> dict:
        if FALL_AGENT not in (state.get("agents_to_run") or []):
            return {"specialist_outputs": []}

        my_anomalies = [
            a for a in (state.get("normalised_anomalies") or [])
            if a.get("type") in ("FALLEN", "UNCLEARED")
        ]
        result = FallAgent(rag).run(state["person_id"], state["risk_result"], my_anomalies)
        return {"specialist_outputs": [result]}
    return fall_node


def _make_med_node(rag: RAGRetriever):
    def med_node(state: AgentState) -> dict:
        if MED_AGENT not in (state.get("agents_to_run") or []):
            return {"specialist_outputs": []}

        my_anomalies = [
            a for a in (state.get("normalised_anomalies") or [])
            if a.get("activity") == "pill_taking"
        ]
        result = MedAgent(rag).run(state["person_id"], state["risk_result"], my_anomalies)
        return {"specialist_outputs": [result]}
    return med_node


def _make_routine_node(rag: RAGRetriever):
    def routine_node(state: AgentState) -> dict:
        if ROUTINE_AGENT not in (state.get("agents_to_run") or []):
            return {"specialist_outputs": []}

        routine_activities = ("eating", "walking", "sitting", "lying_down")
        my_anomalies = [
            a for a in (state.get("normalised_anomalies") or [])
            if a.get("activity") in routine_activities or a.get("type") == "TIMING"
        ]
        if not my_anomalies:
            my_anomalies = state.get("normalised_anomalies") or []

        result = RoutineAgent(rag).run(state["person_id"], state["risk_result"], my_anomalies)
        return {"specialist_outputs": [result]}
    return routine_node


def summary_node(state: AgentState) -> dict:
    """SummaryAgent synthesises specialist outputs. Passes cusum_result as constructor arg."""
    if state.get("risk_result") is None:
        return {"final_result": AgentResult(
            error=state.get("error", "Detection failed"),
            risk_score=0, risk_level="UNKNOWN", anomalies=[], summary="",
            ai_explanation=AIExplanation(summary="", concern_level="watch", action="", positive=""),
            rag_context_used=False, cusum_result=None,
        )}
    outputs = state.get("specialist_outputs") or []
    risk_result = state["risk_result"]
    cusum_result = state.get("cusum_result")
    sa = SummaryAgent()
    final = sa.synthesise(outputs, risk_result, cusum_result=cusum_result)
    return {"final_result": final}


def human_gate_node(state: AgentState) -> dict:
    """
    Human-in-the-loop gate (currently pass-through).
    Re-add interrupt_before after alert_store.thread_id column is added.
    """
    logger.info("human_gate_node: waiting for caregiver acknowledgement for %s", state["person_id"])
    return {"human_approved": True}


def _make_alert_node(alerts: AlertSuppressionLayer, audit: AuditLogger):
    def alert_node(state: AgentState) -> dict:
        final = state.get("final_result")
        if final is None:
            logger.error("alert_node: final_result is None — skipping alert")
            return {"alert_sent": False}

        person_id = state["person_id"]
        send_alert = state.get("send_alert", True)

        if send_alert:
            alerts.send(
                final.model_dump(),
                person_name=person_id.replace("_", " ").title(),
                resident_id=person_id,
            )

        final.prompt_version = getattr(state.get("_variant"), "variant_id", "langgraph")
        audit.write(person_id, final)
        return {"alert_sent": send_alert}
    return alert_node


# ─────────────────────────────────────────────
# Conditional edge: should we pause for human?
# ─────────────────────────────────────────────

def _route_after_summary(state: AgentState) -> str:
    """RED alerts go to human_gate_node. All others go directly to alert_node."""
    risk_result = state.get("risk_result")
    if risk_result and risk_result.risk_level == "RED":
        return "human_gate_node"
    return "alert_node"


# ─────────────────────────────────────────────
# Graph builder
# ─────────────────────────────────────────────

def build_graph(db_path: str = DB_PATH):
    """
    Construct and compile the CareWatch LangGraph.

    Returns a compiled StateGraph ready for .invoke() or .stream().
    Uses MemorySaver to allow config={"configurable": {"thread_id": ...}} without ValueError.

    Args:
        db_path: path to carewatch.db (overridden in eval for isolation)
    """
    detector = DeviationDetector(db_path=db_path)
    cusum    = ResidentCUSUMMonitor()
    rag      = RAGRetriever()
    alerts   = AlertSuppressionLayer(db_path=db_path)
    audit    = AuditLogger(db_path=db_path)

    graph = StateGraph(AgentState)

    graph.add_node("detect_node",    lambda s: detect_node(s, detector, cusum))
    graph.add_node("route_node",     route_node)
    graph.add_node("fall_node",      _make_fall_node(rag))
    graph.add_node("med_node",       _make_med_node(rag))
    graph.add_node("routine_node",   _make_routine_node(rag))
    graph.add_node("summary_node",   summary_node)
    graph.add_node("human_gate_node", human_gate_node)
    graph.add_node("alert_node",     _make_alert_node(alerts, audit))

    graph.set_entry_point("detect_node")

    graph.add_edge("detect_node",  "route_node")
    graph.add_edge("route_node",   "fall_node")
    graph.add_edge("fall_node",    "med_node")
    graph.add_edge("med_node",     "routine_node")
    graph.add_edge("routine_node", "summary_node")

    graph.add_conditional_edges(
        "summary_node",
        _route_after_summary,
        {"human_gate_node": "human_gate_node", "alert_node": "alert_node"},
    )
    graph.add_edge("human_gate_node", "alert_node")
    graph.add_edge("alert_node", END)

    checkpointer = MemorySaver()
    compiled = graph.compile(checkpointer=checkpointer)

    return compiled
