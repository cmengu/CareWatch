"""
run_pipeline.py
================
CareWatch pipeline entry point. Runs the full risk pipeline for one or more
residents and fires Telegram alerts for any RED results.

Pipeline sequence:
    1. (Once) Verify ChromaDB is initialised — rebuild if empty
    2. Resolve target resident(s) from args or active_alerts table
    3. CareWatchAgent.run(person_id) per resident
       -> DeviationDetector.check()     (deviation + persistent alert check)
       -> ResidentCUSUMMonitor.check()  (trend detection)
       -> RAGRetriever.get_context()    (ChromaDB knowledge retrieval)
       -> explain_risk()               (Groq LLM explanation + self-check)
       -> AlertSuppressionLayer.send() (Telegram, YELLOW/RED only)
    4. Print structured summary to stdout

KNOWN LIMITATION:
    --all mode runs DeviationDetector.check() for every resident, but
    get_today() filters activity_log by datetime.now().date(). Mock data
    was generated for past dates, so today_logs is always empty and all
    non-alert residents return GREEN. Use --find-red for reliable E2E testing.
    To use --all with real results, re-run generate_mock_data.py without --reset
    so it writes rows dated today, or run the live camera pipeline.

USAGE:
    # Find first resident with active RED alert and fire Telegram:
    python run_pipeline.py --find-red

    # Dry run — no Telegram:
    python run_pipeline.py --find-red --no-alert

    # Specific resident:
    python run_pipeline.py --resident resident_0042 --no-alert

    # Batch (GREEN for all unless active alert exists — see KNOWN LIMITATION):
    python run_pipeline.py --all --no-alert

REQUIRES:
    .env: GROQ_API_KEY, CAREWATCH_BOT_TOKEN, CAREWATCH_CHAT_ID
    data/carewatch.db       (run generate_mock_data.py first)
    baselines table         (run build_baselines_bulk.py first — 1000 rows)
    data/chroma_db/         (auto-rebuilt if missing)
"""

import argparse
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Logging setup before any src imports
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_pipeline")

# Load .env from repo root
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
        logger.info(".env loaded from %s", _env_path)
    except ImportError:
        logger.warning("python-dotenv not installed — set env vars manually")

DB_PATH     = "data/carewatch.db"
CHROMA_PATH = Path("data/chroma_db")
FACTS_PATH  = Path("data/drug_interactions.txt")


# ── ChromaDB bootstrap ──────────────────────────────────────────────────────

def _ensure_chroma() -> bool:
    """
    Check ChromaDB collection exists and has documents.
    Rebuilds from data/drug_interactions.txt if empty or missing.
    Returns True if RAG available, False if it should be skipped.
    """
    try:
        import chromadb
    except ImportError:
        logger.warning("chromadb not installed — RAG skipped. pip install chromadb")
        return False

    try:
        client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        try:
            col   = client.get_collection("carewatch_knowledge")
            count = col.count()
            if count > 0:
                logger.info("ChromaDB ready: %d documents", count)
                return True
            logger.warning("ChromaDB empty — rebuilding from %s", FACTS_PATH)
        except Exception:
            logger.warning("ChromaDB collection missing — building from %s", FACTS_PATH)

        if not FACTS_PATH.exists():
            logger.error(
                "Cannot build ChromaDB: %s not found. "
                "Complete Step 1.1 first.",
                FACTS_PATH,
            )
            return False

        from src.knowledge_base import build_knowledge_base
        build_knowledge_base()
        logger.info("ChromaDB rebuilt successfully")
        return True

    except Exception as e:
        logger.warning("ChromaDB init failed (%s) — continuing without RAG", e)
        return False


# ── Resident resolution ─────────────────────────────────────────────────────

def _find_red_resident() -> str | None:
    """Return person_id of first resident with an uncleared active alert."""
    try:
        conn = sqlite3.connect(DB_PATH)
        row  = conn.execute(
            "SELECT person_id FROM active_alerts "
            "WHERE cleared_at IS NULL ORDER BY triggered_at ASC LIMIT 1"
        ).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        logger.error("Could not query active_alerts: %s", e)
        return None


def _all_residents() -> list[str]:
    """Return all distinct person_ids from activity_log."""
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT DISTINCT person_id FROM activity_log ORDER BY person_id"
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception as e:
        logger.error("Could not query activity_log: %s", e)
        return []


# ── Result printing ─────────────────────────────────────────────────────────

_LEVEL_COLOR = {
    "GREEN":   "\033[92m",
    "YELLOW":  "\033[93m",
    "RED":     "\033[91m",
    "UNKNOWN": "\033[90m",
}
_RESET    = "\033[0m"
_SEV_ICON = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🔵"}


