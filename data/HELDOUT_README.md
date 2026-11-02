# Held-out evaluation gate

`eval_questions_heldout_draft.json` contains 30 proposed questions. They are
not approved evaluation questions and must not be used for tuning or scoring.

Before retrieval is generated, review every question for legal scope,
duplication, clarity, and topic coverage. Only after approval, copy the
reviewed file to the exact versioned path expected by the generator:

```powershell
Copy-Item data\eval_questions_heldout_draft.json data\eval_questions_heldout_approved_v1.json
python prepare_heldout.py --questions data\eval_questions_heldout_approved_v1.json
```

The generator refuses the draft filename and writes new artifacts without
touching development data:

- `data/heldout_eval_candidates_v1.jsonl`
- `data/heldout_relevance_review_v1.xlsx`

The workbook contains blank relevance cells. Do not run held-out metrics until
all pooled candidates have been reviewed. The final evaluator must reject
blank or invalid labels.
