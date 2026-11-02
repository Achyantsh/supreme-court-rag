"""Prepare a blank, source-navigable DEVELOPMENT review workbook from V2 records.

Importing this module does not read inputs, generate answers, or write files.
Call create_review_workbook explicitly; existing outputs are never overwritten.
Only stdlib and openpyxl are required. No V1 review labels are read or reused.
"""

import json
import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.hyperlink import Hyperlink


REVIEW_COLUMNS = [
    "Question ID", "Topic", "Question", "Generated answer", "Model",
    "Retrieved judgment IDs", "Cited case names/citations", "Evidence excerpts",
    "Generation status", "Generation error", "Source IDs", "Resolved sources",
    "Source-reference navigation", "Answer correctness (0/1/2)",
    "Citation support (0/1/2)", "Answer completeness (0/1/2)", "Review notes",
]
SOURCE_COLUMNS = [
    "Question ID", "Source ID", "Rank", "Doc ID", "Chunk ID", "Case name",
    "Citation", "Decision date", "Source PDF", "Score", "Retrieval mode",
    "Full retrieval excerpt", "Resolution status", "Answer review",
    "Supplied citation metadata (preview is not full evidence)",
]
NAVIGATION_COLUMNS = [
    "Question ID", "Original bracket", "Original token", "Source ID",
    "Bracket start (0-based)", "Bracket end (exclusive)",
    "Surrounding answer text", "Resolution status", "Unresolved",
    "Rank", "Doc ID", "Chunk ID", "Case name", "Citation", "Decision date",
    "Source PDF", "Score", "Retrieval mode", "Full retrieval excerpt",
    "Source row", "Answer review",
]
# These definitions are copied verbatim from answer_evaluation.py, not imported
# from the generator (which depends on requests).
INSTRUCTIONS = [
    "ANSWER QUALITY REVIEW — DEVELOPMENT QUESTIONS",
    "H01-H30 are DEVELOPMENT now, not an untouched held-out test set.",
    "All human-review columns are intentionally blank. An LLM output is not ground truth.",
    "Answer correctness: 0 = materially wrong/unsupported; 1 = partly correct or incomplete; 2 = correct and grounded.",
    "Citation support: 0 = cited case is not supported by its retrieved excerpt; 1 = partially supported/ambiguous; 2 = directly supported.",
    "Answer completeness: 0 = fails to address the question; 1 = addresses some issues; 2 = sufficiently addresses the question from evidence.",
    "Review every cited proposition against the exact evidence excerpt and the original judgment when needed.",
    "Source membership is not semantic support. Reviewers must assess the actual claims, including uncited claims and abstentions.",
    "Citation metadata is supplied evidence, NOT guaranteed supporting or actually cited. The historical 'Cited case names/citations' column lists supplied metadata, not verified citations.",
    "Sources contains exact full retrieval_response.results excerpts, not the 350-character answer_response citation previews. These are persisted retrieval excerpts, not necessarily full judgments.",
    "Source IDs come only from answer_response.citations.source_id. Retrieval matches require unambiguous metadata/rank agreement; missing or ambiguous matches are explicitly unresolved.",
    "Citation navigation retains literal bracket text and nearby answer text. Comma-grouped IDs are separate rows. Malformed, unknown, ambiguous and non-source brackets remain flagged; they are never silently repaired.",
    "Navigation is a traceability aid only. Neither a resolved ID nor a displayed snippet is independently verified support; no semantic scoring is performed.",
    "Use the 0,1,2 dropdowns for the three scores and Review notes for rationale. No V1 labels or notes are imported.",
    "Record reviewer identity, review date and adjudication in Provenance. Workbook links are internal; Source PDF is plain supplied metadata, not an external link.",
    "Generated answers, questions, topics and evidence projections are preserved without rewriting. Unsafe Excel/XML strings and oversized cells cause an error instead of silent truncation.",
]

