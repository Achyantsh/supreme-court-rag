"""Audit persisted answer runs and compare human labels without model/API calls.

First run with --prepare-review. Run without that flag only after human review.
Existing workbooks and reports are never overwritten.
"""

import argparse
import hashlib
import json
import math
import random
import statistics
from datetime import datetime, timezone
from pathlib import Path

import openpyxl


ROOT = Path(__file__).resolve().parent
EXPECTED_IDS = tuple(f"H{i:02d}" for i in range(1, 31))
MODEL = "gemini-3.1-flash-lite"
SCORE_COLUMNS = {
    "correctness": "Answer correctness (0/1/2)",
    "citation_support": "Citation support (0/1/2)",
    "completeness": "Answer completeness (0/1/2)",
}
DEFAULT_V1_JSONL = ROOT / "data/answer_evaluation_3_1_flash_lite_v1.jsonl"
DEFAULT_V2_JSONL = ROOT / "data/answer_evaluation_3_1_flash_lite_v2_dev.jsonl"
DEFAULT_V1_WORKBOOK = ROOT / "data/answer_review_3_1_flash_lite_v1.xlsx"
DEFAULT_V2_DEV_WORKBOOK = ROOT / "data/answer_review_3_1_flash_lite_v2_dev.xlsx"
DEFAULT_V2_WORKBOOK = ROOT / "data/answer_review_3_1_flash_lite_v2_final_review.xlsx"
DEFAULT_AUDIT = ROOT / "reports/v1_v2_comparability_audit.md"
DEFAULT_REPORT = ROOT / "reports/v1_v2_answer_quality_comparison.md"
SEED = 20261029
BOOTSTRAP_SAMPLES = 10000
LIMITATIONS = (
    "H01–H30 are now a DEVELOPMENT set: earlier V1 failures informed V2 prompt design. "
    "This comparison cannot establish generalization or final held-out improvement.\n\n"
    "The scores are human judgments on an ordinal 0/1/2 rubric. Reported means and "
    "bootstrap intervals are descriptive summaries of these 30 paired answers, not "
    "proof of general legal accuracy. Each configuration has only one saved answer "
    "per question; generation stochasticity, different run times and provider changes "
    "are not separated from configuration effects. Exact historical prompt text, "
    "generation parameters, model revision and code hashes were not persisted, so "
    "prompt-only causal attribution is not established.\n\n"
    "V1 lacks explicit persisted answer-version tags; its identification as V1 is "
    "inferred from the baseline artifact provenance and legacy response schema. V2 "
    "is explicitly tagged. V2 is a bundle of prompt, source-formatting and traceability "
    "changes, not an isolated instruction change.\n\n"
    "Source-ID membership validation is NOT semantic citation support. Supplied "
    "citation metadata is not a verified claim-to-evidence mapping. Reviewers must "
    "evaluate actual claims, qualifications, attribution and abstentions against the "
    "persisted excerpts, consulting original judgments when necessary. The excerpts "
    "are bounded retrieval windows, not complete judgments.\n\n"
    "The V2 workbook is not blinded to configuration and V1 scores already exist. "
    "Reviewer identity, consistency, independence and adjudication affect comparison "
    "validity; record them in Provenance. Bootstrap resamples questions as paired "
    "units, not individual score cells. Percentile intervals are nominal 95% intervals "
    "with no multiplicity correction across dimensions."
)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_hash(value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def load_records(path, expected_ids=EXPECTED_IDS):
    records = {}
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number}: record must be an object")
            question_id = record.get("question_id")
            if not isinstance(question_id, str) or question_id not in expected_ids:
                raise ValueError(f"{path}:{line_number}: unexpected question ID {question_id!r}")
            if question_id in records:
                raise ValueError(f"{path}: duplicate question ID {question_id}")
            records[question_id] = record
    missing = sorted(set(expected_ids) - records.keys())
    if missing:
        raise ValueError(f"{path}: missing question IDs: {', '.join(missing)}")
    return records


