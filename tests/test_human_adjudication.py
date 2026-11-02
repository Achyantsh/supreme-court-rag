"""Offline human-adjudication tests: all inputs and outputs are temporary fixtures."""

import copy
import hashlib
import io
import json
import os
import random
import tempfile
import unittest
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import quote, unquote

import openpyxl
from openpyxl.utils import get_column_letter

import compare_answer_quality_v1_v2 as compare
import prepare_human_adjudication as adjudication
from test_answer_quality_comparison import synthetic_record, write_review


IDS = tuple(f"H{i:02d}" for i in range(1, 31))
SCORE_HEADERS = [f"{label} {dimension} (0/1/2)" for label in ("A", "B")
                 for dimension in ("Correctness", "Citation support", "Completeness")]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def headers(sheet):
    return {cell.value: cell.column for cell in sheet[1]}


class AssignmentTests(unittest.TestCase):
    def test_exact_pairs_reproducible_independent_of_input_order(self):
        assignment = adjudication.make_assignment(seed=8675309)
        self.assertEqual(adjudication.EXPECTED_IDS, IDS)
        self.assertEqual(list(assignment), list(IDS))
        self.assertEqual(assignment, adjudication.make_assignment(IDS, seed=8675309))
        self.assertEqual(assignment, adjudication.make_assignment(reversed(IDS), seed=8675309))
        for mapping in assignment.values():
            self.assertEqual(set(mapping), {"A", "B"})
            self.assertEqual(Counter(mapping.values()), Counter({"v1": 1, "v2": 1}))

    def test_randomized_balanced_layout_changes_with_seed_without_global_rng_changes(self):
        before = random.getstate()
        first = adjudication.make_assignment(seed=8675309)
        second = adjudication.make_assignment(seed=8675310)
        self.assertEqual(random.getstate(), before)
        self.assertNotEqual(first, second)
        for assignment in (first, second):
            for label in ("A", "B"):
                self.assertEqual(Counter(pair[label] for pair in assignment.values()),
                                 Counter({"v1": 15, "v2": 15}))
            placements = [assignment[qid]["A"] for qid in IDS]
            self.assertGreater(sum(a != b for a, b in zip(placements, placements[1:])), 1)

    def test_private_seed_must_be_explicit(self):
        for seed in (None, True, "synthetic"):
            with self.subTest(seed=seed), self.assertRaisesRegex(ValueError, "private integer seed"):
                adjudication.make_assignment(seed=seed)

    def test_empty_and_duplicate_assignment_ids_rejected(self):
        for ids in ([], ["H01", "H01"], [*IDS, "H01"]):
            with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, "unique nonempty"):
                adjudication.make_assignment(ids)


class AdjudicationFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="synthetic-human-adjudication-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.pdf_dir = self.directory / "synthetic pdfs"
        self.pdf_dir.mkdir()
        (self.pdf_dir / "synthetic-1.pdf").write_bytes(b"%PDF-1.4\nSynthetic only, not a judgment.\n")
        self.v1 = {qid: synthetic_record(qid, "v1") for qid in IDS}
        self.v2 = {qid: synthetic_record(qid, "v2") for qid in IDS}
        self.assignment = adjudication.make_assignment(seed=8675309)
        self.output = self.directory / "reviewer.xlsx"
        self.key_path = self.directory / "coordinator-only.json"
        self.protocol_path = self.directory / "protocol.md"

    def build(self):
        payload = adjudication.build_workbook(self.v1, self.v2, self.assignment,
                                              self.pdf_dir, self.output)
        self.assertIsInstance(payload, bytes)
        self.assertFalse(self.output.exists(), "build_workbook must only return bytes")
        workbook = openpyxl.load_workbook(io.BytesIO(payload), data_only=False)
        self.addCleanup(workbook.close)
        return workbook, payload

    def write_jsonl(self, path, records):
        path.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records)
                        + "\n", encoding="utf-8")

    def prepare_inputs(self):
        self.inputs = {
            "v1_jsonl": self.directory / "baseline-input.jsonl",
            "v2_jsonl": self.directory / "candidate-input.jsonl",
            "v1_draft": self.directory / "baseline-ai-draft.xlsx",
            "v2_draft": self.directory / "candidate-ai-draft.xlsx",
            "previous_report": self.directory / "previous-provisional.md",
        }
        self.write_jsonl(self.inputs["v1_jsonl"], reversed(list(self.v1.values())))
        self.write_jsonl(self.inputs["v2_jsonl"], self.v2.values())
        for version, records, score in (("v1", self.v1, 0), ("v2", self.v2, 2)):
            path = self.inputs[f"{version}_draft"]
            scores = {qid: {dimension: score for dimension in compare.SCORE_COLUMNS} for qid in IDS}
            write_review(path, list(records.values()), scores)
            workbook = openpyxl.load_workbook(path)
            try:
                review = workbook["Answer Review"]
                review.cell(2, headers(review)["Review notes"], "PRIVATE_AI_DRAFT_NOTE")
                provenance = workbook.create_sheet("Provenance")
                provenance.append(["Field", "Value"])
                provenance.append(["Reviewer identity", "Synthetic AI-assisted draft reviewer"])
                provenance.append(["Review date", "2026-01-01"])
                provenance.append(["Adjudication", "No independent human judgment review"])
                sources = workbook.create_sheet("Draft sources")
                sources.append(["Preserve this synthetic evidence", records["H01"]["retrieval_response"]["results"][0]["excerpt"]])
                workbook.save(path)
            finally:
                workbook.close()
        self.inputs["previous_report"].write_text(
            "# Synthetic provisional comparison\ncomplete valid human labels\nPRIVATE_OLD_REPORT\n",
            encoding="utf-8")
        return {**self.inputs, "output": self.output, "key_path": self.key_path,
                "protocol_path": self.protocol_path, "pdf_dir": self.pdf_dir, "seed": 8675309}

    def assert_no_outputs(self):
        for path in (self.output, self.key_path, self.protocol_path):
            self.assertFalse(path.exists(), str(path))

    def assert_human_fields_blank(self, workbook):
        for sheet_name, human_headers in (("Paired review", adjudication.HUMAN_COLUMNS),
                                           ("Shared sources", adjudication.SOURCE_HUMAN_COLUMNS)):
            sheet = workbook[sheet_name]
            positions = headers(sheet)
            for row in range(2, sheet.max_row + 1):
                for header in human_headers:
                    self.assertIsNone(sheet.cell(row, positions[header]).value,
                                      f"{sheet_name}: {row}, {header}")
        details = workbook["Reviewer details"]
        self.assertEqual(details.max_column, 2)
        self.assertEqual(details.max_row, 11)
        for row in range(2, details.max_row + 1):
            self.assertTrue(details.cell(row, 1).value)
            self.assertIsNone(details.cell(row, 2).value)


