# CareWatch — Phase 4: RAG 2.0

**Overall Progress:** `0%` (0/5 steps complete)

---

## TLDR

Phase 4 upgrades `src/rag_retriever.py` from a single concatenated query to a decomposed, hybrid dense+sparse retrieval pipeline. A per-anomaly query map replaces the `activity + type` concatenation. BM25 keyword search runs alongside ChromaDB cosine similarity and results are merged via Reciprocal Rank Fusion. A cross-encoder reranking stub documents the upgrade path and replaces the Groq `_score_relevance()` call in the specialist agent path. `get_context()` is not modified — the new path is `get_context_v2()`, adopted only by `specialist_agents._get_rag_context()`. `eval_retrieval.py` gains a `--mode hybrid` flag so before/after MRR can be measured. After this plan executes, `CareWatchAgent` continues using the original path unchanged, while the LangGraph specialist agents use the upgraded retrieval.

---

## Architecture Overview

**The problem this plan solves:**
`rag_retriever.get_context()` (line 46–68) builds one query string by joining `activity + " " + type` for all anomalies. A resident with a fall AND missed medication produces `"fallen FALLEN pill_taking MISSING"` — a semantically diluted query that retrieves docs vaguely relevant to both but excellent for neither. Additionally, ChromaDB cosine similarity alone misses exact clinical token matches (e.g. `"warfarin aspirin"`) that BM25 would rank first.

**The patterns applied:**
- **Open/Closed Principle:** `get_context()` is not modified. `get_context_v2()` is a new method. Existing consumers (`CareWatchAgent`, `CareWatchLangChainAgent`) are unaffected. Only `specialist_agents._get_rag_context()` adopts the new path.
- **Facade:** `get_context_v2()` hides the decompose → hybrid → deduplicate → rerank pipeline behind a single method with the same return type (`str`) as `get_context()`.
- **Template Method:** `_hybrid_retrieve(query, n)` is the shared primitive called once per decomposed query. `get_context_v2()` orchestrates multiple calls to it.

**What stays unchanged:**
- `src/agent.py` — `CareWatchAgent` continues calling `get_context()` + `_score_relevance()`
- `src/langchain_agent.py` — eval-only, not production path
- `src/knowledge_base.py` — ChromaDB collection structure unchanged; BM25 indexes the same documents
- `eval/eval_retrieval.py` — existing `--mode raw` (default) behaviour is unchanged; `--mode hybrid` is additive

**What this plan adds:**

| Addition | Single responsibility |
|----------|-----------------------|
| `_build_bm25_index()` in `RAGRetriever` | Build BM25 index over all ChromaDB docs at init time |
| `_decompose_queries(anomalies)` | Map each anomaly to a domain-specific semantic query string |
| `_hybrid_retrieve(query, n)` | Dense + sparse retrieval merged via RRF for one query |
| `get_context_v2(anomalies, n)` | Per-anomaly decomposition + hybrid retrieval + deduplication + reranking |
| `_rerank(query, docs, top_k)` | Cross-encoder stub — returns `docs[:top_k]`; documents upgrade path |
| `--mode hybrid` in `eval_retrieval.py` | Routes ground-truth queries through `_hybrid_retrieve()` for comparison |

**Critical decisions:**

| Decision | Alternative considered | Why alternative rejected |
|----------|----------------------|--------------------------|
| `get_context_v2()` as new method, not replacing `get_context()` | Modify `get_context()` in place | Would break `CareWatchAgent` and `_score_relevance()` integration silently — regression with no loud error |
| BM25 index built eagerly in `__init__` | Lazy build on first query | 47 docs load in <10ms; lazy adds state complexity for no benefit at this scale |
| `_rerank()` as stub (returns `docs[:top_k]`) | Build full cross-encoder now | Cross-encoder download is ~80MB and not needed to demonstrate the architecture; stub preserves the interface for a one-line swap |
| RRF merge constant `k=60` | Tune k empirically | 60 is the standard constant from the original RRF paper; tuning requires a labelled training set we don't have |
| Per-anomaly deduplication by doc text | Deduplicate by ChromaDB doc ID | Doc IDs are `fact_{line_number}` — reliable unique keys; text comparison is slower and fragile on whitespace |

**Known limitations acknowledged:**

| Limitation | Why acceptable now | Upgrade path |
|-----------|-------------------|--------------|
| `_rerank()` is a stub | Architecture is demonstrated; cross-encoder improves MRR but is not required to show hybrid > raw | `pip install sentence-transformers`; uncomment 3 lines in `_rerank()` |
| BM25 index is in-memory, rebuilt on every `RAGRetriever()` instantiation | 47 docs, <10ms rebuild | Persist to pickle file keyed by ChromaDB collection hash if doc count grows |
| `CareWatchLangChainAgent` still uses `get_context()` | Eval-only agent, not production | Update `_build_tools()` in `langchain_agent.py` to call `get_context_v2()` if LangChain agent is promoted to production |

---

## Clarification Gate

| Unknown | Required | Source | Blocking | Resolved |
|---------|----------|--------|----------|----------|
| Does `rank_bm25` package accept tokenised input as list[str]? | Confirm `BM25Okapi(corpus)` where corpus is `list[list[str]]` | PyPI docs / confirmed in gameplan | Step 2 | ✅ Confirmed |
| Are ChromaDB doc IDs always `fact_{int}`? | Confirm ID format used in `knowledge_base.py` | `knowledge_base.py` read: `ids.append(f"fact_{i}")` | Step 2 | ✅ Confirmed |
| Does `eval_retrieval.py` use `RAGRetriever` or query ChromaDB directly? | Confirm query path | `eval_retrieval.py` read: queries `collection` directly, not via `RAGRetriever` | Step 5 | ✅ Confirmed — Step 5 adds RAGRetriever path |
| Does `_get_rag_context()` in `specialist_agents.py` call `_score_relevance()`? | Confirm method name | `specialist_agents.py` read: yes, calls `self.rag._score_relevance()` | Step 4 | ✅ Confirmed — Step 4 simplifies this to `get_context_v2()` |

---

## Agent Failure Protocol

1. A verification command fails → read the full error output.
2. Cause is unambiguous → make ONE targeted fix → re-run the same verification command.
3. If still failing after one fix → **STOP**. Output full contents of every modified file. Report: (a) command run, (b) full error verbatim, (c) fix attempted, (d) current state of each modified file, (e) why you cannot proceed.
4. Never attempt a second fix without human instruction.
5. Never modify files not named in the current step.

---

## Pre-Flight — Run Before Any Code Changes