def audit_runs(v1, v2, expected_ids=EXPECTED_IDS):
    """Validate each run; record cross-run differences without hiding confounds."""
    if set(v1) != set(expected_ids) or set(v2) != set(expected_ids):
        raise ValueError("Both runs must contain exactly the expected question IDs")
    confounds = []
    per_question = []
    for question_id in expected_ids:
        a, b = v1[question_id], v2[question_id]
        for version, record in (("v1", a), ("v2", b)):
            response = record.get("answer_response", {})
            answer = response.get("answer")
            if (record.get("generation_status") != "success"
                    or not isinstance(answer, str) or not answer.strip()
                    or record.get("generation_error") not in (None, "", {})):
                raise ValueError(f"{question_id} {version}: successful non-empty answer required")
            if record.get("model") != MODEL or response.get("model") != MODEL:
                raise ValueError(f"{question_id} {version}: expected model {MODEL}")
            if not isinstance(record.get("question"), str) or not record["question"].strip():
                raise ValueError(f"{question_id} {version}: missing question text")
            if not isinstance(record.get("topic"), str) or not record["topic"].strip():
                raise ValueError(f"{question_id} {version}: missing topic")
            if response.get("question", response.get("query")) != record["question"]:
                raise ValueError(f"{question_id} {version}: answer-response question mismatch")
            retrieval = record.get("retrieval_response", {})
            results = retrieval.get("results")
            top_k = record.get("top_k")
            if type(top_k) is not int or top_k < 1:
                raise ValueError(f"{question_id} {version}: invalid top_k")
            if (not isinstance(results, list) or len(results) != top_k
                    or retrieval.get("count") != len(results)
                    or retrieval.get("question") != record["question"]):
                raise ValueError(f"{question_id} {version}: inconsistent retrieval envelope")
            mode = record.get("retrieval_mode")
            if mode not in {"dense", "bm25", "hybrid_rrf", "hybrid_reranked"}:
                raise ValueError(f"{question_id} {version}: unknown retrieval mode")
            if retrieval.get("retrieval_mode") != mode or response.get("retrieval_mode") != mode:
                raise ValueError(f"{question_id} {version}: retrieval mode disagreement")
            doc_ids = set()
            citations = response.get("citations", [])
            if not isinstance(citations, list) or len(citations) != len(results):
                raise ValueError(f"{question_id} {version}: incomplete supplied citation metadata")
            for rank, (result, citation) in enumerate(zip(results, citations), 1):
                if type(result.get("rank")) is not int or result["rank"] != rank:
                    raise ValueError(f"{question_id} {version}: invalid ordered retrieval rank")
                doc_id = result.get("doc_id")
                if not isinstance(doc_id, str) or not doc_id or doc_id in doc_ids:
                    raise ValueError(f"{question_id} {version}: missing/duplicate document identity")
                doc_ids.add(doc_id)
                if not isinstance(result.get("excerpt"), str) or not result["excerpt"].strip():
                    raise ValueError(f"{question_id} {version}: missing evidence excerpt")
                if result.get("retrieval_mode") != mode:
                    raise ValueError(f"{question_id} {version}: result retrieval mode disagreement")
                for key in ("case_name", "citation", "decision_date", "source_pdf", "score"):
                    if citation.get(key) != result.get(key):
                        raise ValueError(f"{question_id} {version}: citation {rank} {key} mismatch")
                if citation.get("excerpt") != result["excerpt"][:350] + "...":
                    raise ValueError(f"{question_id} {version}: citation preview differs from evidence")
                if version == "v2":
                    if (citation.get("source_id") != f"S{rank}"
                            or citation.get("doc_id") != doc_id or citation.get("rank") != rank):
                        raise ValueError(f"{question_id} v2: invalid source identity/rank mapping")
            tags = (record.get("answer_version"), response.get("answer_version"))
            if version == "v2" and tags != ("v2", "v2"):
                raise ValueError(f"{question_id} v2: both explicit version tags required")
            if version == "v1" and any(tag not in (None, "v1") for tag in tags):
                raise ValueError(f"{question_id} v1: unexpected version tag")
        differences = [key for key in ("question", "topic", "model", "retrieval_mode", "top_k", "sdk")
                       if a.get(key) != b.get(key)]
        evidence_equal = canonical_hash(a["retrieval_response"]) == canonical_hash(b["retrieval_response"])
        if not evidence_equal:
            differences.append("retrieval_response (ordered evidence/envelope)")
        if differences:
            confounds.append(f"{question_id}: {', '.join(differences)}")
        per_question.append({
            "question_id": question_id, "evidence_equal": evidence_equal,
            "v1_evidence_sha256": canonical_hash(a["retrieval_response"]),
            "v2_evidence_sha256": canonical_hash(b["retrieval_response"]),
            "differences": differences,
        })
    return {"confounds": confounds, "per_question": per_question}


