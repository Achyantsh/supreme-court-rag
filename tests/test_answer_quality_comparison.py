"""Offline regression tests; every record, review label and output is synthetic."""

import copy
import hashlib
import json
import random
import statistics
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import openpyxl

import compare_answer_quality_v1_v2 as comparison
import prepare_answer_quality_review as preparation


ROOT = Path(__file__).resolve().parents[1]


def synthetic_record(question_id, version="v2"):
    question = f"Synthetic question {question_id}?"
    results = []
    for rank in (1, 2):
        results.append({
            "rank": rank,
            "doc_id": f"{question_id}-doc-{rank}",
            "case_name": f"Synthetic case {rank}",
            "citation": f"[2000] SYN {rank}",
            "decision_date": "2000-01-01",
            "source_pdf": f"synthetic-{rank}.pdf",
            "chunk_id": f"{question_id}-chunk-{rank}",
            "score": 0.03076923076923077 / rank,
            "retrieval_mode": "hybrid_reranked",
            "excerpt": (f"Synthetic evidence {question_id}/{rank}. " * 20)
                       + "\nExact ending: café — no real judgment.",
        })
    citations = []
    for result in results:
        citation = {key: result[key] for key in (
            "case_name", "citation", "decision_date", "source_pdf", "score"
        )}
        citation["excerpt"] = result["excerpt"][:350] + "..."
        if version == "v2":
            citation.update(source_id=f"S{result['rank']}", doc_id=result["doc_id"],
                            chunk_id=result["chunk_id"], rank=result["rank"])
        citations.append(citation)
    response = {
        "question": question,
        "answer": f"Synthetic {version} answer for {question_id}: see [S1, S2].",
        "model": comparison.MODEL,
        "retrieval_mode": "hybrid_reranked",
        "citations": citations,
    }
    record = {
        "question_id": question_id,
        "topic": "Synthetic topic",
        "question": question,
        "model": comparison.MODEL,
        "retrieval_mode": "hybrid_reranked",
        "top_k": 2,
        "sdk": {"name": "synthetic-sdk", "version": "test-only"},
        "run_started_utc": "2026-01-01T00:00:00+00:00",
        "generation_status": "success",
        "generation_error": None,
        "retrieval_response": {
            "question": question, "count": 2,
            "retrieval_mode": "hybrid_reranked", "results": results,
        },
        "answer_response": response,
    }
    if version == "v2":
        record["answer_version"] = response["answer_version"] = "v2"
    return record


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def columns(sheet):
    return {cell.value: cell.column for cell in sheet[1]}


def write_review(path, records, scores=None):
    """Build the legacy review projection independently of the preparer."""
    workbook = openpyxl.Workbook()
    try:
        sheet = workbook.active
        sheet.title = "Answer Review"
        sheet.append(preparation.REVIEW_COLUMNS)
        headers = columns(sheet)
        for record in records:
            results = record["retrieval_response"]["results"]
            values = {
                "Question ID": record["question_id"], "Topic": record["topic"],
                "Question": record["question"],
                "Generated answer": record["answer_response"]["answer"],
                "Model": record["model"],
                "Generation status": record["generation_status"],
                "Generation error": record["generation_error"],
                "Retrieved judgment IDs": json.dumps([r["doc_id"] for r in results]),
                "Cited case names/citations": json.dumps([
                    {key: c.get(key) for key in ("case_name", "citation")}
                    for c in record["answer_response"]["citations"]
                ]),
                "Evidence excerpts": json.dumps([
                    {key: r.get(key) for key in ("doc_id", "case_name", "citation", "excerpt")}
                    for r in results
                ]),
            }
            if scores is not None:
                values.update({header: scores[record["question_id"]][dimension]
                               for dimension, header in comparison.SCORE_COLUMNS.items()})
            row = sheet.max_row + 1
            for header, value in values.items():
                cell = sheet.cell(row, headers[header], value)
                if isinstance(value, str):
                    cell.data_type = "s"
        workbook.save(path)
    finally:
        workbook.close()


def labels_for(ids, value):
    return {qid: {dimension: value for dimension in comparison.SCORE_COLUMNS} for qid in ids}


class TemporaryFixtureTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="synthetic-answer-quality-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def mutate_workbook(self, path, mutate):
        workbook = openpyxl.load_workbook(path, data_only=False)
        try:
            mutate(workbook["Answer Review"], columns(workbook["Answer Review"]))
            workbook.save(path)
        finally:
            workbook.close()

    def write_jsonl(self, name, records):
        path = self.directory / name
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
                        encoding="utf-8")
        return path


class ParseScoreTests(unittest.TestCase):
    def test_accepts_only_valid_labels_and_integral_numeric_equivalents(self):
        for value in (0, 1, 2, "0", "1", "2", 0.0, 1.0, 2.0):
            with self.subTest(value=value):
                result = comparison.parse_score(value, "synthetic cell")
                self.assertEqual(result, int(value))
                self.assertIs(type(result), int)

    def test_rejects_missing_weird_fractional_formula_boolean_and_nonfinite(self):
        for value in (None, "", " ", " 1", "1 ", "1.0", "01", "two", "NaN",
                      "=1+1", "=SUM(1,1)", True, False, 0.5, 1.5, 1.999999999,
                      float("nan"), float("inf"), float("-inf"), -1, 3, -0.1, 2.1,
                      "-1", "3", [], {}):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError):
                    comparison.parse_score(value, "synthetic cell")


class LoadRecordsTests(TemporaryFixtureTest):
    def test_loads_exact_ids_independently_of_file_order(self):
        records = [synthetic_record("H02"), synthetic_record("H01")]
        path = self.write_jsonl("records.jsonl", records)
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n   \n")
        self.assertEqual(comparison.load_records(path, ("H01", "H02")),
                         {r["question_id"]: r for r in records})

    def test_rejects_duplicate_missing_extra_and_missing_id(self):
        a, b = synthetic_record("H01"), synthetic_record("H02")
        no_id = copy.deepcopy(b)
        del no_id["question_id"]
        cases = (([a, b, a], "duplicate"), ([a], "missing"),
                 ([a, b, synthetic_record("H31")], "unexpected"),
                 ([a, no_id], "unexpected"))
        for records, message in cases:
            with self.subTest(message=message, count=len(records)):
                path = self.write_jsonl("invalid.jsonl", records)
                with self.assertRaisesRegex(ValueError, message):
                    comparison.load_records(path, ("H01", "H02"))


