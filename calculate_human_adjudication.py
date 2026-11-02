"""Validate, unblind and summarize user-confirmed human excerpt-review scores.

Reads only the paired adjudication workbook; never imports provisional draft labels,
rewrites the workbook, calls a model, or claims independent/full-judgment validation.
"""

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import openpyxl

from compare_answer_quality_v1_v2 import (
    BOOTSTRAP_SAMPLES, EXPECTED_IDS, ROOT, SCORE_COLUMNS, SEED,
    audit_runs, canonical_hash, load_records, parse_score, sha256, summarize_pairs,
)
from prepare_human_adjudication import (
    DEFAULT_KEY, DEFAULT_WORKBOOK, REVIEW_COLUMNS, SOURCE_COLUMNS,
    SOURCE_HUMAN_COLUMNS, VERIFICATION_OPTIONS, make_assignment,
)

DEFAULT_REPORT = ROOT / "reports/v1_v2_human_adjudicated_comparison.md"
DEFAULT_JSON = ROOT / "reports/v1_v2_human_adjudicated_comparison.json"
EXCERPT_STATUS = "Verified against retrieved text excerpts"
DIMENSIONS = {"correctness": "Correctness", "citation_support": "Citation support", "completeness": "Completeness"}


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f"Duplicate JSON key: {name}")
        result[name] = value
    return result


def _text(cell, location):
    if cell.data_type == "f":
        raise ValueError(f"{location}: formulas are not accepted")
    return cell.value


def _headers(sheet, expected):
    actual = [cell.value for cell in sheet[1]]
    if actual != expected:
        raise ValueError(f"{sheet.title}: changed, missing or duplicated column headers")
    return {name: index for index, name in enumerate(actual)}