def parse_score(value, location):
    # bool is an int subclass; floats must be integral, never truncated.
    if isinstance(value, bool):
        raise ValueError(f"{location}: boolean is not a review score")
    if isinstance(value, str):
        if value not in ("0", "1", "2"):
            raise ValueError(f"{location}: missing/invalid score {value!r}; use 0, 1 or 2")
        return int(value)
    if isinstance(value, (int, float)) and math.isfinite(value) and value in (0, 1, 2):
        return int(value)
    raise ValueError(f"{location}: missing/invalid score {value!r}; use 0, 1 or 2")


def load_review(path, records, require_complete=True):
    """Read formula-free labels and bind each reviewed answer to its JSONL record."""
    workbook = openpyxl.load_workbook(path, data_only=False)
    try:
        if "Answer Review" not in workbook:
            raise ValueError(f"{path}: missing Answer Review sheet")
        sheet = workbook["Answer Review"]
        headers = [cell.value for cell in sheet[1]]
        nonempty = [header for header in headers if header is not None]
        if len(set(nonempty)) != len(nonempty):
            raise ValueError(f"{path}: duplicate column headers")
        positions = {header: index for index, header in enumerate(headers) if header is not None}
        required = {"Question ID", "Topic", "Question", "Generated answer", "Model",
                    "Retrieved judgment IDs", "Cited case names/citations", "Evidence excerpts",
                    "Generation status", "Generation error", *SCORE_COLUMNS.values()}
        if not required <= positions.keys():
            raise ValueError(f"{path}: missing columns: {sorted(required - positions.keys())}")
        labels, errors = {}, []
        for row_number, cells in enumerate(sheet.iter_rows(min_row=2), 2):
            values = [cell.value for cell in cells]
            if all(value is None for value in values):
                continue
            question_id = values[positions["Question ID"]]
            if question_id not in records:
                raise ValueError(f"{path}:{row_number}: unexpected/missing question ID {question_id!r}")
            if question_id in labels:
                raise ValueError(f"{path}: duplicate question ID {question_id}")
            record = records[question_id]
            for header, expected in (
                ("Topic", record["topic"]), ("Question", record["question"]),
                ("Generated answer", record["answer_response"]["answer"]),
                ("Model", record["model"]), ("Generation status", record["generation_status"]),
            ):
                cell = cells[positions[header]]
                if cell.data_type == "f" or cell.value != expected:
                    raise ValueError(f"{path}:{question_id}: {header} does not match JSONL")
            if values[positions["Generation error"]] not in (None, ""):
                raise ValueError(f"{path}:{question_id}: unexpected generation error")
            results = record["retrieval_response"]["results"]
            evidence = [{key: item.get(key) for key in ("doc_id", "case_name", "citation", "excerpt")}
                        for item in results]
            citations = [{key: item.get(key) for key in ("case_name", "citation")}
                         for item in record["answer_response"]["citations"]]
            for header, expected in (
                ("Evidence excerpts", evidence),
                ("Retrieved judgment IDs", [item["doc_id"] for item in results]),
                ("Cited case names/citations", citations),
            ):
                try:
                    actual = json.loads(values[positions[header]])
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"{path}:{question_id}: invalid {header} JSON") from exc
                if actual != expected:
                    raise ValueError(f"{path}:{question_id}: {header} does not match JSONL")
            labels[question_id] = {}
            for dimension, header in SCORE_COLUMNS.items():
                cell = cells[positions[header]]
                try:
                    if cell.data_type == "f":
                        raise ValueError(f"{path}:{question_id}: formulas are not human labels")
                    labels[question_id][dimension] = parse_score(cell.value, f"{question_id} {header}")
                except ValueError as exc:
                    errors.append(str(exc))
        missing = set(records) - labels.keys()
        if missing:
            raise ValueError(f"{path}: missing question IDs: {', '.join(sorted(missing))}")
        if require_complete and errors:
            raise ValueError(f"Human review incomplete/invalid: {len(errors)} score(s) in {path}. "
                             + "; ".join(errors[:6]))
        return labels, errors
    finally:
        workbook.close()


