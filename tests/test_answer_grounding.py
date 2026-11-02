"""Regression tests for the opt-in V2 answer-grounding contract."""

import unittest
from unittest.mock import MagicMock

from rag_engine import (
    RAGEngine,
    build_source_records,
    validate_source_references,
)


CONTEXTS = [
    {
        "doc_id": "doc-h01",
        "case_name": "Case H01",
        "citation": "[2023] 1 S.C.R. 1",
        "decision_date": "01-01-2023",
        "rank": 1,
        "score": 0.9,
        "excerpt": "A passage about custodial interrogation.",
    },
    {
        "doc_id": "doc-h05",
        "case_name": "Case H05",
        "citation": "[2023] 2 S.C.R. 2",
        "decision_date": "02-01-2023",
        "rank": 2,
        "score": 0.8,
        "excerpt": "A PMLA-specific passage.",
    },
]


class TestAnswerGrounding(unittest.TestCase):
    def test_v2_prompt_requires_source_ids_and_legal_discipline(self):
        engine = object.__new__(RAGEngine)
        prompt = engine.build_prompt("What movement restrictions apply?", CONTEXTS, "v2")
        self.assertIn("[S1]", prompt)
        self.assertIn("[S2]", prompt)
        self.assertIn("counsel submissions", prompt)
        self.assertIn("PMLA-specific", prompt)
        self.assertIn("neighbouring question", prompt)
        self.assertIn("movement", prompt.lower())

    def test_v1_prompt_remains_the_baseline_contract(self):
        engine = object.__new__(RAGEngine)
        prompt = engine.build_prompt("Question", CONTEXTS)
        self.assertIn("--- [Extract 1] ---", prompt)
        self.assertIn("Cite the corresponding case name for each point.", prompt)
        self.assertNotIn("V2 LEGAL-SOURCE DISCIPLINE", prompt)

    def test_source_metadata_is_stable_and_preserved(self):
        sources = build_source_records(CONTEXTS)
        self.assertEqual([source["source_id"] for source in sources], ["S1", "S2"])
        self.assertEqual(sources[0]["doc_id"], "doc-h01")
        self.assertEqual(sources[1]["citation"], "[2023] 2 S.C.R. 2")
        self.assertEqual(sources[1]["rank"], 2)

    def test_unknown_and_malformed_source_ids_are_rejected(self):
        result = validate_source_references(
            "The holding is here [S1]. Another claim is here [S99]. [Sx].",
            build_source_records(CONTEXTS),
        )
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["unknown_source_ids"], ["S99"])
        self.assertEqual(result["malformed_source_references"], ["Sx"])
        self.assertFalse(result["semantic_support_verified"])

    def test_mocked_v2_response_resolves_original_case_metadata(self):
        engine = object.__new__(RAGEngine)
        engine.model = "test-model"
        engine.client = MagicMock()
        engine.query_engine = MagicMock()
        engine.client.models.generate_content.return_value.text = (
            "The answer is limited to the supplied passage [S2]."
        )
        result = engine.generate_answer(
            "Does the statutory rule apply?",
            model="test-model",
            contexts=CONTEXTS,
            answer_version="v2",
        )
        self.assertEqual(result["grounding_validation"]["status"], "valid")
        self.assertEqual(result["citations"][1]["source_id"], "S2")
        self.assertEqual(result["citations"][1]["doc_id"], "doc-h05")
        self.assertEqual(result["citations"][1]["citation"], "[2023] 2 S.C.R. 2")

    def test_known_failure_scenarios_are_prompt_guardrails_not_auto_scores(self):
        engine = object.__new__(RAGEngine)
        prompt = engine.build_prompt(
            "H01 H05 H11 H22 H27: answer the precise requested legal issue.",
            CONTEXTS,
            "v2",
        )
        self.assertIn("lower-court reasoning", prompt)
        self.assertIn("exceptions", prompt)
        self.assertIn("missing", prompt.lower())
        self.assertNotIn("correctness score", prompt.lower())


if __name__ == "__main__":
    unittest.main()
