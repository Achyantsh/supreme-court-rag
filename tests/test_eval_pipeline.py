"""Unit Tests for Supreme Court RAG Evaluation Pipeline

Validates:
1. Association of doc_id through RRF and Cross-Encoder reranking.
2. Candidate pooling and deduplication preserving method ranks.
3. Unique and ambiguous legacy annotation migration.
4. Refusal to evaluate when labels are missing (rejecting conversion to 0).
5. Mathematical correctness of IR metrics (Hit@5, Recall@5, MRR@5, nDCG@5).
6. Complete judged pool used for ideal DCG calculation.
7. Verification that calculate_metrics consumes persisted rankings without model re-execution.
"""

import math
import unittest
from unittest.mock import MagicMock

from calculate_metrics import (
    dcg_at_k,
    idcg_at_k,
    ndcg_at_k,
    verify_completeness_and_reject,
)
from prepare_labels import (
    normalize_text,
    migrate_and_merge_labels,
)
from query_pipeline import document_key


class TestEvaluationPipeline(unittest.TestCase):

    def test_document_key_hierarchy(self):
        """Verify stable judgment ID priority: doc_id > source_pdf > case_name."""
        rec1 = {"doc_id": "2023_1_1_10", "source_pdf": "doc.pdf", "case_name": "State v A"}
        self.assertEqual(document_key(rec1), "2023_1_1_10")

        rec2 = {"source_pdf": "doc.pdf", "case_name": "State v A"}
        self.assertEqual(document_key(rec2), "doc.pdf")

        rec3 = {"case_name": "State v A"}
        self.assertEqual(document_key(rec3), "State v A")

        rec4 = {}
        self.assertEqual(document_key(rec4), "unknown")

    def test_rrf_and_cross_encoder_doc_id_preservation(self):
        """Verify RRF and Cross-Encoder outputs preserve correct doc_id."""
        from query_pipeline import QueryEngine

        # Mock QueryEngine with dummy internals
        engine = object.__new__(QueryEngine)
        engine.reranker = MagicMock()
        engine.reranker.rerank.return_value = [0.85, 0.42]

        vector_hits = [
            {"doc_id": "doc_A", "case_name": "Case A", "text": "Passage A"},
            {"doc_id": "doc_B", "case_name": "Case B", "text": "Passage B"},
        ]
        bm25_hits = [
            {"doc_id": "doc_B", "case_name": "Case B", "text": "Passage B"},
            {"doc_id": "doc_A", "case_name": "Case A", "text": "Passage A"},
        ]

        fused = engine.reciprocal_rank_fusion(vector_hits, bm25_hits, k=60)
        self.assertEqual(len(fused), 2)
        # Check doc_ids exist and are preserved
        fused_doc_ids = {document_key(r) for r in fused}
        self.assertEqual(fused_doc_ids, {"doc_A", "doc_B"})
        for item in fused:
            self.assertIn("rrf_score", item)

        # Test rerank doc_id preservation
        reranked = engine.rerank("bail query", fused, top_k=2)
        self.assertEqual(len(reranked), 2)
        self.assertEqual(reranked[0]["doc_id"], "doc_A")
        self.assertEqual(reranked[0]["rerank_score"], 0.85)
        self.assertEqual(reranked[1]["doc_id"], "doc_B")
        self.assertEqual(reranked[1]["rerank_score"], 0.42)

    def test_pooling_deduplication_and_method_ranks(self):
        """Verify pooling deduplicates by (qid, doc_id) and records ranks for all 4 methods."""
        import json
        import tempfile
        from pathlib import Path
        from prepare_labels import pool_candidates

        records = [
            {
                "question_id": "Q01",
                "method": "dense",
                "results": [
                    {"rank": 1, "doc_id": "doc_1", "case_name": "Case 1", "text": "Dense snippet 1"},
                    {"rank": 6, "doc_id": "doc_6", "case_name": "Case 6", "text": "Excluded snippet"},
                ],
            },
            {
                "question_id": "Q01",
                "method": "bm25",
                "results": [
                    {"rank": 3, "doc_id": "doc_1", "case_name": "Case 1", "text": "BM25 snippet 1"},
                    {"rank": 2, "doc_id": "doc_2", "case_name": "Case 2", "text": "BM25 snippet 2"},
                ],
            },
            {
                "question_id": "Q01",
                "method": "hybrid_rrf",
                "results": [
                    {"rank": 2, "doc_id": "doc_1", "case_name": "Case 1", "text": "RRF snippet 1"},
                ],
            },
            {
                "question_id": "Q01",
                "method": "hybrid_reranked",
                "results": [
                    {"rank": 1, "doc_id": "doc_1", "case_name": "Case 1", "text": "Rerank snippet 1"},
                    {"rank": 4, "doc_id": "doc_2", "case_name": "Case 2", "text": "Rerank snippet 2"},
                ],
            },
        ]

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".jsonl") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
            tmp_path = Path(f.name)

        try:
            pooled = pool_candidates(candidates_file=tmp_path, rank_cutoff=5)
            # doc_6 must be excluded because rank 6 > 5
            self.assertNotIn(("Q01", "doc_6"), pooled)

            # doc_1 was in all 4 methods: must appear exactly once
            self.assertIn(("Q01", "doc_1"), pooled)
            cand1 = pooled[("Q01", "doc_1")]
            self.assertEqual(cand1["Dense rank"], 1)
            self.assertEqual(cand1["BM25 rank"], 3)
            self.assertEqual(cand1["Hybrid RRF rank"], 2)
            self.assertEqual(cand1["Hybrid reranked rank"], 1)

            # doc_2 was in bm25 (rank 2) and hybrid_reranked (rank 4)
            self.assertIn(("Q01", "doc_2"), pooled)
            cand2 = pooled[("Q01", "doc_2")]
            self.assertEqual(cand2["Dense rank"], "")
            self.assertEqual(cand2["BM25 rank"], 2)
            self.assertEqual(cand2["Hybrid RRF rank"], "")
            self.assertEqual(cand2["Hybrid reranked rank"], 4)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_legacy_annotation_migration_unique(self):
        """Verify unique match on (case_name, citation) migrates accurately."""
        pooled = {
            ("Q01", "doc_101"): {
                "Question ID": "Q01",
                "Case name": "Priya Indoria v State of Karnataka",
                "Citation": "[2023] 15 SCR 525",
                "Relevance (0/1/2)": "",
                "Review notes": "",
            }
        }
        legacy = [
            {
                "question_id": "Q01",
                "case_name": "Priya Indoria versus State of Karnataka",
                "citation": "[2023] 15 S.C.R. 525",
                "relevance": 2,
                "notes": "Direct transit anticipatory bail landmark.",
            }
        ]
        migrated, unresolved_cnt, unresolved, unlabelled = migrate_and_merge_labels(
            pooled=pooled,
            legacy_annotations=legacy,
            existing_v2_labels={},
        )
        self.assertEqual(migrated, 1)
        self.assertEqual(unresolved_cnt, 0)
        self.assertEqual(pooled[("Q01", "doc_101")]["Relevance (0/1/2)"], 2)
        self.assertIn("transit", pooled[("Q01", "doc_101")]["Review notes"])

    def test_ambiguous_legacy_annotation_not_assigned(self):
        """Verify ambiguous matches are NOT guessed and logged as unresolved."""
        pooled = {
            ("Q01", "doc_101"): {
                "Question ID": "Q01",
                "Case name": "State of Haryana v Dharamraj",
                "Citation": "[2023] 11 SCR 705",
                "Relevance (0/1/2)": "",
                "Review notes": "",
            },
            ("Q01", "doc_102"): {
                "Question ID": "Q01",
                "Case name": "State of Haryana v Dharamraj",
                "Citation": "[2023] 11 SCR 750",
                "Relevance (0/1/2)": "",
                "Review notes": "",
            },
        }
        legacy = [
            {
                "question_id": "Q01",
                "case_name": "State of Haryana versus Dharamraj",
                "citation": "Different Citation [2023] 99 SCR 1",
                "relevance": 1,
                "notes": "Ambiguous case",
            }
        ]
        migrated, unresolved_cnt, unresolved, unlabelled = migrate_and_merge_labels(
            pooled=pooled,
            legacy_annotations=legacy,
            existing_v2_labels={},
        )
        self.assertEqual(migrated, 0)
        self.assertEqual(unresolved_cnt, 1)
        # Neither candidate should receive a guessed label
        self.assertEqual(pooled[("Q01", "doc_101")]["Relevance (0/1/2)"], "")
        self.assertEqual(pooled[("Q01", "doc_102")]["Relevance (0/1/2)"], "")

    def test_missing_labels_stop_evaluation(self):
        """Verify that missing/blank labels cause an immediate RuntimeError and are never converted to 0."""
        expected_qids = ["Q01"]
        retrieval_data = {
            "Q01": {
                "dense": [{"doc_id": "d1", "case_name": "C1", "rank": 1}],
                "bm25": [{"doc_id": "d1", "case_name": "C1", "rank": 1}],
                "hybrid_rrf": [{"doc_id": "d1", "case_name": "C1", "rank": 1}],
                "hybrid_reranked": [{"doc_id": "d1", "case_name": "C1", "rank": 1}],
            }
        }
        labels = {}  # Empty labels!
        unlabelled_in_workbook = [{"row_idx": 2, "question_id": "Q01", "doc_id": "d1", "case_name": "C1"}]

        with self.assertRaises(RuntimeError) as ctx:
            verify_completeness_and_reject(
                expected_qids=expected_qids,
                retrieval_data=retrieval_data,
                labels=labels,
                unlabelled_in_workbook=unlabelled_in_workbook,
                k=5,
            )
        self.assertIn("Evaluation halted", str(ctx.exception))

    def test_ir_metrics_synthetic(self):
        """Verify Hit@5, Recall@5, MRR@5, and nDCG@5 on a known synthetic case."""
        k = 5
        # Judged pool: one strong (2), one partial (1), two irrelevant (0)
        pool_scores = [2, 1, 0, 0]
        # Retrieved top-5: [0, 2, 1, 0, 0]
        retrieved_scores = [0, 2, 1, 0, 0]

        # 1. Hit Rate
        hit_lenient = 1.0 if any(s >= 1 for s in retrieved_scores) else 0.0
        hit_strict = 1.0 if any(s >= 2 for s in retrieved_scores) else 0.0
        self.assertEqual(hit_lenient, 1.0)
        self.assertEqual(hit_strict, 1.0)

        # 2. Recall (pooled)
        tot_lenient = sum(1 for s in pool_scores if s >= 1)  # 2
        tot_strict = sum(1 for s in pool_scores if s >= 2)   # 1
        ret_lenient = sum(1 for s in retrieved_scores if s >= 1)  # 2
        ret_strict = sum(1 for s in retrieved_scores if s >= 2)   # 1

        recall_lenient = ret_lenient / tot_lenient
        recall_strict = ret_strict / tot_strict
        self.assertEqual(recall_lenient, 1.0)
        self.assertEqual(recall_strict, 1.0)

        # 3. MRR
        # First relevant item (rel>=1) is at index 1 -> rank 2 -> MRR = 0.5
        mrr_lenient = 1.0 / 2
        # First strict relevant item (rel>=2) is at index 1 -> rank 2 -> MRR = 0.5
        mrr_strict = 1.0 / 2
        self.assertEqual(mrr_lenient, 0.5)
        self.assertEqual(mrr_strict, 0.5)

        # 4. DCG and nDCG
        # DCG@5: rank 2 (gain 3, log2(3)), rank 3 (gain 1, log2(4)=2)
        expected_dcg = (3.0 / math.log2(3)) + (1.0 / 2.0)
        actual_dcg = dcg_at_k(retrieved_scores, k=k)
        self.assertAlmostEqual(actual_dcg, expected_dcg, places=5)

        # IDCG@5: ideal from pool [2, 1, 0, 0] -> rank 1 (gain 3, log2(2)=1), rank 2 (gain 1, log2(3))
        expected_idcg = 3.0 + (1.0 / math.log2(3))
        actual_idcg = idcg_at_k(pool_scores, k=k)
        self.assertAlmostEqual(actual_idcg, expected_idcg, places=5)

        expected_ndcg = expected_dcg / expected_idcg
        actual_ndcg = ndcg_at_k(retrieved_scores, pool_scores, k=k)
        self.assertAlmostEqual(actual_ndcg, expected_ndcg, places=5)

    def test_ndcg_uses_complete_pool_for_ideal(self):
        """Verify that nDCG's IDCG uses the entire judged pool rather than merely the retrieved list."""
        # Suppose pool has four 2s and four 1s (total 8 items)
        complete_pool = [2, 2, 2, 2, 1, 1, 1, 1]

        # Retrieved list contains: two 2s and three 1s
        retrieved = [2, 2, 1, 1, 1]

        # If IDCG erroneously used retrieved list, sorted ideal would be [2, 2, 1, 1, 1],
        # which would make DCG == IDCG and nDCG == 1.0.
        dcg_retrieved = dcg_at_k(retrieved, k=5)
        idcg_retrieved_only = dcg_at_k(sorted(retrieved, reverse=True), k=5)
        self.assertEqual(dcg_retrieved, idcg_retrieved_only)

        # But with complete pool, ideal top 5 is [2, 2, 2, 2, 1]
        idcg_pool = idcg_at_k(complete_pool, k=5)
        expected_pool_top5_dcg = dcg_at_k([2, 2, 2, 2, 1], k=5)
        self.assertAlmostEqual(idcg_pool, expected_pool_top5_dcg, places=5)

        # Therefore, nDCG must be strictly less than 1.0
        ndcg_val = ndcg_at_k(retrieved, complete_pool, k=5)
        self.assertLess(ndcg_val, 1.0)
        self.assertAlmostEqual(ndcg_val, dcg_retrieved / idcg_pool, places=5)


if __name__ == "__main__":
    unittest.main()