def verify_review_provenance(path, inputs):
    workbook = openpyxl.load_workbook(path, data_only=False)
    try:
        if "Provenance" not in workbook:
            raise ValueError("V2 final review workbook lacks preparation provenance")
        provenance = {}
        for key, value in workbook["Provenance"].iter_rows(min_row=2, max_col=2):
            if key.value is None:
                continue
            if key.value in provenance:
                raise ValueError("Duplicate provenance keys")
            if key.data_type == "f" or value.data_type == "f":
                raise ValueError("Formula in preparation provenance")
            provenance[key.value] = value.value
        for name, source in inputs.items():
            if provenance.get(f"{name}_sha256") != sha256(source):
                raise ValueError(f"V2 review provenance mismatch: {name} changed since preparation")
        return provenance
    finally:
        workbook.close()


def percentile(values, probability):
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def paired_bootstrap(v1, v2, samples=BOOTSTRAP_SAMPLES, seed=SEED):
    if not v1 or len(v1) != len(v2) or type(samples) is not int or samples < 1:
        raise ValueError("Bootstrap needs nonempty equal-length pairs and positive sample count")
    rng = random.Random(seed)
    replicates = {"v1_mean": [], "v2_mean": [], "mean_difference": []}
    n = len(v1)
    for _ in range(samples):
        indices = [rng.randrange(n) for _ in range(n)]
        a = sum(v1[index] for index in indices) / n
        b = sum(v2[index] for index in indices) / n
        replicates["v1_mean"].append(a)
        replicates["v2_mean"].append(b)
        replicates["mean_difference"].append(b - a)
    return {key: (percentile(values, 0.025), percentile(values, 0.975))
            for key, values in replicates.items()}


def summarize_pairs(v1, v2, samples=BOOTSTRAP_SAMPLES, seed=SEED):
    if not v1 or set(v1) != set(v2):
        raise ValueError("Paired scoring requires identical nonempty question ID sets")
    summary = {}
    question_ids = sorted(v1)
    for dimension in SCORE_COLUMNS:
        a = [parse_score(v1[q].get(dimension), f"{q} v1 {dimension}") for q in question_ids]
        b = [parse_score(v2[q].get(dimension), f"{q} v2 {dimension}") for q in question_ids]
        differences = [new - old for old, new in zip(a, b)]
        summary[dimension] = {
            "v1_mean": statistics.mean(a), "v2_mean": statistics.mean(b),
            "mean_difference": statistics.mean(differences),
            "v1_distribution": {label: a.count(label) for label in (0, 1, 2)},
            "v2_distribution": {label: b.count(label) for label in (0, 1, 2)},
            "v1_score_2_percent": 100 * a.count(2) / len(a),
            "v2_score_2_percent": 100 * b.count(2) / len(b),
            "improved": sum(difference > 0 for difference in differences),
            "unchanged": differences.count(0),
            "degraded": sum(difference < 0 for difference in differences),
            "per_question": dict(zip(question_ids, differences)),
            "confidence_intervals": paired_bootstrap(a, b, samples, seed),
        }
    return summary


