"""Prepare best-effort blinded paired adjudication; never score or call an API."""

import argparse
import hashlib
import io
import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from compare_answer_quality_v1_v2 import (
    DEFAULT_REPORT, DEFAULT_V1_JSONL, DEFAULT_V1_WORKBOOK, DEFAULT_V2_JSONL,
    DEFAULT_V2_WORKBOOK, EXPECTED_IDS, ROOT, audit_runs, canonical_hash,
    load_records, sha256,
)
from prepare_answer_quality_review import _append, _format_table, _link


DEFAULT_WORKBOOK = ROOT / "data/answer_review_v1_v2_human_adjudication.xlsx"
DEFAULT_KEY = ROOT / "reports/private_review_mapping.json"
DEFAULT_PROTOCOL = ROOT / "reports/v1_v2_human_adjudication_protocol.md"

RUBRIC = (
    "Answer correctness: 0 = materially wrong/unsupported; 1 = partly correct or incomplete; 2 = correct and grounded.",
    "Citation support: 0 = cited case is not supported by its retrieved excerpt; 1 = partially supported/ambiguous; 2 = directly supported.",
    "Answer completeness: 0 = fails to address the question; 1 = partially addresses it; 2 = sufficiently addresses the question from evidence.",
)
VERIFICATION_OPTIONS = (
    "Verified against full judgment",
    "Excerpt sufficient; PDF not consulted",
    "Needs full-judgment verification",
    "Uncertain / unresolved",
)
REVIEW_COLUMNS = [
    "Question ID", "Topic", "Exact question", "Answer A",
    "A Correctness (0/1/2)", "A Citation support (0/1/2)", "A Completeness (0/1/2)",
    "A Review notes / uncertainty", "A Full-judgment verification status", "A PDF pages / paragraphs checked",
    "Answer B", "B Correctness (0/1/2)", "B Citation support (0/1/2)", "B Completeness (0/1/2)",
    "B Review notes / uncertainty", "B Full-judgment verification status", "B PDF pages / paragraphs checked",
    "Exact shared retrieval evidence and metadata", "Shared sources", "Pair-level notes / unresolved issues",
    "Human reviewer name", "Review date",
]
HUMAN_COLUMNS = [column for column in REVIEW_COLUMNS if column not in {
    "Question ID", "Topic", "Exact question", "Answer A", "Answer B",
    "Exact shared retrieval evidence and metadata", "Shared sources",
}]
SOURCE_COLUMNS = [
    "Question ID", "Source reference", "Retrieval rank", "Document ID", "Chunk ID",
    "Case name", "SCR citation", "Decision date", "Source PDF", "Retrieval score (exact text)",
    "Retrieval mode", "Exact retrieved excerpt", "Local PDF availability", "Open original judgment PDF",
    "Full-judgment verification status", "Verified PDF pages / paragraphs",
    "Holding / submissions / lower-court context", "Source review notes / uncertainty", "Back to pair",
]
SOURCE_HUMAN_COLUMNS = SOURCE_COLUMNS[14:18]
INSTRUCTIONS = [
    "PAIRED LEGAL ANSWER ADJUDICATION — HUMAN ANNOTATION ONLY",
    "Review 30 question pairs (60 answers). Independently score A and B on three dimensions: 180 score cells.",
    "All new human-review fields start blank. No provisional draft scores or notes have been copied.",
    "Existing scores and the previous comparison are PROVISIONAL AI-ASSISTED DRAFT ASSESSMENTS, not independently human-reviewed ground truth, and were not adjudicated against full judgments. Do not use them as final resume evidence.",
    "A/B placement was randomized before review. The coordinator holds the separate mapping key; do not consult it, earlier answers, draft scores or comparison reports while annotating.",
    "Blinding is BEST-EFFORT: citation formatting or prior familiarity may reveal an answer configuration. Answers remain verbatim; formatting was not normalized. Record prior exposure and any suspected unblinding in Reviewer details.",
    "H01–H30 are a DEVELOPMENT set: earlier failures informed changes to the answer configuration. Even adjudicated results cannot establish untouched held-out generalization or isolate a prompt-only causal effect.",
    *RUBRIC,
    "For EACH answer, check every specific legal proposition against the source passage. Evaluate accuracy, citation support and completeness separately; do not score an answer merely because it sounds plausible.",
    "Distinguish Supreme Court holdings from counsel submissions, quoted arguments, lower-court reasoning, statutes and background discussion. Verify whether the Court adopted the proposition.",
    "Check statutory and procedural scope, exceptions, qualifications, the precise legal issue asked, missing elements and whether abstention is justified.",
    "Verify every cited source supports its ADJACENT proposition. Supplied source metadata and a valid source ID establish traceability only, NOT semantic citation support. Also inspect uncited claims.",
    "Shared sources lists exact retrieved excerpts and neutral S1, S2, etc. references by retrieval rank for BOTH answers. These are evidence windows, not complete judgments; supplied sources are not necessarily cited by an answer.",
    "Open the original PDF whenever an excerpt is insufficient, truncated or ambiguous about a holding or its scope. PDF hyperlinks point to local project files; Excel may request permission to open them.",
    "Record full-judgment verification status separately for A and B, the PDF pages/paragraphs actually checked, and source-level context in Shared sources. PDF availability is NOT verification; no verification status has been prefilled.",
    "If an excerpt suffices without opening the PDF, explicitly choose 'Excerpt sufficient; PDF not consulted'. Do not describe such a review as full-judgment verified.",
    "Record uncertainty rather than guessing: leave affected scores blank, choose 'Uncertain / unresolved' or 'Needs full-judgment verification', explain what is missing, and seek adjudication. Blank is NOT score 0.",
    "Enter human reviewer identity, qualifications, dates, prior exposure and conflicts in Reviewer details. Record actual human review/adjudication, not an AI name as a human reviewer. If multiple reviewers disagree, retain their original independent work and document resolution.",
    "Complete all 180 human scores and all required verification/provenance fields only after resolving uncertainty. Keep original answer/evidence cells unchanged. Return the workbook to the coordinator without opening the mapping key.",
    "STOP at annotation: no final metrics or quality-improvement claims are generated by this workbook. The old comparison calculator reads draft workbooks; do not run it as the final adjudication analysis.",
]


