# Evaluation Audit Report

Generated from the frozen v2 artifacts on 2026-10-27. The source rankings, workbook labels, and saved metrics were not modified.

## Baseline validity

The full baseline is **valid for the stated pooled benchmark**. Re-running `calculate_metrics.py --scope full --k 5` against `data/eval_candidates_v2.jsonl` and `data/relevance_review_v2.xlsx` reproduced the saved report values and metadata. This validates reproducibility, not generalization beyond the reviewed pool.

- Questions: 30 (Q01-Q30)
- Persisted ranking rows: 120 (30 questions x 4 methods)
- Human-reviewed unique pairs: 280
- Label counts: 0 = 96, 1 = 70, 2 = 114
- Top-5 candidates missing labels: 0
- Duplicate persisted judgments within a method: 0
- Rank-field inconsistencies: 0
- Strict zero-relevance questions: Q04, Q07, Q17, Q30

## Saved baseline metrics

| Method | Hit@5 lenient | Recall@5 lenient | MRR@5 lenient | nDCG@5 | Hit@5 strict | Recall@5 strict | MRR@5 strict |
|---|---:|---:|---:|---:|---:|---:|---:|
| dense | 1.0000 | 0.5723 | 0.9222 | 0.7657 | 0.8667 | 0.5840 | 0.7722 |
| bm25 | 1.0000 | 0.6451 | 0.9233 | 0.8521 | 0.8333 | 0.6631 | 0.8000 |
| hybrid_rrf | 1.0000 | 0.6264 | 0.9500 | 0.8270 | 0.8667 | 0.6341 | 0.8167 |
| hybrid_reranked | 1.0000 | 0.6239 | 0.9444 | 0.7944 | 0.8333 | 0.5947 | 0.7861 |

## Metric implementation audit

- **Hit@5:** implemented as whether any of the first five labels meets the threshold; the report stores lenient `>=1` and strict `>=2` variants.
- **Pooled Recall@5:** counts retrieved relevant judgments in the first five and divides by all relevant judgments in that question's reviewed pool. The denominator is not the full 800-document corpus.
- **MRR@5:** uses the reciprocal rank of the first retrieved label meeting the threshold, or zero when none appears in the first five.
- **nDCG@5:** uses exponential gain `2^rel - 1`, logarithmic rank discount, and derives IDCG by sorting the complete judged pool for the question before truncating to five. This is correct for the declared pooled protocol.
- **Missing labels:** `load_ground_truth` records blank, non-integer, and out-of-range values as incomplete; `verify_completeness_and_reject` raises before metrics are written if any workbook row or evaluated top-five item is unlabelled. It does not silently convert missing values to zero.

## Comparability and caveats

All four methods use the same 30 questions, the same `(question_id, doc_id)` labels, the same K=5 metric cutoff, and the same pooled judged candidates. The persisted generator uses a common candidate depth of 50 chunks for dense and BM25, judgment-level RRF, and a top-20 RRF judgment set for the cross-encoder before returning its top 20 persisted rankings. Therefore the methods are comparable at the final top-five evaluation cutoff, but the reranker is a staged method with a distinct top-20 input boundary; candidate depth is not an independently varied factor in this benchmark.

The full candidate file contains up to 20 persisted judgments per method, while labels cover the pooled top-five union. Metrics intentionally inspect only top five and reject missing labels there. Any analysis of ranks beyond five must be treated as descriptive unless new human labels are collected.

## Strengths and weaknesses supported by the data

- **Dense:** perfect lenient Hit@5, but lowest nDCG (0.7657) and lowest lenient Recall@5 (0.5723); it finds some related material but places graded relevance less effectively.
- **BM25:** highest nDCG (0.8521), highest lenient Recall@5 (0.6451), and strong MRR (0.9233), indicating that exact legal vocabulary and statutory phrases are valuable for this question set.
- **Hybrid RRF:** highest lenient MRR (0.9500) and tied-best strict Hit@5 (0.8667), combining signals effectively for the first relevant judgment, though it trails BM25 on nDCG and recall.
- **Hybrid reranked:** improves lenient MRR over BM25 slightly (0.9444 vs 0.9233) and over dense, but underperforms BM25 and RRF on nDCG (0.7944) and strict recall (0.5947). This is a measured ranking-quality weakness, not evidence that the cross-encoder itself is intrinsically unsuitable.

## Limitation

Pooled recall is optimistic and incomplete: it measures recovery of relevant judgments among the union of candidates selected for review, not recall over the unreviewed 800-document corpus. Human labels are preserved and were not regenerated.
