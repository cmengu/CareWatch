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
            # Cache once — avoids O(n) dict rebuild on every _hybrid_retrieve call.
            self._id_to_doc: dict[str, str] = dict(zip(self._bm25_ids, self._bm25_docs))
            logger.info("BM25 index built: %d documents", len(self._bm25_docs))
        except Exception as e:
            logger.warning("BM25 index build failed (non-blocking): %s", e)
            self._bm25      = None
            self._bm25_docs = []
            self._bm25_ids  = []
            self._id_to_doc = {}

    # ─────────────────────────────────────────────────────────────────
    # RAG 2.0 — query decomposition + hybrid retrieval (4 spaces = class level)
    # ─────────────────────────────────────────────────────────────────

    # Per-anomaly semantic query map. Keys: (activity, anomaly_type).
    _QUERY_MAP: dict = {
        ("fallen",      "FALLEN"):    "fall detection emergency response hip fracture elderly",
        ("fallen",      "UNCLEARED"): "fall alert persistent uncleared caregiver response protocol",
        ("pill_taking", "MISSING"):   "missed medication elderly morning dosing window adherence",
        ("pill_taking", "TIMING"):    "medication timing deviation dosing window late",
        ("eating",      "MISSING"):   "missed meal elderly nutrition appetite loss hypoglycaemia",
        ("eating",      "TIMING"):    "eating timing unusual late meal elderly blood sugar",
        ("walking",     "MISSING"):   "reduced mobility elderly sedentary inactivity physiotherapy",
        ("walking",     "TIMING"):    "walking timing unusual night wandering fall risk",
        ("sitting",          "MISSING"):   "prolonged inactivity elderly pressure sores thrombosis",
        ("sitting",          "TIMING"):    "unusual sitting timing elderly night restlessness",
        ("lying_down",       "MISSING"):   "lying down prolonged elderly pressure ulcer circulation",
        ("lying_down",       "TIMING"):    "lying down night wandering sleep disturbance dementia",
        ("persistent_alert", "UNCLEARED"): "fall alert persistent uncleared caregiver response protocol",
    }
    _QUERY_FALLBACK: str = "elderly resident activity deviation monitoring safety"

    def _decompose_queries(self, anomalies: list) -> list[str]:
        """
        Map each dict anomaly to a domain-specific semantic query string.
        Returns a deduplicated list of query strings (one per distinct anomaly type).
        String anomalies (no-baseline path) are skipped silently.
        Returns [_QUERY_FALLBACK] if no anomalies match the query map.
        """
        queries = []
        seen = set()
        for a in anomalies:
            if not isinstance(a, dict):
                continue
            key = (a.get("activity", ""), a.get("type", ""))
            q = self._QUERY_MAP.get(key, self._QUERY_FALLBACK)
            if q not in seen:
                queries.append(q)
                seen.add(q)
        return queries if queries else [self._QUERY_FALLBACK]

    def _hybrid_retrieve(self, query: str, n: int = 3) -> list[str]:
        """
        Retrieve top-n documents using Reciprocal Rank Fusion over:
          - Dense: ChromaDB cosine similarity
          - Sparse: BM25 keyword match

        Returns list of document text strings (not IDs).
        Falls back to dense-only if self._bm25 is None.
        Never raises — returns [] on any failure.
        """
        if not self._available:
            return []

        fetch_n = min(n * 2, self.collection.count())
        if fetch_n < 1:
            return []

        try:
            # Dense retrieval
            dense_results = self.collection.query(
                query_texts=[query],
                n_results=fetch_n,
            )
            dense_ids = dense_results.get("ids", [[]])[0]

            # Sparse retrieval — skip if BM25 not available
            sparse_ids = []
            if self._bm25 is not None and self._bm25_ids:
                bm25_scores = self._bm25.get_scores(query.lower().split())
                ranked_indices = sorted(
                    range(len(bm25_scores)),
                    key=lambda i: bm25_scores[i],
                    reverse=True,
                )
                sparse_ids = [self._bm25_ids[i] for i in ranked_indices[:fetch_n]]

            # Reciprocal Rank Fusion (k=60 per original RRF paper)
            k = 60
            rrf_scores: dict[str, float] = {}
            for rank, doc_id in enumerate(dense_ids):
                rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
            for rank, doc_id in enumerate(sparse_ids):
                rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)

            top_ids = sorted(rrf_scores, key=rrf_scores.get, reverse=True)[:n]

            # Resolve IDs → text using the cached map built in _build_bm25_index()
            return [self._id_to_doc[doc_id] for doc_id in top_ids if doc_id in self._id_to_doc]

        except Exception as e:
            logger.warning("_hybrid_retrieve failed (non-blocking): %s", e)
            return []

    def get_context_v2(self, anomalies: list, n_results: int = 3) -> str:
        """
        RAG 2.0 entry point — replaces get_context() in the specialist agent path.

        Pipeline:
          1. Decompose anomalies into per-type semantic queries
          2. Retrieve top-n docs per query via hybrid dense+sparse (RRF)
          3. Deduplicate results by doc ID across all queries
          4. Rerank the merged set (stub — returns top-n as-is)
          5. Return as newline-joined string (same format as get_context())

        Returns empty string if RAG unavailable or all retrieval fails.
        Never raises.
        """
        if not self._available or not anomalies:
            return ""

        if self.collection.count() == 0:
            return ""

        try:
            queries = self._decompose_queries(anomalies)
            seen_texts: set[str] = set()
            merged_docs: list[str] = []

            for query in queries:
                docs = self._hybrid_retrieve(query, n=n_results)
                for doc in docs:
                    # Deduplicate by doc text — unique at 47 facts; will need ID-based
                    # dedup if the knowledge base grows to include near-duplicate entries.
                    if doc not in seen_texts:
                        seen_texts.add(doc)
                        merged_docs.append(doc)

            if not merged_docs:
                return ""

            reranked = self._rerank(
                query=queries[0],
                docs=merged_docs,
                top_k=n_results,
            )

            return "\n".join(reranked)

        except Exception as e:
            logger.warning("get_context_v2 failed (non-blocking): %s", e)
            return ""

    def _rerank(self, query: str, docs: list[str], top_k: int = 3) -> list[str]:
        """
        Cross-encoder reranking stub.
        Currently returns docs[:top_k] — highest-scoring from RRF merge.

        Upgrade path (one swap when cross-encoder model is available):
          from sentence_transformers import CrossEncoder
          model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
          scores = model.predict([(query, doc) for doc in docs])
          ranked = sorted(range(len(docs)), key=lambda i: scores[i], reverse=True)
          return [docs[i] for i in ranked[:top_k]]
        """
        return docs[:top_k]
