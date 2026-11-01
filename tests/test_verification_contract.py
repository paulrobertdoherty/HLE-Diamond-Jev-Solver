"""Routing and coverage regressions; these fixtures do not measure model accuracy."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from jev_solver.candidates.selection import select
from jev_solver.config import Config, Limits, RelevancePolicy
from jev_solver.controller.budget import BudgetExceeded
from jev_solver.controller.engine import Solver
from jev_solver.evaluation.components import components, workflow_metrics
from jev_solver.judgments.pipeline import constraints, rerank
from jev_solver.models import (
    Candidate,
    Dependency,
    EvidencePassage,
    Judgment,
    QuestionView,
    digest,
    record,
)
from jev_solver.providers.backbone import MockBackbone
from jev_solver.retrieval.evidence import diverse_packet
from jev_solver.tracing.store import Store


QUOTE = "The synthetic cobalt code is 27."


def passage(identifier="p", text=QUOTE, **kwargs):
    return EvidencePassage(
        identifier,
        "https://reference.example.org/a",
        digest(text),
        text,
        0,
        len(text),
        "fixture",
        "fixture",
        **kwargs,
    )


def audit_result(dep, status="passed", **changes):
    result = {
        "completeness": {"status": "passed", "reason": "Reviewed all necessary premises."},
        "answer_check": {"status": "passed", "reason": "Checked the complete proposed answer."},
        "dependencies": [{**record(dep), "status": status, "reason": "Independent fixture check."}],
        "gap_assessments": [],
        "queries": [],
        **changes,
    }
    return json.loads(json.dumps(result))


class VerificationContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.serial = 0

    def solver(self, **kwargs):
        self.serial += 1
        store = Store(self.root / f"{self.serial}.sqlite3")
        self.addCleanup(store.close)
        solver = Solver(Config(**kwargs), store, "verification-fixture")
        self.addAsyncCleanup(solver.close)
        return solver

    async def test_undeclared_factual_guess_and_critical_gap_cannot_bypass_audit(self):
        solver = self.solver()
        candidate = Candidate(
            "c",
            "28",
            0.99,
            "I recall this value but it needs verification.",
            gaps=("Verify the necessary reference value.",),
        )
        result = await solver.assess(
            QuestionView("q", "What is the fictional cobalt code?"), candidate, []
        )
        self.assertFalse(result["eligible"])
        self.assertEqual(result["coverage"]["status"], "not_run")
        self.assertEqual(result["dependencies"][0]["kind"], "factual")
        self.assertTrue(result["queries"])
        self.assertEqual(result["citation_checks"], [])

    async def test_no_declared_gaps_still_plans_research_and_corrects_answer(self):
        solver = self.solver(limits=replace(Limits(), rounds=1, retries=0))
        original = MockBackbone.generate

        async def guess(backbone, q, context, schema):
            result = await original(backbone, q, context, schema)
            if context["task"] == "independent initial solution":
                draft = json.loads(result["text"])
                draft.update(answer="28", gaps=[], queries=[], dependencies=[])
                result["text"] = json.dumps(draft)
            return result

        with patch.object(MockBackbone, "generate", guess):
            prediction = await solver.solve(QuestionView("q", "What is the fictional cobalt code?"))
        self.assertEqual((prediction.status, prediction.answer), ("completed", "27"))
        self.assertEqual(prediction.candidate_answers, ("28", "27"))
        selection = json.loads(
            solver.store.db.execute(
                "SELECT data FROM events WHERE kind='candidate_selection'"
            ).fetchone()[0]
        )
        self.assertEqual(selection["eligible"], ["revised-0"])

    async def test_checked_derivation_survives_incidental_gap_without_citations(self):
        solver = self.solver()
        candidate = Candidate(
            "c", "42", 0.9, "6 * 7 = 42.", gaps=("An optional historical note is unknown.",)
        )
        result = await solver.assess(QuestionView("q", "What is 6 * 7?"), candidate, [])
        self.assertTrue(result["eligible"])
        self.assertEqual(result["coverage"]["status"], "passed")
        self.assertFalse(result["gap_assessments"][0]["critical"])

    async def test_empty_audit_and_unclassified_gap_do_not_count_as_verified(self):
        dep = Dependency("d", "derived", "The sum is 42.", True, basis="6 * 7 = 42.")
        for audit in ({}, audit_result(dep, dependencies=[]), audit_result(dep)):
            solver = self.solver()
            solver.gateway.generate = AsyncMock(return_value=audit)
            candidate = Candidate(
                "c", "42", 0.9, "Checked.", gaps=("A required check is pending.",)
            )
            result = await solver.assess(QuestionView("q", "What is the sum?"), candidate, [])
            self.assertFalse(result["eligible"])

    async def test_factual_pass_requires_actual_source_and_semantic_availability(self):
        for refs, judgments in (((), {}), (("invented",), {}), (("p",), {})):
            solver = self.solver()
            dep = Dependency(
                "d", "factual", QUOTE, True, basis="Reference states the value.", passage_ids=refs
            )
            solver.gateway.generate = AsyncMock(return_value=audit_result(dep))
            solver.jev.request = AsyncMock(return_value=judgments)
            result = await solver.assess(
                QuestionView("q", "Find the code."),
                Candidate("c", "27", 0.9, "Reference."),
                [passage()],
            )
            self.assertFalse(result["eligible"])
        self.assertEqual(result["dependencies"][0]["status"], "unavailable")

    async def test_generated_repair_requires_successful_execution_of_that_exact_code(self):
        code = "print(42)"
        candidate = Candidate("c", "42", 0.9, "Computed.", code=code)
        dep = Dependency(
            "d",
            "numerical",
            "The numeric result is 42.",
            True,
            basis="Verified the output.",
            artifact_ids=("run",),
            code_hash=digest(code),
        )
        artifact = {
            "id": "run",
            "code_hash": digest(code),
            "returncode": 0,
            "stdout": "42",
            "synthetic": False,
            "truncated": False,
        }
        for change, expected in (
            ({}, True),
            ({"returncode": 1}, False),
            ({"synthetic": True}, False),
            ({"truncated": True}, False),
            ({"code_hash": digest("broken()")}, False),
        ):
            solver = self.solver(arm="B2")
            solver.gateway.generate = AsyncMock(return_value=audit_result(dep))
            result = await solver.assess(
                QuestionView("q", "Compute the value."), candidate, [], [{**artifact, **change}]
            )
            self.assertEqual(result["eligible"], expected)
        solver = self.solver(arm="B2")
        solver.gateway.generate = AsyncMock(return_value=audit_result(dep))
        result = await solver.assess(
            QuestionView("q", "Compute."), replace(candidate, code="print(43)"), [], [artifact]
        )
        self.assertEqual(result["dependencies"][0]["status"], "not_run")

    async def test_visual_checks_reference_original_images_received_by_backbone(self):
        dep = Dependency(
            "image",
            "visual",
            "The diagram has three vertices.",
            True,
            basis="Counted the three marked vertices.",
            image_indices=(0,),
        )
        for images, eligible in (((), False), (("data:image/png;base64,fixture",), True)):
            solver = self.solver(arm="B2")
            solver.gateway.generate = AsyncMock(return_value=audit_result(dep))
            q = QuestionView("q", "How many vertices are shown?", images)
            result = await solver.assess(q, Candidate("c", "3", 0.8, "Counted vertices."), [])
            self.assertEqual(result["eligible"], eligible)
            self.assertEqual(solver.gateway.generate.await_args.args[0].images, images)
            solver.jev.request = AsyncMock()
            self.assertEqual(result["dependencies"][0]["method"], "backbone_visual_review")

    async def test_j4_receives_real_evidence_artifacts_and_coverage(self):
        jev = SimpleNamespace(request=AsyncMock(return_value={}))
        result = await constraints(
            jev,
            "q",
            "Question",
            Candidate("c", "42", 0.8, "checked"),
            [passage()],
            [{"id": "run", "stdout": "42"}],
            {"coverage": {"status": "failed"}},
        )
        state = jev.request.await_args.args[2]
        self.assertEqual(state["evidence"][0]["text"], QUOTE)
        self.assertEqual(state["tool_artifacts"][0]["stdout"], "42")
        self.assertTrue(all(c["status"] == "unavailable" for c in result.values()))

    async def test_original_question_neutral_fact_and_query_remain_separate_at_j2(self):
        jev = SimpleNamespace(
            request=AsyncMock(
                return_value={"relevance": Judgment("J2", "relevance", 0.3567, 0, "fixture")}
            )
        )
        p = passage(
            question="Which feature distinguishes the painting?",
            subquestion="The distinguishing feature",
            search_query="initial guessed feature painting",
            dependency_id="feature",
        )
        ranked = await rerank(jev, "q", [p])
        state = jev.request.await_args.args[2]
        self.assertEqual(state["question"], p.question)
        self.assertEqual(state["missing_fact"], p.subquestion)
        self.assertEqual(state["search_query"], p.search_query)
        self.assertEqual(ranked[0].relevance_status, "uncertain")
        confident = [
            replace(p, id=str(i), score=0.9, text=f"Other text {i}", relevance_status="useful")
            for i in range(6)
        ]
        packet = diverse_packet(confident + ranked, 1000, 2)
        self.assertIn("p", {x.id for x in packet})

    async def test_uncertain_alternatives_are_bounded_and_confident_background_is_excluded(self):
        jev = SimpleNamespace(
            request=AsyncMock(
                return_value={"relevance": Judgment("J2", "relevance", 0.4, 0.1, "fixture")}
            )
        )
        result = await rerank(
            jev, "q", [passage(str(i)) for i in range(5)], RelevancePolicy(alternative_slots=1)
        )
        self.assertEqual(len(result), 1)
        jev.request.return_value = {"relevance": Judgment("J2", "relevance", 0.4, 0.99, "fixture")}
        self.assertEqual(await rerank(jev, "q", [passage()]), [])

    async def test_sixth_snippet_lead_is_prioritized_and_failure_outcomes_are_visible(self):
        solver = self.solver(
            arm="B2", limits=replace(Limits(), rounds=2, search=2, fetch=4, retries=0)
        )
        solver.plans["q"] = [
            {
                "dependency_id": "d",
                "missing_fact": "cobalt code decisive name",
                "query": "cobalt code",
            }
        ]
        solver.web.backend.search = AsyncMock(
            return_value=[
                {
                    "url": f"https://reference.example.org/{i}",
                    "title": "Reference",
                    "snippet": "cobalt code decisive name" if i == 5 else "General background",
                }
                for i in range(6)
            ]
        )
        solver.web.backend.fetch = AsyncMock(
            return_value={
                "url": "https://reference.example.org/5",
                "title": "Reference",
                "text": QUOTE,
            }
        )
        packet = await solver.research(
            QuestionView("q", "Find the fictional value."), Candidate("c", "", 0.1, "")
        )
        self.assertTrue(solver.web.backend.fetch.await_args_list[0].args[0].endswith("/5"))
        self.assertEqual(solver.web.backend.fetch.await_count, 3)
        outcome = solver.research_outcomes["q"][0]
        self.assertEqual(outcome["reserved_followup_fetches"], 1)
        self.assertTrue(any(lead["status"] == "not_fetched" for lead in outcome["leads"]))
        self.assertTrue(all(p.text == QUOTE for p in packet))

    async def test_feedback_plans_a_second_query_and_uses_reserved_fetch_capacity(self):
        solver = self.solver(limits=replace(Limits(), rounds=2, search=2, fetch=4, retries=0))
        original = MockBackbone.generate

        async def planning(backbone, q, context, schema):
            result = await original(backbone, q, context, schema)
            if (
                "completeness" in schema["properties"]
                and context["research_outcomes"]
                and not context["evidence"]
            ):
                audit = json.loads(result["text"])
                audit["queries"] = [
                    {
                        "dependency_id": "reference",
                        "missing_fact": "synthetic cobalt code",
                        "query": "cobalt code primary reference",
                    }
                ]
                result["text"] = json.dumps(audit)
            return result

        solver.web.backend.search = AsyncMock(
            side_effect=[
                [],
                [
                    {
                        "url": "https://reference.example.org/a",
                        "title": "Cobalt code",
                        "snippet": QUOTE,
                    }
                ],
            ]
        )
        with patch.object(MockBackbone, "generate", planning):
            prediction = await solver.solve(QuestionView("q", "What is the fictional cobalt code?"))
        self.assertEqual((prediction.status, prediction.answer), ("completed", "27"))
        self.assertEqual(solver.budget.snapshot("q")["counts"]["search"], 2)
        self.assertEqual(len(solver.research_outcomes["q"]), 2)
        self.assertEqual(solver.research_outcomes["q"][0]["searches"][0]["status"], "empty")

    async def test_finalization_calls_are_reserved_from_optional_tools(self):
        solver = self.solver(limits=replace(Limits(), calls=4, finalization_calls=2))
        await solver.budget.reserve("q", "search", 0)
        await solver.budget.reserve("q", "fetch", 0)
        with self.assertRaises(BudgetExceeded):
            await solver.budget.reserve("q", "fetch", 0)
        await solver.budget.reserve("q", "model", 0, final=True)
        await solver.budget.reserve("q", "model", 0, final=True)
        with self.assertRaises(BudgetExceeded):
            await solver.budget.reserve("q", "model", 0, final=True)

    async def test_repaired_code_is_executed_on_followup_before_it_can_establish_answer(self):
        solver = self.solver(arm="B2", limits=replace(Limits(), rounds=2, code=2))
        original = MockBackbone.generate
        broken, repaired = "raise ValueError('fixture')", "print(42)"

        async def generate(backbone, q, context, schema):
            result = await original(backbone, q, context, schema)
            if "answer" in schema["properties"]:
                code = broken if "previous" not in context else repaired
                draft = Candidate(
                    "unused", "42", 0.8, "Check the numerical calculation.", code=code
                )
                data = record(draft)
                del data["id"]
            elif "completeness" in schema["properties"]:
                code = context["draft"]["code"]
                matches = [a for a in context["tool_artifacts"] if a["code_hash"] == digest(code)]
                dep = Dependency(
                    "numeric",
                    "numerical",
                    "The numerical result is 42.",
                    True,
                    basis="Compared execution output with the requested result.",
                    code_hash=digest(code),
                    artifact_ids=tuple(a["id"] for a in matches),
                )
                data = audit_result(dep, "passed" if matches else "not_run")
            else:
                return result
            result["text"] = json.dumps(data)
            return result

        async def execute(item, code):
            return {
                "id": digest(code),
                "code_hash": digest(code),
                "code": code,
                "stdout": "42" if code == repaired else "",
                "stderr": "" if code == repaired else "fixture error",
                "returncode": 0 if code == repaired else 1,
                "synthetic": False,
                "truncated": False,
            }

        solver.sandbox.execute = AsyncMock(side_effect=execute)
        with patch.object(MockBackbone, "generate", generate):
            result = await solver.solve(QuestionView("q", "Find the numerical result."))
        self.assertEqual((result.status, result.answer), ("completed", "42"))
        self.assertEqual(
            [call.args[1] for call in solver.sandbox.execute.await_args_list], [broken, repaired]
        )
        checks = [
            json.loads(row[0])
            for row in solver.store.db.execute(
                "SELECT data FROM events WHERE kind='candidate_checks' ORDER BY seq"
            )
        ]
        before_execution = next(c for c in checks if c["candidate_id"] == "revised-0")
        self.assertFalse(before_execution["eligible"])
        self.assertTrue(next(c for c in checks if c["candidate_id"] == "revised-1")["eligible"])

    async def test_selection_cannot_claim_unrun_or_omit_critical_checks(self):
        solver = self.solver(arm="B2")
        candidate = Candidate("c", "42", 0.9, "6 * 7 = 42.")
        assessment = await solver.assess(QuestionView("q", "Compute 6 * 7."), candidate, [])
        for refs in ([], ["invented"]):
            solver.gateway.generate = AsyncMock(
                return_value={
                    "selected": "candidate_0",
                    "reason": "It looks correct.",
                    "checked_dependencies": refs,
                }
            )
            with self.assertRaisesRegex(ValueError, "selection basis"):
                await select(
                    solver.jev,
                    solver.gateway,
                    QuestionView("q", "Compute 6 * 7."),
                    [candidate],
                    "backbone",
                    17,
                    assessments={"c": assessment},
                )

    async def test_research_replay_reaudits_cached_full_sources_before_exposure(self):
        solver = self.solver(arm="B2", limits=replace(Limits(), rounds=1))
        plan = [{"dependency_id": "d", "missing_fact": "cobalt code", "query": "cobalt code"}]
        solver.plans["q"] = plan
        q = QuestionView("q", "Find the fictional value.")
        candidate = Candidate("c", "", 0.1, "Pending reference.")
        self.assertTrue(await solver.research(q, candidate))
        for key, raw in solver.store.db.execute(
            "SELECT key,value FROM cache WHERE item='q'"
        ).fetchall():
            value = json.loads(raw)
            if "page" in value:
                value["page"]["text"] += " Humanity's Last Exam answer"
                solver.store.cache("q", key, value)
        solver.research_outcomes["q"] = []
        solver.web.backend.fetch = AsyncMock(side_effect=AssertionError("must not fetch again"))
        self.assertEqual(await solver.research(q, candidate), [])
        solver.web.backend.fetch.assert_not_awaited()

    async def test_component_metrics_measure_decisions_packets_and_negative_support(self):
        result = await components(
            Config(), Path("tests/fixtures/components.jsonl"), self.root / "components"
        )
        self.assertEqual(result["metrics"]["J2"]["answer_bearing_recall_at_packet_budget"], 1)
        self.assertEqual(
            result["metrics"]["J3"]["confusion_matrix"]["contradicted"]["supported"], 1
        )
        path = self.root / "workflow.jsonl"
        path.write_text(
            "\n".join(
                json.dumps(row)
                for row in [
                    {
                        "stage": "coverage",
                        "required_claims": ["a", "b"],
                        "discovered_claims": ["a", "b"],
                        "checked_claims": ["a"],
                    },
                    {
                        "stage": "selection",
                        "candidate_ids": ["correct", "wrong"],
                        "correct_ids": ["correct"],
                        "selected_id": "wrong",
                    },
                    {
                        "stage": "selection",
                        "candidate_ids": ["correct"],
                        "correct_ids": ["correct"],
                        "selected_id": None,
                    },
                ]
            )
        )
        metrics = workflow_metrics(path, self.root / "metrics.json")
        self.assertEqual(metrics["claim_discovery_recall"], 1)
        self.assertEqual(metrics["claim_coverage_recall"], 0.5)
        self.assertEqual(metrics["wrong_answer_acceptance_rate"], 1)
        self.assertEqual(metrics["correct_answer_rejection_rate"], 0.5)

    async def test_component_usefulness_accuracy_does_not_require_exact_continuous_scores(self):
        original = MockBackbone.generate

        async def judge(backbone, q, context, schema):
            result = await original(backbone, q, context, schema)
            if schema.get("properties", {}).get("judgment", {}).get("type") == "number":
                result["text"] = json.dumps(
                    {"judgment": 0.8 if "cobalt code" in context["state"]["passage"] else 0.1}
                )
            return result

        with patch.object(MockBackbone, "generate", judge):
            result = await components(
                Config(),
                Path("tests/fixtures/components.jsonl"),
                self.root / "fractional",
                judge="backbone",
            )
        self.assertEqual(result["metrics"]["J2"]["accuracy"], 1)
        self.assertAlmostEqual(result["metrics"]["J2"]["mean_absolute_error"], 0.15)