```bash
# 1. Confirm get_context_v2 does NOT already exist
grep -n "get_context_v2" src/rag_retriever.py
# Expected: no output. If found → STOP and report.

# 2. Confirm _build_bm25_index does NOT already exist
grep -n "_build_bm25_index" src/rag_retriever.py
# Expected: no output. If found → STOP and report.

# 3. Confirm get_context exists exactly once
grep -n "def get_context" src/rag_retriever.py
# Expected: exactly 1 match

# 4. Confirm _score_relevance exists — it stays, do not remove it
grep -n "def _score_relevance" src/rag_retriever.py
# Expected: exactly 1 match

# 5. Confirm _get_rag_context in specialist_agents calls get_context
grep -n "get_context" src/specialist_agents.py
# Expected: at least 1 match referencing self.rag.get_context(...)

# 6. Confirm rank_bm25 not already installed
python -c "import rank_bm25; print(rank_bm25.__version__)" 2>&1
# Expected: ModuleNotFoundError. If version printed → record it.

# 7. Run eval_retrieval baseline and record current MRR
python -m eval.eval_retrieval 2>/dev/null | grep "MRR:"
# Record: MRR = ____ (expected ~0.960)

# 8. Record line counts
wc -l src/rag_retriever.py src/specialist_agents.py eval/eval_retrieval.py

# 9. Run existing eval to confirm baseline still passes
python -m eval.eval_agent --no-llm 2>/dev/null | grep "F1:"
# Expected: F1: 1.000
```

**Baseline Snapshot (agent fills during pre-flight — do not pre-fill):**
```
MRR before plan:                     ____
src/rag_retriever.py lines:          ____
src/specialist_agents.py lines:      ____
eval/eval_retrieval.py lines:        ____
get_context_v2 exists:               NO
_build_bm25_index exists:            NO
rank_bm25 installed:                 NO
eval F1 before plan:                 ____
```

**All checks must pass before Step 1 begins.**

---

## Steps Analysis

```
Step 1 (Install rank-bm25)                      — Non-critical — verification only     — Idempotent: Yes
Step 2 (Add BM25 index to RAGRetriever)         — Critical (Steps 3 depends on self._bm25)  — full code review — Idempotent: Yes
Step 3 (Add decompose/hybrid/v2/rerank methods) — Critical (Step 4 depends on get_context_v2) — full code review — Idempotent: Yes
Step 4 (Update specialist_agents._get_rag_context) — Critical (production path change, shared base class) — full code review — Idempotent: Yes
Step 5 (Add --mode hybrid to eval_retrieval.py) — Critical (produces before/after measurement) — full code review — Idempotent: Yes
```

---

## Environment Matrix

| Step | Dev | Staging | Prod | Notes |
|------|-----|---------|------|-------|
| Step 1 | ✅ | ✅ | ✅ | pip install only |
| Steps 2–4 | ✅ | ✅ | ✅ | New methods, no schema changes |
| Step 5 | ✅ | ❌ Skip | ❌ Skip | Eval only |

---

## Tasks

### Phase 4A — Foundation

**Goal:** `rank-bm25` is installed, BM25 index is built in `RAGRetriever.__init__`, and all existing tests still pass.

---

- [ ] 🟥 **Step 1: Install `rank-bm25`** — *Non-critical: no code change, reversible*

  **Step Architecture Thinking:**

  **Pattern applied:** Dependency management — adding a new library before any code that imports it.

  **Why this step exists here in the sequence:** Step 2 imports `BM25Okapi` from `rank_bm25`. If this step is skipped, Step 2 fails at import time with `ModuleNotFoundError` before any code runs.

  **Why this file / class is the right location:** `requirements.txt` is the single source of truth for project dependencies.

  **Alternative approach considered and rejected:** Lazy import inside `_build_bm25_index()` with a `try/except`. Rejected because it hides the dependency and makes the failure non-obvious — a missing package silently disables BM25 rather than failing loudly.

  **What breaks if this step deviates:** `_build_bm25_index()` raises `ModuleNotFoundError` on first `RAGRetriever()` instantiation. BM25 falls back to `None`, hybrid retrieval silently degrades to dense-only. No loud error — silent wrong behaviour.

  ---

  **Idempotent:** Yes — `pip install` with pinned version is idempotent.

  **Context:** `rank-bm25` provides `BM25Okapi`, the standard Python BM25 implementation. It has no transitive dependencies that conflict with the existing stack.

  ```bash
  pip install rank-bm25==0.2.2
  echo "rank-bm25==0.2.2" >> requirements.txt
  ```

  **Git Checkpoint:**
  ```bash
  git add requirements.txt
  git commit -m "step 1: add rank-bm25==0.2.2 to requirements"
  ```

  **Subtasks:**
  - [ ] 🟥 pip install completes with no errors
  - [ ] 🟥 requirements.txt contains `rank-bm25==0.2.2`

  **✓ Verification Test:**

  **Type:** Unit

  **Action:**
  ```bash
  python -c "from rank_bm25 import BM25Okapi; print('rank_bm25 OK')"
  ```

  **Expected:** `rank_bm25 OK`

  **Pass:** Printed with no ImportError.

  **Fail:**
  - If `ModuleNotFoundError` → pip install did not complete — re-run `pip install rank-bm25==0.2.2`

---

