"""Evaluation Candidate Generator for Supreme Court RAG

Generates Top-20 unique judgment rankings across 4 retrieval strategies:
1. Dense Vector Retrieval (bge-small-en-v1.5)
2. Lexical Retrieval (BM25Okapi)
3. Hybrid Fusion (Reciprocal Rank Fusion, k=60)
4. Multi-stage Hybrid + Cross-Encoder Reranker (ms-marco-MiniLM-L-6-v2)

Uses QueryEngine from query_pipeline.py as the unified source of truth.
Outputs candidate rankings to data/eval_candidates_v2.jsonl.
"""

import json
from pathlib import Path
from typing import Dict, Any, List

from query_pipeline import QueryEngine, document_key

QUESTIONS_FILE = Path("data/eval_questions.json")
OUTPUT_FILE = Path("data/eval_candidates_v2.jsonl")

CANDIDATE_K = 50
TOP_K = 20
METHODS = ["dense", "bm25", "hybrid_rrf", "hybrid_reranked"]


def generate_evaluation_candidates(
    questions_file: Path = QUESTIONS_FILE,
    output_file: Path = OUTPUT_FILE,
    candidate_k: int = CANDIDATE_K,
    top_k: int = TOP_K,
    engine: QueryEngine = None,
) -> List[Dict[str, Any]]:
    """Retrieve top-K unique judgments across all 4 methods for evaluation questions."""
    if not questions_file.exists():
        raise FileNotFoundError(f"Missing evaluation questions: {questions_file}")

    with questions_file.open(encoding="utf-8") as f:
        questions = json.load(f)

    print(f"Loaded {len(questions)} evaluation questions from {questions_file}")
    owns_engine = False
    if engine is None:
        engine = QueryEngine()
        owns_engine = True

    try:
        output_rows = []
        seen_pairs = set()

        for idx, item in enumerate(questions, start=1):
            qid = item["id"]
            topic = item.get("topic", "")
            query = item["question"]
            print(f"[{idx:02d}/{len(questions)}] Processing {qid} ({topic}): {query[:60]}...")

            # Retrieve rankings across all four methods using unified pipeline
            method_rankings = engine.retrieve_all_methods(
                query=query,
                top_k=top_k,
                candidate_k=candidate_k,
            )

            for method in METHODS:
                pair_key = (qid, method)
                if pair_key in seen_pairs:
                    raise ValueError(f"Duplicate evaluation record detected for {pair_key}")
                seen_pairs.add(pair_key)

                judgments = method_rankings.get(method, [])

                # Verify no judgment is ranked twice within the same method
                seen_docs = set()
                results = []

                for rank, record in enumerate(judgments, start=1):
                    doc_id = document_key(record)
                    if doc_id in seen_docs:
                        raise ValueError(
                            f"Duplicate judgment '{doc_id}' in ranking for {qid} method '{method}'"
                        )
                    seen_docs.add(doc_id)

                    results.append({
                        "rank": rank,
                        "doc_id": doc_id,
                        "case_name": record.get("case_name"),
                        "citation": record.get("citation"),
                        "decision_date": record.get("decision_date"),
                        "source_pdf": record.get("source_pdf"),
                        "chunk_id": record.get("chunk_id"),
                        "score": record.get("rerank_score", record.get("score")),
                        "text": (record.get("text") or "")[:1800],
                    })

                output_rows.append({
                    "question_id": qid,
                    "topic": topic,
                    "question": query,
                    "method": method,
                    "results": results,
                })

        # Final sanity validations
        expected_rows = len(questions) * len(METHODS)
        if len(output_rows) != expected_rows:
            raise RuntimeError(
                f"Generated {len(output_rows)} rows, but expected {expected_rows} "
                f"({len(questions)} questions x {len(METHODS)} methods)."
            )

        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("w", encoding="utf-8") as f:
            for row in output_rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

        print("\n--- CANDIDATE GENERATION COMPLETE ---")
        print(f"Questions processed: {len(questions)}")
        print(f"Retrieval methods:    {len(METHODS)} ({', '.join(METHODS)})")
        print(f"Ranking records:      {len(output_rows)}")
        print(f"Output saved to:      {output_file.resolve()}")

        return output_rows

    finally:
        if owns_engine:
            engine.close()


def main():
    generate_evaluation_candidates()


if __name__ == "__main__":
    main()
