
import json
import re
from collections import defaultdict
from pathlib import Path

from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from rank_bm25 import BM25Okapi


QUESTIONS_FILE = Path("data/eval_questions.json")
CHUNKS_FILE = Path("data/chunks.jsonl")
DB_PATH = Path("qdrant_storage")
OUTPUT_FILE = Path("data/eval_candidates.jsonl")

COLLECTION = "supreme_court_2023"
MODEL_NAME = "BAAI/bge-small-en-v1.5"

CANDIDATE_K = 50
FINAL_K = 10
RRF_K = 60


def tokenize(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def document_key(record):
    # Prefer a stable judgment-level ID, not a chunk ID.
    return (
        record.get("doc_id")
        or record.get("source_pdf")
        or record.get("case_name", "unknown")
    )


def load_jsonl(path):
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def unique_documents(ranked_records, limit=FINAL_K):
    """Keep the highest-ranked chunk for each judgment."""
    results = []
    seen = set()

    for record in ranked_records:
        key = document_key(record)

        if key in seen:
            continue

        seen.add(key)
        results.append(record)

        if len(results) == limit:
            break

    return results


def reciprocal_rank_fusion(vector_records, bm25_records):
    scores = defaultdict(float)
    records = {}

    # Fuse unique judgments, not individual chunks.
    for ranked_list in (vector_records, bm25_records):
        seen_docs = set()
        document_rank = 0

        for record in ranked_list:
            doc_key = document_key(record)

            if doc_key in seen_docs:
                continue

            seen_docs.add(doc_key)
            document_rank += 1

            scores[doc_key] += 1.0 / (RRF_K + document_rank)

            # Keep one representative chunk for each judgment.
            if doc_key not in records:
                records[doc_key] = record

    ranked_docs = sorted(
        scores,
        key=lambda doc_key: scores[doc_key],
        reverse=True,
    )

    return [
        {
            **records[doc_key],
            "rrf_score": scores[doc_key],
        }
        for doc_key in ranked_docs
    ]


def main():
    for path in (QUESTIONS_FILE, CHUNKS_FILE):
        if not path.exists():
            raise FileNotFoundError(f"Missing file: {path}")

    with QUESTIONS_FILE.open(encoding="utf-8") as file:
        questions = json.load(file)

    chunks = load_jsonl(CHUNKS_FILE)

    print("Evaluation questions:", len(questions))
    print("Corpus chunks:", len(chunks))

    print("Building BM25 index...")
    bm25 = BM25Okapi([
        tokenize(record.get("text", ""))
        for record in chunks
    ])

    print("Loading embedding model...")
    embedding_model = TextEmbedding(model_name=MODEL_NAME)

    # Use the local database only after other Qdrant clients are closed.
    client = QdrantClient(path=str(DB_PATH.resolve()))

    try:
        output_rows = []

        for number, item in enumerate(questions, start=1):
            question = item["question"]
            print(f"[{number}/{len(questions)}] {item['id']}: {question}")

            # 1. Dense retrieval
            query_vector = list(
                embedding_model.query_embed(question)
            )[0].tolist()

            vector_hits = client.query_points(
                collection_name=COLLECTION,
                query=query_vector,
                limit=CANDIDATE_K,
                with_payload=True,
            ).points

            vector_ranked = [
                {**point.payload, "dense_score": point.score}
                for point in vector_hits
                if point.payload
            ]

            # 2. BM25 retrieval
            bm25_scores = bm25.get_scores(tokenize(question))
            bm25_indices = sorted(
                range(len(bm25_scores)),
                key=lambda idx: bm25_scores[idx],
                reverse=True,
            )[:CANDIDATE_K]

            bm25_ranked = [
                {**chunks[idx], "bm25_score": float(bm25_scores[idx])}
                for idx in bm25_indices
                if bm25_scores[idx] > 0
            ]

            # 3. Hybrid ranking over chunk-level rankings
            hybrid_ranked = reciprocal_rank_fusion(
                vector_ranked,
                bm25_ranked,
            )

            methods = {
                "dense": vector_ranked,
                "bm25": bm25_ranked,
                "hybrid_rrf": hybrid_ranked,
            }

            for method, ranked in methods.items():
                documents = unique_documents(ranked)

                output_rows.append({
                    "question_id": item["id"],
                    "topic": item["topic"],
                    "question": question,
                    "method": method,
                    "results": [
                        {
                            "rank": rank,
                            "doc_id": document_key(record),
                            "case_name": record.get("case_name"),
                            "citation": record.get("citation"),
                            "decision_date": record.get("decision_date"),
                            "source_pdf": record.get("source_pdf"),
                            "chunk_id": record.get("chunk_id"),
                            "score": record.get(
                                "dense_score",
                                record.get(
                                    "bm25_score",
                                    record.get("rrf_score"),
                                ),
                            ),
                            "text": record.get("text", "")[:1800],
                        }
                        for rank, record in enumerate(documents, start=1)
                    ],
                })

        with OUTPUT_FILE.open("w", encoding="utf-8") as file:
            for row in output_rows:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")

        print("\n--- CANDIDATE GENERATION REPORT ---")
        print("Questions processed:", len(questions))
        print("Retrieval methods:", len(methods))
        print("Candidate rows:", len(output_rows))
        print("Output:", OUTPUT_FILE.resolve())
        print("Expected rows:", len(questions) * 3)

        if len(output_rows) != len(questions) * 3:
            raise RuntimeError("Unexpected number of output rows.")

        print("\nSUCCESS: Candidate results saved.")

    finally:
        client.close()


if __name__ == "__main__":
    main()