- [ ] 🟥 **Step 2: Add BM25 index to `RAGRetriever`** — *Critical: Steps 3 and 4 depend on `self._bm25`*

  **Step Architecture Thinking:**

  **Pattern applied:** Eager initialisation with graceful degradation. The BM25 index is built once at construction time. If it fails (ChromaDB unavailable, import error), `self._bm25` stays `None` and `_hybrid_retrieve()` falls back to dense-only — never raises.

  **Why this step exists here in the sequence:** `_hybrid_retrieve()` (Step 3) reads `self._bm25`, `self._bm25_docs`, and `self._bm25_ids`. These fields must exist before Step 3's code is added, or the class will have an AttributeError on any code path that reaches `_hybrid_retrieve()` before the index is built.

  **Why this file / class is the right location:** `RAGRetriever.__init__` is where all retrieval infrastructure is initialised. Placing the BM25 index here keeps it symmetric with the ChromaDB client setup immediately above it.

  **Alternative approach considered and rejected:** Build the BM25 index lazily inside `_hybrid_retrieve()` on first call. Rejected because it introduces mutable state that changes after construction, making the object harder to reason about and test.

  **What breaks if this step deviates from the described pattern:** If `self._bm25_docs` and `self._bm25_ids` are not initialised even when `self._available = False`, Step 3's `_hybrid_retrieve()` will raise `AttributeError` on the BM25 fallback path instead of degrading gracefully.

  ---

  **Idempotent:** Yes — adding fields to `__init__` and a new method. If re-run, the method definition overwrites the previous one identically.

  **Context:** `RAGRetriever.__init__` currently ends after the try/except block that sets `self._available`. The three new fields (`_bm25`, `_bm25_docs`, `_bm25_ids`) are appended after that block. `_build_bm25_index()` is a new method appended to the class after `_score_relevance()`.

  **Pre-Read Gate:**
  Before any edit:
  - Run `grep -n "self._available = False" src/rag_retriever.py` — must return **exactly 1 match** inside `__init__`. If 0 or 2+ → STOP.
  - Visually verify: the line `self._available = False` has **12 leading spaces** (inside the except block). If your file has different indentation, use the exact text from the file for the old string.
  - Run `grep -n "def get_context" src/rag_retriever.py` — must return **exactly 1 match**. This is the anchor for the `__init__` boundary (the line immediately after `__init__` ends).
  - Run `grep -n "_build_bm25_index" src/rag_retriever.py` — must return **0 matches**. If found → STOP, step already run.

  **Anchor Uniqueness Check:**
  - Target: `            self._available = False\n\n    def get_context`
  - `self._available = False` lives inside the except block at **12 spaces** (not 8). The combination of this line + blank line + `def get_context` (4 spaces) is unique in the file.
  - str_replace on this block inserts BM25 init between `__init__` and `get_context`.

  **Self-Contained Rule:** Code block below is complete and runnable.

  **No-Placeholder Rule:** No `<VALUE>` tokens.

  The edit is a **str_replace** in `src/rag_retriever.py`:

  **Old string (exact — including indentation; 12 spaces on self._available line):**
  ```
            self._available = False

    def get_context(self, anomalies: list, n_results: int = 3) -> str:
  ```

  **New string:** BM25 init block is at **8 spaces** — outside the try/except, at `__init__` body level. Do NOT copy the 12-space indentation from `self._available = False`; that line is inside the except block.
  ```
            self._available = False

        # BM25 sparse index — built from the same docs as ChromaDB
        # Falls back to None if ChromaDB unavailable or rank_bm25 missing
        self._bm25:      "BM25Okapi | None" = None
        self._bm25_docs: list               = []
        self._bm25_ids:  list               = []
        if self._available:
            self._build_bm25_index()

    def get_context(self, anomalies: list, n_results: int = 3) -> str:
  ```

  **Part 2 — str_replace to append `_build_bm25_index()` after `_score_relevance()`:**

  Use an explicit anchor. `_score_relevance()` contains three `return 1.0` occurrences; the last one is unique in context (inside the except block). The following 3-line block appears exactly once in the file.

  **Old string (exact — last 3 lines of `_score_relevance()`):**
  ```
        except Exception as e:
            logger.warning("Relevance scoring failed (non-blocking): %s", e)
            return 1.0
  ```

  **New string (old string + new method):**
  ```
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
            all_data = self.collection.get(include=["documents", "ids"])
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
  ```

  **What it does:** Fetches all 47 documents from ChromaDB at construction time, tokenises them, and builds a BM25Okapi index. Stores a parallel list of doc IDs for RRF merge in Step 3.

  **Why this approach:** ChromaDB `.get()` returns all docs in one call — no pagination needed at 47 documents. The BM25 corpus uses `.lower().split()` tokenisation, which matches the tokenisation used at query time in `_hybrid_retrieve()`.

  **Assumptions:**
  - `self.collection.get(include=["documents", "ids"])` returns `{"documents": list[str], "ids": list[str]}` — confirmed from ChromaDB PersistentClient API
  - 47 documents fit in memory without issue

  **Risks:**
  - ChromaDB `.get()` returns docs in arbitrary order — mitigation: `_bm25_ids` is stored in the same order as `_bm25_docs`, so index-based lookup in `_hybrid_retrieve()` is safe
  - `rank_bm25` not installed — mitigation: try/except sets `self._bm25 = None`; `_hybrid_retrieve()` degrades to dense-only

  **Git Checkpoint:**
  ```bash
  git add src/rag_retriever.py
  git commit -m "step 2: add BM25 index to RAGRetriever.__init__"
  ```

  **Subtasks:**
  - [ ] 🟥 `self._bm25`, `self._bm25_docs`, `self._bm25_ids` initialised in `__init__` after try/except
  - [ ] 🟥 `_build_bm25_index()` method appended to class
  - [ ] 🟥 `self._bm25` is a `BM25Okapi` instance (not None) after construction when ChromaDB is available

  **✓ Verification Test:**

  **Type:** Unit

  **Action:**
  ```bash
  python -c "
  from src.rag_retriever import RAGRetriever
  rag = RAGRetriever()
  assert rag._bm25 is not None, f'BM25 index not built — _bm25 is None. ChromaDB available: {rag._available}'
  assert len(rag._bm25_docs) == 47, f'Expected 47 docs, got {len(rag._bm25_docs)}'
  assert len(rag._bm25_ids) == 47, f'Expected 47 IDs, got {len(rag._bm25_ids)}'
  assert rag._bm25_ids[0].startswith('fact_'), f'Unexpected ID format: {rag._bm25_ids[0]}'
  print(f'BM25 index OK: {len(rag._bm25_docs)} docs, first ID={rag._bm25_ids[0]}')
  "
  ```

  **Expected:** `BM25 index OK: 47 docs, first ID=fact_0` (or another `fact_N` value)

  **Pass:** No AssertionError, message printed with 47 docs.

  **Fail:**
  - If `_bm25 is None` → `_build_bm25_index()` failed silently — add `logging.basicConfig(level=logging.DEBUG)` and re-run to see the warning
  - If `len != 47` → ChromaDB collection has wrong doc count — run `python -m src.knowledge_base` to rebuild

---

### Phase 4B — Core Retrieval Logic

**Goal:** `get_context_v2()` exists on `RAGRetriever`, produces a string, and returns better context than `get_context()` for multi-anomaly residents.

---