class LoadReviewTests(TemporaryFixtureTest):
    def setUp(self):
        super().setUp()
        self.records = {qid: synthetic_record(qid) for qid in ("H01", "H02")}
        self.labels = labels_for(self.records, 1)
        self.labels["H02"] = {"correctness": 2, "citation_support": 0, "completeness": 2}
        self.path = self.directory / "review.xlsx"
        write_review(self.path, list(self.records.values()), self.labels)

    def test_requires_complete_labels_but_inspection_retains_errors(self):
        write_review(self.path, list(self.records.values()))
        with self.assertRaisesRegex(ValueError, "incomplete/invalid.*6 score"):
            comparison.load_review(self.path, self.records)
        labels, errors = comparison.load_review(self.path, self.records, require_complete=False)
        self.assertEqual(labels, {"H01": {}, "H02": {}})
        self.assertEqual(len(errors), 6)

    def test_rejects_duplicate_unexpected_blank_and_missing_question_ids(self):
        for value, message in (("H01", "duplicate"), ("H31", "unexpected"),
                               (None, "unexpected/missing")):
            with self.subTest(value=value):
                write_review(self.path, list(self.records.values()), self.labels)

                def change(sheet, headers):
                    sheet.cell(3, headers["Question ID"]).value = value

                self.mutate_workbook(self.path, change)
                with self.assertRaisesRegex(ValueError, message):
                    comparison.load_review(self.path, self.records, require_complete=False)
        write_review(self.path, list(self.records.values()), self.labels)
        self.mutate_workbook(self.path, lambda sheet, headers: sheet.delete_rows(3))
        with self.assertRaisesRegex(ValueError, "missing question IDs: H02"):
            comparison.load_review(self.path, self.records, require_complete=False)

    def test_binds_reviewed_content_and_evidence_to_original_record(self):
        replacements = {
            "Topic": "Changed topic", "Question": "Changed question?",
            "Generated answer": "Changed answer", "Model": "wrong-model",
            "Generation status": "failed", "Generation error": "synthetic error",
            "Retrieved judgment IDs": '["wrong-doc"]',
            "Cited case names/citations": '[{"case_name": "wrong"}]',
            "Evidence excerpts": '[{"excerpt": "changed evidence"}]',
        }
        for header, replacement in replacements.items():
            with self.subTest(header=header):
                write_review(self.path, list(self.records.values()), self.labels)

                def change(sheet, headers):
                    sheet.cell(2, headers[header]).value = replacement

                self.mutate_workbook(self.path, change)
                with self.assertRaisesRegex(ValueError, "(?i)" + header):
                    comparison.load_review(self.path, self.records)

    def test_rejects_formula_and_fractional_labels_after_excel_roundtrip(self):
        for value in ("=1+1", 0.5, 1.5, 1.999999):
            with self.subTest(value=value):
                write_review(self.path, list(self.records.values()), self.labels)

                def change(sheet, headers):
                    sheet.cell(2, headers[comparison.SCORE_COLUMNS["correctness"]]).value = value

                self.mutate_workbook(self.path, change)
                workbook = openpyxl.load_workbook(self.path, data_only=False)
                try:
                    cell = workbook["Answer Review"].cell(
                        2, columns(workbook["Answer Review"])[comparison.SCORE_COLUMNS["correctness"]])
                    self.assertEqual(cell.value, value)
                    if isinstance(value, float):
                        self.assertIsInstance(cell.value, float)
                    else:
                        self.assertEqual(cell.data_type, "f")
                finally:
                    workbook.close()
                with self.assertRaisesRegex(ValueError, "incomplete/invalid"):
                    comparison.load_review(self.path, self.records)

    def test_joins_independent_workbook_row_orders_by_question_id(self):
        reversed_path = self.directory / "reversed.xlsx"
        write_review(reversed_path, list(reversed(list(self.records.values()))), self.labels)
        first, errors = comparison.load_review(self.path, self.records)
        second, other_errors = comparison.load_review(reversed_path, self.records)
        self.assertEqual(first, self.labels)
        self.assertEqual(second, self.labels)
        self.assertEqual(errors + other_errors, [])
        summary = comparison.summarize_pairs(first, second, samples=50)
        for result in summary.values():
            self.assertEqual(result["per_question"], {"H01": 0, "H02": 0})
            self.assertEqual(result["unchanged"], 2)


