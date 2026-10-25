# Project Status & Repository Audit

**Project:** Eval-Driven Production RAG over Indian Supreme Court Judgments  
**Date of Audit:** October 25, 2026  
**Status:** All Minor Fixes Applied & Verified

---

## 1. Executive Summary

All primary data preparation and indexing stages are completed and verified:
- **Corpus:** 800 English Supreme Court judgments (2023) parsed into `data/judgments.jsonl`.
- **Chunks:** 21,451 chunks in `data/chunks.jsonl` (~2,200 chars / 250 overlap).
- **Qdrant Vector Database:** 21,451 embeddings (`BAAI/bge-small-en-v1.5`, 384 dimensions) indexed in collection `supreme_court_2023`.
- **Evaluation Questions:** 30 validated questions across 8 legal topics in `data/eval_questions.json`.
- **Candidate Generation:** Top-10 candidates per method generated in `data/eval_candidates.jsonl` (90 rows).
- **Excel Review Workbook Generator (`prepare_labels.py`):** Fully operational (`openpyxl` 3.1.5 installed).
- **Workbook Status:**
  - `data/relevance_review.xlsx` exists (34 unlabelled Pilot rows, 241 All Top-5 rows).
  - `data/relevance_review_pilot_labeled.xlsx` also exists, containing assistant pre-reviewed pilot annotations and detailed notes across all 34 pairs for human spot-checking.

---

## 2. Verification of Core Files

| File | Status | Verification Details |
|---|---|---|
| `retrieve.py` | **Synchronized & Fixed** | 185 lines. Updated to judgment-level RRF matching `eval.py` (`document_key` + chunk deduplication before RRF, `CANDIDATE_K = 50`). |
| `prepare_labels.py` | **Fixed & Operational** | 308 lines. Key name `"Evidence excerpt"` made consistent; added graceful `PermissionError` handling if open in Excel. |
| `.gitignore` | **Fixed** | Properly ignores 400MB+ corpus binaries while whitelisting evaluation benchmarks (`eval_questions.json`, `relevance_review.xlsx`, etc.). |
| `eval.py` | **Operational** | 229 lines. Generates 10 unique judgments per method (`dense`, `bm25`, `hybrid_rrf`). Correctly implements judgment-level RRF collapsing chunks to unique documents before scoring. |
| `data/eval_candidates.jsonl` | **Verified** | 1,865,685 bytes (~1.86 MB). Exactly 90 rows (30 questions × 3 retrieval methods). Top-10 ranked judgments per row with scores and text snippets. |
| `data/chunks.jsonl` | **Verified** | 53,354,502 bytes (~53.3 MB). Exactly 21,451 lines. Schema: `chunk_id`, `doc_id`, `chunk_index`, `case_name`, `citation`, `year`, `decision_date`, `source_pdf`, `text`. |
| `data/eval_questions.json` | **Verified** | 4,291 bytes. Exactly 30 questions covering 8 topics. |
| `data/relevance_review.xlsx` | **Generated** | 225,370 bytes. Contains sheets: `Instructions`, `Pilot Review` (34 rows, empty labels), `All Top-5` (241 rows, empty labels). |
| `data/relevance_review_pilot_labeled.xlsx` | **Existing Pilot Draft** | 229,501 bytes. Contains assistant draft labels (10 Strong, 13 Partial, 11 Irrelevant) + `Pilot Summary` sheet. |

---

## 3. Discrepancies Resolved

1. **RRF Granularity Mismatch (`retrieve.py` vs `eval.py`):** Fixed. `retrieve.py` now implements judgment-level collapsing before RRF score accumulation.
2. **Git Root Misalignment:** Resolved. Initialized local git repository in `C:\Users\achya\supreme-court-rag\.git`.
3. **`.gitignore` Data Exclusion:** Resolved. Added whitelist exceptions for evaluation JSON/JSONL and Excel review workbooks.
4. **Excel Workbook Field Name Case Discrepancy:** Resolved. Standardized on `"Evidence excerpt"` across all dictionary keys and column lookups.
5. **Excel File Lock Handling:** Added friendly notification in `prepare_labels.py` if `relevance_review.xlsx` is open in Microsoft Excel.

---

## 4. Current Pilot Review Status (Q01–Q05)

The pilot candidate pool contains **34 unique question–judgment pairs** across Q01 to Q05.

In `data/relevance_review_pilot_labeled.xlsx`, the breakdown is:
- **Label 2 (Strongly Relevant):** 10 candidates
- **Label 1 (Partially Relevant):** 13 candidates
- **Label 0 (Irrelevant):** 11 candidates

### Pilot Breakdown by Question:
- **Q01 (Anticipatory bail factors):** 4 Strong, 2 Partial, 0 Irrelevant (cleanest query).
- **Q02 (Continuation after chargesheet):** 2 Strong, 1 Partial, 4 Irrelevant (default-bail false positives).
- **Q03 (Blanket anticipatory bail):** 3 Strong, 3 Partial, 1 Irrelevant.
- **Q04 (Flee from justice assessment):** 0 Strong, 6 Partial, 1 Irrelevant (general lists mention fleeing, but lack detailed assessment rules).
- **Q05 (Transit anticipatory bail):** 1 Strong (*Priya Indoria*), 1 Partial, 5 Irrelevant (narrow topic).

---

## 5. Next Steps for Project Advancement

1. **User Action:** Open [data/relevance_review_pilot_labeled.xlsx](file:///C:/Users/achya/supreme-court-rag/data/relevance_review_pilot_labeled.xlsx), skim the 34 pilot candidates in the `Pilot Review` sheet, and verify whether you agree with the labels (0, 1, 2) or want to change any.
2. **Agent Action:** Implement `calculate_metrics.py` to automatically compute Hit@5, Recall@5, MRR@5, and nDCG@5 across dense, BM25, and hybrid retrieval.