def make_assignment(question_ids=EXPECTED_IDS, seed=None):
    """Balanced fixed-seed allocation; mapping is coordinator-only."""
    ids = sorted(question_ids)
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Assignment requires unique nonempty question IDs")
    if type(seed) is not int:
        raise ValueError("An explicit private integer seed is required")
    placements = ["v1"] * (len(ids) // 2) + ["v2"] * (len(ids) - len(ids) // 2)
    random.Random(seed).shuffle(placements)
    return {qid: {"A": version, "B": "v2" if version == "v1" else "v1"}
            for qid, version in zip(ids, placements)}


def _dropdown(sheet, column_name, headers, options, last_row):
    column = headers.index(column_name) + 1
    validation = DataValidation(type="list", formula1='"' + ",".join(options) + '"', allow_blank=True)
    validation.errorStyle = "stop"
    validation.showErrorMessage = True
    validation.errorTitle = "Choose an allowed value"
    validation.error = "Use the dropdown, or leave blank if review is incomplete."
    validation.showDropDown = False
    sheet.add_data_validation(validation)
    validation.add(f"{get_column_letter(column)}2:{get_column_letter(column)}{last_row}")


def build_workbook(v1, v2, assignment, pdf_dir, output):
    """Return serialized workbook bytes; no key, draft labels or per-version hashes embedded."""
    audit = audit_runs(v1, v2)
    if audit["confounds"]:
        raise ValueError("Cannot share evidence across confounded runs: " + "; ".join(audit["confounds"]))
    if set(assignment) != set(EXPECTED_IDS):
        raise ValueError("Assignment must cover exactly H01–H30")
    if any(set(mapping) != {"A", "B"} or set(mapping.values()) != {"v1", "v2"}
           for mapping in assignment.values()):
        raise ValueError("Each pair must contain one V1 and one V2 answer")
    workbook = Workbook()
    try:
        workbook.properties.title = "Paired legal answer adjudication"
        workbook.properties.creator = "Evaluation coordinator"
        instructions = workbook.active
        instructions.title = "Instructions"
        for text in INSTRUCTIONS:
            _append(instructions, [text])
        _format_table(instructions, [125])
        for index in range(1, instructions.max_row + 1):
            instructions.row_dimensions[index].height = 65
        review = workbook.create_sheet("Paired review")
        sources = workbook.create_sheet("Shared sources")
        details = workbook.create_sheet("Reviewer details")
        _append(review, REVIEW_COLUMNS)
        _append(sources, SOURCE_COLUMNS)
        _append(details, ["Human review provenance", "Reviewer entry"])
        for field in ("Human reviewer name", "Qualifications / legal expertise", "Review start date",
                      "Review completion date", "Prior exposure to answers or draft scores",
                      "Suspected unblinding / conflicts", "Independent second reviewer (if any)",
                      "Disagreement resolution / adjudication", "Unresolved limitations",
                      "Human sign-off / date"):
            _append(details, [field, None])
        for pair_row, qid in enumerate(EXPECTED_IDS, 2):
            record = v1[qid]
            results = record["retrieval_response"]["results"]
            first_source_row = sources.max_row + 1
            answers = {"v1": record["answer_response"]["answer"], "v2": v2[qid]["answer_response"]["answer"]}
            values = {
                "Question ID": qid, "Topic": record["topic"], "Exact question": record["question"],
                "Answer A": answers[assignment[qid]["A"]], "Answer B": answers[assignment[qid]["B"]],
                "Exact shared retrieval evidence and metadata": json.dumps(results, ensure_ascii=False, allow_nan=False),
                "Shared sources": f"Open {len(results)} shared sources",
            }
            _append(review, [values.get(header) for header in REVIEW_COLUMNS])
            _link(review.cell(pair_row, REVIEW_COLUMNS.index("Shared sources") + 1), "Shared sources", first_source_row)
            for result in results:
                filename = result["source_pdf"]
                if not filename or "/" in filename or "\\" in filename:
                    raise ValueError(f"{qid}: source PDF must be a plain filename")
                pdf = Path(pdf_dir) / filename
                available = pdf.is_file()
                source_row = _append(sources, [
                    qid, f"S{result['rank']}", result["rank"], result["doc_id"], result.get("chunk_id"),
                    result.get("case_name"), result.get("citation"), result.get("decision_date"), filename,
                    json.dumps(result.get("score"), allow_nan=False), result.get("retrieval_mode"), result["excerpt"],
                    "Available locally (not yet verified)" if available else "Missing locally; obtain original judgment",
                    "Open original judgment PDF" if available else "PDF unavailable",
                    None, None, None, None, "Back to pair",
                ])
                if available:
                    relative = os.path.relpath(pdf.resolve(), Path(output).parent.resolve()).replace("\\", "/")
                    sources.cell(source_row, 14).hyperlink = quote(relative, safe="/:")
                    sources.cell(source_row, 14).style = "Hyperlink"
                _link(sources.cell(source_row, 19), "Paired review", pair_row)
        _format_table(review, [12, 23, 48, 85, 22, 23, 24, 48, 35, 35, 85, 22, 23, 24, 48, 35, 35, 100, 30, 48, 26, 20])
        _format_table(sources, [12, 18, 14, 30, 35, 55, 35, 20, 40, 28, 24, 110, 45, 30, 35, 35, 55, 55, 22])
        _format_table(details, [55, 100])
        review.freeze_panes = "D2"
        for sheet, headers, fields in ((review, REVIEW_COLUMNS, HUMAN_COLUMNS),
                                        (sources, SOURCE_COLUMNS, SOURCE_HUMAN_COLUMNS)):
            for header in fields:
                column = headers.index(header) + 1
                for row in range(2, sheet.max_row + 1):
                    sheet.cell(row, column).fill = PatternFill("solid", fgColor="FFF2CC")
                if "(0/1/2)" in header:
                    _dropdown(sheet, header, headers, ("0", "1", "2"), sheet.max_row)
                elif "verification status" in header:
                    _dropdown(sheet, header, headers, VERIFICATION_OPTIONS, sheet.max_row)
        for row in range(2, review.max_row + 1):
            review.row_dimensions[row].height = 120
        for row in range(2, details.max_row + 1):
            details.cell(row, 2).fill = PatternFill("solid", fgColor="FFF2CC")
        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()
    finally:
        workbook.close()


def _draft_provenance(path):
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        if "Provenance" not in workbook:
            return {"status": "Provisional AI-assisted draft; human adjudication not established"}
        values = dict(workbook["Provenance"].iter_rows(min_row=2, max_col=2, values_only=True))
        return {field: values.get(field) for field in ("Reviewer identity", "Review date", "Adjudication")}
    finally:
        workbook.close()


def prepare_adjudication(v1_jsonl=DEFAULT_V1_JSONL, v2_jsonl=DEFAULT_V2_JSONL,
                         v1_draft=DEFAULT_V1_WORKBOOK, v2_draft=DEFAULT_V2_WORKBOOK,
                         previous_report=DEFAULT_REPORT, output=DEFAULT_WORKBOOK,
                         key_path=DEFAULT_KEY, protocol_path=DEFAULT_PROTOCOL,
                         pdf_dir=ROOT / "data/pdfs", seed=None):
    outputs = [Path(output), Path(key_path), Path(protocol_path)]
    if len({path.resolve() for path in outputs}) != 3:
        raise ValueError("Output paths must be distinct")
    for path in outputs:
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite existing artifact: {path}")
        if not path.parent.is_dir():
            raise ValueError(f"Output directory does not exist: {path.parent}")
    inputs = {"v1_jsonl": Path(v1_jsonl), "v2_jsonl": Path(v2_jsonl),
              "v1_provisional_draft": Path(v1_draft), "v2_provisional_draft": Path(v2_draft),
              "previous_provisional_comparison": Path(previous_report)}
    baseline = {name: sha256(path) for name, path in inputs.items()}
    v1, v2 = load_records(v1_jsonl), load_records(v2_jsonl)
    audit = audit_runs(v1, v2)
    if audit["confounds"]:
        raise ValueError("Evidence/settings differ; refusing shared-evidence adjudication: " + "; ".join(audit["confounds"]))
    assignment = make_assignment(seed=seed)
    payload = build_workbook(v1, v2, assignment, pdf_dir, output)
    created = datetime.now(timezone.utc).isoformat()
    key = {
        "schema_version": 1, "access": "COORDINATOR ONLY — do not distribute to reviewers",
        "created_utc": created, "seed": seed,
        "randomization": "Sorted H01–H30; shuffle a balanced 15/15 answer-A allocation with random.Random(seed)",
        "scope": "DEVELOPMENT; earlier V1 failures informed V2. No final quality calculation performed.",
        "old_scores_status": "PROVISIONAL AI-ASSISTED DRAFT ASSESSMENTS; not independent human ground truth; not adjudicated against full judgments",
        "draft_reviewer_provenance": {"v1": _draft_provenance(v1_draft), "v2": _draft_provenance(v2_draft)},
        "preserved_inputs": {name: {"path": str(path), "sha256": baseline[name]} for name, path in inputs.items()},
        "pairs": {qid: {
            **assignment[qid], "shared_evidence_sha256": canonical_hash(v1[qid]["retrieval_response"]),
            "answer_sha256": {
                label: hashlib.sha256(
                    (v1 if version == "v1" else v2)[qid]["answer_response"]["answer"].encode("utf-8")
                ).hexdigest() for label, version in assignment[qid].items()
            },
        } for qid in EXPECTED_IDS},
    }
    pdf_names = sorted({result["source_pdf"] for record in v1.values() for result in record["retrieval_response"]["results"]})
    key["pdf_sha256"] = {name: sha256(Path(pdf_dir) / name) if (Path(pdf_dir) / name).is_file() else None for name in pdf_names}
    key["initial_workbook_sha256"] = hashlib.sha256(payload).hexdigest()
    protocol = (
        "# Human adjudication protocol — annotation pending\n\n"
        "## Correction to the interpretation of earlier results\n\n"
        "The existing answer-review scores and `v1_v2_answer_quality_comparison.md` are "
        "**provisional AI-assisted draft assessments**, not independent human-reviewed ground truth. "
        "The recorded reviewer identity is AI-assisted, and no full-judgment human adjudication was "
        "established. In particular, the old report's phrase 'complete valid human labels' overstates "
        "the provenance. The old files are preserved unchanged as history, not endorsed as final results. "
        "Do not cite their quality improvements as human-validated resume results.\n\n"
        "## New annotation package\n\n"
        f"- Reviewer workbook: `{Path(output).name}`.\n"
        "- 30 paired questions, 60 verbatim answers, 180 initially blank human score cells.\n"
        "- Both runs contain exactly H01–H30 once, one successful answer per configuration per question, "
        "the same recorded model/settings/SDK, and exactly matching ordered retrieval evidence.\n"
        "- Answer placement is fixed-seed randomized and balanced. The separate coordinator-only JSON "
        "key contains allocation, provenance and input hashes; it is not embedded in the workbook. "
        "Do not give reviewers the key, generation code, previous scores or comparison report.\n"
        "- Blinding is best-effort: original citation formatting and prior exposure may reveal a version. "
        "Collect reviewer exposure/conflict disclosures.\n\n"
        "## Review process\n\n"
        "1. Give the reviewer the workbook and access to the local original PDFs under `data/pdfs/`; "
        "keep the coordinator key separate.\n"
        "2. Complete Reviewer details, then assess A and B independently using the unchanged 0/1/2 rubric. "
        "Check individual propositions, source adjacency, holdings versus submissions/lower-court reasoning, "
        "and statutory/procedural context.\n"
        "3. Open full judgments whenever an excerpt is insufficient. Record actual PDF pages/paragraphs, "
        "source context, per-answer verification statuses and uncertainty. PDF availability does not mean "
        "verification, and source membership does not mean semantic support. Do not guess; leave uncertain "
        "scores blank pending resolution.\n"
        "4. Retain independent reviewer records and adjudicate disagreements if a second reviewer is used. "
        "Document actual human identity, dates, expertise and sign-off. Do not claim independent double "
        "review or full-judgment verification unless actually performed.\n"
        "5. Return the annotated workbook to the coordinator. STOP: unblinding and final calculation "
        "are a later milestone. Do not use the old draft-workbook calculator as final adjudication analysis.\n\n"
        "## Interpretation limits\n\n"
        "H01–H30 remain a **development set** because their earlier failures informed V2. Even after "
        "human adjudication, this package cannot establish fresh held-out generalization, eliminate "
        "single-generation variability, establish perfect blinding, or prove a prompt-only causal effect. "
        "No final scores are calculated during preparation.\n"
    )
    # Check preservation again before writing. Exclusive file creation prevents accidental
    # overwrites; on write failure remove only paths successfully created by this invocation.
    if any(sha256(path) != baseline[name] for name, path in inputs.items()):
        raise ValueError("A source artifact changed during preparation")
    created_paths = []
    try:
        for path, data in ((Path(output), payload),
                           (Path(key_path), (json.dumps(key, ensure_ascii=False, indent=2) + "\n").encode("utf-8")),
                           (Path(protocol_path), protocol.encode("utf-8"))):
            with path.open("xb") as handle:
                created_paths.append(path)
                handle.write(data)
    except OSError:
        for path in reversed(created_paths):
            path.unlink()
        raise
    return key


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--seed", type=int, required=True,
                        help="Private coordinator seed; keep it and the generated mapping out of Git")
    args = parser.parse_args(argv)
    try:
        prepare_adjudication(output=args.output, key_path=args.key,
                             protocol_path=args.protocol, seed=args.seed)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"Adjudication preparation stopped: {exc}\n")
    print(f"Prepared 30 pairs / 60 answers / 180 BLANK human score cells: {args.output}")
    print(f"Coordinator-only mapping key: {args.key}")
    print(f"Provisional-score clarification and review protocol: {args.protocol}")
    print("Stopped at human annotation. No final scores calculated; no API calls made.")


if __name__ == "__main__":
    main()
