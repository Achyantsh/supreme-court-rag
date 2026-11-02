# Final held-out retrieval comparison

This report uses the separately reviewed held-out set of 30 questions and 292 pooled question-judgment labels. It preserves the original development and held-out artifacts. Bootstrap resamples questions as paired units with seed `20261027` and 10,000 samples. Intervals are descriptive; no statistical significance is claimed unless an interval excludes zero.

## Metrics

| Method | Hit@5 | Recall@5 | MRR@5 | nDCG@5 | Strict Hit@5 | Strict Recall@5 | Strict MRR@5 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Dense | 1.0000 | 0.5525 | 0.9400 | 0.7292 | 0.9333 | 0.5990 | 0.7578 |
| BM25 | 1.0000 | 0.5544 | 0.9583 | 0.7988 | 0.9333 | 0.6509 | 0.8361 |
| Hybrid RRF | 1.0000 | 0.6138 | 0.9500 | 0.8178 | 0.9667 | 0.6710 | 0.8472 |
| Hybrid reranked | 0.9667 | 0.5789 | 0.9500 | 0.7811 | 0.9000 | 0.5731 | 0.7789 |
| BM25 + reranked fusion | 0.9667 | 0.5870 | 0.9444 | 0.8043 | 0.9333 | 0.6534 | 0.7750 |

## Paired Hybrid RRF comparisons

| Comparison | Metric | Mean difference | 95% CI |
|---|---|---:|---:|
| hybrid rrf minus dense | hit | +0.0000 | [+0.0000, +0.0000] |
| hybrid rrf minus dense | recall | +0.0613 | [+0.0203, +0.1094] |
| hybrid rrf minus dense | mrr | +0.0100 | [-0.0400, +0.0600] |
| hybrid rrf minus dense | ndcg | +0.0887 | [+0.0491, +0.1285] |
| hybrid rrf minus dense | hit_strict | +0.0333 | [+0.0000, +0.1000] |
| hybrid rrf minus dense | recall_strict | +0.0720 | [+0.0233, +0.1243] |
| hybrid rrf minus dense | mrr_strict | +0.0894 | [+0.0106, +0.1756] |
| hybrid rrf minus bm25 | hit | +0.0000 | [+0.0000, +0.0000] |
| hybrid rrf minus bm25 | recall | +0.0594 | [+0.0033, +0.1244] |
| hybrid rrf minus bm25 | mrr | -0.0083 | [-0.0667, +0.0500] |
| hybrid rrf minus bm25 | ndcg | +0.0191 | [-0.0425, +0.0781] |
| hybrid rrf minus bm25 | hit_strict | +0.0333 | [+0.0000, +0.1000] |
| hybrid rrf minus bm25 | recall_strict | +0.0201 | [-0.0798, +0.1282] |
| hybrid rrf minus bm25 | mrr_strict | +0.0111 | [-0.0722, +0.0917] |
| hybrid rrf minus hybrid reranked | hit | +0.0333 | [+0.0000, +0.1000] |
| hybrid rrf minus hybrid reranked | recall | +0.0349 | [-0.0197, +0.1133] |
| hybrid rrf minus hybrid reranked | mrr | +0.0000 | [-0.0667, +0.0667] |
| hybrid rrf minus hybrid reranked | ndcg | +0.0367 | [-0.0342, +0.1106] |
| hybrid rrf minus hybrid reranked | hit_strict | +0.0667 | [+0.0000, +0.1667] |
| hybrid rrf minus hybrid reranked | recall_strict | +0.0978 | [-0.0019, +0.2039] |
| hybrid rrf minus hybrid reranked | mrr_strict | +0.0683 | [-0.0278, +0.1750] |
| hybrid rrf minus bm25 reranker rrf top5 | hit | +0.0333 | [+0.0000, +0.1000] |
| hybrid rrf minus bm25 reranker rrf top5 | recall | +0.0269 | [-0.0269, +0.1056] |
| hybrid rrf minus bm25 reranker rrf top5 | mrr | +0.0056 | [-0.0667, +0.0778] |
| hybrid rrf minus bm25 reranker rrf top5 | ndcg | +0.0136 | [-0.0493, +0.0776] |
| hybrid rrf minus bm25 reranker rrf top5 | hit_strict | +0.0333 | [+0.0000, +0.1000] |
| hybrid rrf minus bm25 reranker rrf top5 | recall_strict | +0.0176 | [-0.0731, +0.1159] |
| hybrid rrf minus bm25 reranker rrf top5 | mrr_strict | +0.0722 | [-0.0194, +0.1722] |

## Interpretation

- Hybrid RRF is the best held-out method on nDCG@5 (0.8178), lenient Recall@5 (0.6138), strict Hit@5 (0.9667), strict Recall@5 (0.6710), and strict MRR@5 (0.8472).
- Hybrid RRF beats Dense on nDCG; its paired 95% interval excludes zero in the generated report.
- Hybrid RRF has higher point estimates than BM25, hybrid reranking, and BM25 + reranked fusion on nDCG and recall, but the paired intervals for those comparisons include zero. These results do not establish statistically significant superiority.
- Hybrid reranking and the fusion method have lower lenient Hit@5 (0.9667) than the other methods (1.0000).
- The test set has only 30 questions, and pooled recall is limited to the reviewed candidate pool rather than the complete 800-judgment corpus.

## Per-question results

Per-question values, including strict metrics and relevance score sequences, are persisted in `reports/heldout_final_metrics_v1.json` under `per_question`.