class PairedStatisticsTests(unittest.TestCase):
    def test_exact_summary_including_distributions_and_question_differences(self):
        ids = ("H01", "H02", "H03", "H04")
        old = {
            "correctness": (0, 1, 2, 2),
            "citation_support": (2, 2, 1, 0),
            "completeness": (0, 0, 0, 0),
        }
        new = {
            "correctness": (2, 1, 0, 2),
            "citation_support": (1, 2, 2, 0),
            "completeness": (1, 2, 1, 0),
        }
        v1 = {qid: {d: old[d][i] for d in old} for i, qid in enumerate(ids)}
        v2 = {qid: {d: new[d][i] for d in new} for i, qid in reversed(list(enumerate(ids)))}
        summary = comparison.summarize_pairs(v1, v2, samples=100, seed=17)
        expected = {
            "correctness": (1.25, 1.25, 0, {0: 1, 1: 1, 2: 2}, {0: 1, 1: 1, 2: 2},
                            50, 50, 1, 2, 1, (2, 0, -2, 0)),
            "citation_support": (1.25, 1.25, 0, {0: 1, 1: 1, 2: 2}, {0: 1, 1: 1, 2: 2},
                                 50, 50, 1, 2, 1, (-1, 0, 1, 0)),
            "completeness": (0, 1, 1, {0: 4, 1: 0, 2: 0}, {0: 1, 1: 2, 2: 1},
                             0, 25, 3, 1, 0, (1, 2, 1, 0)),
        }
        keys = ("v1_mean", "v2_mean", "mean_difference", "v1_distribution", "v2_distribution",
                "v1_score_2_percent", "v2_score_2_percent", "improved", "unchanged", "degraded")
        for dimension, values in expected.items():
            with self.subTest(dimension=dimension):
                result = summary[dimension]
                self.assertEqual({key: result[key] for key in keys}, dict(zip(keys, values[:-1])))
                self.assertEqual(result["per_question"], dict(zip(ids, values[-1])))
                self.assertEqual(set(result["confidence_intervals"]),
                                 {"v1_mean", "v2_mean", "mean_difference"})

    def test_bootstrap_reproducibility_and_local_random_state(self):
        state = random.getstate()
        first = comparison.paired_bootstrap([0, 1, 2, 0], [2, 1, 0, 1], samples=201, seed=7)
        self.assertEqual(first, comparison.paired_bootstrap(
            [0, 1, 2, 0], [2, 1, 0, 1], samples=201, seed=7))
        self.assertEqual(random.getstate(), state)

    def test_bootstrap_constant_difference_and_pair_preservation(self):
        # Means vary widely; independent resampling would not have an exact zero CI.
        identical = comparison.paired_bootstrap([0, 2, 0, 2], [0, 2, 0, 2], samples=301, seed=11)
        self.assertEqual(identical["mean_difference"], (0.0, 0.0))
        self.assertEqual(identical["v1_mean"], identical["v2_mean"])
        shifted = comparison.paired_bootstrap([0, 1, 0, 1], [1, 2, 1, 2], samples=301, seed=11)
        self.assertEqual(shifted["mean_difference"], (1.0, 1.0))
        self.assertEqual(shifted["v2_mean"], tuple(x + 1 for x in shifted["v1_mean"]))

    def test_bootstrap_matches_independent_paired_resampling_reference(self):
        a, b, seed, samples = [0, 1, 2], [2, 0, 2], 37, 113
        rng = random.Random(seed)
        replicates = {"v1_mean": [], "v2_mean": [], "mean_difference": []}
        for _ in range(samples):
            selected = [rng.randrange(len(a)) for _ in a]
            old = statistics.mean(a[i] for i in selected)
            new = statistics.mean(b[i] for i in selected)
            replicates["v1_mean"].append(old)
            replicates["v2_mean"].append(new)
            replicates["mean_difference"].append(new - old)
        expected = {}
        for key, values in replicates.items():
            ordered = sorted(values)
            endpoints = []
            for numerator in (25, 975):
                position = (samples - 1) * numerator / 1000
                lower = int(position)
                weight = position - lower
                endpoints.append(ordered[lower] * (1 - weight) + ordered[lower + 1] * weight)
            expected[key] = endpoints
        actual = comparison.paired_bootstrap(a, b, samples=samples, seed=seed)
        for key, endpoints in expected.items():
            for result, endpoint in zip(actual[key], endpoints):
                self.assertAlmostEqual(result, endpoint)

    def test_rejects_invalid_pair_sets_and_bootstrap_arguments(self):
        for a, b, samples in (([], [], 10), ([0], [0, 1], 10), ([0], [1], 0),
                              ([0], [1], 1.5), ([0], [1], True)):
            with self.subTest(a=a, b=b, samples=samples):
                with self.assertRaises(ValueError):
                    comparison.paired_bootstrap(a, b, samples=samples)
        for a, b in (({}, {}), (labels_for(["H01"], 0), labels_for(["H02"], 1))):
            with self.assertRaises(ValueError):
                comparison.summarize_pairs(a, b, samples=10)


class AuditRunsTests(unittest.TestCase):
    def runs(self):
        return ({"H01": synthetic_record("H01", "v1")},
                {"H01": synthetic_record("H01", "v2")})

    def test_identical_evidence_is_not_a_confounded_run(self):
        v1, v2 = self.runs()
        result = comparison.audit_runs(v1, v2, expected_ids=("H01",))
        self.assertEqual(result["confounds"], [])
        item = result["per_question"][0]
        self.assertTrue(item["evidence_equal"])
        self.assertEqual(item["differences"], [])
        self.assertEqual(item["v1_evidence_sha256"], item["v2_evidence_sha256"])

    def test_detects_cross_run_evidence_and_sdk_confounds(self):
        v1, v2 = self.runs()
        record = v2["H01"]
        result = record["retrieval_response"]["results"][0]
        result["excerpt"] += "\nSynthetic changed evidence."
        record["answer_response"]["citations"][0]["excerpt"] = result["excerpt"][:350] + "..."
        record["sdk"]["version"] = "different-test-sdk"
        audit = comparison.audit_runs(v1, v2, expected_ids=("H01",))
        self.assertEqual(len(audit["confounds"]), 1)
        self.assertIn("sdk", audit["confounds"][0])
        self.assertIn("retrieval_response", audit["confounds"][0])
        self.assertFalse(audit["per_question"][0]["evidence_equal"])
        self.assertNotEqual(audit["per_question"][0]["v1_evidence_sha256"],
                            audit["per_question"][0]["v2_evidence_sha256"])

    def test_rejects_wrong_versions_models_failures_and_identity_mapping(self):
        cases = (
            ("v1", (), "answer_version", "v2", "version tag"),
            ("v2", (), "answer_version", "v1", "version tags"),
            ("v2", ("answer_response",), "answer_version", None, "version tags"),
            ("v2", (), "model", "wrong-model", "expected model"),
            ("v2", ("answer_response",), "model", "wrong-model", "expected model"),
            ("v2", (), "generation_status", "failed", "successful non-empty"),
            ("v2", (), "generation_error", "synthetic failure", "successful non-empty"),
            ("v2", ("answer_response",), "answer", "  ", "successful non-empty"),
            ("v2", ("answer_response", "citations", 0), "source_id", "S2", "identity/rank"),
        )
        for version, nested, key, value, message in cases:
            with self.subTest(version=version, nested=nested, key=key):
                v1, v2 = self.runs()
                target = (v1 if version == "v1" else v2)["H01"]
                for part in nested:
                    target = target[part]
                target[key] = value
                with self.assertRaisesRegex(ValueError, message):
                    comparison.audit_runs(v1, v2, expected_ids=("H01",))


