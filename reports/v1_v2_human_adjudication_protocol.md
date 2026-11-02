# Human adjudication protocol — annotation pending

## Correction to the interpretation of earlier results

The existing answer-review scores and `v1_v2_answer_quality_comparison.md` are **provisional AI-assisted draft assessments**, not independent human-reviewed ground truth. The recorded reviewer identity is AI-assisted, and no full-judgment human adjudication was established. In particular, the old report's phrase 'complete valid human labels' overstates the provenance. The old files are preserved unchanged as history, not endorsed as final results. Do not cite their quality improvements as human-validated resume results.

## New annotation package

- Reviewer workbook: `answer_review_v1_v2_human_adjudication.xlsx`.
- 30 paired questions, 60 verbatim answers, 180 initially blank human score cells.
- Both runs contain exactly H01–H30 once, one successful answer per configuration per question, the same recorded model/settings/SDK, and exactly matching ordered retrieval evidence.
- Answer placement is fixed-seed randomized and balanced. The separate coordinator-only JSON key contains allocation, provenance and input hashes; it is not embedded in the workbook. Do not give reviewers the key, generation code, previous scores or comparison report.
- Blinding is best-effort: original citation formatting and prior exposure may reveal a version. Collect reviewer exposure/conflict disclosures.

## Review process

1. Give the reviewer the workbook and access to the local original PDFs under `data/pdfs/`; keep the coordinator key separate.
2. Complete Reviewer details, then assess A and B independently using the unchanged 0/1/2 rubric. Check individual propositions, source adjacency, holdings versus submissions/lower-court reasoning, and statutory/procedural context.
3. Open full judgments whenever an excerpt is insufficient. Record actual PDF pages/paragraphs, source context, per-answer verification statuses and uncertainty. PDF availability does not mean verification, and source membership does not mean semantic support. Do not guess; leave uncertain scores blank pending resolution.
4. Retain independent reviewer records and adjudicate disagreements if a second reviewer is used. Document actual human identity, dates, expertise and sign-off. Do not claim independent double review or full-judgment verification unless actually performed.
5. Return the annotated workbook to the coordinator. STOP: unblinding and final calculation are a later milestone. Do not use the old draft-workbook calculator as final adjudication analysis.

## Interpretation limits

H01–H30 remain a **development set** because their earlier failures informed V2. Even after human adjudication, this package cannot establish fresh held-out generalization, eliminate single-generation variability, establish perfect blinding, or prove a prompt-only causal effect. No final scores are calculated during preparation.
