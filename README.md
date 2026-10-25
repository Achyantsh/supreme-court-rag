# Eval-Driven Production RAG over Indian Supreme Court Judgments

An evaluation-first, production-grade Retrieval-Augmented Generation (RAG) system built over 800 selected 2023 Indian Supreme Court judgments.

The goal of this project is to rigorously benchmark and compare retrieval methods—**Dense Vector Search**, **BM25 Keyword Search**, and **Hybrid Retrieval with Reciprocal Rank Fusion (RRF)**—using empirical IR metrics (`Hit Rate@5`, `Recall@5`, `MRR@5`, `nDCG@5`) on a human-verified ground-truth evaluation set.

---

## Architecture Overview

```
                      +---------------------------------------+
                      | Indian Supreme Court Judgments (2023) |
                      |    800 PDFs (~40.6M characters)       |
                      +---------------------------------------+
                                          |
                                 [ build_corpus.py ]
                                          |
                                          v
                      +---------------------------------------+
                      |           judgments.jsonl             |
                      +---------------------------------------+
                                          |
                                 [ chunk_corpus.py ]
                                          |
                                          v
                      +---------------------------------------+
                      |             chunks.jsonl              |
                      |   21,451 Chunks (2,200 chars / 250 ov) |
                      +---------------------------------------+
                                          |
                       +------------------+------------------+
                       |                                     |
                       v                                     v
           [ Dense Embedding Index ]               [ BM25 Lexical Index ]
        Model: BAAI/bge-small-en-v1.5                  rank-bm25
          Qdrant Local (qdrant_storage/)           In-memory tokenized
                       |                                     |
                       +------------------+------------------+
                                          |
                                          v
                           +------------------------------+
                           |  Judgment-level Fusion (RRF) |
                           |           RRF_K = 60         |
                           +------------------------------+
                                          |
                                          v
                           +------------------------------+
                           |  Evaluation & Benchmarking   |
                           |   30 Curated Legal Questions |
                           |   Pooled Relevance Review    |
                           +------------------------------+
```

---

## Technical Stack & Environment

- **OS:** Windows (PowerShell)
- **Python:** 3.13.1
- **Virtual Environment:** `.venv/`
- **Vector Database:** Qdrant (Local disk mode at `qdrant_storage/`)
- **Embedding Model:** `BAAI/bge-small-en-v1.5` (FastEmbed, 384 dimensions)
- **Lexical Search:** `rank-bm25` (BM25Okapi)
- **Data Processing:** `pandas`, `pyarrow`, `pypdf`
- **Evaluation Workbooks:** `openpyxl`

---

## Corpus & Dataset Summary

- **Source:** [Indian Supreme Court Judgments Archive](https://github.com/vanga/indian-supreme-court-judgments)
- **Scope:** Selected 2023 English judgments (800 judgments parsed).
- **Extracted Text:** ~40,673,343 characters (~50,841 characters/judgment).
- **Chunking Strategy:** ~2,200 characters with ~250 character overlap, respecting paragraph (`\n\n`, `\n`) and sentence boundaries (`. `, `; `).
- **Total Chunks:** 21,451 chunks stored in `data/chunks.jsonl`.
- **Vector Index:** 21,451 points indexed in Qdrant collection `supreme_court_2023`.

---

## Project Structure

```
supreme-court-rag/
│
├── data/
│   ├── eval_questions.json             # 30 curated legal evaluation questions
│   ├── eval_candidates.jsonl           # Top candidates from Dense, BM25, and Hybrid
│   ├── relevance_review.xlsx           # Excel review workbook (Pilot + All Top-5)
│   ├── relevance_review_pilot_labeled.xlsx  # Pilot review (Q01-Q05) with notes
│   ├── relevance_labels.csv            # Earlier pooled CSV (Top-10 pool)
│   ├── chunks.jsonl                    # 21,451 chunked records
│   ├── judgments.jsonl                 # 800 parsed judgment records
│   ├── metadata_2023.parquet           # Raw source metadata
│   └── selected_metadata.parquet       # Filtered metadata for 2023
│
├── build_corpus.py                     # PDF extraction and metadata parsing
├── chunk_corpus.py                     # Paragraph-aware chunking pipeline
├── embed_store.py                      # FastEmbed embedding + Qdrant indexing
├── retrieve.py                         # Interactive retrieval CLI (Dense/BM25/RRF)
├── eval.py                             # Evaluation candidate retrieval generator
├── prepare_labels.py                   # Formatted Excel workbook generator
├── app.py                              # RAG answer generation entry point (upcoming)
│
├── README.md                           # Project documentation
├── PROJECT_STATUS.md                   # Real-time component tracking & audit log
└── EVAL_PROTOCOL.md                    # Benchmark rules, metrics, and labeling guide
```

---

## Getting Started

### 1. Activate Environment

```powershell
.venv\Scripts\Activate.ps1
```

### 2. Interactive Retrieval CLI

To test retrieval interactively for any legal question:

```powershell
python retrieve.py
```

### 3. Generate Evaluation Candidates

To run dense, BM25, and hybrid retrieval across all 30 evaluation questions:

```powershell
python eval.py
```

*Output:* `data/eval_candidates.jsonl` (90 question-method blocks).

### 4. Generate the Human Review Workbook

To generate the formatted Excel workbook (`data/relevance_review.xlsx`) with data validation and conditional styling:

```powershell
python prepare_labels.py
```

---

## Evaluation Workflow

1. **Candidate Pooling:** Dense, BM25, and Hybrid RRF candidates are pooled (top-5 per method) and deduplicated per judgment.
2. **Pilot Review (Q01–Q05):** 34 unique question–judgment pairs reviewed to validate snippet readability and rubric clarity.
3. **Full Review (Q01–Q30):** 241 unique candidates reviewed with graded relevance labels:
   - `0`: Irrelevant (does not meaningfully address the question).
   - `1`: Partially relevant (related legal principles/context, but indirect).
   - `2`: Strongly relevant (direct and substantive legal answer).
4. **Metrics Calculation:** Empirical comparison across methods using `Hit@5`, `Recall@5`, `MRR@5`, and `nDCG@5`.
5. **Answer Generation (RAG):** Grounded synthesis and citation verification.

For complete evaluation protocols, see [EVAL_PROTOCOL.md](file:///C:/Users/achya/supreme-court-rag/EVAL_PROTOCOL.md).
