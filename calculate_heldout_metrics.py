"""Score the approved held-out workbook after all labels are entered.

The command fails closed on blank, invalid, duplicate, or missing labels.
"""

import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path

import openpyxl

METHODS = ["dense", "bm25", "hybrid_rrf", "hybrid_reranked", "bm25_reranker_rrf_top5"]
BOOTSTRAP_SEED = 20261027
BOOTSTRAP_SAMPLES = 10000


def dcg(scores: list[int], k: int = 5) -> float:
    return sum((2**score - 1) / math.log2(index + 2) for index, score in enumerate(scores[:k]))


def bootstrap_ci(differences: list[float], seed: int = BOOTSTRAP_SEED) -> tuple[float, float, float]:
    """Return mean and percentile CI, resampling questions as paired units."""
    rng = random.Random(seed)
    sample_means = []
    for _ in range(BOOTSTRAP_SAMPLES):
        sample = [differences[rng.randrange(len(differences))] for _ in differences]
        sample_means.append(sum(sample) / len(sample))
    sample_means.sort()
    return (
        sum(differences) / len(differences),
        sample_means[int(0.025 * BOOTSTRAP_SAMPLES)],
        sample_means[int(0.975 * BOOTSTRAP_SAMPLES)],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=Path("data/heldout_eval_candidates_v1.jsonl"))
    parser.add_argument("--workbook", type=Path, default=Path("data/heldout_relevance_review_v1.xlsx"))
    parser.add_argument("--output", type=Path, default=Path("reports/heldout_metrics_v1.json"))
    args = parser.parse_args()

    rankings: dict[str, dict[str, list[dict]]] = defaultdict(dict)
    with args.candidates.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            question_id = row.get("question_id") or row.get("id")

            if not question_id:
              raise ValueError("Candidate row is missing question ID.")

            rankings[question_id][row["method"]] = row["results"]
    question_ids = set(rankings)
    if not question_ids or any(set(rankings[q]) != set(METHODS) for q in question_ids):
        raise ValueError("Held-out candidates must contain all five methods for every question.")

    workbook = openpyxl.load_workbook(args.workbook, data_only=True)
    if "Relevance Review" not in workbook.sheetnames:
        raise ValueError("Held-out workbook is missing the Relevance Review sheet.")
    sheet = workbook["Relevance Review"]
    headers = list(next(sheet.iter_rows(values_only=True)))
    index = {name: headers.index(name) for name in ("Question ID", "doc_id", "Relevance (0/1/2)")}
    labels: dict[tuple[str, str], int] = {}
    for row in sheet.iter_rows(min_row=2, values_only=True):
        key = (str(row[index["Question ID"]] or "").strip(), str(row[index["doc_id"]] or "").strip())
        value = row[index["Relevance (0/1/2)"]]
        if not key[0] and not key[1]:
            continue
        if value is None or str(value).strip() == "":
            raise RuntimeError(f"Annotation gate blocked: blank label for {key[0]} / {key[1]}.")
        try:
            value = int(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"Annotation gate blocked: invalid label for {key}.") from exc
        if value not in (0, 1, 2) or key in labels:
            raise RuntimeError(f"Annotation gate blocked: invalid or duplicate label for {key}.")
        labels[key] = value
    workbook.close()

    missing = [(q, method, item["doc_id"]) for q in question_ids for method in METHODS for item in rankings[q][method][:5] if (q, item["doc_id"]) not in labels]
    if missing:
        raise RuntimeError(f"Annotation gate blocked: {len(missing)} evaluated candidates are unlabeled.")

    summary = {}
    per_question = {}
    for method in METHODS:
        values = {
            "hit": [], "recall": [], "mrr": [], "ndcg": [],
            "hit_strict": [], "recall_strict": [], "mrr_strict": [],
        }
        for q in sorted(question_ids):
            pool = [value for (question, _), value in labels.items() if question == q]
            scores = [labels[(q, item["doc_id"])] for item in rankings[q][method][:5]]
            relevant = sum(value >= 1 for value in pool)
            strict_relevant = sum(value >= 2 for value in pool)
            ideal = dcg(sorted(pool, reverse=True))
            strict_mrr = next((1 / (index + 1) for index, value in enumerate(scores) if value >= 2), 0.0)
            values["hit"].append(float(any(value >= 1 for value in scores)))
            values["recall"].append(sum(value >= 1 for value in scores) / relevant if relevant else 0.0)
            values["mrr"].append(next((1 / (index + 1) for index, value in enumerate(scores) if value >= 1), 0.0))
            values["ndcg"].append(dcg(scores) / ideal if ideal else (1.0 if dcg(scores) == 0 else 0.0))
            values["hit_strict"].append(float(any(value >= 2 for value in scores)))
            values["recall_strict"].append(sum(value >= 2 for value in scores) / strict_relevant if strict_relevant else 0.0)
            values["mrr_strict"].append(strict_mrr)
            per_question.setdefault(q, {})[method] = {
                "rel_scores": scores,
                "hit": values["hit"][-1],
                "recall": values["recall"][-1],
                "mrr": values["mrr"][-1],
                "ndcg": values["ndcg"][-1],
                "hit_strict": values["hit_strict"][-1],
                "recall_strict": values["recall_strict"][-1],
                "mrr_strict": values["mrr_strict"][-1],
            }
        summary[method] = {key: round(sum(items) / len(items), 4) for key, items in values.items()}

    comparisons = {}
    for other in METHODS:
        if other == "hybrid_rrf":
            continue
        comparisons[f"hybrid_rrf_minus_{other}"] = {}
        for metric in ("hit", "recall", "mrr", "ndcg", "hit_strict", "recall_strict", "mrr_strict"):
            differences = [
                per_question[q]["hybrid_rrf"][metric] - per_question[q][other][metric]
                for q in sorted(question_ids)
            ]
            mean, lower, upper = bootstrap_ci(differences)
            comparisons[f"hybrid_rrf_minus_{other}"][metric] = {
                "mean_difference": round(mean, 4),
                "ci95_lower": round(lower, 4),
                "ci95_upper": round(upper, 4),
            }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "questions_count": len(question_ids),
        "k": 5,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "summary": summary,
        "per_question": per_question,
        "paired_bootstrap_comparisons": comparisons,
        "interpretation_note": "Intervals resample questions as paired units; they are descriptive and do not establish significance on this small held-out set.",
    }, indent=2), encoding="utf-8")
    print(f"Wrote held-out metrics for {len(question_ids)} questions to {args.output}")


if __name__ == "__main__":
    main()
