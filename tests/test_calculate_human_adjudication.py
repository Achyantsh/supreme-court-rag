"""Offline calculator regressions; all scores and reviewer entries are synthetic.

No fixture represents actual human assessment, and no real evaluation artifacts,
judgments, model clients or APIs are used. All runtime writes stay in a temp dir.
"""

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import openpyxl

import calculate_human_adjudication as calculator
from prepare_human_adjudication import prepare_adjudication
from test_answer_quality_comparison import synthetic_record, write_review


IDS = tuple(f"H{i:02d}" for i in range(1, 31))
DIMENSIONS = ("correctness", "citation_support", "completeness")
TITLES = ("Correctness", "Citation support", "Completeness")
STATUS = "Verified against retrieved text excerpts"
REVIEWER = "SYNTHETIC TEST IDENTITY — not a human assessment"
NOTE = "SYNTHETIC TEST CONFIRMATION ONLY; no actual human review occurred."
DATE = "2026-01-02"


def headers(sheet):
    return {cell.value: cell.column for cell in sheet[1]}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CalculatorFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="synthetic-excerpt-calculator-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.workbook_path = self.directory / "synthetic-paired-review.xlsx"
        self.key_path = self.directory / "synthetic-private-key.json"
        self.protocol_path = self.directory / "synthetic-protocol.md"
        self.report = self.directory / "synthetic-result.md"
        self.json_output = self.directory / "synthetic-result.json"
        pdf_dir = self.directory / "empty-synthetic-pdfs"
        pdf_dir.mkdir()
        inputs = {}
        for version in ("v1", "v2"):
            records = [synthetic_record(qid, version) for qid in IDS]
            path = self.directory / f"synthetic-{version}.jsonl"
            path.write_text("\n".join(json.dumps(record) for record in reversed(records)) + "\n",
                            encoding="utf-8")
            inputs[f"{version}_jsonl"] = path
            draft = self.directory / f"synthetic-{version}-old-draft.xlsx"
            # Deliberately unrelated to the reviewed 0/2 values below.
            scores = {qid: {dimension: (index + offset) % 3
                            for offset, dimension in enumerate(DIMENSIONS)}
                      for index, qid in enumerate(IDS)}
            write_review(draft, records, scores)
            inputs[f"{version}_draft"] = draft
        previous = self.directory / "synthetic-previous-report.md"
        previous.write_text("# FAKE provisional comparison\nNo actual human assessment.\n",
                            encoding="utf-8")
        inputs["previous_report"] = previous
        self.inputs = inputs
        self.key = prepare_adjudication(
            **inputs, output=self.workbook_path, key_path=self.key_path,
            protocol_path=self.protocol_path, pdf_dir=pdf_dir, seed=8675309)
        self.blank_workbook = self.workbook_path.read_bytes()
        self.mutate_workbook(self.populate_synthetic_review)
        self.complete_workbook = self.workbook_path.read_bytes()
        self.original_key = self.key_path.read_bytes()
        self.preserved_paths = [self.workbook_path, self.key_path, self.protocol_path,
                                *inputs.values()]

    def mutate_workbook(self, mutate):
        workbook = openpyxl.load_workbook(self.workbook_path, data_only=False)
        try:
            mutate(workbook)
            workbook.save(self.workbook_path)
        finally:
            workbook.close()

    def populate_synthetic_review(self, workbook):
        sheet = workbook["Paired review"]
        columns = headers(sheet)
        for row in range(2, sheet.max_row + 1):
            qid = sheet.cell(row, columns["Question ID"]).value
            for label in ("A", "B"):
                score = {"v1": 0, "v2": 2}[self.key["pairs"][qid][label]]
                for title in TITLES:
                    sheet.cell(row, columns[f"{label} {title} (0/1/2)"], score)
                sheet.cell(row, columns[f"{label} Full-judgment verification status"], STATUS)
                sheet.cell(row, columns[f"{label} PDF pages / paragraphs checked"],
                           "Synthetic excerpt only; no PDF checked")
                sheet.cell(row, columns[f"{label} Review notes / uncertainty"],
                           f"Synthetic fixture note {qid}/{label}; not an assessment")
            sheet.cell(row, columns["Human reviewer name"], REVIEWER)
            sheet.cell(row, columns["Review date"], DATE)
            sheet.cell(row, columns["Pair-level notes / unresolved issues"],
                       "Synthetic pair note; no real adjudication")
        details = workbook["Reviewer details"]
        for row in range(2, details.max_row + 1):
            field = details.cell(row, 1).value
            if field == "Human reviewer name":
                details.cell(row, 2, REVIEWER)
            elif field in ("Review start date", "Review completion date"):
                details.cell(row, 2, DATE)
        # Sign-off, qualifications, exposure/conflicts and second review stay blank.

    def set_cell(self, sheet_name, column, value, row=2):
        def change(workbook):
            sheet = workbook[sheet_name]
            sheet.cell(row, headers(sheet)[column]).value = value
        self.mutate_workbook(change)

    def validate(self, **kwargs):
        options = {"human_review_confirmed": True, "confirmation_note": NOTE}
        options.update(kwargs)
        return calculator.validate_review(self.workbook_path, self.key_path, **options)

    def cli_args(self, confirmed=True):
        args = ["--workbook", str(self.workbook_path), "--key", str(self.key_path),
                "--output", str(self.report), "--json-output", str(self.json_output),
                "--bootstrap-samples", "64", "--seed", "1234"]
        if confirmed:
            args += ["--human-review-confirmed", "--confirmation-note", NOTE]
        return args

    def snapshot(self):
        return {path: digest(path) for path in self.preserved_paths}

    def assert_cli_failure(self, message, args=None):
        before = self.snapshot()
        stderr = io.StringIO()
        with redirect_stderr(stderr), redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                calculator.main(self.cli_args() if args is None else args)
        self.assertEqual(raised.exception.code, 2)
        self.assertRegex(stderr.getvalue(), message)
        self.assertFalse(self.report.exists())
        self.assertFalse(self.json_output.exists())
        self.assertEqual(self.snapshot(), before)

    def assert_invalid(self, message):
        with self.assertRaisesRegex(ValueError, message):
            self.validate()
        self.assert_cli_failure(message)


