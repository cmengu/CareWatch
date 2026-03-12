# CareWatch AI Agent — Part 2 of 5: RAG Pipeline

**Overall Progress:** `100%` (Part 1 + Part 2 complete)

**What this part does:** Builds the medical knowledge retrieval layer.
Creates a text file of drug/elderly care facts, loads them into ChromaDB,
and builds a retriever class that Part 4 (agent) will call.

**End state when Part 2 is done:**
- `data/drug_interactions.txt` exists with 12 facts
- `data/chroma_db/` exists and contains a queryable ChromaDB collection
- `src/knowledge_base.py` builds the collection (run once, idempotent)
- `src/rag_retriever.py` queries the collection and returns relevant context
- Querying with `pill_taking` anomaly returns a non-empty string

---

## Agent Failure Protocol

1. A verification command fails → read the full error output.
2. Cause is unambiguous → make ONE targeted fix → re-run the same verification command.
3. If still failing after one fix → **STOP**. Before stopping, output the full current contents
   of every file modified in this step. Report: (a) command run, (b) full error verbatim,
   (c) fix attempted, (d) current state of each modified file, (e) why you cannot proceed.
4. Never attempt a second fix without human instruction.
5. Never modify files not named in the current step.

---

## Pre-Flight — Run Before Touching Anything

```bash
# 1. Confirm Part 1 is done
python -c "import groq; import chromadb; print('deps OK')"
python -c "from src.alert_system import AlertSystem; print('alert OK')"
python -c "from app.api import app; print('api OK')"

# 2. Confirm new files do NOT exist yet
ls data/drug_interactions.txt 2>&1
ls src/knowledge_base.py 2>&1
ls src/rag_retriever.py 2>&1
# Expected: "No such file or directory" for all three

# 3. Confirm data/ directory exists
ls data/
# Expected: carewatch.db and/or baselines/ present
```

**Baseline Snapshot — agent fills this before Step 1:**
```
Part 1 deps OK:                          ____
drug_interactions.txt absent:            ____
knowledge_base.py absent:               ____
rag_retriever.py absent:                ____
data/ directory exists:                  ____
```

**All checks must pass before Step 1 begins.**

---

## Tasks

---

- [x] 🟩 **Step 1: Create `data/drug_interactions.txt`** — *Non-critical: plain text, no code*

  **Idempotent:** Yes — file creation overwrites if it already exists.

  **Context:** This is the "textbook" the RAG system searches. Each line is one fact.
  Format is `topic: fact`. ChromaDB will index each line as a separate document.
  When the agent detects an anomaly (e.g. `pill_taking` missed), it queries this file
  and retrieves the most relevant lines to pass to the LLM.

  Create file at exactly this path: `data/drug_interactions.txt`

  ```
  metformin: Take with food. Missing a dose for a diabetic elderly patient increases risk of hyperglycemia. Critical to take consistently.
  warfarin: Blood thinner. Missing doses causes stroke risk. Must be taken at the same time daily. Interaction with aspirin increases bleeding risk.
  lisinopril: Blood pressure medication. Missing doses can cause dangerous blood pressure spikes in elderly patients.
  amlodipine: Calcium channel blocker for blood pressure. Dizziness and falls are common side effects especially in elderly.
  atorvastatin: Cholesterol medication. Evening dose preferred. Missing occasional doses less critical than blood pressure meds.
  aspirin: Daily low-dose aspirin for heart patients. Do not combine with warfarin without doctor approval.
  omeprazole: Stomach acid reducer. Take 30 minutes before breakfast. Missing doses causes acid reflux discomfort.
  general: Elderly patients missing more than 2 doses of any critical medication should be flagged for family follow-up.
  general: Inactivity exceeding 4 hours during waking hours 7am to 9pm is a fall risk indicator in elderly patients.
  general: Sudden change in routine such as eating or walking patterns in elderly can indicate onset of infection or depression.
  fallen: Any fall in elderly patient requires immediate medical assessment even if patient appears uninjured.
  pill_taking: Missed pill-taking activity combined with risk score above 60 requires family notification within 1 hour.
  ```

  **Git Checkpoint:**
  ```bash
  git add data/drug_interactions.txt
  git commit -m "part2 step1: add drug interactions knowledge base text file"
  ```

  **✓ Verification Test:**

  **Type:** Unit

  **Action:**
  ```bash
  python -c "
  lines = [l for l in open('data/drug_interactions.txt').readlines() if l.strip()]
  assert len(lines) == 12, f'Expected 12 lines, got {len(lines)}'
  assert all(':' in l for l in lines), 'Every line must contain a colon'
  print('PASS:', len(lines), 'facts ready')
  "
  ```

  **Expected:** `PASS: 12 facts ready`

  **Pass:** Exact string printed, no AssertionError

  **Fail:**
  - If `FileNotFoundError` → file saved to wrong path → confirm path is `data/drug_interactions.txt` not project root or `src/`
  - If `AssertionError: Expected 12` → blank lines included or a line was missed → recount and re-save
  - If `AssertionError: Every line must contain a colon` → formatting error on a line → open file and check