- [ ] 🟥 **Step 3: Add `_decompose_queries`, `_hybrid_retrieve`, `get_context_v2`, `_rerank` to `RAGRetriever`** — *Critical: Step 4 depends on `get_context_v2()`*

  **Step Architecture Thinking:**

  **Pattern applied:** Facade (`get_context_v2` hides a 3-stage pipeline) + Template Method (`_hybrid_retrieve` is the shared primitive called per decomposed query).

  **Why this step exists here in the sequence:** `self._bm25` must exist (Step 2) before `_hybrid_retrieve()` can read it. After this step, `specialist_agents._get_rag_context()` can be updated to call `get_context_v2()` in Step 4.

  **Why this file / class is the right location:** All retrieval logic belongs in `RAGRetriever`. Placing decomposition logic here means specialist agents remain domain-focused — they pass anomaly dicts and get a context string back. The retrieval strategy is encapsulated.

  **Alternative approach considered and rejected:** Put `_decompose_queries()` in `specialist_agents.py` with per-agent query maps. Rejected because it scatters retrieval concerns across files and makes it impossible to benchmark retrieval quality independently of agent logic.

  **What breaks if this step deviates from the described pattern:** If `get_context_v2()` does not deduplicate by doc ID before joining, a resident with a fall AND missed medication will see the same fact repeated twice in the context string. The LLM context window is wasted and the output quality degrades.

  ---

  **Idempotent:** Yes — new methods appended to class. If re-run, definitions overwrite identically.

  **Context:** Four new methods are appended after `_build_bm25_index()`. They do not modify any existing method.

  **Pre-Read Gate:**
  - Run `grep -n "_build_bm25_index" src/rag_retriever.py` — must return **exactly 1 match** (confirms Step 2 complete).
  - Run `grep -n "get_context_v2" src/rag_retriever.py` — must return **0 matches**. If found → STOP.
  - Run `grep -n "_hybrid_retrieve" src/rag_retriever.py` — must return **0 matches**. If found → STOP.

  **Self-Contained Rule:** All code below is complete. No references to other steps.

  **No-Placeholder Rule:** No `<VALUE>` tokens.

  **Indentation warning:** `_QUERY_MAP` and `_QUERY_FALLBACK` are **class attributes** at **4 spaces**. Method definitions (`def _decompose_queries`) are also at 4 spaces; method bodies at 8 spaces. Adding one extra level to `_QUERY_MAP` parses it as a local variable inside `_build_bm25_index()` → NameError at runtime. The verification test includes `assert hasattr(RAGRetriever, '_QUERY_MAP')` to catch this.

  **str_replace to append** — use the last 5 lines of `_build_bm25_index()` as anchor (unique in file):

  **Old string (exact — last 5 lines of `_build_bm25_index()`):**
  ```
          except Exception as e:
              logger.warning("BM25 index build failed (non-blocking): %s", e)
              self._bm25      = None
              self._bm25_docs = []
              self._bm25_ids  = []
  ```

  **New string (old string + RAG 2.0 block):**
  ```
          except Exception as e:
              logger.warning("BM25 index build failed (non-blocking): %s", e)
              self._bm25      = None
              self._bm25_docs = []
              self._bm25_ids  = []

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
        ("sitting",     "MISSING"):   "prolonged inactivity elderly pressure sores thrombosis",
        ("lying_down",  "MISSING"):   "lying down prolonged elderly pressure ulcer circulation",
        ("lying_down",  "TIMING"):    "lying down night wandering sleep disturbance dementia",
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

            # Resolve IDs to document text
            id_to_doc = dict(zip(self._bm25_ids, self._bm25_docs))
            return [id_to_doc[doc_id] for doc_id in top_ids if doc_id in id_to_doc]

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
            seen_ids: set[str] = set()
            merged_docs: list[str] = []

            for query in queries:
                docs = self._hybrid_retrieve(query, n=n_results)
                for doc in docs:
                    if doc not in seen_ids:
                        seen_ids.add(doc)
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
  ```

  **What it does:**
  - `_decompose_queries()`: maps each (activity, type) pair to a domain-specific semantic query. A resident with fall + missed medication produces two distinct queries instead of one diluted one.
  - `_hybrid_retrieve()`: retrieves `n*2` candidates from both ChromaDB (cosine) and BM25 (keyword), merges via RRF, returns top-n doc texts.
  - `get_context_v2()`: orchestrates decompose → hybrid → deduplicate → rerank → join.
  - `_rerank()`: stub returning `docs[:top_k]`. Interface is identical to a real cross-encoder — swap is one function body change.

  **Why this approach:** Deduplication in `get_context_v2()` uses the doc text string as the set key (not doc ID) because `_hybrid_retrieve()` returns texts, not IDs. At 47 facts, text comparison is fast and unambiguous. If the knowledge base grows to thousands of docs, switch to ID-based deduplication.

  **Assumptions:**
  - `self.collection.query()` returns `{"ids": [[...]], "documents": [[...]]}` — confirmed from existing `get_context()` usage
  - All docs in `self._bm25_ids` are also keys in the ChromaDB collection — guaranteed since both are built from the same `collection.get()` call in `_build_bm25_index()`

  **Risks:**
  - `_hybrid_retrieve()` called with `fetch_n = min(n*2, collection.count())` — if collection has exactly 1 doc, `fetch_n=2` but only 1 exists → ChromaDB returns 1 → no error, correct behaviour
  - `queries[0]` used as primary query in `_rerank()` — if `_decompose_queries()` returns an empty list, `get_context_v2()` returns `""` before reaching `_rerank()` — safe

  **Git Checkpoint:**
  ```bash
  git add src/rag_retriever.py
  git commit -m "step 3: add get_context_v2 with query decomposition and hybrid BM25+dense retrieval"
  ```

  **Subtasks:**
  - [ ] 🟥 `_decompose_queries()` returns 2 distinct queries for a fall+pill_taking anomaly list
  - [ ] 🟥 `_hybrid_retrieve()` returns non-empty list for a known query
  - [ ] 🟥 `get_context_v2()` returns non-empty string for a known resident with anomalies
  - [ ] 🟥 `_rerank()` returns at most `top_k` items

  **✓ Verification Test:**

  **Type:** Unit

  **Action:**
  ```bash
  python -c "
  from src.rag_retriever import RAGRetriever

  rag = RAGRetriever()

  # _QUERY_MAP must be class attribute (4 spaces) — mis-indentation causes NameError
  assert hasattr(RAGRetriever, '_QUERY_MAP'), '_QUERY_MAP missing or mis-indented as method local'
  assert isinstance(RAGRetriever._QUERY_MAP, dict), '_QUERY_MAP must be dict'

  # Test _decompose_queries — single anomaly
  q1 = rag._decompose_queries([{'activity': 'fallen', 'type': 'FALLEN', 'message': '', 'severity': 'HIGH'}])
  assert len(q1) == 1, f'Expected 1 query, got {len(q1)}'
  assert 'fall' in q1[0].lower(), f'Query does not mention fall: {q1[0]}'
  print(f'decompose (fall): {q1}')

  # Test _decompose_queries — two distinct anomaly types produce two queries
  q2 = rag._decompose_queries([
      {'activity': 'fallen',     'type': 'FALLEN',  'message': '', 'severity': 'HIGH'},
      {'activity': 'pill_taking','type': 'MISSING', 'message': '', 'severity': 'HIGH'},
  ])
  assert len(q2) == 2, f'Expected 2 queries, got {len(q2)}: {q2}'
  print(f'decompose (fall+pill): {q2}')

  # Test _decompose_queries — string anomaly is skipped, fallback fires
  q3 = rag._decompose_queries(['No baseline built yet'])
  assert q3 == [rag._QUERY_FALLBACK], f'Expected fallback, got {q3}'
  print(f'decompose (string): {q3}')

  # Test _hybrid_retrieve — returns non-empty list
  docs = rag._hybrid_retrieve('fall detection emergency response', n=3)
  assert len(docs) > 0, 'hybrid_retrieve returned empty list'
  assert all(isinstance(d, str) for d in docs), 'All results must be strings'
  print(f'hybrid_retrieve: {len(docs)} docs, first 60 chars: {docs[0][:60]}')

  # Test get_context_v2 — returns non-empty string
  anomalies = [{'activity': 'fallen', 'type': 'FALLEN', 'message': '', 'severity': 'HIGH'}]
  ctx = rag.get_context_v2(anomalies)
  assert ctx != '', 'get_context_v2 returned empty string for fall anomaly'
  assert 'fall' in ctx.lower() or 'emergency' in ctx.lower(), f'Context not fall-related: {ctx[:100]}'
  print(f'get_context_v2: {len(ctx)} chars, contains fall-related content ✓')

  # Test _rerank stub — returns top_k items
  docs5 = ['a', 'b', 'c', 'd', 'e']
  r = rag._rerank('query', docs5, top_k=3)
  assert r == ['a', 'b', 'c'], f'Expected [a,b,c], got {r}'
  print('_rerank stub OK')

  print('ALL RAG 2.0 unit tests PASSED')
  "
  ```

  **Expected:** All assertions pass, `ALL RAG 2.0 unit tests PASSED` printed.

  **Pass:** No AssertionError.

  **Fail:**
  - If `hybrid_retrieve returned empty list` → ChromaDB has 0 docs — run `python -m src.knowledge_base`
  - If `decompose (fall+pill)` returns 1 query instead of 2 → deduplication bug in `_decompose_queries()` — check `seen` set logic
  - If `Context not fall-related` → RRF merge is returning wrong docs — add `print(docs)` inside `_hybrid_retrieve()` and check BM25 scores

