# Human-Reviewed Answer Quality: Gemini 3.1 Flash-Lite

## Validation

This report is based only on:

- `data/answer_evaluation_3_1_flash_lite_v1.jsonl`
- `data/answer_review_3_1_flash_lite_v1.xlsx`

The Gemini 3.5 Flash-Lite evaluation and its scores are not included.

- Model: `gemini-3.1-flash-lite`
- Held-out questions: 30 (`H01`-`H30`)
- JSONL records: 30
- Unique question IDs: 30
- Successful generations: 30
- Generation success rate: **100.0%**
- Records with retrieved evidence: 30/30
- Duplicate records: none
- Reviewed answers: 30

The workbook contains the existing rubrics:

- **Answer correctness:** 0 = materially wrong/unsupported; 1 = partly
  correct or incomplete; 2 = correct and grounded.
- **Citation support:** 0 = cited case is not supported by its retrieved
  excerpt; 1 = partially supported/ambiguous; 2 = directly supported.
- **Answer completeness:** 0 = fails to address the question; 1 = partially
  addresses it; 2 = sufficiently addresses it from the evidence.

All 30 rows have valid labels in all three fields. No labels were assigned or
changed by this report.

## Descriptive human-review results

The denominator for every table and mean is **30 reviewed, successfully
generated answers**. Generation success is reported separately from the
quality labels.

### Answer correctness

| Label | Count | Proportion |
|---:|---:|---:|
| 0 | 1 | 0.0333 |
| 1 | 13 | 0.4333 |
| 2 | 16 | 0.5333 |

Mean score: **1.5000 / 2.0000**

### Citation support

| Label | Count | Proportion |
|---:|---:|---:|
| 0 | 1 | 0.0333 |
| 1 | 18 | 0.6000 |
| 2 | 11 | 0.3667 |

Mean score: **1.3333 / 2.0000**

### Answer completeness

| Label | Count | Proportion |
|---:|---:|---:|
| 0 | 4 | 0.1333 |
| 1 | 11 | 0.3667 |
| 2 | 15 | 0.5000 |

Mean score: **1.3667 / 2.0000**

These are descriptive human-review scores under the workbook rubric. They are
not automated faithfulness, context-precision, answer-relevancy, or general
legal-accuracy scores. They reflect reviewer judgments for this 30-question
held-out set and the persisted retrieved evidence only.

## Completion

The Gemini 3.1 Flash-Lite answer-generation and human-review evaluation is
complete for all 30 questions. The source JSONL and workbook remain
unchanged. Retrieval rankings, relevance labels, retrieval metrics, and the
separate Gemini 3.5 artifacts were not modified.