---

- [x] 🟩 **Step 2: Create `src/knowledge_base.py`** — *Critical: RAG depends on this running once*

  **Idempotent:** Yes — drops and recreates the ChromaDB collection on every run.

  **Context:** Reads `data/drug_interactions.txt` line by line, loads each fact into
  a persistent ChromaDB collection at `data/chroma_db/`. Must be run once before
  `rag_retriever.py` can query anything. Safe to re-run — collection is wiped and rebuilt.

  **Pre-Read Gate:**
  ```bash
  # Confirm text file exists from Step 1
  ls data/drug_interactions.txt
  # Expected: file listed, no error

  # Check chroma_db state
  ls data/chroma_db 2>&1
  # If "No such file or directory" → proceed normally.
  # If data/chroma_db already exists → DO NOT STOP. Proceed anyway.
  # The script drops and recreates the collection. Pre-existing chroma_db is not an error.
  ```

  Create file at exactly: `src/knowledge_base.py`

  ```python
  """
  knowledge_base.py
  ==================
  Run ONCE to load data/drug_interactions.txt into ChromaDB.
  After running, rag_retriever.py can query it.
  Safe to re-run — drops and rebuilds the collection each time.

  USAGE:
      python -m src.knowledge_base
  """

  import chromadb
  from pathlib import Path

  DB_PATH    = str(Path(__file__).parents[1] / "data" / "chroma_db")
  FACTS_PATH = Path(__file__).parents[1] / "data" / "drug_interactions.txt"


  def build_knowledge_base():
      client = chromadb.PersistentClient(path=DB_PATH)

      # Drop and recreate for clean idempotent build
      try:
          client.delete_collection("carewatch_knowledge")
      except Exception:
          pass

      collection = client.create_collection("carewatch_knowledge")

      facts = []
      ids   = []

      with open(FACTS_PATH, "r") as f:
          for i, line in enumerate(f):
              line = line.strip()
              if line and ":" in line:
                  facts.append(line)
                  ids.append(f"fact_{i}")

      if not facts:
          print("ERROR: No facts found. Check data/drug_interactions.txt exists.")
          return

      collection.add(documents=facts, ids=ids)
      print(f"Loaded {len(facts)} facts into ChromaDB at {DB_PATH}")

      # Verify write succeeded immediately
      count = collection.count()
      assert count == len(facts), f"ChromaDB count mismatch: expected {len(facts)}, got {count}"
      print(f"Verified: {count} documents queryable")


  if __name__ == "__main__":
      build_knowledge_base()
  ```

  **Subtasks:**
  - [ ] 🟥 File created at `src/knowledge_base.py`
  - [ ] 🟥 Run `python -m src.knowledge_base` immediately after creating the file — do this before running the verification test
  - [ ] 🟥 Confirm terminal output shows `Verified: 12 documents queryable` — if it does not, STOP and report
  - [ ] 🟥 Verification test passes

  **Git Checkpoint:**
  ```bash
  git add src/knowledge_base.py
  git commit -m "part2 step2: add ChromaDB knowledge base builder"
  ```

  **✓ Verification Test:**

  **Type:** Integration

  **Action:**
  ```bash
  python -c "
  import chromadb
  from pathlib import Path

  client = chromadb.PersistentClient(path=str(Path('data/chroma_db')))
  col    = client.get_collection('carewatch_knowledge')
  count  = col.count()

  assert count == 12, f'Expected 12, got {count}'
  print('PASS 1: collection has', count, 'documents')

  # Confirm it is actually queryable
  results = col.query(query_texts=['pill taking missed dose'], n_results=2)
  docs    = results['documents'][0]
  assert len(docs) == 2, f'Expected 2 results, got {len(docs)}'
  print('PASS 2: query returned', len(docs), 'results')
  print('Top result:', docs[0][:80])
  "
  ```

  **Expected:** `PASS 1` and `PASS 2` printed with document count and top result preview

  **Pass:** Both PASS lines printed

  **Fail:**
  - If `CollectionNotFoundError` → `python -m src.knowledge_base` subtask was skipped → run it now, confirm "Verified: 12 documents queryable", then retry verification
  - If `count != 12` → blank lines or lines without `:` were skipped → re-check `drug_interactions.txt` formatting
  - If query returns 0 results → ChromaDB indexing failed silently → `rm -rf data/chroma_db` then re-run `python -m src.knowledge_base`

