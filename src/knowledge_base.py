"""
knowledge_base.py
==================
Run ONCE to load data/drug_interactions.txt into ChromaDB.
After running, rag_retriever.py can query it.
Safe to re-run — drops and rebuilds the collection each time.

USAGE:
    python -m src.knowledge_base
"""

import logging
import chromadb
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = str(Path(__file__).parents[1] / "data" / "chroma_db")
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
    ids = []

    with open(FACTS_PATH, "r") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if line.startswith("#"):
                continue
            if line and ":" in line:
                facts.append(line)
                ids.append(f"fact_{i}")

    if not facts:
        logger.error("No facts found. Check data/drug_interactions.txt exists.")
        return

    collection.add(documents=facts, ids=ids)
    logger.info("Loaded %d facts into ChromaDB at %s", len(facts), DB_PATH)

    # Verify write succeeded immediately
    count = collection.count()
    assert count == len(facts), f"ChromaDB count mismatch: expected {len(facts)}, got {count}"
    logger.info("Verified: %d documents queryable", count)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    build_knowledge_base()
