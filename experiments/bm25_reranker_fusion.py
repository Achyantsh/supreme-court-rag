"""Offline BM25/reranker rank-fusion experiment.

This experiment intentionally does not alter the application pipeline or
baseline artifacts. It combines persisted top-five rankings only.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_rankings(path: Path) -> dict[str, dict[str, list[dict[str, Any]]]]:
    rankings: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(dict)
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                rankings[row["question_id"]][row["method"]] = row["results"]
    return rankings


def fuse_top_five(
    rankings: dict[str, list[dict[str, Any]]],
    rrf_k: int = 60,
) -> list[dict[str, Any]]:
    """Fuse BM25 and reranker rankings without using relevance labels."""
    scores: defaultdict[str, float] = defaultdict(float)
    records: dict[str, dict[str, Any]] = {}
    for method in ("bm25", "hybrid_reranked"):
        for rank, record in enumerate(rankings[method][:5], start=1):
            doc_id = record["doc_id"]
            scores[doc_id] += 1.0 / (rrf_k + rank)
            records.setdefault(doc_id, record)
    return [
        records[doc_id]
        for doc_id in sorted(scores, key=lambda doc_id: (-scores[doc_id], doc_id))
    ][:5]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path("data/eval_candidates_v2.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/bm25_reranker_fusion_rankings.jsonl"),
    )
    args = parser.parse_args()

    rankings = load_rankings(args.candidates)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for question_id in sorted(rankings):
            fused = fuse_top_five(rankings[question_id])
            handle.write(
                json.dumps(
                    {
                        "question_id": question_id,
                        "method": "bm25_reranker_rrf_top5",
                        "results": [
                            {**record, "rank": rank}
                            for rank, record in enumerate(fused, start=1)
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    print(f"Wrote {len(rankings)} fused rankings to {args.output}")


if __name__ == "__main__":
    main()