class PreparationTests(TemporaryFixtureTest):
    def test_blank_scores_notes_dropdowns_and_exact_sources_and_grouped_navigation(self):
        records = [synthetic_record("H01"), synthetic_record("H02")]
        original = copy.deepcopy(records)
        path = self.directory / "prepared.xlsx"
        preparation.create_review_workbook(records, path, {"fixture": "synthetic only"})
        self.assertEqual(records, original)
        workbook = openpyxl.load_workbook(path, data_only=False)
        try:
            sheet = workbook["Answer Review"]
            headers = columns(sheet)
            for row in range(2, 4):
                for header in (*comparison.SCORE_COLUMNS.values(), "Review notes"):
                    self.assertIsNone(sheet.cell(row, headers[header]).value)
            validations = list(sheet.data_validations.dataValidation)
            self.assertEqual(len(validations), 3)
            self.assertEqual({str(item.sqref) for item in validations}, {"N2:N3", "O2:O3", "P2:P3"})
            for validation in validations:
                self.assertEqual(validation.type, "list")
                self.assertEqual(validation.formula1, '"0,1,2"')
                self.assertTrue(validation.allow_blank)
                self.assertEqual(validation.errorStyle, "stop")
                self.assertTrue(validation.showErrorMessage)
                self.assertFalse(validation.showDropDown)
            sources = workbook["Sources"]
            source_headers = columns(sources)
            navigation = workbook["Citation navigation"]
            nav_headers = columns(navigation)
            self.assertEqual(sources.max_row, 5)
            self.assertEqual(navigation.max_row, 5)
            for index, record in enumerate(records):
                resolved = json.loads(sheet.cell(index + 2, headers["Resolved sources"]).value)
                self.assertEqual([s["source_id"] for s in resolved], ["S1", "S2"])
                for rank, result in enumerate(record["retrieval_response"]["results"], 1):
                    row = index * 2 + rank + 1
                    for header, key in (("Rank", "rank"), ("Doc ID", "doc_id"),
                                        ("Chunk ID", "chunk_id"), ("Case name", "case_name"),
                                        ("Citation", "citation"), ("Decision date", "decision_date"),
                                        ("Source PDF", "source_pdf"), ("Score", "score"),
                                        ("Retrieval mode", "retrieval_mode"),
                                        ("Full retrieval excerpt", "excerpt")):
                        expected_value = json.dumps(result[key]) if key == "score" else result[key]
                        self.assertEqual(sources.cell(row, source_headers[header]).value, expected_value)
                    self.assertEqual(sources.cell(row, source_headers["Question ID"]).value,
                                     record["question_id"])
                    self.assertEqual(sources.cell(row, source_headers["Source ID"]).value, f"S{rank}")
                    self.assertEqual(navigation.cell(row, nav_headers["Original bracket"]).value, "[S1, S2]")
                    self.assertEqual(navigation.cell(row, nav_headers["Source ID"]).value, f"S{rank}")
                    self.assertEqual(navigation.cell(row, nav_headers["Unresolved"]).value, "No")
                    self.assertEqual(navigation.cell(row, nav_headers["Score"]).value,
                                     json.dumps(result["score"]))
                    self.assertEqual(navigation.cell(row, nav_headers["Full retrieval excerpt"]).value,
                                     result["excerpt"])
                    start = navigation.cell(row, nav_headers["Bracket start (0-based)"]).value
                    end = navigation.cell(row, nav_headers["Bracket end (exclusive)"]).value
                    self.assertEqual(record["answer_response"]["answer"][start:end], "[S1, S2]")
                    link = navigation.cell(row, nav_headers["Source row"]).hyperlink
                    self.assertEqual(link.location, f"'Sources'!A{row}")
                    self.assertIsNone(link.target)
                    self.assertEqual(sources.cell(row, source_headers["Answer review"]).hyperlink.location,
                                     f"'Answer Review'!A{index + 2}")
                    preview = record["answer_response"]["citations"][rank - 1]["excerpt"]
                    self.assertNotEqual(result["excerpt"], preview)
                    self.assertEqual(resolved[rank - 1]["excerpt"], result["excerpt"])
            self.assertEqual(sheet.cell(2, headers["Source-reference navigation"]).hyperlink.location,
                             "'Citation navigation'!A2")
        finally:
            workbook.close()
        labels, errors = comparison.load_review(path, {r["question_id"]: r for r in records},
                                                 require_complete=False)
        self.assertEqual(len(errors), 6)
        self.assertEqual(labels, {"H01": {}, "H02": {}})

    def test_formula_injection_strings_are_preserved_as_text(self):
        for prefix in ("=", "+", "-", "@"):
            with self.subTest(prefix=prefix):
                record = synthetic_record("H01")
                dangerous = prefix + 'HYPERLINK("https://invalid.example", "synthetic")'
                record["topic"] = record["question"] = dangerous
                record["answer_response"]["answer"] = dangerous + " [S1, S2]"
                result = record["retrieval_response"]["results"][0]
                result["excerpt"] = result["case_name"] = result["source_pdf"] = dangerous
                citation = record["answer_response"]["citations"][0]
                citation.update(case_name=dangerous, source_pdf=dangerous,
                                excerpt=dangerous[:350] + "...")
                path = self.directory / f"text-{ord(prefix)}.xlsx"
                preparation.create_review_workbook([record], path, {"synthetic": dangerous})
                workbook = openpyxl.load_workbook(path, data_only=False)
                try:
                    for sheet_name, coordinate, expected in (
                        ("Answer Review", "B2", dangerous), ("Answer Review", "C2", dangerous),
                        ("Answer Review", "D2", dangerous + " [S1, S2]"),
                        ("Sources", "F2", dangerous), ("Sources", "I2", dangerous),
                        ("Sources", "L2", dangerous), ("Citation navigation", "S2", dangerous),
                        ("Provenance", "B2", dangerous),
                    ):
                        cell = workbook[sheet_name][coordinate]
                        self.assertEqual(cell.value, expected)
                        self.assertEqual(cell.data_type, "s")
                    for sheet in workbook:
                        self.assertFalse(any(cell.data_type == "f" for row in sheet for cell in row))
                finally:
                    workbook.close()

    def test_existing_output_is_never_overwritten(self):
        path = self.directory / "prepared.xlsx"
        records = [synthetic_record("H01")]
        preparation.create_review_workbook(records, path, {})
        before = file_hash(path)
        with self.assertRaises(FileExistsError):
            preparation.create_review_workbook([synthetic_record("H02")], path, {})
        self.assertEqual(file_hash(path), before)


