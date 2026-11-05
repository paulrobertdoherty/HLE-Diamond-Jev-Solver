import json
import unittest
import tempfile
import time
from pathlib import Path
from dataclasses import replace
from unittest.mock import AsyncMock

from jev_solver.judgments.graph import (
    parse_contract,
    reconcile_graph,
    validate_graph,
    propagate_failures,
)
from jev_solver.models import Dependency, QuestionView, record
from jev_solver.config import Config, RemediationPolicy
from jev_solver.controller.engine import Solver
from jev_solver.tracing.store import Store


class PersistentGraphTests(unittest.TestCase):
    def test_edges_follow_logical_identity_across_local_candidate_ids(self):
        nodes = [
            self.dep("candidate-local", logical_id="stable-premise", status="not_run"),
            self.dep("answer", kind="derived", depends_on=["stable-premise"]),
        ]
        validate_graph(nodes, self.contract())
        propagate_failures(nodes)
        self.assertEqual(nodes[1]["status"], "not_run")

    def contract(self):
        return parse_contract(
            {
                "obligations": [
                    {
                        "id": "output",
                        "kind": "output",
                        "text": "Find the value.",
                        "anchor": "Find",
                        "image_indices": [],
                    },
                    {
                        "id": "chronology",
                        "kind": "chronology",
                        "text": "After completion.",
                        "anchor": "after",
                        "image_indices": [],
                    },
                ],
                "alternatives": ["Convention A or B"],
            },
            QuestionView("q", "Find the value after completion."),
        )

    def dep(self, identifier="fact", **changes):
        return {
            **json.loads(
                json.dumps(
                    record(
                        Dependency(
                            identifier,
                            "factual",
                            "Convention A applies.",
                            True,
                            basis="Source.",
                            logical_id=identifier,
                            obligations=("output",),
                            assumptions=("Convention A",),
                        )
                    )
                )
            ),
            "status": "passed",
            "reason": "Checked.",
            **changes,
        }

    def test_omitted_chronology_or_convention_is_retained(self):
        old = self.dep(obligations=["chronology"])
        nodes, events, _ = reconcile_graph([], [old], self.contract())
        self.assertEqual(nodes[0]["status"], "not_run")
        self.assertEqual(nodes[0]["assumptions"], ["Convention A"])
        self.assertEqual(events[0]["event"], "premise_retained")

    def test_changed_premise_invalidates_descendants_and_keeps_criticality(self):
        old = self.dep()
        changed = self.dep(statement="Convention B applies.", critical=False)
        child = self.dep("answer", kind="derived", depends_on=["fact"])
        nodes, _, _ = reconcile_graph([changed, child], [old, child], self.contract())
        self.assertEqual(nodes[0]["premise_version"], 2)
        self.assertTrue(nodes[0]["critical"])
        self.assertEqual(nodes[1]["status"], "not_run")

    def test_factual_to_derived_cannot_erase_basis_across_revisions(self):
        old = self.dep()
        new = self.dep(kind="derived", passage_ids=[])
        nodes, _, _ = reconcile_graph([new], [old], self.contract())
        self.assertEqual(nodes[0]["kind"], "factual")
        nodes, _, _ = reconcile_graph([new], nodes, self.contract())
        self.assertEqual(nodes[0]["kind"], "factual")

    def test_cycles_dangling_obligations_and_dependency_limit_fail(self):
        for nodes in (
            [self.dep(depends_on=["missing"])],
            [self.dep(depends_on=["fact"])],
            [self.dep(obligations=["invented"])],
            [self.dep(str(i)) for i in range(13)],
        ):
            with self.assertRaises(ValueError):
                validate_graph(nodes, self.contract())

    def test_independent_checked_route_and_optional_removal(self):
        old = self.dep(assumptions=[])
        independent = self.dep(
            "proof", kind="derived", basis="Elementary derivation from givens.", assumptions=[]
        )
        nodes, events, _ = reconcile_graph(
            [independent],
            [old],
            self.contract(),
            [
                {
                    "logical_id": "fact",
                    "action": "independent_route",
                    "replacement_ids": ["proof"],
                    "reason": "Uses only givens.",
                }
            ],
        )
        self.assertEqual(len(nodes), 1)
        self.assertEqual(events[0]["event"], "discharged")
        nodes, _, _ = reconcile_graph(
            [],
            [self.dep(critical=False)],
            self.contract(),
            [
                {
                    "logical_id": "fact",
                    "action": "optional_removed",
                    "replacement_ids": [],
                    "reason": "Removed optional explanation.",
                }
            ],
        )
        self.assertEqual(nodes, [])

    def test_unresolved_parent_blocks_checked_child(self):
        nodes = [
            self.dep(status="unavailable"),
            self.dep("answer", kind="derived", depends_on=["fact"]),
        ]
        propagate_failures(nodes)
        self.assertEqual(nodes[1]["status"], "not_run")

    def test_contract_anchors_cannot_be_invented(self):
        contract = self.contract()
        raw = {k: contract[k] for k in ("obligations", "alternatives")}
        raw["obligations"][0]["anchor"] = "not in question"
        with self.assertRaisesRegex(ValueError, "anchored"):
            parse_contract(raw, QuestionView("q", "Find the value after completion."))


class ContractResumeTests(unittest.IsolatedAsyncioTestCase):
    async def test_corrected_contract_restores_version_without_new_generation_allowance(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "events.sqlite3")
            config = replace(Config(), remediation=RemediationPolicy(contract="remediation-v1"))
            solver = Solver(config, store, "fixture")
            q = QuestionView("q", "Compute 6 * 7.")
            solver.starts[q.id] = time.time()
            await solver.question_contract(q)
            raw = {k: solver.contracts[q.id][k] for k in ("obligations", "alternatives")}
            raw["alternatives"] = ["Interpret units if specified."]
            corrected = solver.correct_contract(
                q, raw, "Preserve the answer-changing interpretation."
            )
            await solver.close()
            restored = Solver(config, store, "fixture")
            restored.starts[q.id] = time.time()
            restored.gateway.generate = AsyncMock(
                side_effect=AssertionError("A correction must survive resume.")
            )
            try:
                await restored.question_contract(q)
                self.assertEqual(restored.contracts[q.id]["hash"], corrected["hash"])
                self.assertEqual(restored.contracts[q.id]["version"], 2)
                restored.gateway.generate.assert_not_awaited()
            finally:
                await restored.close()
                store.close()