def validate_review(workbook_path, key_path, human_review_confirmed=False, confirmation_note=""):
    """Return validated unblinded labels plus transparent, self-reported provenance."""
    if not human_review_confirmed or not confirmation_note.strip():
        raise ValueError("Explicit human-review confirmation and a nonempty confirmation note are required")
    key = json.loads(Path(key_path).read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    if key.get("schema_version") != 1 or set(key.get("pairs", {})) != set(EXPECTED_IDS):
        raise ValueError("Key must cover exactly H01–H30 using schema version 1")
    preserved = key["preserved_inputs"]
    required_inputs = {"v1_jsonl", "v2_jsonl", "v1_provisional_draft", "v2_provisional_draft", "previous_provisional_comparison"}
    if set(preserved) != required_inputs:
        raise ValueError("Missing or unexpected preserved-input provenance")
    input_hashes = {"review_workbook": sha256(workbook_path), "mapping_key": sha256(key_path)}
    for name, item in preserved.items():
        if sha256(item["path"]) != item["sha256"]:
            raise ValueError(f"Preserved input changed: {name}")
        input_hashes[name] = item["sha256"]
    v1 = load_records(preserved["v1_jsonl"]["path"])
    v2 = load_records(preserved["v2_jsonl"]["path"])
    audit = audit_runs(v1, v2)
    if audit["confounds"]:
        raise ValueError("Recorded runs are confounded: " + "; ".join(audit["confounds"]))
    expected_assignment = make_assignment(seed=key["seed"])
    for qid in EXPECTED_IDS:
        pair = key["pairs"][qid]
        if {label: pair.get(label) for label in ("A", "B")} != expected_assignment[qid]:
            raise ValueError(f"{qid}: mapping does not match fixed-seed allocation")
        if pair.get("shared_evidence_sha256") != canonical_hash(v1[qid]["retrieval_response"]):
            raise ValueError(f"{qid}: shared evidence hash mismatch")
        for label in ("A", "B"):
            answer = {"v1": v1, "v2": v2}[pair[label]][qid]["answer_response"]["answer"]
            if pair.get("answer_sha256", {}).get(label) != hashlib.sha256(answer.encode("utf-8")).hexdigest():
                raise ValueError(f"{qid}: answer/key hash mismatch")
    workbook = openpyxl.load_workbook(workbook_path, data_only=False)
    try:
        if not {"Paired review", "Shared sources", "Reviewer details"} <= set(workbook.sheetnames):
            raise ValueError("Required adjudication sheets missing")
        sheet = workbook["Paired review"]
        columns = _headers(sheet, REVIEW_COLUMNS)
        labels = {"v1": {}, "v2": {}}
        review_rows, statuses = {}, Counter()
        names, dates, references = set(), set(), Counter()
        for row_number, row in enumerate(sheet.iter_rows(min_row=2), 2):
            values = {name: _text(row[index], f"Paired review row {row_number} {name}") for name, index in columns.items()}
            if all(value is None for value in values.values()):
                continue
            qid = values["Question ID"]
            if qid not in v1 or qid in review_rows:
                raise ValueError(f"Unexpected, missing or duplicate question ID: {qid!r}")
            if values["Topic"] != v1[qid]["topic"] or values["Exact question"] != v1[qid]["question"]:
                raise ValueError(f"{qid}: changed question or topic")
            if json.loads(values["Exact shared retrieval evidence and metadata"]) != v1[qid]["retrieval_response"]["results"]:
                raise ValueError(f"{qid}: changed shared evidence")
            row_record = {"reviewer": values["Human reviewer name"], "review_date": values["Review date"], "answers": {}}
            if not isinstance(row_record["reviewer"], str) or not row_record["reviewer"].strip() or not row_record["review_date"]:
                raise ValueError(f"{qid}: human reviewer name and review date required")
            names.add(row_record["reviewer"])
            dates.add(str(row_record["review_date"]))
            for label in ("A", "B"):
                version = key["pairs"][qid][label]
                original = {"v1": v1, "v2": v2}[version][qid]["answer_response"]["answer"]
                if values[f"Answer {label}"] != original:
                    raise ValueError(f"{qid}: changed answer {label}")
                scores = {dimension: parse_score(values[f"{label} {title} (0/1/2)"], f"{qid} {label} {dimension}")
                          for dimension, title in DIMENSIONS.items()}
                status = values[f"{label} Full-judgment verification status"]
                # Keep the user's non-dropdown wording verbatim and interpret it only
                # as excerpt-based assessment, never as proof that a PDF was checked.
                if status not in {EXCERPT_STATUS, VERIFICATION_OPTIONS[1]}:
                    raise ValueError(f"{qid} {label}: this excerpt-review calculator requires an explicit excerpt-only status; found {status!r}")
                statuses[status] += 1
                reference = values[f"{label} PDF pages / paragraphs checked"]
                references[str(reference)] += 1
                labels[version][qid] = scores
                row_record["answers"][version] = {"display_label": label, "scores": scores,
                    "verification_status_raw": status, "reference_entry_raw": reference,
                    "notes": values[f"{label} Review notes / uncertainty"]}
            row_record["pair_notes"] = values["Pair-level notes / unresolved issues"]
            review_rows[qid] = row_record
        if set(review_rows) != set(EXPECTED_IDS):
            raise ValueError("Review workbook must contain exactly H01–H30")
        source_sheet = workbook["Shared sources"]
        source_columns = _headers(source_sheet, SOURCE_COLUMNS)
        expected_sources = {(qid, result["rank"]): result for qid, record in v1.items()
                            for result in record["retrieval_response"]["results"]}
        seen = set()
        source_blank_fields = Counter()
        for row in source_sheet.iter_rows(min_row=2):
            values = {name: _text(row[index], f"Shared sources {name}") for name, index in source_columns.items()}
            if all(value is None for value in values.values()):
                continue
            identity = (values["Question ID"], values["Retrieval rank"])
            if identity in seen or identity not in expected_sources:
                raise ValueError(f"Duplicate or unexpected source: {identity}")
            seen.add(identity)
            expected = expected_sources[identity]
            metadata = {"Source reference": f"S{expected['rank']}", "Document ID": expected["doc_id"],
                "Chunk ID": expected.get("chunk_id"), "Case name": expected.get("case_name"),
                "SCR citation": expected.get("citation"), "Decision date": expected.get("decision_date"),
                "Source PDF": expected["source_pdf"], "Retrieval score (exact text)": json.dumps(expected.get("score")),
                "Retrieval mode": expected["retrieval_mode"], "Exact retrieved excerpt": expected["excerpt"]}
            if any(values[name] != value for name, value in metadata.items()):
                raise ValueError(f"Changed source metadata or excerpt: {identity}")
            for field in SOURCE_HUMAN_COLUMNS:
                source_blank_fields[field] += values[field] in (None, "")
        if seen != expected_sources.keys():
            raise ValueError("Missing shared-source rows")
        details = {}
        for row in workbook["Reviewer details"].iter_rows(min_row=2, max_col=2):
            field, value = (_text(cell, "Reviewer details") for cell in row)
            if field in details:
                raise ValueError("Duplicate reviewer-detail fields")
            details[field] = value
        if not details.get("Human reviewer name") or names != {details["Human reviewer name"]}:
            raise ValueError("Reviewer-details identity must match every question row")
        return labels, {
            "confirmation": {"basis": "User explicitly confirmed personal assessment and review in this session",
                             "user_confirmation": confirmation_note, "recorded_utc": datetime.now(timezone.utc).isoformat(),
                             "independently_authenticated": False},
            "review_basis": "Human-assessed retrieved-excerpt review; no full-judgment verification established",
            "reviewer_details_raw": details, "row_review_dates_raw": sorted(dates),
            "verification_status_counts_raw": dict(statuses), "reference_entry_counts_raw": dict(references),
            "source_review_blank_field_counts": dict(source_blank_fields),
            "question_count": len(review_rows), "answer_count": 2 * len(review_rows), "score_count": 6 * len(review_rows),
            "input_sha256": input_hashes, "per_question": review_rows,
            "missing_reviewer_provenance": [field for field, value in details.items() if value in (None, "")],
        }
    finally:
        workbook.close()


def render_report(result):
    summary = result["summary"]
    provenance = result["review_provenance"]
    lines = ["# User-confirmed human excerpt-review comparison — DEVELOPMENT", "",
        "## Review provenance and scope", "",
        "The reviewer explicitly confirmed personal assessment and review in the project conversation. "
        "This report analyzes the paired A/B adjudication workbook, not the earlier AI-assisted draft scores. "
        "The confirmation is self-reported; it is not independently authenticated or independent expert double review.", "",
        "**Review basis: retrieved text excerpts, not established full-judgment verification.** "
        "The raw status 'Verified against retrieved text excerpts' is accepted as excerpt-based only. "
        "Original workbook statuses, references, notes and scores were not rewritten.", "",
        "H01–H30 are a **development set**: earlier V1 failures informed V2. These results do not establish "
        "fresh held-out generalization, legal safety, or a prompt-only causal improvement.", "",
        f"- Paired questions: {provenance['question_count']}; answers: {provenance['answer_count']}; valid scores: {provenance['score_count']}.",
        "- Recorded model, retrieval settings and entire ordered evidence are identical across versions.",
        "- The private fixed-seed key, answer hashes, shared evidence and all source rows were validated before unblinding.",
        "- Source-ID membership is traceability, **not semantic citation support**; citation-support scores here are reviewer assessments.", "",
        "## Mean scores and paired changes", "",
        "| Dimension | V1 mean /2 | V2 mean /2 | V2 − V1 | Paired 95% CI | Improved | Unchanged | Degraded |",
        "|---|---:|---:|---:|---|---:|---:|---:|"]
    for dimension, values in summary.items():
        low, high = values["confidence_intervals"]["mean_difference"]
        lines.append(f"| {dimension} | {values['v1_mean']:.4f} | {values['v2_mean']:.4f} | {values['mean_difference']:+.4f} | "
                     f"[{low:+.4f}, {high:+.4f}] | {values['improved']} | {values['unchanged']} | {values['degraded']} |")
    if all(values["v1_mean"] == 2 and values["v2_mean"] == 2 for values in summary.values()):
        lines += ["", "## Rating ceiling and interpretation", "",
            "All 180 submitted scores are the maximum (2/2). Both versions have identical ratings on "
            "every question and dimension: **no observed V2 improvement** in this review. This is a "
            "rating ceiling; these scores do not discriminate between configurations.", "",
            "The degenerate difference intervals [0, 0] arise from constant observed paired labels. "
            "They do not establish zero uncertainty, statistical equivalence, or perfect legal accuracy "
            "outside this review. These labels supersede neither the historical failure evidence nor "
            "the need for fresh, independently reviewed questions."]
    lines += ["", "## Label distributions and score-2 rates", "",
        "| Dimension | Version | Score 0 | Score 1 | Score 2 | Score-2 percentage | Mean 95% CI |",
        "|---|---|---:|---:|---:|---:|---|"]
    for dimension, values in summary.items():
        for version in ("v1", "v2"):
            distribution = values[f"{version}_distribution"]
            low, high = values["confidence_intervals"][f"{version}_mean"]
            lines.append(f"| {dimension} | {version.upper()} | {distribution[0]} | {distribution[1]} | {distribution[2]} | "
                         f"{values[f'{version}_score_2_percent']:.2f}% | [{low:.4f}, {high:.4f}] |")
    lines += ["", "## Per-question differences (V2 − V1)", "",
              "| Question | Correctness | Citation support | Completeness |", "|---|---:|---:|---:|"]
    for qid in EXPECTED_IDS:
        lines.append(f"| {qid} | " + " | ".join(f"{summary[d]['per_question'][qid]:+d}" for d in SCORE_COLUMNS) + " |")
    lines += ["", "## Statistical procedure", "",
        f"Paired question-level percentile bootstrap, {result['bootstrap_samples']:,} samples, seed `{result['seed']}`. "
        "Each resampled question index is shared by V1 and V2. Endpoints use linearly interpolated 2.5th/97.5th "
        "percentiles. No multiplicity correction is applied. Mean scores summarize an ordinal rubric; small-sample "
        "bootstrap intervals do not establish population-wide legal correctness.", "",
        "## Recorded reviewer details", ""]
    for field, value in provenance["reviewer_details_raw"].items():
        lines.append(f"- {field}: `{json.dumps(value if value not in (None, '') else 'Not recorded', ensure_ascii=False, default=str)}`")
    lines += ["", "### Explicit confirmation", "",
              f"`{json.dumps(provenance['confirmation']['user_confirmation'], ensure_ascii=False)}`", "",
              "This conversational confirmation authorizes analysis but does not fill or substitute for a signed workbook field. "
              "The workbook sign-off and other missing disclosures remain unrecorded.", "",
              "### Verification limitations", "",
              "Raw per-answer verification statuses:", "",
              *[f"- `{status}`: {count} answers." for status, count in provenance["verification_status_counts_raw"].items()],
              "", "Raw page/paragraph-reference entries:", "",
              *[f"- `{reference}`: {count} answers." for reference, count in provenance["reference_entry_counts_raw"].items()],
              "", "Blank source-level review fields:", "",
              *[f"- {field}: {count}." for field, count in provenance["source_review_blank_field_counts"].items()],
              "", "These entries do not establish which full judgments or legal paragraphs were verified. "
              "Prior exposure, unblinding/conflicts and independent second-review status are not assumed absent merely "
              "because fields are blank. No inter-reviewer agreement or independent expert certification is claimed.",
              "", "## Interpretation and responsible reporting", "",
              "Report these as **single-reviewer, user-confirmed, excerpt-based development assessments**. "
              "Do not call them independently adjudicated ground truth or full-judgment-verified results. "
              "Citation formatting may compromise blinding. One generated answer per configuration/question, "
              "incomplete historical prompt/decoding provenance and unmeasured reviewer variability limit causal inference. "
              "The earlier AI-assisted comparison remains provisional and was not overwritten.", "",
              "## Input integrity", "", "| Input | SHA-256 |", "|---|---|"]
    for name, digest in provenance["input_sha256"].items():
        lines.append(f"| {name} | `{digest}` |")
    lines += ["", "Machine-readable output stores the unblinded reviewed labels, per-question differences, "
              "raw provenance and bootstrap parameters for reproducibility. No model/API call was made.", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--human-review-confirmed", action="store_true")
    parser.add_argument("--confirmation-note", default="")
    parser.add_argument("--bootstrap-samples", type=int, default=BOOTSTRAP_SAMPLES)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)
    created = []
    try:
        if args.bootstrap_samples < 1:
            raise ValueError("Bootstrap samples must be positive")
        if args.output.resolve() == args.json_output.resolve():
            raise ValueError("Report output paths must differ")
        if args.output.exists() or args.json_output.exists():
            raise ValueError("Output already exists; existing reports are never overwritten")
        labels, provenance = validate_review(args.workbook, args.key, args.human_review_confirmed, args.confirmation_note)
        summary = summarize_pairs(labels["v1"], labels["v2"], args.bootstrap_samples, args.seed)
        result = {"scope": "DEVELOPMENT", "review_provenance": provenance,
                  "bootstrap_samples": args.bootstrap_samples, "seed": args.seed,
                  "summary": summary, "unblinded_scores": labels}
        report = render_report(result)
        if sha256(args.workbook) != provenance["input_sha256"]["review_workbook"] or sha256(args.key) != provenance["input_sha256"]["mapping_key"]:
            raise ValueError("Workbook or key changed during calculation")
        for path, text in ((args.output, report), (args.json_output, json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n")):
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                created.append(path)
                handle.write(text)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        for path in reversed(created):
            path.unlink()
        parser.exit(2, f"Comparison stopped: {exc}\n")
    print(f"User-confirmed excerpt-review DEVELOPMENT comparison: {args.output}")
    print(f"Reproducible scores and provenance: {args.json_output}")
    for dimension, values in summary.items():
        print(f"{dimension}: V1 {values['v1_mean']:.4f}/2; V2 {values['v2_mean']:.4f}/2; "
              f"delta {values['mean_difference']:+.4f}; CI {values['confidence_intervals']['mean_difference']}")
    print("Original workbook, key, JSONL and provisional draft artifacts were not modified.")


if __name__ == "__main__":
    main()
