"""Generate versioned held-out rankings and a blank annotation workbook.

This command deliberately requires an approved question file. It never reads
or migrates development relevance labels.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from eval import METHODS
from query_pipeline import QueryEngine, document_key

APPROVED_NAME = "eval_questions_heldout_approved_v1.json"
OUTPUT_CANDIDATES = Path("data/heldout_eval_candidates_v1.jsonl")
OUTPUT_WORKBOOK = Path("data/heldout_relevance_review_v1.xlsx")
REVIEW_METHODS = METHODS + ["bm25_reranker_rrf_top5"]
COLUMNS = [
    "Question ID", "Topic", "Question", "doc_id", "Case name", "Citation",
    "Decision date", "Dense rank", "BM25 rank", "Hybrid RRF rank",
    "Hybrid reranked rank", "BM25+r rerank RRF rank", "Evidence excerpts",
    "Relevance (0/1/2)", "Review notes",
]


def load_questions(path: Path) -> list[dict[str, str]]:
    if path.name != APPROVED_NAME:
        raise ValueError(f"Refusing unapproved question file; expected {APPROVED_NAME}.")
    questions = json.loads(path.read_text(encoding="utf-8"))
    ids = [item["id"] for item in questions]
    if len(questions) != 30 or len(set(ids)) != 30 or any(not item.get("question") for item in questions):
        raise ValueError("Approved held-out file must contain 30 unique non-empty questions.")
    return questions


def fuse(records: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    scores: defaultdict[str, float] = defaultdict(float)
    selected: dict[str, dict[str, Any]] = {}
    for method in ("bm25", "hybrid_reranked"):
        for rank, record in enumerate(records[method][:5], start=1):
            doc_id = document_key(record)
            scores[doc_id] += 1.0 / (60 + rank)
            selected.setdefault(doc_id, record)
    return [selected[key] for key in sorted(scores, key=lambda key: (-scores[key], key))][:5]


def write_workbook(rows: list[dict[str, Any]], path: Path) -> None:
    workbook = Workbook()
    instructions = workbook.active
    instructions.title = "Instructions"
    instructions.append(["HELD-OUT REVIEW WORKBOOK — LABELS REQUIRED"])
    instructions.append(["All relevance cells are intentionally blank. Do not score until every row is reviewed."])
    instructions.append(["0 = Irrelevant; 1 = Partial; 2 = Strong. Review full judgments when excerpts are ambiguous."])
    sheet = workbook.create_sheet("Relevance Review")
    sheet.append(COLUMNS)
    for item in rows:
        sheet.append([item.get(column, "") for column in COLUMNS])
    for cell in sheet[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor="1F497D")
        cell.alignment = Alignment(wrap_text=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for row in sheet.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    relevance_column = COLUMNS.index("Relevance (0/1/2)") + 1
    validation = DataValidation(type="list", formula1='"0,1,2"', allow_blank=True)
    sheet.add_data_validation(validation)
    validation.add(f"{openpyxl.utils.get_column_letter(relevance_column)}2:{openpyxl.utils.get_column_letter(relevance_column)}{sheet.max_row}")
    sheet.conditional_formatting.add(
        f"{openpyxl.utils.get_column_letter(relevance_column)}2:{openpyxl.utils.get_column_letter(relevance_column)}{sheet.max_row}",
        CellIsRule(operator="equal", formula=["0"], fill=PatternFill("solid", fgColor="FCE4D6")),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, default=OUTPUT_CANDIDATES)
    parser.add_argument("--workbook", type=Path, default=OUTPUT_WORKBOOK)
    args = parser.parse_args()
    questions = load_questions(args.questions)
    engine = QueryEngine()
    try:
        output: list[dict[str, Any]] = []
        pooled: dict[tuple[str, str], dict[str, Any]] = {}
        for question in questions:
            rankings = engine.retrieve_all_methods(question["question"], top_k=20, candidate_k=50)
            rankings["bm25_reranker_rrf_top5"] = fuse(rankings)
            for method in REVIEW_METHODS:
                results = []
                for rank, record in enumerate(rankings[method], start=1):
                    results.append({
                        "rank": rank, "doc_id": document_key(record),
                        "case_name": record.get("case_name"), "citation": record.get("citation"),
                        "decision_date": record.get("decision_date"), "source_pdf": record.get("source_pdf"),
                        "chunk_id": record.get("chunk_id"), "score": record.get("rerank_score", record.get("score")),
                        "text": (record.get("text") or "")[:1800],
                    })
                output.append({**question, "method": method, "results": results})
                for item in results[:5]:
                    key = (question["id"], item["doc_id"])
                    row = pooled.setdefault(key, {
                        "Question ID": question["id"], "Topic": question["topic"],
                        "Question": question["question"], "doc_id": item["doc_id"],
                        "Case name": item["case_name"] or "", "Citation": item["citation"] or "",
                        "Decision date": item["decision_date"] or "", "Dense rank": "",
                        "BM25 rank": "", "Hybrid RRF rank": "", "Hybrid reranked rank": "",
                        "BM25+r rerank RRF rank": "", "Evidence excerpts": "",
                        "Relevance (0/1/2)": "", "Review notes": "",
                    })
                    rank_column = {
                        "dense": "Dense rank", "bm25": "BM25 rank",
                        "hybrid_rrf": "Hybrid RRF rank", "hybrid_reranked": "Hybrid reranked rank",
                        "bm25_reranker_rrf_top5": "BM25+r rerank RRF rank",
                    }[method]
                    row[rank_column] = item["rank"]
                    excerpt = item["text"] or ""
                    row["Evidence excerpts"] += (("\n\n" if row["Evidence excerpts"] else "") + f"[{method}, rank {item['rank']}] {excerpt}")
    finally:
        engine.close()
    args.candidates.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in output) + "\n", encoding="utf-8")
    write_workbook(list(pooled.values()), args.workbook)
    print(f"Wrote {len(output)} ranking rows and {len(pooled)} blank-label candidates.")


if __name__ == "__main__":
    main()
