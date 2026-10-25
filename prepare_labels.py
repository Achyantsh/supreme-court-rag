
import json
import re
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.formatting.rule import CellIsRule
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter


INPUT_FILE = Path("data/eval_candidates.jsonl")
OUTPUT_FILE = Path("data/relevance_review.xlsx")

METHODS = ["dense", "bm25", "hybrid_rrf"]
PILOT_QUESTIONS = {"Q01", "Q02", "Q03", "Q04", "Q05"}
REVIEW_RANK = 5

COLUMNS = [
    "Question ID",
    "Topic",
    "Question",
    "Case name",
    "Citation",
    "Decision date",
    "Dense rank",
    "BM25 rank",
    "Hybrid RRF rank",
    "Evidence excerpt",
    "Relevance (0/1/2)",
    "Review notes",
]


def question_number(qid):
    match = re.search(r"\d+", qid)
    return int(match.group()) if match else 9999


def clean_text(text):
    # Make excerpts easier to read without changing their meaning.
    return re.sub(r"\s+", " ", text or "").strip()


def load_candidates():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Cannot find {INPUT_FILE}. Run python eval.py first."
        )

    pooled = {}

    with INPUT_FILE.open(encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]

    for row in rows:
        qid = row["question_id"]
        method = row["method"]

        for result in row.get("results", []):
            rank = int(result["rank"])

            # Keep candidates appearing in at least one method's top 5.
            if rank > REVIEW_RANK:
                continue

            doc_id = result.get("doc_id") or result.get("case_name") or "unknown"
            key = (qid, doc_id)

            if key not in pooled:
                pooled[key] = {
                    "Question ID": qid,
                    "Topic": row.get("topic", ""),
                    "Question": row.get("question", ""),
                    "Case name": result.get("case_name") or "",
                    "Citation": result.get("citation") or "",
                    "Decision date": result.get("decision_date") or "",
                    "Dense rank": "",
                    "BM25 rank": "",
                    "Hybrid RRF rank": "",
                    "Evidence excerpt": [],
                    "Relevance (0/1/2)": "",
                    "Review notes": "",
                }

            item = pooled[key]

            rank_column = {
                "dense": "Dense rank",
                "bm25": "BM25 rank",
                "hybrid_rrf": "Hybrid RRF rank",
            }[method]

            item[rank_column] = rank

            snippet = clean_text(result.get("text", ""))
            if snippet:
                tagged = f"[{method}, rank {rank}] {snippet}"
                if tagged not in item["Evidence excerpt"]:
                    item["Evidence excerpt"].append(tagged)

    # Keep only the best two distinct excerpts per judgment.
    for item in pooled.values():
        item["Evidence excerpt"] = "\n\n".join(
            item["Evidence excerpt"][:2]
        )

    return sorted(
        pooled.values(),
        key=lambda item: (
            question_number(item["Question ID"]),
            item["Case name"],
        ),
    )


