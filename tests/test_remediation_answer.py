import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from jev_solver.config import Config, Limits, RemediationPolicy
from jev_solver.controller.engine import Solver
from jev_solver.judgments.answer import apply_final_result, parse_whole_answer
from jev_solver.models import Candidate, Dependency, QuestionView, record
from jev_solver.tracing.store import Store
from jev_solver.candidates.selection import select


class WholeAnswerTests(unittest.IsolatedAsyncioTestCase):
    def node(self, identifier="d", **changes):
        return {
            **json.loads(
                json.dumps(
                    record(
                        Dependency(identifier, "derived", "6 * 7 = 42", True, basis="Arithmetic.")
                    )
                )
            ),
            "status": "passed",
            "reason": "Checked.",
            **changes,
        }

    def audit(self, nodes):
        return {
            "dependencies": nodes,
            "completeness": {"status": "passed", "reason": "Complete."},
            "answer_check": {"status": "passed", "reason": "Provisional."},
            "coverage": {"status": "passed"},
        }

    def raw(self):
        return {
            "whole_answer": {"status": "passed", "reason": "All outputs checked."},
            "applicability": {"status": "passed", "reason": "Applicable to givens."},
            "obligation_checks": [
                {"id": "output", "status": "passed", "reason": "Checked.", "dependency_ids": ["d"]}
            ],
            "interpretation_checks": [],
            "derived_rechecks": [],
            "source_scope": [],
        }

    def test_conditional_chronology_multipart_and_wrong_model_fail_actual_final_gate(self):
        candidate = Candidate("c", "42", 0.8, "Conditional proof.")
        for issue in (
            "Construction applicability unresolved.",
            "Procedure already completed.",
            "Missing second output.",
            "Executed the wrong modeled algorithm.",
        ):
            raw = self.raw()
            raw["applicability"] = {"status": "failed", "reason": issue}
            result, _ = apply_final_result(raw, self.audit([self.node()]), [], [], candidate)
            self.assertEqual(result["coverage"]["status"], "failed")

    def test_qualified_possibility_and_independent_reasoning_can_pass(self):
        result, _ = apply_final_result(
            self.raw(),
            self.audit([self.node()]),
            [],
            [],
            Candidate("c", "A possible explanation is X.", 0.7, "Defensible possibility."),
        )
        self.assertEqual(result["coverage"]["status"], "passed")

    def test_whole_answer_cannot_override_missing_factual_premise(self):
        result, _ = apply_final_result(
            self.raw(),
            self.audit([self.node(kind="factual", status="not_run")]),
            [],
            [],
            Candidate("c", "42", 0.9, "Check."),
        )
        self.assertEqual(result["coverage"]["status"], "failed")
        raw = self.raw()
        raw["derived_rechecks"] = [
            {"id": "d", "status": "passed", "reason": "Claimed.", "basis": "Model memory."}
        ]
        with self.assertRaisesRegex(ValueError, "relabel"):
            parse_whole_answer(
                raw,
                {
                    "question_contract": {"obligations": [{"id": "output"}], "alternatives": []},
                    "local_results": {"dependencies": [self.node(kind="factual")]},
                },
            )

    def test_alternative_interpretations_cannot_disappear(self):
        with self.assertRaisesRegex(ValueError, "interpretation"):
            parse_whole_answer(
                self.raw(),
                {
                    "question_contract": {
                        "obligations": [{"id": "output"}],
                        "alternatives": ["Convention B"],
                    },
                    "local_results": {"dependencies": [self.node()]},
                },
            )

    async def test_selection_rejects_foreign_candidate_check_even_if_marked_eligible(self):
        gateway = SimpleNamespace(
            config=replace(Config(), remediation=RemediationPolicy(final="remediation-v1"))
        )
        with self.assertRaisesRegex(ValueError, "candidate-scoped"):
            await select(
                None,
                gateway,
                QuestionView("q", "Compute."),
                [Candidate("c", "42", 0.9, "Check.")],
                "vote",
                17,
                assessments={"c": {"eligible": True, "final_check": {"candidate_id": "other"}}},
            )

    async def test_integrated_symbolic_solution_preserves_original_image_and_uses_no_jev(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "events.sqlite3")
            config = replace(
                Config(arm="B2"),
                remediation=RemediationPolicy(
                    contract="remediation-v1", final="remediation-v1", generation="remediation-v1"
                ),
                limits=replace(Limits(), calls=40),
            )
            solver = Solver(config, store, "synthetic")
            solver.jev.request = AsyncMock(
                side_effect=AssertionError("No Jev in Sol-only reasoning.")
            )
            try:
                result = await solver.solve(
                    QuestionView("q", "Compute 6 * 7.", ("data:image/png;base64,original",))
                )
                self.assertEqual(result.answer, "42", result.error)
                solver.jev.request.assert_not_awaited()
                events = [
                    json.loads(r[0])
                    for r in store.db.execute(
                        "SELECT data FROM events WHERE kind='candidate_checks'"
                    )
                ]
                self.assertEqual(events[-1]["final_check"]["whole_answer"]["status"], "passed")
            finally:
                await solver.close()
                store.close()