def write_new_text(path, text):
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def audit_markdown(audit, v1, v2, inputs, workbook_errors):
    lines = ["# V1 vs V2 comparability audit", "",
             f"Audited UTC: {datetime.now(timezone.utc).isoformat()}", "",
             "## Conclusion", ""]
    if audit["confounds"]:
        lines += ["**Potentially confounded comparison.** Recorded differences:", "",
                  *[f"- {item}" for item in audit["confounds"]]]
    else:
        lines += ["**Comparable for a paired descriptive DEVELOPMENT comparison on the recorded inputs.** "
                  "No question, topic, model, retrieval configuration, SDK or retrieval-evidence "
                  "differences were found. This is not proof of a prompt-only causal effect."]
    lines += ["", "## All-record checks", "",
              "- Both JSONL files contain exactly H01–H30, once each (30 records per run).",
              f"- Every record and answer response identifies `{MODEL}`.",
              "- Every record has successful generation, a non-empty answer and no generation error.",
              f"- V1 recorded settings: {sorted({(r['retrieval_mode'], r['top_k']) for r in v1.values()})}.",
              f"- V2 recorded settings: {sorted({(r['retrieval_mode'], r['top_k']) for r in v2.values()})}.",
              "- Entire retrieval-response objects were compared exactly via canonical JSON hashes: "
              "ordered ranks, doc IDs, chunk IDs, excerpts, case names, SCR citations, decision dates, "
              "PDF names, scores, result modes and response envelopes. Object key order is immaterial; "
              "list order and excerpt whitespace are preserved.",
              "- Each run's supplied citation metadata/previews were checked against its retrieval results. "
              "All V2 S1–S5 identity/rank mappings were checked; this is not semantic support verification.",
              "- V1 answer-version tags are absent in the legacy records: V1 is inferred from baseline "
              "provenance and schema, not a frozen historical prompt/hash. Both V2 version tags are explicit.",
              "- Both original workbooks have exact H01–H30 coverage and their questions, topics, answers, "
              "models, statuses, supplied citations, document-ID lists and evidence projections match JSONL.",
              f"- V1 workbook missing/invalid labels: {len(workbook_errors['v1'])}/90.",
              f"- Existing V2 development workbook missing/invalid labels: {len(workbook_errors['v2_dev'])}/90.",
              "- Original workbook evidence columns retain doc_id, case_name, citation and excerpt only; "
              "the new workbook adds a Sources sheet with full persisted retrieval metadata.", "",
              "## Run provenance", ""]
    for version, records in (("V1", v1), ("V2", v2)):
        lines += [f"- {version} run timestamps: " + ", ".join(sorted({r['run_started_utc'] for r in records.values()})),
                  f"- {version} SDK metadata: `{json.dumps(next(iter(records.values())).get('sdk'), sort_keys=True)}`."]
    lines += ["", "## Per-question evidence comparison", "",
              "| Question | Exact retrieval equality | V1 evidence SHA-256 | V2 evidence SHA-256 |",
              "|---|---|---|---|"]
    for item in audit["per_question"]:
        lines.append(f"| {item['question_id']} | {item['evidence_equal']} | "
                     f"`{item['v1_evidence_sha256']}` | `{item['v2_evidence_sha256']}` |")
    lines += ["", "## Preserved source files", "", "| Input | Path | SHA-256 |", "|---|---|---|"]
    for name, path in inputs.items():
        lines.append(f"| {name} | `{Path(path).name}` | `{sha256(path)}` |")
    lines += ["", "## Human review gate", "",
              "The new V2 final-review workbook contains original answers, exact retrieved excerpts, "
              "resolved source metadata and citation-navigation aids. All 90 human score cells and "
              "review notes start blank. Existing scores are not copied. No quality improvement is claimed.",
              "", "After review, run from the repository root:", "", "```powershell",
              ".\\.venv\\Scripts\\python.exe compare_answer_quality_v1_v2.py", "```", "",
              "The calculator rejects missing, duplicate or unexpected IDs, changed reviewed content, "
              "changed source hashes, formulas, missing labels and non-0/1/2 values before writing a report. "
              "It never overwrites an existing review workbook or comparison report.",
              "", "## Methodological limitations", "", LIMITATIONS, ""]
    return "\n".join(lines)


