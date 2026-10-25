"""Retrieval Evaluation Metrics Calculator

Computes empirical IR metrics (Hit@K, Recall@K, MRR@K, nDCG@K) for Dense, BM25,
and Hybrid RRF retrieval pipelines against human-reviewed ground truth labels.
"""

import json
import math
from collections import defaultdict
from pathlib import Path

import openpyxl

LABELED_WORKBOOK = Path("data/relevance_review_pilot_labeled.xlsx")
CANDIDATES_FILE = Path("data/eval_candidates.jsonl")
OUTPUT_METRICS = Path("data/baseline_metrics.json")

K = 5


def dcg_at_k(rel_scores, k=K):
    """Compute Discounted Cumulative Gain at rank K."""
    return sum(
        (2**rel - 1) / math.log2(idx + 1)
        for idx, rel in enumerate(rel_scores[:k], start=1)
    )


def ndcg_at_k(rel_scores, ideal_scores, k=K):
    """Compute Normalized Discounted Cumulative Gain at rank K."""
    dcg = dcg_at_k(rel_scores, k)
    idcg = dcg_at_k(ideal_scores, k)
    return dcg / idcg if idcg > 0 else 0.0


def load_ground_truth(sheet_name="Pilot Review"):
    """Load relevance annotations from the review workbook."""
    if not LABELED_WORKBOOK.exists():
        raise FileNotFoundError(f"Missing labeled workbook: {LABELED_WORKBOOK}")

    wb = openpyxl.load_workbook(LABELED_WORKBOOK, data_only=True)
    if sheet_name not in wb.sheetnames:
        raise ValueError(f"Sheet '{sheet_name}' not found in {LABELED_WORKBOOK}")

    ws = wb[sheet_name]
    labels = {}

    for row in list(ws.iter_rows(values_only=True))[1:]:
        qid = row[0]
        case_name = row[3]
        rel = row[10]
        if rel is not None:
            labels[(qid, case_name)] = int(rel)

    wb.close()
    return labels


