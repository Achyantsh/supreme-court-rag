# Answer-quality evaluation protocol

## Scope

This evaluation uses the 30 approved held-out questions and the fixed
`hybrid_rrf` retrieval mode. It does not tune retrieval, change the prompt, or
use held-out relevance labels to select a configuration. The generated
answers, retrieved evidence, citations, model name, and run metadata are
persisted in `reports/answer_evaluation_v1.jsonl`.

The attempted run produced 30 JSONL records: 30 retrieval evidence records,
4 successful Gemini answers (H01-H04), and 26 explicit generation failures
(H05-H30) with HTTP 502 responses from the existing `/api/query` endpoint.
No fallback or fabricated answer was inserted. The workbook therefore remains
an incomplete review gate and cannot support a 30-question answer-quality
result until the answer-generation failure is resolved and the missing
questions are regenerated.

The 502 responses were traced with a direct SDK smoke test. The configured
`gemini-2.5-flash` model and `google-genai` 2.33.0 returned HTTP 429
`RESOURCE_EXHAUSTED`: the Free Tier daily generate-content quota was 20
requests per project/model, with a provider-supplied retry delay of roughly
16 hours. The local API intentionally maps this vendor failure to 502 for
clients, while logging the sanitized upstream status, model, elapsed time,
and error message and returning the upstream status in `X-Upstream-Status`.
The evaluation runner treats this quota response as non-transient and does
not perform a long retry.

## Reproducibility

The generator is [answer_evaluation.py](../answer_evaluation.py). It calls the
existing local FastAPI interfaces:

- `POST /api/retrieve` with `retrieval_mode=hybrid_rrf`, `top_k=5`
- `POST /api/query` with the same question, mode, and cutoff

The JSONL stores the exact retrieval response excerpts and the generated
answer response. The run records the UTC start time, question order, method,
cutoff, and installed `google-genai` version (`2.33.0`). The application
continues to use its existing `rag_engine.py` prompt and Gemini model.

The runner checkpoints one record per question ID, preserves successful
records, and retries only records whose status is `failed`. Existing
retrieval responses are reused for failed records rather than calling
`/api/retrieve` again. After quota or configuration recovery, rerun:

```powershell
.\.venv\Scripts\python.exe answer_evaluation.py --api http://127.0.0.1:8000
```

The command rewrites the JSONL by question ID and does not create duplicate
question records.

## Human review gate

The review workbook is [answer_review_v1.xlsx](answer_review_v1.xlsx). Human
review fields are blank by design. An LLM judge is not treated as ground truth.
Reviewers should check each cited proposition against the exact retrieved
excerpt and consult the original judgment for ambiguous cases.

Rubrics:

- **Answer correctness:** 0 = materially wrong or unsupported; 1 = partly
  correct/incomplete; 2 = correct and grounded in the evidence.
- **Citation support:** 0 = cited case is not supported by its retrieved
  excerpt; 1 = partly supported or ambiguous; 2 = directly supported.
- **Answer completeness:** 0 = does not address the question; 1 = addresses
  some issues; 2 = sufficiently addresses the question from the evidence.

The workbook also preserves question text, generated answer, cited cases and
citations, retrieved judgment IDs, and exact evidence excerpts.

## Separate Flash-Lite run

The explicit model override was tested separately with
`gemini-3.5-flash-lite`. The existing `ThinkingConfig(thinking_budget=0)`
setting is accepted by the production `gemini-2.5-flash` default but is
rejected by Flash-Lite with HTTP 400 `INVALID_ARGUMENT`; the override omits
that optional setting without changing the prompt or production default.

The run artifacts are [answer_evaluation_3_5_flash_lite_v1.jsonl](../data/answer_evaluation_3_5_flash_lite_v1.jsonl)
and [answer_review_3_5_flash_lite_v1.xlsx](../data/answer_review_3_5_flash_lite_v1.xlsx).
All 30 records use exactly `gemini-3.5-flash-lite`, and all 30 reuse persisted
retrieval evidence from the prior run. The smoke test succeeded before the
sequential run. 28 generations succeeded; H23 and H24 failed with provider
HTTP 429 quota exhaustion (returned by the local API as HTTP 502 with
`X-Upstream-Status: 429`). They remain explicit failures and must be retried
later through checkpoint/resume after quota recovery.

Run command:

```powershell
.\.venv\Scripts\python.exe answer_evaluation.py `
  --model gemini-3.5-flash-lite `
  --output data/answer_evaluation_3_5_flash_lite_v1.jsonl `
  --workbook data/answer_review_3_5_flash_lite_v1.xlsx `
  --evidence-source reports/answer_evaluation_v1.jsonl `
  --smoke
```

## Automatic metrics

No automatic faithfulness, answer-relevancy, or context-precision score is
reported in this run. `deepeval`, `ragas`, BERTScore, and
`sentence-transformers` are not installed in the selected environment.
`google-genai` is installed and was verified for answer generation, but it does
not provide an answer-quality ground-truth evaluator. Installing an evaluator
later would require verifying its version and metric API, then reporting its
outputs separately from human labels.

After human review, aggregate the three workbook fields by question and report
the distribution and macro average. Do not call those labels objective truth;
report reviewer identity, adjudication, and agreement if multiple reviewers
participate.

## Citation-grounding check

For each claim containing a case reference, reviewers should identify the
corresponding case/citation in the retrieved evidence and mark Citation
support. A citation that appears in metadata but does not support the stated
proposition should receive 0 or 1, not 2. Abstentions should be reviewed for
whether the evidence was actually insufficient.

## Limitations

The held-out set contains only 30 questions and the corpus is a selected 2023
subset. Generated answers are stochastic model outputs even with the existing
low-temperature configuration. Retrieval and answer generation are separate
API calls, so the persisted retrieval response is the evidence record and the
answer response's citation excerpts are retained for comparison. These
results are a human-review dataset, not a claim of automatic answer quality.

## Opt-in V2 grounding run

The answer generator also supports an explicit, separate `v2` configuration.
It assigns request-local source IDs (`S1`, `S2`, and so on) to the persisted
retrieved passages and requires those IDs after material legal propositions.
The response retains the original retrieved `doc_id`, case name, citation,
decision date, excerpt, rank, and score in the source map. Deterministic
validation reports unknown or malformed source IDs and resolves valid IDs back
to that metadata. A valid source ID proves only that the source was retrieved;
it does not prove that the passage semantically supports every claim.

The production default remains V1. A future V2 development run must use a
separate output and workbook, for example:

```powershell
.\.venv\Scripts\python.exe answer_evaluation.py `
  --answer-version v2 `
  --model gemini-3.1-flash-lite `
  --output data/answer_evaluation_3_1_flash_lite_v2_dev.jsonl `
  --workbook data/answer_review_3_1_flash_lite_v2_dev.xlsx `
  --evidence-source data/answer_evaluation_3_1_flash_lite_v1.jsonl `
  --smoke
```

The V2 run must receive human review before any answer-quality comparison.
Its citation-membership status is an automated traceability check, not a
faithfulness, legal-correctness, or semantic-support score.