def comparison_markdown(summary, audit, inputs, provenance, samples, seed):
    lines = ["# V1 vs V2 answer-quality comparison — DEVELOPMENT", "",
             f"Generated UTC: {datetime.now(timezone.utc).isoformat()}", "",
             "All 30 question IDs have complete valid human labels for both versions. "
             "No labels were generated or assigned by this calculator.", "",
             "## Comparability", ""]
    lines += (["**Potentially confounded.** Do not attribute differences to the V2 prompt alone.",
               *[f"- {item}" for item in audit["confounds"]]] if audit["confounds"] else
              ["Recorded questions, topics, models, retrieval settings, SDK and complete ordered "
               "retrieval responses match. Historical prompt/decoding provenance remains incomplete."])
    lines += ["", "## Mean scores and paired differences", "",
              "| Dimension | V1 mean /2 | V2 mean /2 | V2 − V1 | Paired 95% CI for difference | Improved | Unchanged | Degraded |",
              "|---|---:|---:|---:|---|---:|---:|---:|"]
    for dimension, result in summary.items():
        low, high = result["confidence_intervals"]["mean_difference"]
        lines.append(f"| {dimension} | {result['v1_mean']:.4f} | {result['v2_mean']:.4f} | "
                     f"{result['mean_difference']:+.4f} | [{low:+.4f}, {high:+.4f}] | "
                     f"{result['improved']} | {result['unchanged']} | {result['degraded']} |")
    lines += ["", "## Label distributions and maximum-score rates", "",
              "| Dimension | Version | Score 0 | Score 1 | Score 2 | Receiving score 2 | Mean 95% CI |",
              "|---|---|---:|---:|---:|---:|---|"]
    for dimension, result in summary.items():
        for version in ("v1", "v2"):
            distribution = result[f"{version}_distribution"]
            low, high = result["confidence_intervals"][f"{version}_mean"]
            lines.append(f"| {dimension} | {version.upper()} | {distribution[0]} | {distribution[1]} | "
                         f"{distribution[2]} | {result[f'{version}_score_2_percent']:.2f}% | [{low:.4f}, {high:.4f}] |")
    lines += ["", "## Per-question V2 minus V1 scores", "",
              "| Question | Correctness | Citation support | Completeness |", "|---|---:|---:|---:|"]
    for question_id in sorted(next(iter(summary.values()))["per_question"]):
        values = " | ".join(f"{summary[d]['per_question'][question_id]:+d}" for d in SCORE_COLUMNS)
        lines.append(f"| {question_id} | {values} |")
    lines += ["", "## Statistical procedure", "",
              f"Paired percentile bootstrap: {samples:,} replicates, seed `{seed}`, using Python "
              "`random.Random`. Each replicate samples 30 question indices with replacement, "
              "applying the same indices to V1 and V2. Interval endpoints are linearly interpolated "
              "2.5th and 97.5th percentiles. Counts and maximum-score percentages use denominator 30. "
              "Positive differences describe higher V2 review scores, not an established causal effect.",
              "", "## Reviewer provenance", ""]
    for key in ("Reviewer identity", "Review date", "Adjudication"):
        # JSON quoting keeps reviewer-provided multiline text from becoming Markdown structure.
        lines.append(f"- {key}: `{json.dumps(provenance.get(key) or 'Not recorded', ensure_ascii=False)}`")
    lines += ["", "## Input hashes at comparison time", "", "| Input | SHA-256 |", "|---|---|"]
    for name, path in inputs.items():
        lines.append(f"| {name} (`{Path(path).name}`) | `{sha256(path)}` |")
    lines += ["", "## Limitations", "", LIMITATIONS, ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-review", action="store_true", help="Audit inputs and create a NEW blank V2 workbook; do not calculate quality.")
    parser.add_argument("--v1-jsonl", type=Path, default=DEFAULT_V1_JSONL)
    parser.add_argument("--v2-jsonl", type=Path, default=DEFAULT_V2_JSONL)
    parser.add_argument("--v1-workbook", type=Path, default=DEFAULT_V1_WORKBOOK)
    parser.add_argument("--v2-dev-workbook", type=Path, default=DEFAULT_V2_DEV_WORKBOOK)
    parser.add_argument("--v2-workbook", type=Path, default=DEFAULT_V2_WORKBOOK)
    parser.add_argument("--audit-output", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--bootstrap-samples", type=int, default=BOOTSTRAP_SAMPLES)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)
    try:
        if args.bootstrap_samples < 1:
            raise ValueError("--bootstrap-samples must be positive")
        inputs = {"v1_jsonl": args.v1_jsonl, "v2_jsonl": args.v2_jsonl,
                  "v1_workbook": args.v1_workbook, "v2_dev_workbook": args.v2_dev_workbook}
        initial_hashes = {name: sha256(path) for name, path in inputs.items()}
        v1 = load_records(args.v1_jsonl)
        v2 = load_records(args.v2_jsonl)
        audit = audit_runs(v1, v2)
        labels_v1, errors_v1 = load_review(args.v1_workbook, v1, require_complete=False)
        _, errors_v2_dev = load_review(args.v2_dev_workbook, v2, require_complete=False)
        if args.prepare_review:
            if args.v2_workbook.exists() or args.audit_output.exists():
                raise ValueError("Preparation outputs already exist; refusing to overwrite review work or audit")
            from prepare_answer_quality_review import create_review_workbook
            provenance = {f"{name}_sha256": value for name, value in initial_hashes.items()}
            provenance.update({"prepared_utc": datetime.now(timezone.utc).isoformat(),
                               "evaluation_scope": "DEVELOPMENT; V1 failures informed V2",
                               "v1_version": "Inferred legacy V1; explicit tags absent",
                               "v2_version": "Explicit v2 tags on records and responses"})
            text = audit_markdown(audit, v1, v2, inputs, {"v1": errors_v1, "v2_dev": errors_v2_dev})
            create_review_workbook([v2[q] for q in EXPECTED_IDS], args.v2_workbook, provenance)
            write_new_text(args.audit_output, text)
            print(f"Prepared 30 V2 answers with 90 BLANK score cells: {args.v2_workbook}")
            print(f"Comparability audit: {args.audit_output}")
            print("Stopped for human annotation. No answer-quality comparison was calculated.")
        else:
            # Validate EVERYTHING before bootstrapping or opening a report output.
            labels_v1, _ = load_review(args.v1_workbook, v1)
            labels_v2, _ = load_review(args.v2_workbook, v2)
            provenance = verify_review_provenance(args.v2_workbook, inputs)
            if args.output.exists():
                raise ValueError(f"Refusing to overwrite comparison report: {args.output}")
            summary = summarize_pairs(labels_v1, labels_v2, args.bootstrap_samples, args.seed)
            report_inputs = {**inputs, "v2_final_workbook": args.v2_workbook}
            text = comparison_markdown(summary, audit, report_inputs, provenance, args.bootstrap_samples, args.seed)
            write_new_text(args.output, text)
            print(f"Wrote DEVELOPMENT comparison of 30 fully human-reviewed pairs: {args.output}")
        for name, path in inputs.items():
            if sha256(path) != initial_hashes[name]:
                raise ValueError(f"Source artifact changed during operation: {path}")
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"Evaluation stopped: {exc}\n")
    return 0


if __name__ == "__main__":
    main()