def _print_result(result, person_id: str) -> None:
    """Pretty-print an AgentResult to stdout."""
    level = result.risk_level
    score = result.risk_score
    color = _LEVEL_COLOR.get(level, "")
    rag   = "✅ yes" if result.rag_context_used else "❌ no"
    conf  = result.confidence

    print()
    print("=" * 60)
    print(f"  CareWatch — {person_id.replace('_', ' ').title()}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print(f"  Risk:       {color}{level}{_RESET}  ({score}/100)")
    print(f"  RAG used:   {rag}")
    print(f"  Confidence: {conf}")
    print()

    if result.error:
        print(f"  ⚠  Pipeline error: {result.error}")
        print()

    print(f"  Summary: {result.summary}")
    print()

    if result.anomalies:
        print("  Anomalies detected:")
        for a in result.anomalies:
            if isinstance(a, dict):
                icon = _SEV_ICON.get(a.get("severity", ""), "⚪")
                print(f"    {icon}  [{a.get('type', '?')}] {a.get('message', '')}")
            else:
                print(f"    ⚪  {a}")
        print()

    ai = result.ai_explanation
    if ai:
        print("  AI Explanation:")
        print(f"    {ai.summary}")
        print(f"    Concern : {ai.concern_level}")
        print(f"    Action  : {ai.action}")
        print(f"    Positive: {ai.positive}")
        print()

    # CUSUM: uses .summary only — .label does not exist on CUSUMCheckResult
    if result.cusum_result:
        cusum = result.cusum_result
        print(f"  CUSUM trend: {cusum.get('summary', 'no summary')}")
        print()

    print("=" * 60)
    print()


# ── Args ────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="CareWatch risk pipeline")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--resident",  metavar="ID",
                       help="Run for a specific person_id")
    group.add_argument("--find-red",  action="store_true",
                       help="Auto-find first resident with active RED alert")
    group.add_argument("--all",       action="store_true",
                       help="Run for every resident in the DB (see KNOWN LIMITATION)")
    p.add_argument("--no-alert",   action="store_true",
                   help="Dry run — skip Telegram alerts")
    p.add_argument("--skip-chroma", action="store_true",
                   help="Skip ChromaDB bootstrap check")
    p.add_argument("--agent", choices=["custom", "langgraph", "langchain"],
                   default="custom",
                   help="Which agent backend to use (default: custom)")
    return p.parse_args()


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    args = _parse_args()

    # Step 0 — ChromaDB
    if not args.skip_chroma:
        logger.info("Step 0 — checking ChromaDB …")
        _ensure_chroma()
    else:
        logger.info("Step 0 — ChromaDB check skipped (--skip-chroma)")

    # Step 1 — Resolve targets
    logger.info("Step 1 — resolving target resident(s) …")

    if args.resident:
        targets = [args.resident]
        logger.info("Target: %s (explicit)", args.resident)

    elif args.find_red:
        pid = _find_red_resident()
        if not pid:
            logger.warning(
                "No uncleared RED alerts found in active_alerts.\n"
                "Tip: verify with: sqlite3 data/carewatch.db "
                "\"SELECT * FROM active_alerts WHERE cleared_at IS NULL LIMIT 5;\""
            )
            return 1
        targets = [pid]
        logger.info("Target: %s (first active RED alert)", pid)

    else:  # --all
        targets = _all_residents()
        if not targets:
            logger.error(
                "No residents found in activity_log. "
                "Run generate_mock_data.py first."
            )
            return 1
        logger.warning(
            "--all mode: get_today() filters by today's date. "
            "Mock data is from past dates so today_logs is empty. "
            "All non-alert residents will return GREEN. "
            "See KNOWN LIMITATION in module docstring."
        )
        logger.info("Batch mode: %d residents", len(targets))

    # Step 2 — Import agent (selected via --agent flag)
    try:
        if args.agent == "langgraph":
            from src.orchestrator import CareWatchOrchestrator
            agent = CareWatchOrchestrator()
            logger.info("Using LangGraph multi-agent (CareWatchOrchestrator)")
        elif args.agent == "langchain":
            from src.langchain_agent import CareWatchLangChainAgent
            agent = CareWatchLangChainAgent()
            logger.info("Using LangChain tool-calling agent")
        else:
            from src.agent import CareWatchAgent
            agent = CareWatchAgent()
            logger.info("Using custom CareWatchAgent")
    except Exception as e:
        logger.error("Failed to import agent (--agent=%s): %s", args.agent, e)
        return 1
    send_alert = not args.no_alert

    if args.no_alert:
        logger.info("Dry run — Telegram alerts suppressed")

    # Step 3 — Run pipeline
    results = []
    errors  = 0

    for i, person_id in enumerate(targets, 1):
        if len(targets) > 1:
            logger.info(
                "Step 3 [%d/%d] — running agent for %s …",
                i, len(targets), person_id,
            )
        else:
            logger.info("Step 3 — running agent for %s …", person_id)

        try:
            result = agent.run(person_id, send_alert=send_alert)
            results.append((person_id, result))

            if result.error:
                logger.warning(
                    "Agent returned error for %s: %s",
                    person_id, result.error,
                )
                errors += 1
            else:
                logger.info(
                    "Done: %s → %s (%d/100) | concern=%s | rag=%s",
                    person_id,
                    result.risk_level,
                    result.risk_score,
                    result.ai_explanation.concern_level
                        if result.ai_explanation else "n/a",
                    result.rag_context_used,
                )

        except Exception as e:
            logger.error(
                "Unhandled exception for %s: %s",
                person_id, e, exc_info=True,
            )
            errors += 1

    # Step 4 — Print results
    logger.info("Step 4 — printing results …")
    for person_id, result in results:
        _print_result(result, person_id)

    # Summary line for batch mode
    if len(results) > 1:
        reds     = sum(1 for _, r in results if r.risk_level == "RED")
        yellows  = sum(1 for _, r in results if r.risk_level == "YELLOW")
        greens   = sum(1 for _, r in results if r.risk_level == "GREEN")
        unknowns = sum(1 for _, r in results if r.risk_level == "UNKNOWN")
        print(f"Batch complete: {len(results)} residents processed")
        print(
            f"  🟢 GREEN={greens}  🟡 YELLOW={yellows}  "
            f"🔴 RED={reds}  ❓ UNKNOWN={unknowns}"
        )
        if errors:
            print(f"  ⚠  {errors} error(s) — check logs above")
        print()

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