class CommandLineTests(TemporaryFixtureTest):
    def setUp(self):
        super().setUp()
        self.v1 = [synthetic_record(qid, "v1") for qid in comparison.EXPECTED_IDS]
        self.v2 = [synthetic_record(qid, "v2") for qid in comparison.EXPECTED_IDS]
        self.inputs = {
            "v1-jsonl": self.write_jsonl("v1.jsonl", self.v1),
            "v2-jsonl": self.write_jsonl("v2.jsonl", self.v2),
            "v1-workbook": self.directory / "v1.xlsx",
            "v2-dev-workbook": self.directory / "v2-dev.xlsx",
        }
        # These scores are deliberately fabricated test labels, never human judgments.
        write_review(self.inputs["v1-workbook"], self.v1, labels_for(comparison.EXPECTED_IDS, 0))
        write_review(self.inputs["v2-dev-workbook"], list(reversed(self.v2)),
                     labels_for(comparison.EXPECTED_IDS, 2))
        self.final_workbook = self.directory / "v2-final.xlsx"
        self.audit = self.directory / "audit.md"
        self.report = self.directory / "comparison.md"
        self.argv = []
        for flag, path in self.inputs.items():
            self.argv.extend([f"--{flag}", str(path)])
        self.argv.extend(["--v2-workbook", str(self.final_workbook),
                          "--audit-output", str(self.audit), "--output", str(self.report),
                          "--bootstrap-samples", "101", "--seed", "123"])
        self.protected = [*self.inputs.values(), ROOT / "compare_answer_quality_v1_v2.py",
                          ROOT / "prepare_answer_quality_review.py"]
        self.initial_hashes = self.hashes(self.protected)

    @staticmethod
    def hashes(paths):
        return {path: file_hash(path) for path in paths}

    def cli(self, *extra):
        return subprocess.run(
            [sys.executable, "-B", str(ROOT / "compare_answer_quality_v1_v2.py"),
             *self.argv, *extra],
            cwd=self.directory, capture_output=True, text=True, timeout=45,
        )

    def assert_success(self, process):
        self.assertEqual(process.returncode, 0, (process.stdout + process.stderr)[-4000:])

    def prepare(self):
        result = self.cli("--prepare-review")
        self.assert_success(result)
        self.assertTrue(self.final_workbook.is_file())
        self.assertTrue(self.audit.is_file())
        self.assertFalse(self.report.exists())
        self.assertEqual(self.hashes(self.protected), self.initial_hashes)

    def test_default_comparison_gate_refuses_incomplete_scores_without_report(self):
        self.prepare()
        protected = [*self.protected, self.final_workbook, self.audit]
        before = self.hashes(protected)
        result = self.cli()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("incomplete/invalid", result.stderr)
        self.assertFalse(self.report.exists())
        self.assertEqual(self.hashes(protected), before)

    def test_preparation_repeat_preserves_every_input_and_output_hash(self):
        self.prepare()
        protected = [*self.protected, self.final_workbook, self.audit]
        before = self.hashes(protected)
        result = self.cli("--prepare-review")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("refusing to overwrite", result.stderr)
        self.assertFalse(self.report.exists())
        self.assertEqual(self.hashes(protected), before)

    def test_complete_synthetic_30_question_cli_report_and_no_source_changes(self):
        self.prepare()

        def synthetic_annotation(sheet, headers):
            for row in range(2, sheet.max_row + 1):
                for header in comparison.SCORE_COLUMNS.values():
                    sheet.cell(row, headers[header]).value = 1
                sheet.cell(row, headers["Review notes"]).value = "SYNTHETIC TEST LABEL; not human review"

        self.mutate_workbook(self.final_workbook, synthetic_annotation)
        protected = [*self.protected, self.final_workbook, self.audit]
        before = self.hashes(protected)
        result = self.cli()
        self.assert_success(result)
        text = self.report.read_text(encoding="utf-8")
        self.assertIn("DEVELOPMENT", text)
        self.assertIn("| correctness | 0.0000 | 1.0000 | +1.0000 | [+1.0000, +1.0000] | 30 | 0 | 0 |", text)
        self.assertIn("| correctness | V1 | 30 | 0 | 0 | 0.00%", text)
        self.assertIn("| correctness | V2 | 0 | 30 | 0 | 0.00%", text)
        for qid in comparison.EXPECTED_IDS:
            self.assertIn(f"| {qid} | +1 | +1 | +1 |", text)
        self.assertIn("101 replicates", text)
        self.assertIn("`123`", text)
        self.assertIn("not an established causal effect", text)
        self.assertEqual(self.hashes(protected), before)
        report_hash = file_hash(self.report)
        repeat = self.cli()
        self.assertEqual(repeat.returncode, 2, repeat.stdout + repeat.stderr)
        self.assertIn("Refusing to overwrite comparison report", repeat.stderr)
        self.assertEqual(file_hash(self.report), report_hash)
        self.assertEqual(self.hashes(protected), before)


if __name__ == "__main__":
    unittest.main()
