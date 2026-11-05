import unittest
from dataclasses import replace
from unittest.mock import AsyncMock

from jev_solver.config import RelevancePolicy
from jev_solver.evaluation.calibration import relevance_validation
from jev_solver.judgments.pipeline import relevance_request, rerank
from jev_solver.models import EvidencePassage, Judgment


class LocalRelevanceTests(unittest.IsolatedAsyncioTestCase):
    def passage(self, identifier="p"):
        return EvidencePassage(
            identifier,
            "https://example.org",
            "hash",
            "F means move forward.",
            0,
            21,
            "now",
            "v1",
            subquestion="Which command moves forward?",
            question="Interpret the program.",
            dependency_id="mapping",
            dependency_version=2,
            view={"kind": "table_row", "header_status": "unavailable"},
        )

    def test_atomic_subfact_and_provenance_have_distinct_contract_fields(self):
        state, spec = relevance_request(self.passage(), "remediation-v1")
        self.assertEqual(state["dependency_version"], 2)
        self.assertEqual(state["source_identity"]["source_hash"], "hash")
        self.assertEqual(state["structured_view"]["header_status"], "unavailable")
        self.assertIn("separate", state["provenance_policy"])
        self.assertIn("DISCONFIRMING", spec["instructions"])
        self.assertNotEqual(state, relevance_request(self.passage())[0])

    async def test_12_slot_allowance_probabilities_confidence_and_availability(self):
        jev = AsyncMock()
        probabilities = {"background": 0.1, "partial": 0.8, "direct": 0.1}
        jev.request.side_effect = [
            {"relevance": Judgment("J2", "relevance", 0.8, 0.1, "mock", probabilities)},
            {},
        ] + [{"relevance": Judgment("J2", "relevance", 0.1, 0.99, "mock")} for _ in range(10)]
        observations = []
        result = await rerank(
            jev,
            "q",
            [replace(self.passage(str(i))) for i in range(20)],
            RelevancePolicy(),
            task_policy="remediation-v1",
            observations=observations,
        )
        self.assertEqual(jev.request.await_count, 12)
        self.assertEqual(result[0].relevance_probabilities, probabilities)
        self.assertEqual(result[0].score, 0.8)
        self.assertEqual(result[0].confidence, 0.1)
        self.assertEqual(result[1].relevance_status, "unavailable")
        self.assertEqual(len(observations), 12)

    def test_calibration_needs_adjudication_and_separate_families(self):
        def row(identifier, score=0.8, useful=True):
            return {
                "question_family": identifier,
                "source_family": identifier,
                "input_hash": identifier,
                "label_status": "adjudicated",
                "score": score,
                "useful": useful,
            }

        calibration = [row("cal-use", 0.6), row("cal-false", 0.1, False)]
        validation = [row("val-use", 0.6), row("val-false", 0.1, False)]
        result = relevance_validation(calibration, validation, [2 / 3, 0.5])
        self.assertTrue(result["promotion_gate"])
        self.assertFalse(result["policy_changed"])
        with self.assertRaisesRegex(ValueError, "leakage"):
            relevance_validation(calibration, calibration, [0.5])
        with self.assertRaisesRegex(ValueError, "adjudicated"):
            relevance_validation(
                [{**calibration[0], "label_status": "provisional"}], validation, [0.5]
            )
        self.assertEqual(relevance_validation([], [], [0.5])["status"], "unavailable")