---

- [x] 🟩 **Step 3: Create `src/rag_retriever.py`** — *Critical: agent depends on this in Part 4*

  **Idempotent:** Yes — stateless query class, no writes.

  **Context:** Wraps ChromaDB with a safe interface for the agent to call. Three guards
  are built in that would otherwise cause crashes or silent wrong results:

  - **Guard 1:** ChromaDB collection not found → `_available = False` → returns `""` instead of crashing
  - **Guard 2:** Collection is empty → `count() == 0` → skip query (ChromaDB raises `ValueError` with `n_results=0`)
  - **Guard 3:** `deviation_detector.check()` can return anomalies as **strings** (e.g. `"No baseline built yet — need 7 days of data"`) not just dicts. String items must be skipped with `isinstance(a, dict)` — no crash, returns empty context for those inputs.

  All three guards return empty string — agent always continues without RAG rather than crashing.

  **Pre-Read Gate:**
  ```bash
  # Confirm knowledge base was built — Step 2 verification must have passed before this runs
  python -c "
  import chromadb
  from pathlib import Path
  col = chromadb.PersistentClient(path=str(Path('data/chroma_db'))).get_collection('carewatch_knowledge')
  print('collection count:', col.count())
  "
  # Expected: collection count: 12
  # If error → Step 2 did not complete → go back and fix Step 2 first. Do not create this file.
  ```

  Create file at exactly: `src/rag_retriever.py`

  ```python
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

  import chromadb
  from pathlib import Path

  DB_PATH = str(Path(__file__).parents[1] / "data" / "chroma_db")


  class RAGRetriever:
      def __init__(self):
          try:
              client = chromadb.PersistentClient(path=DB_PATH)
              self.collection  = client.get_collection("carewatch_knowledge")
              self._available  = True
          except Exception as e:
              print(f"RAG not available: {e}. Run: python -m src.knowledge_base")
              self.collection  = None
              self._available  = False

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
              print(f"RAG query failed: {e}")
              return ""
  ```

  **Git Checkpoint:**
  ```bash
  git add src/rag_retriever.py
  git commit -m "part2 step3: add RAG retriever with collection, empty, and string-anomaly guards"
  ```

  **Subtasks:**
  - [ ] 🟥 Pre-read gate confirms `collection count: 12`
  - [ ] 🟥 File created at `src/rag_retriever.py`
  - [ ] 🟥 All five verification tests pass

  **✓ Verification Test:**

  **Type:** Integration

  **Action:**
  ```bash
  python -c "
  from src.rag_retriever import RAGRetriever

  rag = RAGRetriever()
  assert rag._available, 'RAG not available — run python -m src.knowledge_base first'
  print('PASS 1: RAGRetriever initialised')

  # Test with real dict anomaly shape from deviation_detector.check()
  anomalies = [{'activity': 'pill_taking', 'type': 'MISSING', 'message': 'Pill Taking not detected', 'severity': 'HIGH'}]
  context = rag.get_context(anomalies)
  assert len(context) > 0, 'Expected context string, got empty'
  print('PASS 2: context retrieved for pill_taking anomaly')
  print('Preview:', context[:100])

  # Test empty anomaly list returns empty string (not crash)
  empty = rag.get_context([])
  assert empty == '', f'Expected empty string, got: {repr(empty)}'
  print('PASS 3: empty anomaly list handled cleanly')

  # Test dict anomaly (fallen detection path) — fallen IS a valid dict anomaly; context should be non-empty
  fallen = rag.get_context([{'activity': 'fallen', 'type': 'FALLEN', 'message': 'Fall detected', 'severity': 'HIGH'}])
  assert len(fallen) > 0, f'Expected context for fallen anomaly, got empty'
  print('PASS 4: fallen dict anomaly handled, context:', repr(fallen[:60]))

  # Test string anomaly (no-baseline path: deviation_detector returns anomalies=[str])
  string_only = rag.get_context(['No baseline built yet — need 7 days of data'])
  assert string_only == '', f'String anomaly must return empty context, got: {repr(string_only)}'
  print('PASS 5: string anomaly skipped cleanly, no crash')
  "
  ```

  **Expected:** All five `PASS` lines printed, context preview shown after PASS 2

  **Observe:** Terminal output — all five lines must appear

  **Pass:** `PASS 1` through `PASS 5` all printed

  **Fail:**
  - If `_available = False` → Step 2 did not complete → re-run `python -m src.knowledge_base` then retry
  - If `PASS 2` fails with empty context → query terms not matching documents → add `print(query_terms)` inside `get_context` before the query call to debug
  - If `PASS 4` fails with empty context → `fallen` query returned no results → confirm `data/drug_interactions.txt` has a line starting with `fallen:` and that ChromaDB loaded it; re-run `python -m src.knowledge_base`
  - If `PASS 5` fails with non-empty string → `isinstance(a, dict)` guard missing or wrong → check that guard is present in `get_context`
  - If any PASS crashes → read full traceback, fix only the identified line, re-run verification

