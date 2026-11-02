# Retrieval Error Analysis

This report uses only persisted rankings and the existing 280 human labels. Bootstrap uses seed `20261027` and 10,000 question-level resamples. Confidence intervals describe paired differences on this development benchmark; they are not a held-out test estimate.

## Macro averages

| Method | Hit@5 | Recall@5 | MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| Dense | 1.0000 | 0.5723 | 0.9222 | 0.7657 |
| BM25 | 1.0000 | 0.6451 | 0.9233 | 0.8521 |
| Hybrid RRF | 1.0000 | 0.6264 | 0.9500 | 0.8270 |
| Hybrid reranked | 1.0000 | 0.6239 | 0.9444 | 0.7944 |

## Topic-wise results

### `anticipatory_bail` (n=7)

| Method | Hit@5 | Recall@5 | MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| BM25 | 1.0000 | 0.7219 | 1.0000 | 0.9256 |
| Hybrid RRF | 1.0000 | 0.7696 | 0.9286 | 0.9048 |
| Hybrid reranked | 1.0000 | 0.7457 | 1.0000 | 0.8985 |

### `arrest` (n=5)

| Method | Hit@5 | Recall@5 | MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| BM25 | 1.0000 | 0.7333 | 0.8000 | 0.7395 |
| Hybrid RRF | 1.0000 | 0.8000 | 0.9000 | 0.8627 |
| Hybrid reranked | 1.0000 | 0.6750 | 0.7667 | 0.6505 |

### `bail` (n=2)

| Method | Hit@5 | Recall@5 | MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| BM25 | 1.0000 | 0.6071 | 1.0000 | 0.8783 |
| Hybrid RRF | 1.0000 | 0.6071 | 1.0000 | 0.8065 |
| Hybrid reranked | 1.0000 | 0.5446 | 1.0000 | 0.7787 |

### `constitutional_rights` (n=3)

| Method | Hit@5 | Recall@5 | MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| BM25 | 1.0000 | 0.6603 | 1.0000 | 0.8437 |
| Hybrid RRF | 1.0000 | 0.5270 | 1.0000 | 0.7650 |
| Hybrid reranked | 1.0000 | 0.6603 | 1.0000 | 0.8563 |

### `corruption` (n=3)

| Method | Hit@5 | Recall@5 | MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| BM25 | 1.0000 | 0.6131 | 1.0000 | 0.9644 |
| Hybrid RRF | 1.0000 | 0.4405 | 1.0000 | 0.6996 |
| Hybrid reranked | 1.0000 | 0.4488 | 1.0000 | 0.8045 |

### `criminal_procedure` (n=3)

| Method | Hit@5 | Recall@5 | MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| BM25 | 1.0000 | 0.4643 | 0.5667 | 0.4978 |
| Hybrid RRF | 1.0000 | 0.3690 | 0.8333 | 0.5544 |
| Hybrid reranked | 1.0000 | 0.5000 | 1.0000 | 0.5049 |

### `preventive_detention` (n=3)

| Method | Hit@5 | Recall@5 | MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| BM25 | 1.0000 | 0.7222 | 1.0000 | 0.9798 |
| Hybrid RRF | 1.0000 | 0.6667 | 1.0000 | 0.9477 |
| Hybrid reranked | 1.0000 | 0.7222 | 1.0000 | 0.9964 |

### `quashing` (n=4)

| Method | Hit@5 | Recall@5 | MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| BM25 | 1.0000 | 0.5099 | 1.0000 | 0.9434 |
| Hybrid RRF | 1.0000 | 0.5456 | 1.0000 | 0.9125 |
| Hybrid reranked | 1.0000 | 0.5099 | 0.8750 | 0.8121 |

## Paired differences and bootstrap 95% CIs