class WorkbookTests(AdjudicationFixture):
    def test_exact_30_pairs_verbatim_answers_shared_evidence_and_all_blank_human_fields(self):
        original = copy.deepcopy((self.v1, self.v2, self.assignment))
        audit = compare.audit_runs(self.v1, self.v2)
        self.assertEqual(audit["confounds"], [])
        self.assertEqual(len(audit["per_question"]), 30)
        workbook, _ = self.build()
        review = workbook["Paired review"]
        self.assertEqual([cell.value for cell in review[1]], adjudication.REVIEW_COLUMNS)
        self.assertEqual(review.max_row, 31)
        positions = headers(review)
        self.assertEqual([review.cell(row, positions["Question ID"]).value for row in range(2, 32)], list(IDS))
        for row, qid in enumerate(IDS, 2):
            self.assertEqual(review.cell(row, positions["Topic"]).value, self.v1[qid]["topic"])
            self.assertEqual(review.cell(row, positions["Exact question"]).value, self.v1[qid]["question"])
            for label in ("A", "B"):
                record = {"v1": self.v1, "v2": self.v2}[self.assignment[qid][label]][qid]
                self.assertEqual(review.cell(row, positions[f"Answer {label}"]).value,
                                 record["answer_response"]["answer"])
            shared = review.cell(row, positions["Exact shared retrieval evidence and metadata"]).value
            for records in (self.v1, self.v2):
                self.assertEqual(json.loads(shared), records[qid]["retrieval_response"]["results"])
        self.assertEqual(len(SCORE_HEADERS), 6)
        scores = [review.cell(row, positions[header]).value for row in range(2, 32) for header in SCORE_HEADERS]
        self.assertEqual(scores, [None] * 180)
        self.assert_human_fields_blank(workbook)
        self.assertEqual((self.v1, self.v2, self.assignment), original)

    def test_six_score_dropdowns_and_three_verification_dropdowns_without_prefill(self):
        workbook, _ = self.build()
        for sheet_name, expected_headers in (
                ("Paired review", SCORE_HEADERS + [f"{label} Full-judgment verification status" for label in ("A", "B")]),
                ("Shared sources", ["Full-judgment verification status"])):
            sheet = workbook[sheet_name]
            positions = headers(sheet)
            validations = list(sheet.data_validations.dataValidation)
            expected_ranges = {
                f"{get_column_letter(positions[header])}2:{get_column_letter(positions[header])}{sheet.max_row}": header
                for header in expected_headers
            }
            self.assertEqual(len(validations), len(expected_headers))
            self.assertEqual({str(item.sqref) for item in validations}, set(expected_ranges))
            for validation in validations:
                header = expected_ranges[str(validation.sqref)]
                options = ("0", "1", "2") if header in SCORE_HEADERS else adjudication.VERIFICATION_OPTIONS
                self.assertEqual(validation.type, "list")
                self.assertEqual(validation.formula1, '"' + ",".join(options) + '"')
                self.assertTrue(validation.allow_blank)
                self.assertEqual(validation.errorStyle, "stop")
                self.assertTrue(validation.showErrorMessage)
                self.assertFalse(validation.showDropDown)
        self.assert_human_fields_blank(workbook)

    def test_full_exact_sources_scores_pdf_links_missing_pdf_and_pair_navigation(self):
        workbook, _ = self.build()
        sources = workbook["Shared sources"]
        self.assertEqual([cell.value for cell in sources[1]], adjudication.SOURCE_COLUMNS)
        self.assertEqual(sources.max_row, 61)
        positions = headers(sources)
        review = workbook["Paired review"]
        for index, qid in enumerate(IDS):
            pair_row = index + 2
            first_source_row = index * 2 + 2
            self.assertEqual(review.cell(pair_row, headers(review)["Shared sources"]).hyperlink.location,
                             f"'Shared sources'!A{first_source_row}")
            for offset, result in enumerate(self.v1[qid]["retrieval_response"]["results"]):
                row = first_source_row + offset
                expected = {
                    "Question ID": qid, "Source reference": f"S{result['rank']}",
                    "Retrieval rank": result["rank"], "Document ID": result["doc_id"],
                    "Chunk ID": result["chunk_id"], "Case name": result["case_name"],
                    "SCR citation": result["citation"], "Decision date": result["decision_date"],
                    "Source PDF": result["source_pdf"], "Retrieval mode": result["retrieval_mode"],
                    "Exact retrieved excerpt": result["excerpt"],
                    "Retrieval score (exact text)": json.dumps(result["score"], allow_nan=False),
                }
                for header, value in expected.items():
                    self.assertEqual(sources.cell(row, positions[header]).value, value)
                self.assertEqual(sources.cell(row, positions["Retrieval score (exact text)"]).data_type, "s")
                preview = self.v1[qid]["answer_response"]["citations"][offset]["excerpt"]
                self.assertNotEqual(sources.cell(row, positions["Exact retrieved excerpt"]).value, preview)
                pdf_cell = sources.cell(row, positions["Open original judgment PDF"])
                availability = sources.cell(row, positions["Local PDF availability"]).value
                if offset == 0:
                    self.assertEqual(availability, "Available locally (not yet verified)")
                    relative = os.path.relpath(self.pdf_dir / result["source_pdf"], self.output.parent).replace("\\", "/")
                    self.assertEqual(pdf_cell.hyperlink.target, quote(relative, safe="/:"))
                    self.assertEqual((self.output.parent / unquote(pdf_cell.hyperlink.target)).resolve(),
                                     (self.pdf_dir / result["source_pdf"]).resolve())
                else:
                    self.assertEqual(availability, "Missing locally; obtain original judgment")
                    self.assertEqual(pdf_cell.value, "PDF unavailable")
                    self.assertIsNone(pdf_cell.hyperlink)
                self.assertIsNone(sources.cell(row, positions["Full-judgment verification status"]).value)
                self.assertEqual(sources.cell(row, positions["Back to pair"]).hyperlink.location,
                                 f"'Paired review'!A{pair_row}")

    def test_formula_like_source_text_is_preserved_not_executed(self):
        for prefix in ("=", "+", "-", "@"):
            with self.subTest(prefix=prefix):
                text = prefix + 'HYPERLINK("synthetic", "not executable")'
                for records in (self.v1, self.v2):
                    record = records["H01"]
                    result = record["retrieval_response"]["results"][0]
                    result["excerpt"] = result["case_name"] = text
                    record["answer_response"]["citations"][0].update(case_name=text, excerpt=text + "...")
                workbook, _ = self.build()
                sources = workbook["Shared sources"]
                for header in ("Case name", "Exact retrieved excerpt"):
                    cell = sources.cell(2, headers(sources)[header])
                    self.assertEqual(cell.value, text)
                    self.assertEqual(cell.data_type, "s")
                for sheet in workbook:
                    self.assertFalse(any(cell.data_type == "f" for row in sheet for cell in row))

    def test_oversize_source_text_rejected_without_truncation_or_output(self):
        for records in (self.v1, self.v2):
            record = records["H01"]
            result = record["retrieval_response"]["results"][0]
            result["excerpt"] = "x" * 32768
            record["answer_response"]["citations"][0]["excerpt"] = result["excerpt"][:350] + "..."
        with self.assertRaisesRegex(ValueError, "32767-character limit"):
            self.build()
        self.assert_no_outputs()

    def test_bad_assignments_rejected(self):
        for kind in ("missing", "extra", "same-version", "wrong-version", "wrong-label"):
            with self.subTest(kind=kind):
                assignment = copy.deepcopy(self.assignment)
                if kind == "missing":
                    assignment.pop("H30")
                elif kind == "extra":
                    assignment["H31"] = {"A": "v1", "B": "v2"}
                elif kind == "same-version":
                    assignment["H01"] = {"A": "v1", "B": "v1"}
                elif kind == "wrong-version":
                    assignment["H01"] = {"A": "v1", "B": "v3"}
                else:
                    assignment["H01"] = {"A": "v1", "C": "v2"}
                with self.assertRaisesRegex(ValueError, "Assignment|Each pair"):
                    adjudication.build_workbook(self.v1, self.v2, assignment, self.pdf_dir, self.output)
                self.assert_no_outputs()

    def test_direct_build_requires_exact_30_record_ids(self):
        for version in ("v1", "v2"):
            for kind in ("missing", "extra"):
                with self.subTest(version=version, kind=kind):
                    runs = copy.deepcopy({"v1": self.v1, "v2": self.v2})
                    if kind == "missing":
                        runs[version].pop("H30")
                    else:
                        runs[version]["H31"] = synthetic_record("H31", version)
                    with self.assertRaisesRegex(ValueError, "exactly the expected question IDs"):
                        adjudication.build_workbook(runs["v1"], runs["v2"], self.assignment, self.pdf_dir, self.output)
                    self.assert_no_outputs()


