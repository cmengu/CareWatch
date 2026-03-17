"""
langchain_agent.py
==================
LangChain tool-calling agent implementation of CareWatch pipeline.
Used only for eval benchmarking — NOT for production.

Wraps DeviationDetector, RAGRetriever, AlertSuppressionLayer as LangChain tools.
Uses ChatGroq + create_tool_calling_agent + AgentExecutor.

Returns AgentResult — same interface as CareWatchAgent.run() and
CareWatchOrchestrator.run() for eval compatibility.

USAGE:
    from src.langchain_agent import CareWatchLangChainAgent
    agent = CareWatchLangChainAgent()
    result = agent.run("resident", send_alert=False)
"""

import logging
import os
from src.deviation_detector import DeviationDetector
from src.rag_retriever import RAGRetriever
from src.suppression import AlertSuppressionLayer
from src.audit_logger import AuditLogger
from src.models import AgentResult, AIExplanation

logger = logging.getLogger(__name__)


def _build_tools(
    detector: DeviationDetector,
    rag: RAGRetriever,
    _current_hour: float | None = None,
    _today: str | None = None,
):
    """Build LangChain tools wrapping CareWatch components.
    _current_hour and _today are closed over so the tool's detector call
    matches the ground-truth RiskResult used in the returned AgentResult.
    """
    from langchain.tools import tool

    @tool
    def detect_risk(person_id: str) -> str:
        """
        Run deviation detection for a resident.
        Returns risk_level, risk_score, and anomaly list as a string.
        Input: person_id (str)
        """
        try:
            result = detector.check(
                person_id, _current_hour=_current_hour, _today=_today,
            )
            anomaly_strs = []
            for a in result.anomalies:
                if isinstance(a, dict):
                    anomaly_strs.append(f"{a.get('activity','?')}: {a.get('message','')}")
                else:
                    try:
                        anomaly_strs.append(f"{a.activity}: {a.message}")
                    except AttributeError:
                        anomaly_strs.append(str(a))
            return (
                f"risk_level={result.risk_level} "
                f"risk_score={result.risk_score} "
                f"anomalies=[{'; '.join(anomaly_strs)}]"
            )
        except Exception as e:
            return f"error={e}"

    @tool
    def retrieve_context(anomaly_description: str) -> str:
        """
        Retrieve relevant medical context for an anomaly.
        Input: plain-text description of the anomaly (e.g. 'fall detected hip fracture risk')
        Returns: relevant medical facts as a string.
        """
        try:
            pseudo_anomaly = [{"activity": anomaly_description, "type": "QUERY",
                                "message": anomaly_description, "severity": "MEDIUM"}]
            context = rag.get_context(pseudo_anomaly)
            return context or "No relevant context found."
        except Exception as e:
            return f"error retrieving context: {e}"

    return [detect_risk, retrieve_context]


class CareWatchLangChainAgent:

    def __init__(self, db_path: str | None = None):
        self.detector = DeviationDetector(db_path=db_path) if db_path else DeviationDetector()
        self.rag      = RAGRetriever()
        self.alerts   = AlertSuppressionLayer(db_path=db_path) if db_path else AlertSuppressionLayer()
        self.audit    = AuditLogger()

    def run(
        self,
        person_id: str = "resident",
        send_alert: bool = True,
        _current_hour: float | None = None,
        _today: str | None = None,
        _variant=None,
    ) -> AgentResult:
        """
        Run LangChain tool-calling agent for one resident.
        Returns AgentResult. Never raises.
        """
        try:
            from langchain_groq import ChatGroq
            from langchain.agents import create_tool_calling_agent, AgentExecutor
            from langchain_core.prompts import ChatPromptTemplate

            llm = ChatGroq(
                model="llama-3.3-70b-versatile",
                temperature=0.3,
                api_key=os.environ.get("GROQ_API_KEY"),
            )

            tools = _build_tools(
                self.detector, self.rag,
                _current_hour=_current_hour, _today=_today,
            )

            prompt = ChatPromptTemplate.from_messages([
                ("system", (
                    "You are CareWatch, an AI monitoring system for elderly residents. "
                    "Use the available tools to assess the resident's current status. "
                    "First call detect_risk to get the current risk level. "
                    "Then call retrieve_context for any concerning anomalies. "
                    "Finally, provide a family-facing assessment with: "
                    "risk_level (GREEN/YELLOW/RED), concern_level (normal/watch/urgent), "
                    "summary (one sentence), and action (one sentence)."
                )),
                ("human", "Assess resident: {person_id}"),
                ("placeholder", "{agent_scratchpad}"),
            ])

            agent = create_tool_calling_agent(llm, tools, prompt)
            executor = AgentExecutor(agent=agent, tools=tools, max_iterations=5, verbose=False)

            output = executor.invoke({"person_id": person_id})
            raw_output = output.get("output", "")

            risk_result = self.detector.check(
                person_id,
                _current_hour=_current_hour,
                _today=_today,
            )

            # Naive string-match parsing — "normal" can false-match on phrases like
            # "this is a normal day". Acceptable for eval baseline; not production-grade.
            # Order matters: check "urgent" first so RED alerts aren't downgraded.
            concern = "watch"
            if "urgent" in raw_output.lower():
                concern = "urgent"
            elif "normal" in raw_output.lower() or "green" in raw_output.lower():
                concern = "normal"

            full_result = AgentResult(
                **risk_result.model_dump(),
                ai_explanation=AIExplanation(
                    summary       = raw_output[:300] if raw_output else risk_result.summary,
                    concern_level = concern,
                    action        = "See CareWatch assessment above.",
                    positive      = "LangChain agent monitoring active.",
                ),
                rag_context_used = True,
                cusum_result     = None,
            )

            full_result.prompt_version = "langchain"

            if send_alert:
                self.alerts.send(
                    full_result.model_dump(),
                    person_name=person_id.replace("_", " ").title(),
                    resident_id=person_id,
                )

            self.audit.write(person_id, full_result)
            return full_result

        except Exception as e:
            logger.error("CareWatchLangChainAgent.run() failed: %s", e)
            return AgentResult(
                error=str(e),
                risk_score=0,
                risk_level="UNKNOWN",
                anomalies=[],
                summary="LangChain agent error.",
                ai_explanation=AIExplanation(
                    summary="LangChain agent encountered an error.",
                    concern_level="watch",
                    action="Check the CareWatch system status.",
                    positive="",
                ),
                rag_context_used=False,
                cusum_result=None,
            )
