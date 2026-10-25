# Evaluation Protocol & Benchmark Methodology

**Project:** Eval-Driven Production RAG over Indian Supreme Court Judgments  
**Standard:** Balanced Evaluation Plan

---

## 1. Objectives

The primary objective is to establish an empirical, defensible IR benchmark comparing three retrieval strategies over Indian Supreme Court judgments:
1. **Dense Vector Retrieval** (`BAAI/bge-small-en-v1.5`, cosine similarity in Qdrant)
2. **Sparse Lexical Retrieval** (BM25Okapi on regex-tokenized chunks)
3. **Hybrid Retrieval** (Reciprocal Rank Fusion with $k=60$ after collapsing chunks to unique judgments)

---

## 2. Evaluation Dataset & Topic Distribution

File: `data/eval_questions.json` (30 curated questions)

| Topic | Question Count | Question IDs |
|---|---|---|
| `anticipatory_bail` | 7 | Q01, Q02, Q03, Q04, Q05, Q06, Q07 |
| `arrest` | 5 | Q08, Q09, Q10, Q11, Q12 |
| `quashing` | 4 | Q13, Q14, Q15, Q16 |
| `corruption` | 3 | Q17, Q18, Q19 |
| `preventive_detention` | 3 | Q20, Q21, Q22 |
| `constitutional_rights` | 3 | Q23, Q24, Q25 |
| `criminal_procedure` | 3 | Q26, Q27, Q28 |
| `bail` | 2 | Q29, Q30 |
| **Total** | **30** | **Q01–Q30** |

---

## 3. Candidate Pooling & Deduping Protocol

To avoid annotating hundreds of duplicate candidates while remaining fair to all systems:
1. **Top-5 per Method:** Candidates ranking 1 to 5 from `dense`, `bm25`, and `hybrid_rrf` are included.
2. **Judgment Deduplication:** Deduplicated by `(question_id, doc_id)`.
3. **Evidence Excerpts:** Up to two distinct representative excerpts per judgment are displayed.
4. **Candidate Sizes:**
   - **Pilot Set (Q01–Q05):** 34 unique question–judgment pairs.
   - **Full Evaluation Set (Q01–Q30):** 241 unique question–judgment pairs.

---

## 4. Relevance Annotation Rubric

Every candidate judgment is assigned a graded relevance label based strictly on provided textual evidence:

| Label | Meaning | Operational Definition |
|:---:|:---:|---|
| **0** | **Irrelevant** | Does not meaningfully answer the question. Includes cases discussing unrelated offences, procedural default bail under 167(2) when the question asks about anticipatory bail under 438, civil disputes, or purely generic legal boilerplate. |
| **1** | **Partially Relevant** | Provides related context or tangential principles (e.g., general bail guidelines, reciting statutory sections), but lacks a direct or substantive answer to the specific legal inquiry. |
| **2** | **Strongly Relevant** | Directly, clearly, and substantively addresses the question with core legal tests, ratio decidendi, or definitive holdings. |

### Annotation Best Practices:
- Do not assign a higher label because a judgment has a high retrieval score or rank.
- If an excerpt is truncated or ambiguous, inspect the full judgment text from `data/judgments.jsonl` or the source PDF.
- Record any borderline reasoning in the `Review notes` column.

---

## 5. Information Retrieval Metrics

Metrics will be computed at cutoff $K=5$ across all 30 questions.

### 5.1. Hit Rate@5
Fraction of queries where at least one relevant document (relevance $\ge 1$, or optionally binary strict $\ge 2$) appears in the top 5:
$$\text{Hit@5} = \frac{1}{|Q|} \sum_{q \in Q} \mathbb{I}(\text{rank}(q) \le 5)$$

### 5.2. Recall@5 (Pooled)
Fraction of all known relevant pooled documents retrieved in the top 5 for question $q$:
$$\text{Recall@5} = \frac{1}{|Q|} \sum_{q \in Q} \frac{|\text{Retrieved}_q \cap \text{Relevant}_q|}{|\text{Relevant}_q|}$$
*(Note: Computed against the pooled ground truth; does not claim omniscience over unretrieved corpus judgments).*

### 5.3. Mean Reciprocal Rank (MRR@5)
Evaluates how high the first relevant document is placed:
$$\text{MRR@5} = \frac{1}{|Q|} \sum_{q \in Q} \frac{1}{\min \{ \text{rank}(d) : d \in \text{Relevant}_q, \text{rank}(d) \le 5 \} \cup \{\infty\}}$$

### 5.4. Normalized Discounted Cumulative Gain (nDCG@5)
Evaluates graded relevance handling ($0, 1, 2$):
$$\text{DCG@5} = \sum_{i=1}^{5} \frac{2^{rel_i} - 1}{\log_2(i + 1)}, \quad \text{nDCG@5} = \frac{\text{DCG@5}}{\text{IDCG@5}}$$

---

## 6. Execution Roadmap

```
[Phase 1: Workbook & Pilot Review] (Current)
   - Verify prepare_labels.py
   - Human review & verification of Q01-Q05 (34 pairs)
   - Refine borderline definitions

[Phase 2: Full Benchmark Labeling]
   - Complete review of Q06-Q30 (remaining 207 pairs)
   - Freeze ground-truth dataset in data/relevance_labels_final.json

[Phase 3: Automated Metrics Script]
   - Implement calculate_metrics.py
   - Output baseline_metrics.json & Markdown performance tables

[Phase 4: Retrieval Optimization]
   - Cross-encoder reranking (e.g., BAAI/bge-reranker-base)
   - Fusion weight tuning
   - Direct empirical comparison against baseline

[Phase 5: RAG Generation & Factuality]
   - Grounded generation in app.py
   - Citation verification and faithfulness scoring
```