def style_sheet(ws, widths):
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.sheet_view.showGridLines = False

    header_fill = PatternFill("solid", fgColor="243447")

    for cell in ws[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(
            vertical="center",
            wrap_text=True,
        )

    ws.row_dimensions[1].height = 32

    for column, width in widths.items():
        ws.column_dimensions[column].width = width

    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(
                vertical="top",
                wrap_text=True,
            )

    # Keep long text readable without making every row enormous.
    for row_number in range(2, ws.max_row + 1):
        ws.row_dimensions[row_number].height = 95

    relevance_column = COLUMNS.index("Relevance (0/1/2)") + 1
    validation = DataValidation(
        type="list",
        formula1='"0,1,2"',
        allow_blank=True,
    )
    validation.error = "Choose 0, 1, or 2."
    validation.errorTitle = "Invalid relevance label"
    ws.add_data_validation(validation)
    validation.add(
        f"{get_column_letter(relevance_column)}2:"
        f"{get_column_letter(relevance_column)}{ws.max_row}"
    )

    label_letter = get_column_letter(relevance_column)
    ws.conditional_formatting.add(
        f"{label_letter}2:{label_letter}{ws.max_row}",
        CellIsRule(
            operator="equal",
            formula=["0"],
            fill=PatternFill("solid", fgColor="FCE4D6"),
        ),
    )
    ws.conditional_formatting.add(
        f"{label_letter}2:{label_letter}{ws.max_row}",
        CellIsRule(
            operator="equal",
            formula=["1"],
            fill=PatternFill("solid", fgColor="FFF2CC"),
        ),
    )
    ws.conditional_formatting.add(
        f"{label_letter}2:{label_letter}{ws.max_row}",
        CellIsRule(
            operator="equal",
            formula=["2"],
            fill=PatternFill("solid", fgColor="E2F0D9"),
        ),
    )


def add_review_sheet(wb, title, items):
    ws = wb.create_sheet(title)
    ws.append(COLUMNS)

    for item in items:
        ws.append([
            item["Question ID"],
            item["Topic"],
            item["Question"],
            item["Case name"],
            item["Citation"],
            item["Decision date"],
            item["Dense rank"],
            item["BM25 rank"],
            item["Hybrid RRF rank"],
            item["Evidence excerpt"],
            item["Relevance (0/1/2)"],
            item["Review notes"],
        ])

    style_sheet(ws, {
        "A": 12,
        "B": 22,
        "C": 48,
        "D": 42,
        "E": 22,
        "F": 15,
        "G": 12,
        "H": 12,
        "I": 16,
        "J": 85,
        "K": 18,
        "L": 32,
    })

    return ws


def main():
    candidates = load_candidates()

    pilot = [
        item for item in candidates
        if item["Question ID"] in PILOT_QUESTIONS
    ]

    wb = Workbook()
    instructions = wb.active
    instructions.title = "Instructions"

    guide = [
        ["SUPREME COURT RAG — RELEVANCE REVIEW"],
        [""],
        ["WHAT TO DO"],
        ["1. Start with the Pilot Review sheet only."],
        ["2. Read the question, case name and evidence excerpt."],
        ["3. If the excerpt is insufficient, inspect the full judgment."],
        ["4. Enter one relevance label per question–judgment pair."],
        ["5. Leave uncertain labels blank and explain in Review notes."],
        [""],
        ["LABEL DEFINITIONS"],
        ["0 = Irrelevant: does not meaningfully answer the question."],
        ["1 = Partial: related context, but incomplete or indirect evidence."],
        ["2 = Strong: directly and substantively answers the question."],
        [""],
        ["IMPORTANT"],
        ["Do not label a case relevant just because it ranks highly."],
        ["The ranks show where each method retrieved the same judgment."],
        ["A judgment may appear under more than one method; label it once."],
        ["Automated/model predictions are not verified ground truth."],
        ["This pooled set may miss judgments that all methods failed to retrieve."],
        [""],
        ["AFTER THE PILOT"],
        ["Save this workbook and send it back for a consistency check."],
        ["Do not label the All Top-5 sheet yet."],
    ]

    for row in guide:
        instructions.append(row)

    instructions.column_dimensions["A"].width = 100
    instructions.sheet_view.showGridLines = False

    for row in instructions.iter_rows():
        for cell in row:
            cell.alignment = Alignment(
                vertical="top",
                wrap_text=True,
            )

    instructions["A1"].font = Font(bold=True, size=16, color="243447")
    for row_number in [3, 10, 15, 22]:
        instructions.cell(row=row_number, column=1).font = Font(
            bold=True,
            size=12,
        )

    add_review_sheet(wb, "Pilot Review", pilot)
    add_review_sheet(wb, "All Top-5", candidates)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        wb.save(OUTPUT_FILE)
    except PermissionError:
        print(f"\n[ERROR] Permission denied: '{OUTPUT_FILE}'.")
        print("Please close Microsoft Excel (or any program viewing this file) and re-run.")
        return

    print("\n--- REVIEW WORKBOOK CREATED ---")
    print("Pilot question count:", len(PILOT_QUESTIONS))
    print("Pilot candidates:", len(pilot))
    print("All pooled top-5 candidates:", len(candidates))
    print("Output:", OUTPUT_FILE.resolve())
    print("\nNext: open the workbook and label Pilot Review only.")


if __name__ == "__main__":
    main()
