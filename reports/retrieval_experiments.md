# Controlled Retrieval Experiments

## Scope and guardrails

The baseline artifacts were left unchanged. This experiment used only the persisted top-five rankings and existing labels from the 30 development questions. It did not create labels, rerun model inference, tune on an unseen test set, or change the application UI/API.

## Candidate experiments considered

1. **Longer representative evidence for reranking:** rerun the existing cross-encoder on a larger text window or multiple excerpts per judgment. This is motivated by the current 1,200-character reranker input, but requires fresh model inference and evidence-selection code.
2. **Candidate-depth sweep:** rerun retrieval/reranking with larger than 50-chunk candidates. This is deferred because newly surfaced candidates beyond the reviewed pool do not have human labels.
3. **Lexical safeguard / rank fusion:** combine persisted top-five BM25 and hybrid-reranked lists with judgment-level RRF (`k=60`), without labels or score tuning.

## Experiment actually run

**BM25 + hybrid-reranked top-five RRF fusion**: score each document with `1/(60+rank)` in each of the two persisted lists, deduplicate by `doc_id`, and retain the top five. The isolated implementation is [experiments/bm25_reranker_fusion.py](../experiments/bm25_reranker_fusion.py). This is an offline configuration experiment, not a production application change.

## Exact before/after metrics

| Metric | Baseline BM25 | Baseline hybrid reranked | Experiment | Experiment - reranked |
|---|---:|---:|---:|---:|
| Hit@5 lenient | 1.0000 | 1.0000 | 1.0000 | +0.0000 |
| Recall@5 lenient | 0.6451 | 0.6239 | 0.6802 | +0.0562 |
| MRR@5 lenient | 0.9233 | 0.9444 | 0.9222 | -0.0222 |
| nDCG@5 | 0.8521 | 0.7944 | 0.8591 | +0.0647 |

The experiment reaches nDCG **0.8591**, above the reranker's **0.7944** and BM25's **0.8521**. It also reaches lenient Recall@5 **0.6802** versus reranker **0.6239** and BM25 **0.6451**. This is an offline result on the existing development pool, not a generalization claim.

## Decision

Retain the current baseline application behavior. The fusion configuration is promising, but it must be implemented against live retrieval outputs, tested for score/rank stability, and evaluated after human review of any candidates that enter the top five but were not in the original reviewed pool. No production code was changed in this sprint.

## Stronger benchmark plan

- Keep Q01-Q30 and all existing labels as development history; freeze a versioned manifest with question text, topic, corpus snapshot, candidate-generator version, and workbook hash.
- Add 100-150 new questions through a coverage matrix spanning doctrines, procedural stages, statutory sections, constitutional issues, and fact patterns. Have questions drafted and independently reviewed before retrieval tuning.
- Before tuning, reserve 20-30% as a held-out test set stratified by topic and difficulty. Do not inspect held-out labels or use them for configuration decisions.
- For each development question, pool top-10 or top-20 judgment candidates from every method and candidate-depth configuration, deduplicate by `(question_id, doc_id)`, and preserve method/rank/score provenance.
- Provide annotators full judgment metadata and query-relevant evidence excerpts, with access to the full judgment for ambiguous cases. Use two independent reviewers for all candidates, adjudicating disagreements and reporting agreement.
- Freeze labels and candidate rankings before computing final metrics. Report Hit, pooled Recall, MRR, graded nDCG, per-topic results, paired confidence intervals, and zero-relevance questions.
- Run the selected configuration once on held-out questions and report it separately; do not merge held-out results into development tuning.

No larger benchmark or new human labels were fabricated or claimed complete.
