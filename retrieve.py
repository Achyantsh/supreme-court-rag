import json
import re
from pathlib import Path
from collections import defaultdict

from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from rank_bm25 import BM25Okapi

DB_PATH = Path("qdrant_storage")
CHUNKS_FILE = Path("data/chunks.jsonl")

COLLECTION = "supreme_court_2023"
MODEL_NAME = "BAAI/bge-small-en-v1.5"

TOP_K = 5
CANDIDATE_K = 50
RRF_K = 60


def tokenize(text):
    """Simple tokenizer for BM25 keyword retrieval."""
    return re.findall(r"[a-z0-9]+", text.lower())


def document_key(record):
    """Prefer a stable judgment-level ID, not a chunk ID."""
    return (
        record.get("doc_id")
        or record.get("source_pdf")
        or record.get("case_name", "unknown")
    )


def load_chunks():
    with CHUNKS_FILE.open(encoding="utf-8") as file:
        return [
            json.loads(line)
            for line in file
            if line.strip()
        ]


def reciprocal_rank_fusion(vector_results, bm25_results):
    """Combine rankings at the judgment level without comparing incompatible raw scores."""
    fused_scores = defaultdict(float)
    records = {}

    # Fuse unique judgments, not individual chunks
    for ranked_list in (vector_results, bm25_results):
        seen_docs = set()
        document_rank = 0

        for record in ranked_list:
            doc_key = document_key(record)

            if doc_key in seen_docs:
                continue

            seen_docs.add(doc_key)
            document_rank += 1

            fused_scores[doc_key] += 1.0 / (RRF_K + document_rank)

            # Retain the highest-ranked representative chunk for each judgment
            if doc_key not in records:
                records[doc_key] = record

    ranked_docs = sorted(
        fused_scores,
        key=lambda doc_key: fused_scores[doc_key],
        reverse=True,
    )

    return [
        (records[doc_key], fused_scores[doc_key])
        for doc_key in ranked_docs
    ]


def main():
    if not CHUNKS_FILE.exists():
        raise FileNotFoundError(
            f"Chunks file not found: {CHUNKS_FILE}"
        )

    print("Loading judgment chunks...")
    chunks = load_chunks()
    print(f"Loaded {len(chunks)} chunks.")

    print("Building BM25 keyword index...")
    tokenized_corpus = [
        tokenize(chunk.get("text", ""))
        for chunk in chunks
    ]
    bm25 = BM25Okapi(tokenized_corpus)
    print("BM25 index ready.")

    print("Loading embedding model...")
    embedding_model = TextEmbedding(
        model_name=MODEL_NAME
    )

    client = QdrantClient(
        path=str(DB_PATH.resolve())
    )

    try:
        question = input(
            "\nEnter your legal question: "
        ).strip()

        if not question:
            print("Please enter a question.")
            return

        # 1. Dense vector search
        query_vector = list(
            embedding_model.query_embed(question)
        )[0].tolist()

        vector_hits = client.query_points(
            collection_name=COLLECTION,
            query=query_vector,
            limit=CANDIDATE_K,
            with_payload=True,
        ).points

        vector_results = [
            point.payload
            for point in vector_hits
            if point.payload
        ]

        # 2. BM25 keyword search
        query_tokens = tokenize(question)
        bm25_scores = bm25.get_scores(query_tokens)

        top_indices = sorted(
            range(len(bm25_scores)),
            key=lambda i: bm25_scores[i],
            reverse=True,
        )[:CANDIDATE_K]

        bm25_results = [
            chunks[i]
            for i in top_indices
            if bm25_scores[i] > 0
        ]

        # 3. Reciprocal Rank Fusion at judgment level
        fused_results = reciprocal_rank_fusion(
            vector_results,
            bm25_results,
        )

        print("\n" + "=" * 70)
        print("HYBRID RETRIEVAL RESULTS (VECTOR + BM25 + RRF)")
        print("=" * 70)

        for rank, (record, rrf_score) in enumerate(
            fused_results[:TOP_K], start=1
        ):
            print(f"\nRank: {rank}")
            print(f"RRF score: {rrf_score:.6f}")
            print(
                "Case: "
                f"{record.get('case_name', 'Unknown')}"
            )
            print(
                "Citation: "
                f"{record.get('citation', 'N/A')}"
            )
            print(
                "Decision date: "
                f"{record.get('decision_date', 'N/A')}"
            )
            print(
                "Source PDF: "
                f"{record.get('source_pdf', 'N/A')}"
            )
            print("\nRelevant text:")
            print(record.get("text", "")[:1500])
            print("-" * 70)

    finally:
        client.close()


if __name__ == "__main__":
    main()
