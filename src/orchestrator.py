"""
orchestrator.py
===============
CareWatchOrchestrator — multi-agent drop-in replacement for CareWatchAgent.

Wraps the LangGraph compiled graph. Exposes:
    run(person_id, send_alert, _current_hour, _today, _variant) -> AgentResult
    resume(person_id, thread_id)  — stub: raises NotImplementedError (human-gate deferred)

The signature of run() matches CareWatchAgent.run() exactly so eval_agent.py
can switch between them with a single parameter.

USAGE:
    from src.orchestrator import CareWatchOrchestrator
    orch = CareWatchOrchestrator()
    result = orch.run("mrs_tan", send_alert=True)
"""

import logging
import uuid
from src.graph import build_graph
from src.models import AgentResult, AIExplanation

logger = logging.getLogger(__name__)


class CareWatchOrchestrator:

    def __init__(self, db_path: str | None = None):
        kwargs = {"db_path": db_path} if db_path else {}
        self.graph = build_graph(**kwargs)

    def run(
        self,
        person_id: str = "resident",
        send_alert: bool = True,
        _current_hour: float | None = None,
        _today: str | None = None,
        _variant=None,
    ) -> AgentResult:
        """
        Run the multi-agent pipeline for one resident.
        Returns AgentResult — same type as CareWatchAgent.run().
        Never raises.
        """
        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        initial_state = {
            "person_id":       person_id,
            "send_alert":      send_alert,
            "_current_hour":   _current_hour,
            "_today":          _today,
            "_variant":        _variant,
            "specialist_outputs": [],
            "human_approved":  False,
            "alert_sent":      False,
            "error":           None,
        }

        try:
            result = self.graph.invoke(initial_state, config=config)

            if result.get("error"):
                logger.error("Orchestrator: graph returned error: %s", result["error"])
                return self._error_result(result["error"])

            final = result.get("final_result")
            if final is None:
                logger.error("Orchestrator: final_result is None after graph completion")
                return self._error_result("Graph completed without final_result")

            logger.info(
                "Orchestrator: %s → %s / %s",
                person_id,
                final.risk_level,
                final.ai_explanation.concern_level,
            )
            return final

        except Exception as e:
            logger.error("Orchestrator.run() raised: %s", e)
            return self._error_result(str(e))

    def resume(self, person_id: str, thread_id: str) -> AgentResult:
        """
        Stub: Human-gate deferred. Re-add after alert_store.thread_id column is added.
        In LangGraph 0.2.28, resume would call graph.invoke({"human_approved": True}, config=config).
        """
        raise NotImplementedError(
            "Human-gate deferred. Re-add interrupt_before after alert_store.thread_id column is added. "
            "Architecture documented in README."
        )

    @staticmethod
    def _error_result(error: str) -> AgentResult:
        return AgentResult(
            error=error,
            risk_score=0,
            risk_level="UNKNOWN",
            anomalies=[],
            summary="Orchestrator error.",
            ai_explanation=AIExplanation(
                summary="Multi-agent monitoring encountered an error.",
                concern_level="watch",
                action="Check the CareWatch system status.",
                positive="Alert has been logged for review.",
            ),
            rag_context_used=False,
            cusum_result=None,
        )