_SOURCE_ID = re.compile(r"S[1-9][0-9]*\Z")
# Retain incomplete/nested bracket fragments too, rather than silently treating
# a recognizable ID inside a malformed bracket as a valid citation.
_BRACKET = re.compile(r"\[[^\[\]\r\n]*(?:\]|(?=[\[\r\n])|$)")
_REVIEW_FIELDS = ("Reviewer identity", "Review date", "Adjudication")
_METADATA = (
    "rank", "doc_id", "chunk_id", "case_name", "citation", "decision_date",
    "source_pdf", "score", "retrieval_mode",
)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _metadata_values(source: dict) -> list:
    # Excel numeric cells round long floats; keep the exact JSON score as text.
    return [
        json.dumps(source[key], allow_nan=False)
        if key == "score" and source.get(key) is not None else source.get(key)
        for key in _METADATA
    ]


def _validate_text(value: str, location: str) -> None:
    if len(value) > 32767:
        raise ValueError(f"{location}: text exceeds Excel's 32767-character limit")
    # XML 1.0 permits tab, LF and CR, but not the other C0 controls,
    # unpaired surrogates, U+FFFE or U+FFFF.
    for character in value:
        code = ord(character)
        if not (code in (9, 10, 13) or 0x20 <= code <= 0xD7FF
                or 0xE000 <= code <= 0xFFFD or 0x10000 <= code <= 0x10FFFF):
            raise ValueError(f"{location}: illegal XML character U+{code:04X}")


def _append(sheet, values: list) -> int:
    row = sheet.max_row + 1 if sheet.max_row > 1 or sheet.cell(1, 1).value is not None else 1
    for column, value in enumerate(values, start=1):
        cell = sheet.cell(row, column)
        if isinstance(value, (dict, list)):
            value = _json(value)
        if isinstance(value, str):
            # Validate before assignment: openpyxl otherwise truncates strings.
            _validate_text(value, f"{sheet.title}!{cell.coordinate}")
        cell.value = value
        if isinstance(value, str):
            cell.data_type = "s"  # Including values beginning with =, +, -, @.
    return row


def _link(cell, sheet_name: str, row: int) -> None:
    cell.hyperlink = Hyperlink(
        ref=cell.coordinate, location=f"'{sheet_name}'!A{row}", display=str(cell.value),
    )
    cell.style = "Hyperlink"


def _format_table(sheet, widths: list[int]) -> None:
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.row_dimensions[1].height = 44
    for row in sheet.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for cell in sheet[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor="1F497D")
    for column, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(column)].width = width


def _match_retrieval(citation: dict, results: list[dict]) -> tuple[dict | None, str]:
    """Resolve by persisted identity/rank, never by citation-preview text."""
    identity = [key for key in ("doc_id", "chunk_id") if citation.get(key) is not None]
    if not identity:
        return None, "Unresolved: supplied citation has no doc_id or chunk_id"
    candidates = [
        item for item in results
        if all(item.get(key) == citation[key] for key in identity)
    ]
    if citation.get("rank") is not None:
        candidates = [item for item in candidates if item.get("rank") == citation["rank"]]
    if len(candidates) != 1:
        return None, f"Unresolved: {len(candidates)} retrieval matches for supplied identity/rank"
    item = candidates[0]
    # Conflicting supplied metadata must not be silently replaced by a guess.
    for key in ("case_name", "citation", "decision_date", "source_pdf"):
        if citation.get(key) is not None and citation[key] != item.get(key):
            return None, f"Unresolved: supplied {key} conflicts with retrieval metadata"
    if not isinstance(item.get("excerpt"), str):
        return None, "Unresolved: full retrieval excerpt is missing or not text"
    return item, "Resolved retrieval mapping only; semantic support not verified"