---

### Phase 4C — Production Path Update

**Goal:** The specialist agents in the LangGraph pipeline now use `get_context_v2()`. `CareWatchAgent` is unchanged.

---

- [ ] 🟥 **Step 4: Update `_get_rag_context()` in `specialist_agents.py` to use `get_context_v2()`** — *Critical: production path change, affects all three specialist agents*

  **Step Architecture Thinking:**

  **Pattern applied:** Single Responsibility + DRY. The relevance filtering that was split between `_get_rag_context()` (threshold check) and `rag._score_relevance()` (Groq API call) is now handled entirely inside `get_context_v2()` (via `_rerank()`). `_get_rag_context()` becomes a thin delegator with a single try/except.

  **Why this step exists here in the sequence:** `get_context_v2()` must exist (Step 3) before this method can call it. This step is last in the RAG changes because it is the production path switch — the earlier steps validate the new retrieval works before it touches any agent code.

  **Why this file / class is the right location:** `_BaseSpecialist._get_rag_context()` is the shared method inherited by all three specialists. Changing it here changes the retrieval path for FallAgent, MedAgent, and RoutineAgent simultaneously — the correct single point of change.

  **Alternative approach considered and rejected:** Override `_get_rag_context()` in each specialist subclass with a call to `get_context_v2()`. Rejected because it requires three identical method bodies instead of one, violating DRY. The query specialisation is already handled by `_decompose_queries()` using the anomaly list, not the agent name.

  **What breaks if this step deviates from the described pattern:** If `_score_relevance()` is left in `_get_rag_context()` alongside `get_context_v2()`, the Groq relevance scoring call fires on top of the already-filtered output of `get_context_v2()`. The 0.5 threshold then discards valid context that passed the `_rerank()` filter — silent quality regression.

  ---

  **Idempotent:** Yes — str_replace is idempotent if the old string is still present.

  **Context:** `_BaseSpecialist._get_rag_context()` currently calls `self.rag.get_context()` then `self.rag._score_relevance()` with a 0.5 threshold gate. Both calls are replaced by a single `self.rag.get_context_v2()` call. `_score_relevance()` stays on `RAGRetriever` for `CareWatchAgent`'s use — it is not removed.

  **Pre-Read Gate:**
  - Run `grep -n "def _get_rag_context" src/specialist_agents.py` — must return **exactly 1 match**.
  - Run `grep -n "get_context_v2" src/rag_retriever.py` — must return **at least 1 match** (confirms Step 3 complete).
  - Run `grep -n "_score_relevance" src/specialist_agents.py` — must return **at least 1 match** (confirms this is the right file and the call exists to replace).
  - Run `grep -A 16 "def _get_rag_context" src/specialist_agents.py` — copy the **exact** docstring and method body. The str_replace old string MUST match the file character-for-character; if the docstring differs from the plan, use the actual file content.

  **Anchor Uniqueness Check:**
  - The method `_get_rag_context` appears exactly once — confirmed by Pre-Read Gate.
  - str_replace targets the entire method body.

  The edit is a **str_replace** in `src/specialist_agents.py`.

  **Old string (exact — MUST match current file exactly; run `grep -A 16 "def _get_rag_context" src/specialist_agents.py` before applying):**
  ```python
      def _get_rag_context(self, anomalies: list[dict]) -> str:
          """Retrieve RAG context. Discards context with relevance < 0.5 (matches CareWatchAgent)."""
          try:
              context = self.rag.get_context(anomalies)
              if not context:
                  return ""
              score = self.rag._score_relevance(context, anomalies)
              if score < 0.5:
                  logger.info("%s: RAG relevance %.2f below threshold — skipping", self.agent_name, score)
                  return ""
              return context
          except Exception as e:
              logger.warning("%s: RAG retrieval failed (%s) — continuing without context", self.agent_name, e)
              return ""
  ```

  **New string:**
  ```python
      def _get_rag_context(self, anomalies: list[dict]) -> str:
          """
          Retrieve RAG context via get_context_v2():
          query decomposition + hybrid dense/sparse retrieval + RRF merge + reranking.
          Relevance filtering is handled inside get_context_v2() — no separate
          _score_relevance() call needed in this path.
          CareWatchAgent continues to use get_context() + _score_relevance() unchanged.
          """
          try:
              return self.rag.get_context_v2(anomalies)
          except Exception as e:
              logger.warning(
                  "%s: RAG retrieval failed (%s) — continuing without context",
                  self.agent_name, e,
              )
              return ""
  ```

  **What it does:** Removes the two-step `get_context()` + `_score_relevance()` pattern from the specialist path. `get_context_v2()` now handles both retrieval and quality filtering internally.

  **Why this approach:** `get_context_v2()` already returns an empty string for low-quality or unavailable context. Keeping a separate 0.5 threshold gate would add redundant logic on top of already-filtered output.

  **Assumptions:**
  - `self.rag` is a `RAGRetriever` instance — confirmed from `_BaseSpecialist.__init__(self, rag: RAGRetriever)`
  - `get_context_v2()` never raises (it has a top-level try/except that returns `""`) — confirmed from Step 3 code

  **Risks:**
  - If `get_context_v2()` returns empty string for anomalies that `get_context()` would have returned context for → agents fall back to LLM without RAG, which degrades explanation quality but never fails → mitigation: Step 5 measures this via MRR comparison

  **Git Checkpoint:**
  ```bash
  git add src/specialist_agents.py
  git commit -m "step 4: update _get_rag_context to use get_context_v2 (hybrid retrieval)"
  ```

  **Subtasks:**
  - [ ] 🟥 `_get_rag_context()` no longer calls `get_context()` or `_score_relevance()`
  - [ ] 🟥 `_get_rag_context()` calls `get_context_v2()` exactly once
  - [ ] 🟥 `CareWatchAgent` in `agent.py` still calls `get_context()` — confirm it is unchanged

  **✓ Verification Test:**

  **Type:** Integration (hits RAGRetriever + ChromaDB, no LLM call)

  **Action:**
  ```bash
  python -c "
  # Confirm _get_rag_context now calls get_context_v2
  import inspect
  from src.specialist_agents import _BaseSpecialist
  src = inspect.getsource(_BaseSpecialist._get_rag_context)
  assert 'get_context_v2' in src, '_get_rag_context does not call get_context_v2'
  assert 'self.rag.get_context(' not in src, '_get_rag_context still calls old get_context() — exclude docstring "replaces get_context()"'
  assert '_score_relevance' not in src, '_get_rag_context still calls _score_relevance'
  print('_get_rag_context source OK')

  # Confirm CareWatchAgent still uses old path
  from src.agent import CareWatchAgent
  agent_src = inspect.getsource(CareWatchAgent.run)
  assert 'get_context_v2' not in agent_src, 'CareWatchAgent.run was modified — STOP'
  print('CareWatchAgent unchanged OK')

  # Confirm FallAgent.run still works (no import errors, class loads)
  from src.specialist_agents import FallAgent
  from src.rag_retriever import RAGRetriever
  rag = RAGRetriever()
  agent = FallAgent(rag)
  print(f'FallAgent instantiation OK, agent_name={agent.agent_name}')
  "
  ```

  **Expected:** Three `OK` lines printed, no AssertionError.

  **Pass:** All three assertions pass.

  **Fail:**
  - If `does not call get_context_v2` → str_replace did not apply — re-read `_get_rag_context` source with `grep -A 15 "def _get_rag_context" src/specialist_agents.py`
  - If `CareWatchAgent.run was modified` → `agent.py` was accidentally edited — `git diff src/agent.py` to see what changed, then `git checkout src/agent.py` to restore

