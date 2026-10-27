"""Unified Query & Retrieval Pipeline

Implements:
1. Dense vector search via Qdrant & BAAI/bge-small-en-v1.5
2. Sparse keyword search via BM25Okapi
3. Reciprocal Rank Fusion (RRF, k=60) at judgment level
4. Cross-Encoder Reranking via Xenova/ms-marco-MiniLM-L-6-v2
"""

import json
import re
from collections import defaultdict
from pathlib import Path

from fastembed import TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder
from qdrant_client import QdrantClient

DB_PATH = Path("qdrant_storage")
CHUNKS_FILE = Path("data/chunks.jsonl")

COLLECTION = "supreme_court_2023"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
RERANKER_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"

RRF_K = 60
DEFAULT_CANDIDATE_K = 50
DEFAULT_TOP_K = 5


def tokenize(text):
    """Simple regex tokenizer for BM25 retrieval."""
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def document_key(record):
    """Stable judgment-level identifier, collapsing chunk variations."""
    return (
        record.get("doc_id")
        or record.get("source_pdf")
        or record.get("case_name", "unknown")
    )


class QueryEngine:
    def __init__(self, chunks_path=CHUNKS_FILE, db_path=DB_PATH):
        if not chunks_path.exists():
            raise FileNotFoundError(f"Chunks file missing: {chunks_path}")

        print("Initializing QueryEngine...")
        with chunks_path.open(encoding="utf-8") as f:
            self.chunks = [json.loads(line) for line in f if line.strip()]
        print(f"Loaded {len(self.chunks)} chunks.")

        print("Building BM25 index...")
        from rank_bm25 import BM25Okapi
        tokenized_corpus = [tokenize(c.get("text", "")) for c in self.chunks]
        self.bm25 = BM25Okapi(tokenized_corpus)

        print(f"Loading embedding model: {EMBEDDING_MODEL}...")
        self.embed_model = TextEmbedding(model_name=EMBEDDING_MODEL)

        print(f"Loading cross-encoder reranker: {RERANKER_MODEL}...")
        self.reranker = TextCrossEncoder(model_name=RERANKER_MODEL)

        print(f"Connecting to Qdrant local storage: {db_path}...")
        self.client = QdrantClient(path=str(db_path.resolve()))
        print("QueryEngine ready.")

    def close(self):
        self.client.close()

    def search_dense(self, query, limit=DEFAULT_CANDIDATE_K):
        query_vector = list(self.embed_model.query_embed(query))[0].tolist()
        hits = self.client.query_points(
            collection_name=COLLECTION,
            query=query_vector,
            limit=limit,
            with_payload=True,
        ).points
        return [
            {**point.payload, "score": point.score, "retrieval_method": "dense"}
            for point in hits
            if point.payload
        ]

    def search_bm25(self, query, limit=DEFAULT_CANDIDATE_K):
        tokens = tokenize(query)
        scores = self.bm25.get_scores(tokens)
        top_indices = sorted(
            range(len(scores)),
            key=lambda idx: scores[idx],
            reverse=True,
        )[:limit]
        return [
            {**self.chunks[i], "score": float(scores[i]), "retrieval_method": "bm25"}
            for i in top_indices
            if scores[i] > 0
        ]

    def reciprocal_rank_fusion(self, vector_results, bm25_results, k=RRF_K):
        """Judgment-level Reciprocal Rank Fusion."""
        fused_scores = defaultdict(float)
        records = {}

        for ranked_list in (vector_results, bm25_results):
            seen_docs = set()
            doc_rank = 0

            for record in ranked_list:
                doc_id = document_key(record)
                if doc_id in seen_docs:
                    continue
                seen_docs.add(doc_id)
                doc_rank += 1
                fused_scores[doc_id] += 1.0 / (k + doc_rank)

                if doc_id not in records:
                    records[doc_id] = record

        ranked_docs = sorted(
            fused_scores,
            key=lambda doc_id: fused_scores[doc_id],
            reverse=True,
        )

        return [
            {
                **records[doc_id],
                "score": fused_scores[doc_id],
                "rrf_score": fused_scores[doc_id],
                "retrieval_method": "hybrid_rrf",
            }
            for doc_id in ranked_docs
        ]

    def rerank(self, query, candidate_records, top_k=DEFAULT_TOP_K):
        """Cross-encoder reranking of candidate passages."""
        if not candidate_records:
            return []

        passages = [r.get("text", "")[:1200] for r in candidate_records]
        rerank_scores = list(self.reranker.rerank(query, passages))

        scored_records = []
        for record, score in zip(candidate_records, rerank_scores):
            scored_records.append({
                **record,
                "score": float(score),
                "rerank_score": float(score),
                "retrieval_method": "hybrid_reranked",
            })

        scored_records.sort(key=lambda r: r["rerank_score"], reverse=True)
        return scored_records[:top_k]

    def retrieve(self, query, mode="hybrid_reranked", top_k=DEFAULT_TOP_K, candidate_k=DEFAULT_CANDIDATE_K):
        """Single unified entry point for retrieval."""
        if mode == "dense":
            results = self.search_dense(query, limit=candidate_k)
            return self._dedup_judgments(results)[:top_k]

        elif mode == "bm25":
            results = self.search_bm25(query, limit=candidate_k)
            return self._dedup_judgments(results)[:top_k]

        elif mode == "hybrid_rrf":
            dense_res = self.search_dense(query, limit=candidate_k)
            bm25_res = self.search_bm25(query, limit=candidate_k)
            return self.reciprocal_rank_fusion(dense_res, bm25_res)[:top_k]

        elif mode == "hybrid_reranked":
            dense_res = self.search_dense(query, limit=candidate_k)
            bm25_res = self.search_bm25(query, limit=candidate_k)
            hybrid_res = self.reciprocal_rank_fusion(dense_res, bm25_res)[:20]
            return self.rerank(query, hybrid_res, top_k=top_k)

        else:
            raise ValueError(f"Unknown retrieval mode: {mode}")

    def retrieve_all_methods(self, query, top_k=20, candidate_k=DEFAULT_CANDIDATE_K):
        """Retrieve rankings for all 4 methods sharing intermediate dense and BM25 candidate sets.

        Guarantees exact parity with calling retrieve() individually:
        1. Dense: top_k unique judgments from dense search.
        2. BM25: top_k unique judgments from BM25 search.
        3. Hybrid RRF: top_k unique judgments fused from dense and BM25.
        4. Hybrid Reranked: top 20 RRF judgments reranked by cross-encoder, returning top_k.
        """
        dense_chunks = self.search_dense(query, limit=candidate_k)
        bm25_chunks = self.search_bm25(query, limit=candidate_k)

        dense_res = self._dedup_judgments(dense_chunks)[:top_k]
        bm25_res = self._dedup_judgments(bm25_chunks)[:top_k]

        fused_all = self.reciprocal_rank_fusion(dense_chunks, bm25_chunks)
        hybrid_res = fused_all[:top_k]

        # Application pipeline reranks top 20 RRF judgments
        hybrid_top20 = fused_all[:20]
        reranked_res = self.rerank(query, hybrid_top20, top_k=top_k)

        return {
            "dense": dense_res,
            "bm25": bm25_res,
            "hybrid_rrf": hybrid_res,
            "hybrid_reranked": reranked_res,
        }

    def _dedup_judgments(self, records):
        seen = set()
        deduped = []
        for r in records:
            key = document_key(r)
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        return deduped


if __name__ == "__main__":
    engine = QueryEngine()
    try:
        sample_q = "What factors should courts consider when granting or refusing anticipatory bail?"
        print(f"\nQuery: {sample_q}\n")
        results = engine.retrieve(sample_q, mode="hybrid_reranked", top_k=5)
        for i, r in enumerate(results, 1):
            print(f"[{i}] {r.get('case_name')} (Score: {r.get('rerank_score'):.4f})")
            print(f"    Citation: {r.get('citation')}")
            print(f"    Excerpt: {r.get('text')[:180]}...\n")
    finally:
        engine.close()