def _references(answer: str):
    for match in _BRACKET.finditer(answer):
        bracket = match.group()
        closed = bracket.endswith("]")
        inner = bracket[1:-1] if closed else bracket[1:]
        # Whitespace within a token and non-comma separators are not repaired.
        for token in inner.split(","):
            yield {
                "bracket": bracket, "token": token, "source_id": token.strip(),
                "start": match.start(), "end": match.end(), "closed": closed,
                "context": answer[max(0, match.start() - 180):min(len(answer), match.end() + 180)],
            }


def create_review_workbook(
    records: list[dict], output: Path, provenance: dict[str, str],
) -> None:
    """Write a new blank review workbook without modifying records or inputs.

    Raises FileExistsError for an existing output, and ValueError for ambiguous
    question/source keys, unsafe strings or oversized cells. Failed retrieval
    matches are retained as explicit unresolved rows, never preview substitutes.
    All validation and workbook construction occur before exclusive file creation.
    No parent directories are created: the caller chooses an existing directory.
    """
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite review workbook: {output}")
    workbook = Workbook()
    instructions = workbook.active
    instructions.title = "Instructions"
    _append(instructions, ["Reviewer instructions"])
    for text in INSTRUCTIONS:
        _append(instructions, [text])
    _format_table(instructions, [125])
    for row in range(2, instructions.max_row + 1):
        instructions.row_dimensions[row].height = 48

    review = workbook.create_sheet("Answer Review")
    sources = workbook.create_sheet("Sources")
    navigation = workbook.create_sheet("Citation navigation")
    provenance_sheet = workbook.create_sheet("Provenance")
    _append(review, REVIEW_COLUMNS)
    _append(sources, SOURCE_COLUMNS)
    _append(navigation, NAVIGATION_COLUMNS)
    _append(provenance_sheet, ["Key", "Value"])
    for key, value in provenance.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("Provenance keys and values must be strings")
        if key.casefold() in {field.casefold() for field in _REVIEW_FIELDS}:
            raise ValueError(f"Reserved blank reviewer field in provenance: {key}")
        _append(provenance_sheet, [key, value])
    for field in _REVIEW_FIELDS:
        _append(provenance_sheet, [field, None])

    question_ids = set()
    for record in records:
        question_id = record["question_id"]
        if not isinstance(question_id, str) or not question_id or question_id in question_ids:
            raise ValueError(f"Missing, non-text or duplicate question_id: {question_id!r}")
        question_ids.add(question_id)
        answer_response = record["answer_response"]
        answer = answer_response.get("answer", "")
        if not isinstance(answer, str):
            raise ValueError(f"{question_id}: generated answer must be text")
        citations = answer_response.get("citations") or []
        results = record["retrieval_response"].get("results", [])
        evidence = [
            {"doc_id": item.get("doc_id"), "case_name": item.get("case_name"),
             "citation": item.get("citation"), "excerpt": item.get("excerpt")}
            for item in results
        ]
        cited = [
            {"case_name": item.get("case_name"), "citation": item.get("citation")}
            for item in citations
        ]
        review_row = review.max_row + 1
        source_map = {}
        first_source_row = None
        for citation in citations:
            source_id = citation.get("source_id")
            if not isinstance(source_id, str) or not source_id or source_id in source_map:
                raise ValueError(f"{question_id}: missing, non-text or duplicate source_id: {source_id!r}")
            matched, status = _match_retrieval(citation, results)
            metadata = matched if matched is not None else citation
            # Never put a citation's shortened preview in a full-excerpt column.
            full_excerpt = matched["excerpt"] if matched is not None else None
            source = {"source_id": source_id, **{key: metadata.get(key) for key in _METADATA},
                      "excerpt": full_excerpt, "resolution_status": status}
            source_row = _append(sources, [
                question_id, source_id, *_metadata_values(source),
                full_excerpt, status, "Back to answer", _json(citation),
            ])
            _link(sources.cell(source_row, 14), "Answer Review", review_row)
            source_map[source_id] = (source, source_row, matched is not None)
            if first_source_row is None:
                first_source_row = source_row

        resolved_references = {}
        first_navigation_row = None
        unresolved_count = 0
        for reference in _references(answer):
            source_id = reference["source_id"]
            entry = source_map.get(source_id)
            canonical = _SOURCE_ID.fullmatch(source_id) is not None
            if not reference["closed"]:
                status = "Unresolved: unclosed or nested bracket fragment"
            elif not canonical:
                status = "Unresolved: malformed source token or non-source bracket"
            elif entry is None:
                status = "Unresolved: source ID absent from supplied citations"
            else:
                status = entry[0]["resolution_status"]
            resolved = reference["closed"] and canonical and entry is not None and entry[2]
            source = entry[0] if entry is not None else {}
            if resolved:
                resolved_references[source_id] = source
            else:
                unresolved_count += 1
            navigation_row = _append(navigation, [
                question_id, reference["bracket"], reference["token"], source_id,
                reference["start"], reference["end"], reference["context"], status,
                "No" if resolved else "Yes", *_metadata_values(source),
                source.get("excerpt"), "Supplied source" if entry else "No matching source",
                "Back to answer",
            ])
            if entry is not None:
                _link(navigation.cell(navigation_row, 20), "Sources", entry[1])
            _link(navigation.cell(navigation_row, 21), "Answer Review", review_row)
            if first_navigation_row is None:
                first_navigation_row = navigation_row

        generation_error = record.get("generation_error", "")
        if isinstance(generation_error, (dict, list)):
            generation_error = _json(generation_error)
        _append(review, [
            question_id, record["topic"], record["question"], answer,
            record.get("model") or answer_response.get("model") or "",
            _json([item.get("doc_id") for item in evidence]), _json(cited), _json(evidence),
            record.get("generation_status", ""), generation_error, _json(list(source_map)),
            _json(list(resolved_references.values())),
            (f"Citation navigation ({unresolved_count} unresolved rows)" if first_navigation_row
             else "No bracket references found"), None, None, None, None,
        ])
        if first_source_row is not None:
            _link(review.cell(review_row, 11), "Sources", first_source_row)
        if first_navigation_row is not None:
            _link(review.cell(review_row, 13), "Citation navigation", first_navigation_row)

    _format_table(review, [12, 24, 48, 85, 25, 40, 55, 100, 18, 45, 28, 65, 35, 24, 24, 27, 50])
    _format_table(sources, [12, 12, 10, 28, 32, 55, 35, 18, 38, 22, 24, 100, 60, 22, 65])
    _format_table(navigation, [12, 28, 22, 14, 18, 18, 85, 60, 15, 10, 28, 32, 55, 35, 18, 38, 22, 24, 100, 24, 22])
    _format_table(provenance_sheet, [45, 110])
    for row in range(2, review.max_row + 1):
        review.row_dimensions[row].height = 105
        for column in range(14, 18):
            review.cell(row, column).fill = PatternFill("solid", fgColor="FFF2CC")
    for column in range(14, 17):
        validation = DataValidation(type="list", formula1='"0,1,2"', allow_blank=True)
        validation.errorStyle = "stop"
        validation.showErrorMessage = True
        validation.errorTitle = "Choose 0, 1 or 2"
        validation.error = "Use a rubric score of 0, 1 or 2, or leave blank for review."
        validation.showInputMessage = True
        validation.promptTitle = "Human review score"
        validation.prompt = "See Instructions for the exact rubric."
        validation.showDropDown = False
        review.add_data_validation(validation)
        if records:
            letter = get_column_letter(column)
            validation.add(f"{letter}2:{letter}{review.max_row}")

    # Exclusive mode is essential: the existence check above alone is racy.
    # Saving to a handle prevents openpyxl from opening/truncating the path.
    try:
        with output.open("xb") as handle:
            workbook.save(handle)
    finally:
        workbook.close()
