"""
eval_retrieval.py
=================
Evaluates ChromaDB RAG retrieval quality.
Metrics: Precision@k, Recall@k, MRR across 25 ground-truth queries.

DEFINITIONS:
  A retrieved document is "relevant" if it contains ALL keywords in the
  ground truth relevant_keywords list (case-insensitive).

  Precision@k = |relevant in top-k| / k
  Recall@k    = |relevant in top-k| / min_relevant_docs
  MRR         = mean(1 / rank_of_first_relevant_doc across all queries)
                If no relevant doc in top-k, contribution = 0.

USAGE:
  python eval/eval_retrieval.py           # default k=1,2,3
  python eval/eval_retrieval.py --k 1 3  # specific k values

OUTPUT:
  Prints Precision@k, Recall@k, MRR table.
  Writes full results to eval/results/rag_eval_<timestamp>.json
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import json
import logging
from datetime import datetime

logging.basicConfig(level=logging.WARNING, format="%(name)s — %(message)s")
logger = logging.getLogger("eval_retrieval")

from eval.rag_ground_truth import GROUND_TRUTH, RAGGroundTruth


def doc_is_relevant(doc_text: str, keywords: list[str]) -> bool:
    """A doc is relevant if ALL keywords appear (case-insensitive)."""
    text_lower = doc_text.lower()
    return all(kw.lower() in text_lower for kw in keywords)


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

    relevance = [doc_is_relevant(doc, gt.relevant_keywords) for doc in docs]

    first_relevant_rank = 0
    for i, rel in enumerate(relevance):
        if rel:
            first_relevant_rank = i + 1
            break

    per_k = {}
    for k in k_values:
        top_k_relevant = sum(relevance[:k])
        per_k[k] = {
            "precision": round(top_k_relevant / k, 3),
            "recall": round(top_k_relevant / gt.min_relevant_docs, 3),
        }

    return {
        "query_id": gt.query_id,
        "query": gt.query,
        "relevant_keywords": gt.relevant_keywords,
        "retrieved_docs": docs[:max_k],
        "relevance_mask": relevance[:max_k],
        "first_relevant_rank": first_relevant_rank,
        "reciprocal_rank": (
            round(1 / first_relevant_rank, 3) if first_relevant_rank > 0 else 0.0
        ),
        "per_k": per_k,
    }


def compute_aggregate_metrics(
    query_results: list[dict], k_values: list[int]
) -> dict:
    n = len(query_results)
    mrr = round(sum(r["reciprocal_rank"] for r in query_results) / n, 3)

    per_k_agg = {}
    for k in k_values:
        prec_values = [r["per_k"][k]["precision"] for r in query_results]
        rec_values = [r["per_k"][k]["recall"] for r in query_results]
        per_k_agg[k] = {
            "precision_at_k": round(sum(prec_values) / n, 3),
            "recall_at_k": round(sum(rec_values) / n, 3),
        }

    zero_hit = [
        r["query_id"]
        for r in query_results
        if r["first_relevant_rank"] == 0
    ]

    return {
        "mrr": mrr,
        "per_k": per_k_agg,
        "zero_hit_queries": zero_hit,
        "total_queries": n,
    }


def print_results(
    query_results: list[dict], metrics: dict, k_values: list[int]
) -> None:
    print()
    print("=" * 72)
    print("  CareWatch Eval — RAG Retrieval Metrics")
    print(
        f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  |  "
        f"{len(query_results)} queries"
    )
    print("=" * 72)

    print(f"\n  {'ID':<6} {'Query (truncated)':<38} {'@1':<6} {'@2':<6} {'@3':<6} {'RR'}")
    print("  " + "-" * 68)
    for r in query_results:
        p_at_1 = r["per_k"].get(1, {}).get("precision", "-")
        p_at_2 = r["per_k"].get(2, {}).get("precision", "-")
        p_at_3 = r["per_k"].get(3, {}).get("precision", "-")
        rr = r["reciprocal_rank"]
        query_short = r["query"][:37]
        print(
            f"  {r['query_id']:<6} {query_short:<38} "
            f"{str(p_at_1):<6} {str(p_at_2):<6} {str(p_at_3):<6} {rr}"
        )

    print()
    print("  AGGREGATE METRICS")
    print(f"  MRR: {metrics['mrr']:.3f}")
    for k in k_values:
        m = metrics["per_k"][k]
        print(
            f"  Precision@{k}: {m['precision_at_k']:.3f}   "
            f"Recall@{k}: {m['recall_at_k']:.3f}"
        )

    if metrics["zero_hit_queries"]:
        print(f"\n  ⚠  No relevant doc found for: {metrics['zero_hit_queries']}")
        print("     Review ground truth keywords or expand knowledge base.")
    else:
        print("\n  ★ All queries returned at least one relevant document.")

    print("=" * 72)
    print()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--k",
        type=int,
        nargs="+",
        default=[1, 2, 3],
        help="k values for Precision@k and Recall@k (default: 1 2 3)",
    )
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
    except Exception as e:
        print(f"ChromaDB error: {e}")
        return 1

    doc_count = collection.count()
    print(f"  ChromaDB: {doc_count} documents loaded")
    if doc_count != 47:
        print(
            f"  Doc count mismatch: expected 47, got {doc_count}. "
            f"Run python -m src.knowledge_base."
        )
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


if __name__ == "__main__":
    sys.exit(main())