---

### Phase 4D — Measurement

**Goal:** Before/after MRR numbers exist, demonstrating the improvement from hybrid retrieval.

---

- [ ] 🟥 **Step 5: Add `--mode hybrid` to `eval_retrieval.py` and run comparison** — *Critical: produces the interview measurement*

  **Step Architecture Thinking:**

  **Pattern applied:** Strategy pattern — `--mode` selects the retrieval strategy. The evaluation harness (query loop, metric computation, printing) is shared. Only the document fetch step changes.

  **Why this step exists here in the sequence:** `_hybrid_retrieve()` must exist (Step 3) before `eval_retrieval.py` can call it. This step measures the delta — without it, you have an upgraded system with no evidence of improvement.

  **Why this file / class is the right location:** `eval_retrieval.py` is the existing RAG measurement harness. Adding a mode flag is less work than a new file and keeps all RAG metrics in one place.

  **Alternative approach considered and rejected:** Create a new `eval_retrieval_v2.py`. Rejected because it duplicates the entire harness (query loop, metric computation, output formatting) and makes it harder to compare modes side-by-side.

  **What breaks if this step deviates from the described pattern:** If the `--mode hybrid` path uses a different relevance definition (e.g. querying via `get_context_v2()` string output instead of `_hybrid_retrieve()` doc list), the `doc_is_relevant()` keyword check cannot run per-document. The comparison would be measuring different things. The mode must use `_hybrid_retrieve()` directly, which returns `list[str]` — same shape as `collection.query()["documents"][0]`.

  ---

  **Idempotent:** Yes — adding an argparse argument and a conditional branch. Re-running produces the same eval output.

  **Context:** `eval_retrieval.py` currently has one query path: `collection.query(query_texts=[gt.query], n_results=...)`. The `--mode hybrid` path replaces this with `rag._hybrid_retrieve(gt.query, n=max_k)`. Everything else — `doc_is_relevant()`, metric aggregation, `print_results()` — runs identically.

  **Pre-Read Gate:**
  - Run `grep -n "def main" eval/eval_retrieval.py` — must return **exactly 1 match**.
  - Run `grep -n "add_argument" eval/eval_retrieval.py` — capture existing arguments. The new `--mode` argument must not conflict.
  - Run `grep -n "hybrid" eval/eval_retrieval.py` — must return **0 matches**. If found → STOP.
  - Run `grep -n "collection.query" eval/eval_retrieval.py` — must return **exactly 1 match** inside `evaluate_query()`. This is the line the hybrid mode replaces.
  - **Apply Part A first, then Part B+C (merged).** Part A modifies `evaluate_query()`. Part B+C is a single replacement that handles the argparse, query loop, comparison block, and JSON write together — no inter-part dependencies.

  **Anchor Uniqueness Check:**
  - `def evaluate_query(gt: RAGGroundTruth, collection, k_values: list[int]) -> dict:` appears exactly once.
  - The function signature must be updated to accept an optional `rag` parameter.

  The edit has three parts. Part A modifies `evaluate_query()`. Parts B+C are merged into a single replacement that replaces the query loop + JSON write block together — this avoids the inter-part dependency where Part C's old string must account for text Part B inserted.

  **Part A — Update `evaluate_query` signature and add hybrid branch:**

  The edit is a **str_replace** in `eval/eval_retrieval.py`.

  **Old string:**
  ```python
  def evaluate_query(gt: RAGGroundTruth, collection, k_values: list[int]) -> dict:
      """
      Run one ground truth query against ChromaDB.
      Returns per-k Precision, Recall, and rank of first relevant doc.
      """
      max_k = max(k_values)
      try:
          results = collection.query(
              query_texts=[gt.query],
              n_results=min(max_k, collection.count()),
          )
          docs = results.get("documents", [[]])[0]
      except Exception as e:
          logger.warning("Query failed for %s: %s", gt.query_id, e)
          docs = []
  ```

  **New string:**
  ```python
  def evaluate_query(
      gt: RAGGroundTruth,
      collection,
      k_values: list[int],
      rag=None,
  ) -> dict:
      """
      Run one ground truth query against ChromaDB.
      Returns per-k Precision, Recall, and rank of first relevant doc.

      If rag is provided (RAGRetriever instance), uses _hybrid_retrieve()
      instead of direct ChromaDB query — enables hybrid mode comparison.
      """
      max_k = max(k_values)
      try:
          if rag is not None:
              docs = rag._hybrid_retrieve(gt.query, n=max_k)
          else:
              results = collection.query(
                  query_texts=[gt.query],
                  n_results=min(max_k, collection.count()),
              )
              docs = results.get("documents", [[]])[0]
      except Exception as e:
          logger.warning("Query failed for %s: %s", gt.query_id, e)
          docs = []
  ```

  **Part B+C (merged) — Replace argparse tail + query loop + JSON write in a single str_replace.**

  These were previously two separate replacements (Part B for the loop, Part C for the JSON write). They are merged because Part B inserts a comparison block between the loop and the JSON write, which means Part C's old string would not match the post-Part-B file. A single replacement eliminates this inter-part dependency.

  **How this replacement works:** The old string starts at `args = p.parse_args()` and spans through `return 0` — the entire second half of `main()`. The new string prepends `p.add_argument("--mode", ...)` before `args = p.parse_args()`, then includes the same ChromaDB setup block unchanged, then replaces the query loop and JSON write with the multi-mode versions. `args = p.parse_args()` is **preserved** inside the new string (line 8 of the new block) — it is not deleted. The old string is short relative to the new string because the new string adds the `--mode` argument, mode loop, comparison block, and multi-mode JSON write. This is intentional, not a mistake.

  **Old string (from `args = p.parse_args()` through `return 0` — the entire second half of `main()`):**
  ```python
      args = p.parse_args()

      k_values = sorted(set(args.k))
      if any(k < 1 for k in k_values):
          print("k values must be >= 1")
          return 1

      try:
          import chromadb

          client = chromadb.PersistentClient(path="data/chroma_db")
          collection = client.get_collection("carewatch_knowledge")
          doc_count = collection.count()
          print(f"  ChromaDB: {doc_count} documents loaded")
          assert doc_count == 47, (
              f"Expected 47 docs, got {doc_count}. "
              f"Run python -m src.knowledge_base."
          )
      except Exception as e:
          print(f"ChromaDB error: {e}")
          return 1

      query_results = []
      for gt in GROUND_TRUTH:
          result = evaluate_query(gt, collection, k_values)
          query_results.append(result)
          print(
              f"  {gt.query_id}: RR={result['reciprocal_rank']:.2f}  "
              f"relevant_in_top3={'yes' if result['first_relevant_rank'] > 0 else 'NO'}"
          )

      metrics = compute_aggregate_metrics(query_results, k_values)
      print_results(query_results, metrics, k_values)

      out_dir = Path("eval/results")
      out_dir.mkdir(parents=True, exist_ok=True)
      ts = datetime.now().strftime("%Y%m%d_%H%M%S")
      out_path = out_dir / f"rag_eval_{ts}.json"
      out_path.write_text(
          json.dumps(
              {
                  "run_at": datetime.now().isoformat(),
                  "k_values": k_values,
                  "metrics": metrics,
                  "results": query_results,
              },
              indent=2,
          )
      )
      print(f"  Full results: {out_path}")

      return 0
  ```

  **New string:**
  ```python
      p.add_argument(
          "--mode",
          choices=["raw", "hybrid", "both"],
          default="raw",
          help="raw: ChromaDB only (baseline). hybrid: BM25+dense RRF. both: run both and compare.",
      )
      args = p.parse_args()

      k_values = sorted(set(args.k))
      if any(k < 1 for k in k_values):
          print("k values must be >= 1")
          return 1

      try:
          import chromadb

          client = chromadb.PersistentClient(path="data/chroma_db")
          collection = client.get_collection("carewatch_knowledge")
          doc_count = collection.count()
          print(f"  ChromaDB: {doc_count} documents loaded")
          assert doc_count == 47, (
              f"Expected 47 docs, got {doc_count}. "
              f"Run python -m src.knowledge_base."
          )
      except Exception as e:
          print(f"ChromaDB error: {e}")
          return 1

      modes_to_run = ["raw", "hybrid"] if args.mode == "both" else [args.mode]
      all_metrics = {}
      all_results = {}

      for mode in modes_to_run:
          rag_instance = None
          if mode == "hybrid":
              from src.rag_retriever import RAGRetriever
              rag_instance = RAGRetriever()
              if rag_instance._bm25 is None:
                  print("  ⚠ BM25 index not available — hybrid mode falls back to dense only")

          print(f"\n  === Mode: {mode.upper()} ===")
          query_results = []
          for gt in GROUND_TRUTH:
              result = evaluate_query(gt, collection, k_values, rag=rag_instance)
              query_results.append(result)
              print(
                  f"  {gt.query_id}: RR={result['reciprocal_rank']:.2f}  "
                  f"relevant_in_top3={'yes' if result['first_relevant_rank'] > 0 else 'NO'}"
              )

          metrics = compute_aggregate_metrics(query_results, k_values)
          all_metrics[mode] = metrics
          all_results[mode] = query_results
          print_results(query_results, metrics, k_values)

      if args.mode == "both":
          print("\n  === COMPARISON: RAW vs HYBRID ===")
          raw_mrr    = all_metrics["raw"]["mrr"]
          hybrid_mrr = all_metrics["hybrid"]["mrr"]
          delta      = round(hybrid_mrr - raw_mrr, 3)
          direction  = "↑" if delta >= 0 else "↓"
          print(f"  MRR:  raw={raw_mrr:.3f}  hybrid={hybrid_mrr:.3f}  delta={direction}{abs(delta):.3f}")
          for k in k_values:
              rp = all_metrics["raw"]["per_k"][k]["precision_at_k"]
              hp = all_metrics["hybrid"]["per_k"][k]["precision_at_k"]
              print(f"  P@{k}: raw={rp:.3f}  hybrid={hp:.3f}  delta={'↑' if hp>=rp else '↓'}{abs(hp-rp):.3f}")
          print()

      out_dir = Path("eval/results")
      out_dir.mkdir(parents=True, exist_ok=True)
      ts = datetime.now().strftime("%Y%m%d_%H%M%S")
      out_path = out_dir / f"rag_eval_{ts}.json"
      if args.mode == "both":
          payload = {
              "run_at": datetime.now().isoformat(),
              "k_values": k_values,
              "mode": "both",
              "raw": {"metrics": all_metrics["raw"], "results": all_results["raw"]},
              "hybrid": {"metrics": all_metrics["hybrid"], "results": all_results["hybrid"]},
          }
      else:
          payload = {
              "run_at": datetime.now().isoformat(),
              "k_values": k_values,
              "metrics": all_metrics[args.mode],
              "results": all_results[args.mode],
          }
      out_path.write_text(json.dumps(payload, indent=2))
      print(f"  Full results: {out_path}")

      return 0
  ```

  **What it does:** Adds `--mode raw|hybrid|both` to `eval_retrieval.py`. `--mode raw` is the unchanged baseline. `--mode hybrid` routes queries through `_hybrid_retrieve()`. `--mode both` runs both and prints a side-by-side comparison table showing MRR and Precision@k delta.

  **Git Checkpoint:**
  ```bash
  git add eval/eval_retrieval.py
  git commit -m "step 5: add --mode hybrid to eval_retrieval for before/after RAG comparison"
  ```

  **Subtasks:**
  - [ ] 🟥 `--mode raw` produces same output as before this step (regression check)
  - [ ] 🟥 `--mode hybrid` runs without error and prints metrics
  - [ ] 🟥 `--mode both` prints a comparison table with MRR delta
  - [ ] 🟥 `--mode both` JSON file contains both raw and hybrid results (keys: raw, hybrid)
  - [ ] 🟥 Record MRR delta in README

  **✓ Verification Test:**

  **Type:** Integration

  **Action:**
  ```bash
  # Step 1: confirm raw mode still matches baseline
  python -m eval.eval_retrieval --mode raw 2>/dev/null | grep "MRR:"
  # Must match the MRR recorded in Pre-Flight (expected ~0.960)

  # Step 2: run both modes and capture comparison
  python -m eval.eval_retrieval --mode both 2>/dev/null | grep -A 5 "COMPARISON"

  # Step 3: verify JSON captures both modes (not just last mode)
  # Run after Step 2 — latest rag_eval_*.json will exist
  python -c "
  import json
  from pathlib import Path
  files = sorted(Path('eval/results').glob('rag_eval_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
  assert files, 'No rag_eval JSON found — run --mode both first'
  d = json.loads(files[0].read_text())
  assert 'raw' in d and 'hybrid' in d, f'Expected raw and hybrid keys when --mode both, got: {list(d.keys())}'
  print('JSON contains both raw and hybrid results OK')
  "
  ```

  **Expected (Step 1):** `MRR: 0.960` (or the value recorded in Pre-Flight — must not have changed)

  **Expected (Step 2):**
  ```
  === COMPARISON: RAW vs HYBRID ===
  MRR:  raw=0.960  hybrid=X.XXX  delta=↑/↓X.XXX
  P@1:  raw=0.920  hybrid=X.XXX  delta=...
  P@2:  raw=X.XXX  hybrid=X.XXX  delta=...
  P@3:  raw=X.XXX  hybrid=X.XXX  delta=...
  ```

  **Pass:** Both modes run without error, comparison table is printed, raw MRR matches Pre-Flight baseline.

  **Fail:**
  - If raw MRR changed → `evaluate_query()` str_replace introduced a bug in the raw path — run `git diff eval/eval_retrieval.py` and check the else branch
  - If `hybrid MRR = 0.000` → `_hybrid_retrieve()` returned empty lists for all queries — check BM25 index built correctly with Step 2 verification test
  - If `ModuleNotFoundError: rank_bm25` in hybrid mode → Step 1 was skipped — run `pip install rank-bm25==0.2.2`
  - If `Expected raw and hybrid keys` assertion fails → Part C JSON write replacement was not applied or is incorrect — JSON was still writing single-mode structure after the loop