class ReviewValidationTests(CalculatorFixture):
    def test_explicit_confirmation_and_nonblank_note_required(self):
        with self.assertRaisesRegex(ValueError, "Explicit human-review confirmation"):
            calculator.validate_review(self.workbook_path, self.key_path)
        for confirmed, note in ((False, NOTE), (True, ""), (True, "  \t")):
            with self.subTest(confirmed=confirmed, note=note):
                with self.assertRaisesRegex(ValueError, "Explicit human-review confirmation"):
                    self.validate(human_review_confirmed=confirmed, confirmation_note=note)
                args = self.cli_args(confirmed=False) + ["--confirmation-note", note]
                if confirmed:
                    args.append("--human-review-confirmed")
                self.assert_cli_failure("Explicit human-review confirmation", args)

    def test_unblinds_all_180_scores_and_retains_raw_missing_provenance(self):
        before = self.snapshot()
        labels, provenance = self.validate()
        self.assertEqual(labels, {version: {qid: dict.fromkeys(DIMENSIONS, score) for qid in IDS}
                                  for version, score in (("v1", 0), ("v2", 2))})
        self.assertEqual({pair["A"] for pair in self.key["pairs"].values()}, {"v1", "v2"})
        self.assertEqual((provenance["question_count"], provenance["answer_count"],
                          provenance["score_count"]), (30, 60, 180))
        self.assertEqual(provenance["verification_status_counts_raw"], {STATUS: 60})
        self.assertEqual(provenance["row_review_dates_raw"], [DATE])
        self.assertEqual(provenance["reference_entry_counts_raw"],
                         {"Synthetic excerpt only; no PDF checked": 60})
        self.assertEqual(provenance["confirmation"]["user_confirmation"], NOTE)
        self.assertFalse(provenance["confirmation"]["independently_authenticated"])
        self.assertTrue(provenance["confirmation"]["recorded_utc"])
        self.assertIn("no full-judgment verification established", provenance["review_basis"])
        for field in ("Human sign-off / date", "Qualifications / legal expertise",
                      "Prior exposure to answers or draft scores", "Suspected unblinding / conflicts",
                      "Independent second reviewer (if any)"):
            self.assertIsNone(provenance["reviewer_details_raw"][field])
            self.assertIn(field, provenance["missing_reviewer_provenance"])
        self.assertEqual(set(provenance["source_review_blank_field_counts"].values()), {60})
        self.assertEqual(len(provenance["source_review_blank_field_counts"]), 4)
        for qid, row in provenance["per_question"].items():
            self.assertEqual(row["reviewer"], REVIEWER)
            self.assertEqual(row["review_date"], DATE)
            self.assertEqual(row["pair_notes"], "Synthetic pair note; no real adjudication")
            for version, answer in row["answers"].items():
                label = answer["display_label"]
                self.assertEqual(self.key["pairs"][qid][label], version)
                self.assertEqual(answer["scores"], labels[version][qid])
                self.assertEqual(answer["verification_status_raw"], STATUS)
                self.assertEqual(answer["notes"],
                                 f"Synthetic fixture note {qid}/{label}; not an assessment")
        self.assertEqual(provenance["input_sha256"]["review_workbook"], before[self.workbook_path])
        self.assertEqual(provenance["input_sha256"]["mapping_key"], before[self.key_path])
        for name, item in self.key["preserved_inputs"].items():
            self.assertEqual(provenance["input_sha256"][name], digest(Path(item["path"])))
        self.assertEqual(self.snapshot(), before)

    def test_wrong_duplicate_and_blank_question_ids_rejected(self):
        for value in ("H31", "H01", None):
            with self.subTest(value=value):
                self.workbook_path.write_bytes(self.complete_workbook)
                self.set_cell("Paired review", "Question ID", value, row=3)
                self.assert_invalid("Unexpected, missing or duplicate question ID")

    @staticmethod
    def clear_first_data_row(workbook, sheet_name):
        # Clearing hyperlinks too prevents openpyxl from recreating phantom cells.
        for cell in workbook[sheet_name][2]:
            cell.value = None
            cell.hyperlink = None

    def test_missing_question_row_rejected(self):
        self.mutate_workbook(lambda workbook: self.clear_first_data_row(workbook, "Paired review"))
        self.assert_invalid("must contain exactly H01")

    def test_changed_answers_questions_topics_and_shared_evidence_rejected(self):
        cases = {"Answer A": "Changed synthetic answer A", "Answer B": "Changed synthetic answer B",
                 "Topic": "Changed topic", "Exact question": "Changed question?",
                 "Exact shared retrieval evidence and metadata": "[]"}
        for column, value in cases.items():
            with self.subTest(column=column):
                self.workbook_path.write_bytes(self.complete_workbook)
                self.set_cell("Paired review", column, value)
                self.assert_invalid("changed (answer|question or topic|shared evidence)")

    def test_changed_source_metadata_and_excerpt_rejected(self):
        for column in ("Exact retrieved excerpt", "Document ID", "Source PDF", "Source reference",
                       "Chunk ID", "Case name", "SCR citation", "Decision date",
                       "Retrieval score (exact text)", "Retrieval mode"):
            with self.subTest(column=column):
                self.workbook_path.write_bytes(self.complete_workbook)
                self.set_cell("Shared sources", column, "Changed synthetic source")
                self.assert_invalid("Changed source metadata or excerpt")

    def test_invalid_formula_fractional_and_missing_scores_rejected(self):
        for label in ("A", "B"):
            for title in TITLES:
                for value in (3, "not a score", "=1+1", 0.5, None):
                    with self.subTest(label=label, title=title, value=value):
                        self.workbook_path.write_bytes(self.complete_workbook)
                        self.set_cell("Paired review", f"{label} {title} (0/1/2)", value)
                        self.assert_invalid("formulas are not accepted|invalid|missing")

    def test_unresolved_full_judgment_and_missing_statuses_rejected(self):
        for label in ("A", "B"):
            for status in ("Uncertain / unresolved", "Needs full-judgment verification",
                           "Verified against full judgment", None):
                with self.subTest(label=label, status=status):
                    self.workbook_path.write_bytes(self.complete_workbook)
                    self.set_cell("Paired review", f"{label} Full-judgment verification status", status)
                    self.assert_invalid("requires an explicit excerpt-only status")

    def test_duplicate_unexpected_and_missing_source_rows_rejected(self):
        def duplicate(workbook):
            sheet = workbook["Shared sources"]
            sheet.append([cell.value for cell in sheet[2]])
        for mutate, message in (
                (duplicate, "Duplicate or unexpected source"),
                (lambda workbook: self.clear_first_data_row(workbook, "Shared sources"),
                 "Missing shared-source rows")):
            with self.subTest(message=message):
                self.workbook_path.write_bytes(self.complete_workbook)
                self.mutate_workbook(mutate)
                self.assert_invalid(message)
        self.workbook_path.write_bytes(self.complete_workbook)
        self.set_cell("Shared sources", "Question ID", "H31")
        self.assert_invalid("Duplicate or unexpected source")

    def test_reviewer_identity_mismatch_and_missing_row_identity_or_date_rejected(self):
        for column, value, message in (
                ("Human reviewer name", "Different synthetic identity", "identity must match"),
                ("Human reviewer name", None, "name and review date required"),
                ("Review date", None, "name and review date required")):
            with self.subTest(column=column, value=value):
                self.workbook_path.write_bytes(self.complete_workbook)
                self.set_cell("Paired review", column, value)
                self.assert_invalid(message)
        self.workbook_path.write_bytes(self.complete_workbook)
        def change_details(workbook):
            sheet = workbook["Reviewer details"]
            for row in sheet.iter_rows(min_row=2):
                if row[0].value == "Human reviewer name":
                    row[1].value = "Different synthetic details identity"
        self.mutate_workbook(change_details)
        self.assert_invalid("identity must match")