| Comparison | Metric | Mean difference | 95% bootstrap CI |
|---|---|---:|---:|
| Hybrid RRF - BM25 | recall_lenient | -0.0187 | [-0.0792, 0.0446] |
| Hybrid RRF - BM25 | mrr_lenient | 0.0267 | [-0.0500, 0.1033] |
| Hybrid RRF - BM25 | ndcg_at_5 | -0.0251 | [-0.0924, 0.0419] |
| Hybrid RRF - Hybrid reranked | recall_lenient | 0.0025 | [-0.0780, 0.0876] |
| Hybrid RRF - Hybrid reranked | mrr_lenient | 0.0056 | [-0.0833, 0.0889] |
| Hybrid RRF - Hybrid reranked | ndcg_at_5 | 0.0326 | [-0.0376, 0.1067] |

## Reranking transitions

Reranking changed the top-five membership/rank relative to Hybrid RRF. Across all persisted RRF items, **67** items that were in RRF top five moved below reranked rank five; **43** of those were leniently relevant and **25** were strictly relevant. This is descriptive and includes judgments whose reranked rank is available in the persisted top-20 list.

| Question | Topic | doc_id | RRF rank | Reranked rank | Label |
|---|---|---|---:|---:|---:|
| Q14 | quashing | `2023_5_354_371` | 5 | 6 | 2 |
| Q01 | anticipatory_bail | `2023_3_476_497` | 4 | 6 | 2 |
| Q09 | arrest | `2023_16_743_764` | 3 | 6 | 2 |
| Q03 | anticipatory_bail | `2023_2_1112_1134` | 3 | 7 | 2 |
| Q12 | quashing | `2023_6_655_668` | 3 | 7 | 2 |
| Q14 | quashing | `2023_13_847_860` | 4 | 8 | 2 |
| Q11 | quashing | `2023_14_412_423` | 1 | 6 | 2 |
| Q11 | quashing | `2023_5_354_371` | 2 | 7 | 2 |
| Q15 | corruption | `2023_2_1112_1134` | 3 | 8 | 2 |
| Q21 | constitutional_rights | `2023_15_525_589` | 2 | 7 | 2 |
| Q26 | criminal_procedure | `2023_13_847_860` | 2 | 8 | 2 |
| Q27 | criminal_procedure | `2023_11_507_519` | 4 | 10 | 2 |
| Q28 | criminal_procedure | `2023_10_411_426` | 4 | 10 | 2 |
| Q09 | arrest | `2023_10_1184_1195` | 2 | 9 | 2 |
| Q11 | quashing | `2023_14_55_61` | 3 | 10 | 2 |
| Q15 | corruption | `2023_10_502_516` | 2 | 9 | 2 |
| Q18 | preventive_detention | `2023_12_853_931` | 3 | 10 | 2 |
| Q01 | anticipatory_bail | `2023_15_525_589` | 1 | 10 | 2 |
| Q18 | preventive_detention | `2023_15_480_512` | 4 | 14 | 2 |
| Q09 | arrest | `2023_12_853_931` | 5 | 16 | 2 |

## Measured facts versus hypotheses

- **Measured:** BM25 has higher nDCG than the reranker by 0.0577 and higher lenient recall by 0.0212.
- **Measured:** reranking lowers nDCG relative to RRF on the macro average by 0.0326 and lowers strict recall by 0.0394.
- **Measured:** 43 leniently relevant RRF top-five judgments are pushed below reranked rank five; the examples above include 25 strict-relevance cases.
- **Hypothesis:** the persisted reranking path scores only the first 1,200 characters of each representative passage (`query_pipeline.py`) and the candidate file itself stores a maximum 1,800-character excerpt. Legal ratio or exception language later in a judgment chunk may therefore be absent from the reranker input. This requires a controlled longer-context experiment to prove.
- **Hypothesis:** BM25 benefits from exact statutory and doctrinal terms, while the general MS MARCO cross-encoder may prefer broad semantic similarity over legal issue-specific graded relevance. The current benchmark cannot isolate model-domain mismatch from excerpt selection or candidate-depth effects.


## Interpretation

Hybrid RRF is the strongest first-hit method by lenient MRR, while BM25 is the strongest graded-ranking baseline. The largest actionable failure is not recall collapse but reranking displacement: relevant RRF candidates, including strictly relevant cases, are repeatedly pushed below the top five. Any deployment-facing reranker change should therefore be evaluated against the current BM25/RRF baselines and should preserve a lexical safeguard.
