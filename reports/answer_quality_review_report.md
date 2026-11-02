# Answer-Quality Review Summary

## Scope and validation

This report summarizes the human review workbook
`data/answer_review_3_5_flash_lite_v1.xlsx` against
`data/answer_evaluation_3_5_flash_lite_v1.jsonl`.

- Held-out questions: 30 (`H01`-`H30`)
- Evaluation model: `gemini-3.5-flash-lite` for all 30 records
- Retrieval mode: `hybrid_rrf`
- Records with persisted retrieval evidence: 30/30
- Successful generations: 28
- Failed generations: 2 (`H23`, `H24`)
- Unique question IDs: 30/30
- Duplicate question IDs: none

The workbook contains the expected `Answer Review` headers:
`Answer correctness (0/1/2)`, `Citation support (0/1/2)`, and
`Answer completeness (0/1/2)`. The rubric is:

- Correctness: 0 materially wrong/unsupported; 1 partly correct/incomplete;
  2 correct and grounded.
- Citation support: 0 unsupported citation; 1 partially supported/ambiguous;
  2 directly supported.
- Completeness: 0 does not address the question; 1 partially addresses it;
  2 sufficiently addresses it from the evidence.

All three scoring fields are complete and valid for the 28 successful
generations. H23 and H24 are intentionally blank and are excluded from all
quality summaries because their generation failed.

## Human-reviewed descriptive summaries

The denominator for each table is 28 successfully generated and reviewed
answers. These are descriptive workbook labels, not automatic metrics and not
proof of general model faithfulness.

### Answer correctness

| Label | Count | Proportion |
|---:|---:|---:|
| 0 | 0 | 0.0000 |
| 1 | 2 | 0.0714 |
| 2 | 26 | 0.9286 |

Mean score: **1.9286 / 2.0000**

### Citation support

| Label | Count | Proportion |
|---:|---:|---:|
| 0 | 0 | 0.0000 |
| 1 | 0 | 0.0000 |
| 2 | 28 | 1.0000 |

Mean score: **2.0000 / 2.0000**

### Answer completeness

| Label | Count | Proportion |
|---:|---:|---:|
| 0 | 0 | 0.0000 |
| 1 | 2 | 0.0714 |
| 2 | 26 | 0.9286 |

Mean score: **1.9286 / 2.0000**

Correctness and citation support are reported separately. Citation-support
labels measure the workbook's direct support rubric; they do not establish
faithfulness, truth beyond the retrieved excerpts, or legal correctness in
general.

## Generation failures

| Question | Local API status | Upstream status | Treatment |
|---|---:|---:|---|
| H23 | 502 | 429 quota exhaustion | Excluded; retry after quota recovery |
| H24 | 502 | 429 quota exhaustion | Excluded; retry after quota recovery |

Neither failed record was treated as an incorrect answer. No answer-quality
metric was calculated for these questions.

## Completion status and next step

The annotation review is complete for the 28 answers that were generated.
The **30-question answer-quality evaluation is not complete** because H23 and
H24 still need successful generation and human review. After quota recovery,
rerun the model-specific evaluator with the same output path; checkpoint/resume
will preserve the 28 successful records and retry the failed questions. Then
review the newly generated H23/H24 answers before updating this summary.