---

## Part 2 Complete — State Manifest

Run this after all three step verifications pass:

```bash
python -c "
from src.rag_retriever import RAGRetriever
rag = RAGRetriever()

anomalies = [
    {'activity': 'pill_taking', 'type': 'MISSING', 'message': 'Missed pill', 'severity': 'HIGH'},
    {'activity': 'walking',     'type': 'MISSING', 'message': 'No walking',  'severity': 'MEDIUM'},
]
context = rag.get_context(anomalies)
print('RAG available:', rag._available)
print('Context length:', len(context))
print('---')
print(context)
print('---')
print('Part 2 DONE')
"
```

**Expected output:**
```
RAG available: True
Context length: [number greater than 0]
---
[2-3 lines of medical facts relevant to pill_taking and walking]
---
Part 2 DONE
```

When you see `Part 2 DONE` with non-zero context length → **paste this output and move to Part 3.**

---

## Regression Guard

| System | Pre-change behaviour | Post-change verification |
|--------|---------------------|--------------------------|
| `alert_system.py` | Fixed in Part 1 | `python -c "from src.alert_system import AlertSystem; print('OK')"` |
| `api.py` | Fixed in Part 1 | `python -c "from app.api import app; print('OK')"` |
| `deviation_detector.py` | Untouched | `python -c "from src.deviation_detector import DeviationDetector; print('OK')"` |

No existing files are touched in Part 2. Regression risk is zero.

---

## Rollback

```bash
# Reverse order — one revert per commit
git revert HEAD    # reverts part2 step3 rag_retriever.py
git revert HEAD~1  # reverts part2 step2 knowledge_base.py
git revert HEAD~2  # reverts part2 step1 drug_interactions.txt

# Remove ChromaDB data (not tracked by git)
rm -rf data/chroma_db

# Confirm clean state
ls src/rag_retriever.py 2>&1       # must say No such file or directory
ls src/knowledge_base.py 2>&1      # must say No such file or directory
ls data/chroma_db 2>&1             # must say No such file or directory
```

---

⚠️ **Do not mark a step 🟩 Done until its verification test passes.**
⚠️ **Do not batch multiple steps into one git commit.**
⚠️ **Do not touch any file not named in the current step.**
⚠️ **Step 2: run `python -m src.knowledge_base` as a subtask BEFORE running the verification test.**
⚠️ **Step 3 Pre-Read Gate must confirm `collection count: 12` before creating rag_retriever.py.**
⚠️ **If `data/chroma_db` already exists at Step 2 pre-read — proceed anyway, do not stop.**