---

## Regression Guard

**Systems at risk from this plan:**
- `CareWatchAgent` — calls `get_context()` + `_score_relevance()`. Both stay unchanged. Risk: low but must be verified.
- `CareWatchOrchestrator` specialist agents — now use `get_context_v2()`. If it returns empty for anomaly types that `get_context()` would have returned context for, LLM explanations degrade silently.
- `eval_agent.py` — must not be affected by `eval_retrieval.py` changes.

**Regression verification:**

| System | Pre-change behaviour | Post-change verification |
|--------|---------------------|--------------------------|
| `CareWatchAgent.run()` | Calls `get_context()` + `_score_relevance()` | `grep "get_context_v2" src/agent.py` returns 0 matches |
| `eval_agent.py` F1 | 1.000 / FNR 0.000 | `python -m eval.eval_agent --no-llm 2>/dev/null \| grep "F1:"` → `1.000` |
| `eval_retrieval --mode raw` | MRR = Pre-Flight value | Must match exactly — any change = regression in `evaluate_query()` raw path |

**Test count regression check:**
- Run `python -m pytest eval/ -q --tb=no 2>/dev/null | tail -1` — count must be ≥ Pre-Flight baseline

---

## Rollback Procedure

All steps are additive. Rollback is clean.

```bash
# Rollback Step 5 (eval_retrieval.py mode flag)
git revert HEAD

# Rollback Step 4 (specialist_agents._get_rag_context)
git revert HEAD~1

# Rollback Step 3 (RAGRetriever new methods)
git revert HEAD~2

# Rollback Step 2 (BM25 index in __init__)
git revert HEAD~3

# Rollback Step 1 (rank-bm25)
pip uninstall rank-bm25 -y
# Remove rank-bm25==0.2.2 from requirements.txt manually

# Confirm system is back to pre-plan state:
python -m eval.eval_agent --no-llm 2>/dev/null | grep "F1:"   # must be 1.000
python -m eval.eval_retrieval --mode raw 2>/dev/null | grep "MRR:"  # must match baseline
```