def evaluate(sheet_name="Pilot Review", k=K):
    labels = load_ground_truth(sheet_name=sheet_name)
    eval_qids = sorted(list({qid for (qid, _) in labels.keys()}))

    if not CANDIDATES_FILE.exists():
        raise FileNotFoundError(f"Missing candidates file: {CANDIDATES_FILE}")

    with CANDIDATES_FILE.open(encoding="utf-8") as f:
        candidates = [json.loads(line) for line in f if line.strip()]

    # Ground truth totals per question
    gt_strict = defaultdict(int)   # rel >= 2
    gt_lenient = defaultdict(int)  # rel >= 1
    ideal_ratings = defaultdict(list)

    for (qid, _), rel in labels.items():
        ideal_ratings[qid].append(rel)
        if rel >= 2:
            gt_strict[qid] += 1
        if rel >= 1:
            gt_lenient[qid] += 1

    for qid in ideal_ratings:
        ideal_ratings[qid].sort(reverse=True)

    # Organize candidates by (qid, method)
    retrieval_data = defaultdict(dict)
    for row in candidates:
        qid = row["question_id"]
        if qid in eval_qids:
            retrieval_data[qid][row["method"]] = row["results"]

    methods = ["dense", "bm25", "hybrid_rrf"]
    metrics_by_method = {
        m: {
            "hit_lenient": [],
            "hit_strict": [],
            "recall_lenient": [],
            "recall_strict": [],
            "mrr_lenient": [],
            "mrr_strict": [],
            "ndcg": [],
            "per_question": {},
        }
        for m in methods
    }

    for qid in eval_qids:
        ideal = ideal_ratings[qid]
        tot_strict = gt_strict[qid]
        tot_lenient = gt_lenient[qid]

        for m in methods:
            results = retrieval_data[qid].get(m, [])
            top_k = [r for r in results if r["rank"] <= k]
            rel_scores = [labels.get((qid, r["case_name"]), 0) for r in top_k]

            # Hit Rate@K
            h_lenient = 1.0 if any(s >= 1 for s in rel_scores) else 0.0
            h_strict = 1.0 if any(s >= 2 for s in rel_scores) else 0.0

            # Recall@K
            ret_lenient = sum(1 for s in rel_scores if s >= 1)
            ret_strict = sum(1 for s in rel_scores if s >= 2)
            r_lenient = ret_lenient / tot_lenient if tot_lenient > 0 else 0.0
            r_strict = ret_strict / tot_strict if tot_strict > 0 else 0.0

            # MRR@K
            mrr_lenient = 0.0
            for idx, s in enumerate(rel_scores, start=1):
                if s >= 1:
                    mrr_lenient = 1.0 / idx
                    break

            mrr_strict = 0.0
            for idx, s in enumerate(rel_scores, start=1):
                if s >= 2:
                    mrr_strict = 1.0 / idx
                    break

            # nDCG@K
            ndcg = ndcg_at_k(rel_scores, ideal, k=k)

            metrics_by_method[m]["hit_lenient"].append(h_lenient)
            metrics_by_method[m]["hit_strict"].append(h_strict)
            metrics_by_method[m]["recall_lenient"].append(r_lenient)
            metrics_by_method[m]["recall_strict"].append(r_strict)
            metrics_by_method[m]["mrr_lenient"].append(mrr_lenient)
            metrics_by_method[m]["mrr_strict"].append(mrr_strict)
            metrics_by_method[m]["ndcg"].append(ndcg)

            metrics_by_method[m]["per_question"][qid] = {
                "rel_scores": rel_scores,
                "hit_strict": h_strict,
                "hit_lenient": h_lenient,
                "recall_strict": round(r_strict, 4),
                "recall_lenient": round(r_lenient, 4),
                "mrr_strict": round(mrr_strict, 4),
                "mrr_lenient": round(mrr_lenient, 4),
                "ndcg": round(ndcg, 4),
            }

    # Macro averages
    summary = {}
    num_q = len(eval_qids)

    print("\n" + "=" * 80)
    print(f"RETRIEVAL BENCHMARK REPORT (K={k}) | Scope: {sheet_name} ({num_q} Questions)")
    print("=" * 80)
    print(f"{'Method':<12} | {'Hit@5(L)':<8} | {'Recall@5(L)':<11} | {'MRR@5(L)':<8} | {'nDCG@5':<8} | {'Strict MRR':<10} | {'Strict Rec':<10}")
    print("-" * 80)

    for m in methods:
        data = metrics_by_method[m]
        avg_hl = sum(data["hit_lenient"]) / num_q
        avg_hs = sum(data["hit_strict"]) / num_q
        avg_rl = sum(data["recall_lenient"]) / num_q
        avg_rs = sum(data["recall_strict"]) / num_q
        avg_mrrl = sum(data["mrr_lenient"]) / num_q
        avg_mrrs = sum(data["mrr_strict"]) / num_q
        avg_ndcg = sum(data["ndcg"]) / num_q

        summary[m] = {
            "hit_rate_lenient": round(avg_hl, 4),
            "hit_rate_strict": round(avg_hs, 4),
            "recall_lenient": round(avg_rl, 4),
            "recall_strict": round(avg_rs, 4),
            "mrr_lenient": round(avg_mrrl, 4),
            "mrr_strict": round(avg_mrrs, 4),
            "ndcg_at_5": round(avg_ndcg, 4),
            "per_question": data["per_question"],
        }

        print(
            f"{m:<12} | {avg_hl:<8.4f} | {avg_rl:<11.4f} | {avg_mrrl:<8.4f} | {avg_ndcg:<8.4f} | {avg_mrrs:<10.4f} | {avg_rs:<10.4f}"
        )

    print("=" * 80)
    print("Definitions:")
    print("  (L) = Lenient (relevance >= 1: partial or strong)")
    print("  Strict = (relevance >= 2: strong only)")
    print("  nDCG@5 = Graded relevance gain (0=irrelevant, 1=partial, 2=strong)")
    print("=" * 80)

    # Save to JSON
    report = {
        "benchmark_scope": sheet_name,
        "k": k,
        "questions_count": num_q,
        "questions": eval_qids,
        "summary": summary,
    }
    with OUTPUT_METRICS.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved detailed metrics to: {OUTPUT_METRICS.resolve()}")

    return summary


if __name__ == "__main__":
    evaluate()
