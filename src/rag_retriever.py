"""
rag_retriever.py
=================
Queries the ChromaDB knowledge base built by knowledge_base.py.
Given a list of anomaly dicts from deviation_detector, returns relevant
medical context as a plain string for the LLM to use.

Returns empty string on any failure — agent always continues without RAG.

Anomaly shape from deviation_detector.check():
- Dict path:   {"activity": str, "type": str, "message": str, "severity": str}
- String path: e.g. "No baseline built yet — need 7 days of data" (no-baseline case)
Only dict items are queried. String items are skipped silently.
"""

import json
import logging
import os

import chromadb
from groq import Groq
from pathlib import Path

logger = logging.getLogger(__name__)
DB_PATH = str(Path(__file__).parents[1] / "data" / "chroma_db")


class RAGRetriever:
    def __init__(self):
        try:
            client = chromadb.PersistentClient(path=DB_PATH)
            self.collection = client.get_collection("carewatch_knowledge")
            self._available = True
        except Exception as e:
            logger.warning("RAG not available: %s. Run: python -m src.knowledge_base", e)
            self.collection = None
            self._available = False

        # BM25 sparse index — built from the same docs as ChromaDB
        # Falls back to None if ChromaDB unavailable or rank_bm25 missing
        self._bm25:      "BM25Okapi | None" = None
        self._bm25_docs: list               = []
        self._bm25_ids:  list               = []
        if self._available:
            self._build_bm25_index()

    def get_context(self, anomalies: list, n_results: int = 3) -> str:
        """
        Given anomaly dicts (or mixed list with string items), return relevant facts.
        String anomalies (e.g. "No baseline built yet") are skipped silently.
        Returns empty string if RAG unavailable, collection empty, or query fails.
        """
        if not self._available or not anomalies:
            return ""

        # Guard 2: empty collection causes ValueError in ChromaDB query
        if self.collection.count() == 0:
            return ""

        # Guard 3: skip string anomalies — only process dicts
        query_terms = " ".join([
            a.get("activity", "") + " " + a.get("type", "")
            for a in anomalies
            if isinstance(a, dict)
        ]).strip()

        if not query_terms:
            return ""

        try:
            results = self.collection.query(
                query_texts=[query_terms],
                n_results=min(n_results, self.collection.count()),
            )
            docs = results.get("documents", [[]])[0]
            return "\n".join(docs)
        except Exception as e:
            logger.warning("RAG query failed: %s", e)
            return ""

    def _score_relevance(self, context: str, anomalies: list) -> float:
        """
        Score how relevant the retrieved context is to the current anomalies.
        Returns float 0.0–1.0. Never raises — returns 1.0 on any failure so
        scoring never suppresses valid context on error.

        Only called when context is non-empty.
        """
        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not api_key:
            return 1.0  # no key — skip scoring, pass context through

        clean_anomalies = [a for a in anomalies if isinstance(a, dict)]
        if not clean_anomalies:
            return 1.0  # no dict anomalies to score against

        try:
            client = Groq(api_key=api_key)
            prompt = f"""You are a relevance checker for a medical monitoring system.

Rate how relevant the following retrieved medical context is to the detected anomalies.

Return ONLY valid JSON with exactly this structure:
{{
  "score": 0.0 to 1.0,
  "reason": "one sentence"
}}

Where:
- 1.0 = highly relevant, directly addresses the detected issues
- 0.5 = partially relevant, tangentially related
- 0.0 = not relevant, completely unrelated to the anomalies

Detected anomalies:
{json.dumps(clean_anomalies)}

Retrieved context:
{context[:1000]}

JSON only. No markdown. No extra text."""

            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.0,
            )
            raw = response.choices[0].message.content.strip()

            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            # Find the JSON object if model added prose around it
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start != -1 and end > start:
                raw = raw[start:end]

            result = json.loads(raw)
            score = float(result.get("score", 1.0))
            score = max(0.0, min(1.0, score))  # clamp to valid range
            logger.info("RAG relevance score: %.2f — %s", score, result.get("reason", ""))
            return score

        except Exception as e:
            logger.warning("Relevance scoring failed (non-blocking): %s", e)
            return 1.0

    def _build_bm25_index(self) -> None:
        """
        Build BM25 sparse retrieval index over all ChromaDB documents.
        Called once in __init__ when ChromaDB is available.
        Populates self._bm25, self._bm25_docs, self._bm25_ids.
        Fails silently — BM25 is an enhancement, not a hard requirement.
        """
        try:
            from rank_bm25 import BM25Okapi
            all_data = self.collection.get(include=["documents"])  # ids are always returned
            self._bm25_docs = all_data.get("documents", [])
            self._bm25_ids  = all_data.get("ids", [])
            if not self._bm25_docs:
                logger.warning("BM25 index: no documents found in collection")
                return
            corpus = [doc.lower().split() for doc in self._bm25_docs]
            self._bm25 = BM25Okapi(corpus)
            logger.info("BM25 index built: %d documents", len(self._bm25_docs))
        except Exception as e:
            logger.warning("BM25 index build failed (non-blocking): %s", e)
            self._bm25      = None
            self._bm25_docs = []
            self._bm25_ids  = []