---

## Pre-Flight Checklist

| Phase | Check | How to Confirm | Status |
|-------|-------|----------------|--------|
| **Pre-flight** | `get_context_v2` does not exist | `grep -n "get_context_v2" src/rag_retriever.py` → 0 lines | ⬜ |
| | `rank_bm25` not installed | `python -c "import rank_bm25"` → ModuleNotFoundError | ⬜ |
| | Baseline MRR recorded | `python -m eval.eval_retrieval \| grep "MRR:"` | ⬜ |
| | Eval F1 baseline recorded | `python -m eval.eval_agent --no-llm \| grep "F1:"` | ⬜ |
| **Phase 4A** | `rank_bm25` importable | `python -c "from rank_bm25 import BM25Okapi; print('OK')"` | ⬜ |
| | BM25 index built with 47 docs | Step 2 verification passes | ⬜ |
| **Phase 4B** | `get_context_v2` exists and returns string | Step 3 verification passes | ⬜ |
| | Decomposition returns 2 queries for fall+pill | `_decompose_queries` assertion in Step 3 test | ⬜ |
| **Phase 4C** | `_get_rag_context` calls `get_context_v2` | `grep "get_context_v2" src/specialist_agents.py` ≥ 1 | ⬜ |
| | `CareWatchAgent` unchanged | `grep "get_context_v2" src/agent.py` → 0 lines | ⬜ |
| | Eval F1 still 1.000 | `python -m eval.eval_agent --no-llm \| grep "F1:"` | ⬜ |
| **Phase 4D** | Raw MRR unchanged from baseline | `--mode raw` output matches Pre-Flight MRR | ⬜ |
| | Hybrid mode runs without error | `--mode hybrid` prints metrics | ⬜ |
| | Comparison table printed | `--mode both` prints delta row | ⬜ |

---

## Risk Heatmap

| Step | Risk Level | What Could Go Wrong | Early Detection | Idempotent |
|------|-----------|---------------------|-----------------|------------|
| Step 1 | 🟢 Low | Version conflict with existing packages | `pip install` error output | Yes |
| Step 2 | 🟡 Medium | str_replace anchor wrong (12 vs 8 spaces) or Part 2 anchor ambiguous (3× return 1.0) | Pre-Read Gate + explicit old string; Part 2 uses except-block context | Yes |
| Step 3 | 🟡 Medium | `_QUERY_MAP` mis-indented as method local → NameError; dedup bug in `_decompose_queries` | `hasattr(RAGRetriever, '_QUERY_MAP')` + `len(q2) == 2` | Yes |
| Step 4 | 🔴 High | str_replace modifies wrong method or leaves `_score_relevance` call in place | Step 4 verification: `inspect.getsource` assertion | Yes |
| Step 5 | 🟡 Medium | Large replacement block — old string must match file exactly | Parts B+C merged into single replacement; raw MRR regression check catches errors | Yes |

---

## Success Criteria

| Feature | Target | Verification |
|---------|--------|--------------|
| BM25 index built | 47 docs, `_bm25` is not None | Step 2 verification test |
| `get_context_v2` returns context | Non-empty string for fall anomaly | Step 3 verification test |
| Decomposition produces 2 queries for fall+pill | `len(q2) == 2` | Step 3 verification test |
| `_get_rag_context` uses new path | No `_score_relevance` call in source | Step 4 verification test |
| `CareWatchAgent` unchanged | `get_context_v2` not in `agent.py` | Step 4 verification test |
| Eval F1 unchanged | 1.000 / FNR 0.000 | Regression guard |
| RAW MRR unchanged | Matches Pre-Flight baseline | Step 5 verification |
| Hybrid MRR measured | Printed with delta vs raw | `--mode both` output |

---

⚠️ **Do not mark a step 🟩 Done until its verification test passes.**
⚠️ **Do not proceed past a Human Gate without explicit human input.**
⚠️ **If blocked, mark 🟨 In Progress and output the State Manifest before stopping.**
⚠️ **Do not batch multiple steps into one git commit.**
⚠️ **Step 4 str_replace: read `_get_rag_context` source with grep BEFORE applying — the old string must match exactly including whitespace.**
⚠️ **Step 5 str_replace: there are TWO str_replace operations (Part A: evaluate_query signature, Part B+C merged: argparse + query loop + comparison + JSON write). Apply Part A first, then Part B+C.**