class KeyIntegrityTests(CalculatorFixture):
    def test_mapping_altered_relative_to_seed_rejected(self):
        pair = self.key["pairs"]["H01"]
        pair["A"], pair["B"] = pair["B"], pair["A"]
        pair["answer_sha256"]["A"], pair["answer_sha256"]["B"] = (
            pair["answer_sha256"]["B"], pair["answer_sha256"]["A"])
        self.key_path.write_text(json.dumps(self.key), encoding="utf-8")
        self.assert_invalid("mapping does not match fixed-seed allocation")

    def test_answer_and_evidence_hash_tampering_rejected(self):
        for field, label, message in (("answer_sha256", "A", "answer/key hash mismatch"),
                                      ("answer_sha256", "B", "answer/key hash mismatch"),
                                      ("shared_evidence_sha256", None, "shared evidence hash mismatch")):
            with self.subTest(field=field, label=label):
                key = json.loads(self.original_key)
                pair = key["pairs"]["H01"]
                if label:
                    pair[field][label] = "0" * 64
                else:
                    pair[field] = "0" * 64
                self.key_path.write_text(json.dumps(key), encoding="utf-8")
                self.assert_invalid(message)

    def test_wrong_missing_and_duplicate_key_ids_rejected(self):
        for kind in ("wrong", "missing", "duplicate"):
            with self.subTest(kind=kind):
                key = json.loads(self.original_key)
                if kind == "wrong":
                    key["pairs"]["H31"] = key["pairs"].pop("H01")
                elif kind == "missing":
                    del key["pairs"]["H01"]
                text = json.dumps(key)
                if kind == "duplicate":
                    text = text.replace('"pairs": {', '"pairs": {"H01": {},', 1)
                self.key_path.write_text(text, encoding="utf-8")
                self.assert_invalid("Duplicate JSON key|Key must cover exactly")

    def test_each_preserved_input_hash_change_rejected(self):
        for name, path in self.inputs.items():
            with self.subTest(input=name):
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b"\nSYNTHETIC TAMPERING\n")
                    self.assert_invalid("Preserved input changed")
                finally:
                    path.write_bytes(original)