class PreparationTests(AdjudicationFixture):
    def test_prepare_preserves_all_inputs_records_key_hashes_and_corrects_provisional_status(self):
        kwargs = self.prepare_inputs()
        preserved_paths = [*self.inputs.values(), *self.pdf_dir.iterdir()]
        before = {path: path.read_bytes() for path in preserved_paths}
        key = adjudication.prepare_adjudication(**kwargs)
        self.assertEqual(json.loads(self.key_path.read_text(encoding="utf-8")), key)
        self.assertEqual(key["seed"], 8675309)
        self.assertEqual(key["initial_workbook_sha256"], digest(self.output.read_bytes()))
        self.assertEqual(set(key["pairs"]), set(IDS))
        for qid in IDS:
            pair = key["pairs"][qid]
            self.assertEqual({label: pair[label] for label in ("A", "B")}, self.assignment[qid])
            self.assertEqual(pair["shared_evidence_sha256"], compare.canonical_hash(self.v1[qid]["retrieval_response"]))
            for label in ("A", "B"):
                record = {"v1": self.v1, "v2": self.v2}[pair[label]][qid]
                self.assertEqual(pair["answer_sha256"][label], digest(record["answer_response"]["answer"].encode("utf-8")))
        for name, argument in (("v1_jsonl", "v1_jsonl"), ("v2_jsonl", "v2_jsonl"),
                               ("v1_provisional_draft", "v1_draft"), ("v2_provisional_draft", "v2_draft"),
                               ("previous_provisional_comparison", "previous_report")):
            path = self.inputs[argument]
            self.assertEqual(key["preserved_inputs"][name], {"path": str(path), "sha256": digest(before[path])})
        self.assertEqual(key["pdf_sha256"], {"synthetic-1.pdf": digest(before[self.pdf_dir / "synthetic-1.pdf"]),
                                               "synthetic-2.pdf": None})
        for version in ("v1", "v2"):
            self.assertEqual(key["draft_reviewer_provenance"][version]["Reviewer identity"],
                             "Synthetic AI-assisted draft reviewer")
        self.assertIn("PROVISIONAL AI-ASSISTED", key["old_scores_status"])
        self.assertIn("not independent human ground truth", key["old_scores_status"])
        for path, original in before.items():
            self.assertEqual(path.read_bytes(), original, str(path))
        protocol = self.protocol_path.read_text(encoding="utf-8")
        for text in ("annotation pending", "Correction", "provisional AI-assisted draft assessments",
                     "not independent human-reviewed ground truth", "complete valid human labels",
                     "overstates", "180 initially blank", "best-effort", "development set",
                     "No final scores are calculated", "Do not cite"):
            self.assertIn(text, protocol)
        workbook = openpyxl.load_workbook(self.output, data_only=False)
        try:
            self.assert_human_fields_blank(workbook)
            positions = headers(workbook["Paired review"])
            for row, qid in enumerate(IDS, 2):
                for label in ("A", "B"):
                    answer = workbook["Paired review"].cell(row, positions[f"Answer {label}"]).value
                    self.assertEqual(digest(answer.encode("utf-8")), key["pairs"][qid]["answer_sha256"][label])
        finally:
            workbook.close()

    def test_reviewer_workbook_has_no_hidden_or_coordinator_metadata(self):
        key = adjudication.prepare_adjudication(**self.prepare_inputs())
        workbook = openpyxl.load_workbook(self.output, data_only=False)
        try:
            self.assertEqual(workbook.sheetnames, ["Instructions", "Paired review", "Shared sources", "Reviewer details"])
            self.assertFalse(workbook.defined_names)
            for sheet in workbook:
                self.assertEqual(sheet.sheet_state, "visible")
                self.assertFalse(any(dimension.hidden for dimension in sheet.column_dimensions.values()))
                self.assertFalse(any(dimension.hidden for dimension in sheet.row_dimensions.values()))
                for row in sheet:
                    for cell in row:
                        self.assertIsNone(cell.comment)
                        self.assertNotEqual(cell.data_type, "f")
            self.assertEqual(workbook["Paired review"].max_column, len(adjudication.REVIEW_COLUMNS))
            self.assertEqual(workbook["Shared sources"].max_column, len(adjudication.SOURCE_COLUMNS))
        finally:
            workbook.close()
        with zipfile.ZipFile(self.output) as archive:
            self.assertFalse(any(name.startswith(("customXml/", "xl/embeddings/", "xl/externalLinks/")) for name in archive.namelist()))
            xml = "\n".join(archive.read(name).decode("utf-8") for name in archive.namelist()
                            if name.endswith((".xml", ".rels")))
        forbidden = [str(key["seed"]), self.key_path.name, "answer_version", "answer_sha256",
                     "shared_evidence_sha256", "preserved_inputs", "schema_version", "source_id",
                     "answer_response", "retrieval_response", "PRIVATE_AI_DRAFT_NOTE", "PRIVATE_OLD_REPORT",
                     "Synthetic AI-assisted draft reviewer", "synthetic-sdk", compare.MODEL]
        forbidden.extend(path.name for path in self.inputs.values())
        forbidden.extend(entry["sha256"] for entry in key["preserved_inputs"].values())
        forbidden.extend(key["pdf_sha256"].values())
        for pair in key["pairs"].values():
            forbidden.extend([pair["shared_evidence_sha256"], *pair["answer_sha256"].values()])
        for token in filter(None, forbidden):
            self.assertNotIn(token, xml)
        # The originals intentionally contain v1/v2; only added metadata must be blinded.
        self.assertIn("Synthetic v1 answer", xml)
        self.assertIn("Synthetic v2 answer", xml)
        with zipfile.ZipFile(self.output) as archive:
            properties = "\n".join(archive.read(name).decode("utf-8") for name in archive.namelist()
                                   if name.startswith("docProps/"))
        self.assertNotRegex(properties, r"(?i)\bv[12]\b|answer_version|8675309|coordinator-only\.json")

    def test_duplicate_missing_and_unexpected_jsonl_ids_fail_before_any_output(self):
        kwargs = self.prepare_inputs()
        for version in ("v1", "v2"):
            path = self.inputs[f"{version}_jsonl"]
            original = path.read_bytes()
            for kind in ("duplicate", "missing", "unexpected", "missing-id"):
                with self.subTest(version=version, kind=kind):
                    records = copy.deepcopy(list({"v1": self.v1, "v2": self.v2}[version].values()))
                    if kind == "duplicate":
                        records.append(copy.deepcopy(records[0]))
                    elif kind == "missing":
                        records.pop()
                    elif kind == "unexpected":
                        records[-1]["question_id"] = "H31"
                    else:
                        records[-1].pop("question_id")
                    self.write_jsonl(path, records)
                    with self.assertRaisesRegex(ValueError, "duplicate question ID|missing question IDs|unexpected question ID"):
                        adjudication.prepare_adjudication(**kwargs)
                    self.assert_no_outputs()
            path.write_bytes(original)

    def test_missing_blank_answers_wrong_versions_source_mapping_and_evidence_mismatch_fail_before_output(self):
        kwargs = self.prepare_inputs()
        cases = ("missing-answer", "none-answer", "blank-answer", "wrong-version", "wrong-source-mapping", "evidence-mismatch")
        for version in ("v1", "v2"):
            path = self.inputs[f"{version}_jsonl"]
            original = path.read_bytes()
            for kind in cases:
                if kind == "wrong-source-mapping" and version == "v1":
                    continue
                with self.subTest(version=version, kind=kind):
                    records = copy.deepcopy(list({"v1": self.v1, "v2": self.v2}[version].values()))
                    record = records[0]
                    if kind == "missing-answer":
                        record["answer_response"].pop("answer")
                    elif kind == "none-answer":
                        record["answer_response"]["answer"] = None
                    elif kind == "blank-answer":
                        record["answer_response"]["answer"] = " \n\t"
                    elif kind == "wrong-version":
                        record["answer_version"] = "v2" if version == "v1" else "v1"
                    elif kind == "wrong-source-mapping":
                        record["answer_response"]["citations"][0]["source_id"] = "S2"
                    else:
                        result = record["retrieval_response"]["results"][0]
                        result["excerpt"] += "\nDifferent shared evidence."
                        record["answer_response"]["citations"][0]["excerpt"] = result["excerpt"][:350] + "..."
                    self.write_jsonl(path, records)
                    with self.assertRaisesRegex(ValueError, "successful non-empty|version tag|identity/rank|Evidence/settings differ"):
                        adjudication.prepare_adjudication(**kwargs)
                    self.assert_no_outputs()
            path.write_bytes(original)

    def test_each_existing_output_is_protected_without_partial_other_outputs(self):
        kwargs = self.prepare_inputs()
        input_hashes = {path: digest(path.read_bytes()) for path in self.inputs.values()}
        for occupied in (self.output, self.key_path, self.protocol_path):
            with self.subTest(output=occupied.name):
                occupied.write_bytes(b"Existing synthetic artifact must survive unchanged.\n")
                before = occupied.read_bytes()
                with self.assertRaisesRegex(FileExistsError, "Refusing to overwrite"):
                    adjudication.prepare_adjudication(**kwargs)
                self.assertEqual(occupied.read_bytes(), before)
                for path in (self.output, self.key_path, self.protocol_path):
                    if path != occupied:
                        self.assertFalse(path.exists())
                occupied.unlink()
        self.assertEqual({path: digest(path.read_bytes()) for path in self.inputs.values()}, input_hashes)

    def test_colliding_output_paths_and_nonexistent_output_parent_rejected(self):
        kwargs = self.prepare_inputs()
        for argument in ("key_path", "protocol_path"):
            with self.subTest(argument=argument):
                with self.assertRaisesRegex(ValueError, "Output paths must be distinct"):
                    adjudication.prepare_adjudication(**{**kwargs, argument: self.output})
                self.assert_no_outputs()
        with self.assertRaisesRegex(ValueError, "Output directory does not exist"):
            adjudication.prepare_adjudication(**{**kwargs, "output": self.directory / "absent" / "review.xlsx"})
        self.assertFalse((self.directory / "absent").exists())
        self.assert_no_outputs()


if __name__ == "__main__":
    unittest.main()