class CalculatorCliTests(CalculatorFixture):
    def test_maximum_ratings_warn_about_ceiling_not_perfect_accuracy(self):
        def maximum_ratings(workbook):
            sheet = workbook["Paired review"]
            for row in sheet.iter_rows(min_row=2):
                for cell in row:
                    if "(0/1/2)" in str(sheet.cell(1, cell.column).value):
                        cell.value = 2
        self.mutate_workbook(maximum_ratings)
        with redirect_stdout(io.StringIO()):
            calculator.main(self.cli_args())
        report = self.report.read_text(encoding="utf-8")
        self.assertIn("All 180 submitted scores are the maximum", report)
        self.assertIn("no observed V2 improvement", report)
        self.assertIn("They do not establish zero uncertainty", report)

    def test_complete_synthetic_fixture_writes_separate_reports_without_changing_inputs(self):
        before = self.snapshot()
        with redirect_stdout(io.StringIO()):
            calculator.main(self.cli_args())
        self.assertTrue(self.report.is_file())
        self.assertTrue(self.json_output.is_file())
        self.assertNotEqual(self.report, self.inputs["previous_report"])
        self.assertEqual(self.snapshot(), before)
        result = json.loads(self.json_output.read_text(encoding="utf-8"))
        report = self.report.read_text(encoding="utf-8")
        self.assertEqual(result["scope"], "DEVELOPMENT")
        self.assertEqual((result["bootstrap_samples"], result["seed"]), (64, 1234))
        self.assertEqual(set(result["summary"]), set(DIMENSIONS))
        for dimension in DIMENSIONS:
            summary = result["summary"][dimension]
            self.assertEqual((summary["v1_mean"], summary["v2_mean"], summary["mean_difference"]),
                             (0, 2, 2))
            self.assertEqual(summary["confidence_intervals"]["v1_mean"], [0, 0])
            self.assertEqual(summary["confidence_intervals"]["v2_mean"], [2, 2])
            self.assertEqual(summary["confidence_intervals"]["mean_difference"], [2, 2])
            self.assertEqual(summary["v1_distribution"], {"0": 30, "1": 0, "2": 0})
            self.assertEqual(summary["v2_distribution"], {"0": 0, "1": 0, "2": 30})
            self.assertEqual((summary["v1_score_2_percent"], summary["v2_score_2_percent"]), (0, 100))
            self.assertEqual((summary["improved"], summary["unchanged"], summary["degraded"]), (30, 0, 0))
            self.assertEqual(summary["per_question"], dict.fromkeys(IDS, 2))
            self.assertIn(f"| {dimension} | 0.0000 | 2.0000 | +2.0000 | [+2.0000, +2.0000] | 30 | 0 | 0 |", report)
        expected_labels = {version: {qid: dict.fromkeys(DIMENSIONS, score) for qid in IDS}
                           for version, score in (("v1", 0), ("v2", 2))}
        self.assertEqual(result["unblinded_scores"], expected_labels)
        provenance = result["review_provenance"]
        self.assertEqual(provenance["score_count"], 180)
        self.assertEqual(provenance["verification_status_counts_raw"], {STATUS: 60})
        self.assertEqual(provenance["confirmation"]["user_confirmation"], NOTE)
        self.assertFalse(provenance["confirmation"]["independently_authenticated"])
        for field in provenance["missing_reviewer_provenance"]:
            self.assertIsNone(provenance["reviewer_details_raw"][field])
            self.assertIn(f'- {field}: `"Not recorded"`', report)
        self.assertIn("Human sign-off / date", provenance["missing_reviewer_provenance"])
        for disclosure in ("not independently authenticated or independent expert double review",
                           "retrieved text excerpts, not established full-judgment verification",
                           "does not fill or substitute for a signed workbook field",
                           "workbook sign-off and other missing disclosures remain unrecorded",
                           "No inter-reviewer agreement or independent expert certification is claimed",
                           "Do not call them independently adjudicated ground truth or full-judgment-verified results",
                           "development set", "not semantic citation support"):
            self.assertIn(disclosure, report)
        self.assertIn(f"`{STATUS}`: 60 answers", report)
        self.assertIn(NOTE, report)
        for path in (self.workbook_path, self.key_path):
            self.assertIn(before[path], report)

    def test_repeat_refuses_overwrite_and_preserves_existing_reports(self):
        with redirect_stdout(io.StringIO()):
            calculator.main(self.cli_args())
        outputs = {path: digest(path) for path in (self.report, self.json_output)}
        before = self.snapshot()
        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            calculator.main(self.cli_args())
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("Output already exists", stderr.getvalue())
        self.assertEqual({path: digest(path) for path in outputs}, outputs)
        self.assertEqual(self.snapshot(), before)

    def test_either_existing_output_prevents_partial_other_output(self):
        for existing in (self.report, self.json_output):
            with self.subTest(existing=existing.name):
                existing.write_text("SYNTHETIC EXISTING REPORT\n", encoding="utf-8")
                before = self.snapshot()
                stderr = io.StringIO()
                with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
                    calculator.main(self.cli_args())
                self.assertEqual(raised.exception.code, 2)
                self.assertIn("Output already exists", stderr.getvalue())
                self.assertEqual(existing.read_text(encoding="utf-8"), "SYNTHETIC EXISTING REPORT\n")
                other = self.json_output if existing == self.report else self.report
                self.assertFalse(other.exists())
                self.assertEqual(self.snapshot(), before)
                existing.unlink()

    def test_incomplete_workbook_produces_no_output(self):
        self.workbook_path.write_bytes(self.blank_workbook)
        self.assert_cli_failure("name and review date required|missing")

    def test_second_output_write_failure_removes_first_report(self):
        self.json_output = self.directory / "nonexistent-parent" / "synthetic-result.json"
        self.assert_cli_failure("Comparison stopped")

    def test_colliding_output_paths_and_invalid_bootstrap_produce_no_output(self):
        args = self.cli_args()
        args[args.index("--json-output") + 1] = str(self.report)
        self.assert_cli_failure("Report output paths must differ", args)
        for samples in ("0", "-1"):
            with self.subTest(samples=samples):
                args = self.cli_args()
                args[args.index("--bootstrap-samples") + 1] = samples
                self.assert_cli_failure("Bootstrap samples must be positive", args)


if __name__ == "__main__":
    unittest.main()
