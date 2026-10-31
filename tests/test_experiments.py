import asyncio
import builtins
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from jev_solver.benchmarks.data import prepare
from jev_solver.config import Config, Limits
from jev_solver.controller.engine import Solver, run
from jev_solver.evaluation.analysis import diagnostics, paired, summary
from jev_solver.evaluation.components import components
from jev_solver.evaluation.export import export_report
from jev_solver.evaluation.grading import finalized_predictions, grade, official_prompt
from jev_solver.models import QuestionView, digest
from jev_solver.providers.backbone import MockBackbone, ProviderError
from jev_solver.retrieval.corpus import Corpus, build_corpus
from jev_solver.tools.policy import Policy
from jev_solver.tracing.audit import audit
from jev_solver.tracing.store import Store


class ExperimentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        prepare(self.root / "data", "", Path("tests/fixtures/tasks.jsonl"))
        self.questions = self.root / "data/solver/questions.jsonl"
        self.labels = self.root / "data/evaluator/labels.jsonl"

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_selected_question_run_is_finalized_and_rejects_invalid_selection(self):
        questions = [json.loads(line) for line in self.questions.read_text().splitlines()]
        selected = questions[0]["id"]
        await run(Config(), self.questions, self.root / "selected", question_ids=(selected,))
        manifest, predictions = finalized_predictions(self.root / "selected")
        self.assertEqual(manifest["count"], 1)
        self.assertEqual(manifest["declared_ids"], [selected])
        self.assertEqual([p["question_id"] for p in predictions], [selected])
        for selection in ((selected, selected), ("not-in-dataset",)):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                await run(Config(), self.questions, self.root / "invalid", question_ids=selection)
        self.assertFalse((self.root / "invalid").exists())

    async def test_question_selection_cannot_bypass_the_declared_split(self):
        prepare(self.root / "split-data", "", Path("tests/fixtures/tasks.jsonl"), dev_count=2)
        membership = json.loads((self.root / "split-data/solver/split.json").read_text())
        with self.assertRaisesRegex(ValueError, "declared split"):
            await run(
                Config(),
                self.root / "split-data/solver/questions.jsonl",
                self.root / "wrong-split",
                split="development",
                question_ids=(membership["heldout"][0],),
            )

    async def test_independent_development_preparation_and_identity(self):
        from jev_solver.cli import execute, parser

        result = execute(
            parser().parse_args(
                [
                    "prepare",
                    "--development-file",
                    "tests/fixtures/tasks.jsonl",
                    "--output",
                    str(self.root / "independent"),
                ]
            )
        )
        self.assertEqual(result["dataset"], "independent/development")
        config = replace(
            Config(),
            dataset=result["dataset"],
            dataset_revision=result["revision"],
            scope="independent-development",
        )
        await run(
            config, self.root / "independent/solver/questions.jsonl", self.root / "independent-run"
        )
        await grade(
            self.root / "independent-run",
            self.root / "independent/evaluator/labels.jsonl",
            self.root / "independent-eval",
        )
        export_report(self.root / "independent-eval/grades.json", self.root / "independent-report")
        public = json.loads((self.root / "independent-report/report.json").read_text())
        self.assertFalse(public["measured_benchmark_result"])

    async def test_oracle_retains_answers_rejected_by_citation_verification(self):
        original = MockBackbone.generate

        async def fabricated(backbone, q, context, schema):
            response = await original(backbone, q, context, schema)
            if q.id == "synthetic-reference-1" and context.get("evidence"):
                candidate = json.loads(response["text"])
                candidate["citations"][0]["quote"] = "A fabricated quote."
                response["text"] = json.dumps(candidate)
            return response

        with patch.object(MockBackbone, "generate", fabricated):
            await run(Config(), self.questions, self.root / "rejected")
        await grade(self.root / "rejected", self.labels, self.root / "rejected-eval", oracle=True)
        rows = json.loads((self.root / "rejected-eval/grades.json").read_text())["grades"]
        factual = next(g for g in rows if g["question_id"] == "synthetic-reference-1")
        self.assertFalse(factual["correct"])
        self.assertTrue(factual["oracle_correct"])

    async def test_oracle_grades_saved_candidates_after_solver_failures(self):
        original = Solver.research

        for status in ("budget_exceeded", "timeout", "error"):
            with self.subTest(status=status):

                async def fail_after_initial(solver, q, candidate, expected_status=status):
                    if expected_status == "timeout":
                        raise TimeoutError()
                    if expected_status == "error":
                        raise ProviderError("source unavailable")
                    return await original(solver, q, candidate)

                config = replace(Config(), limits=replace(Limits(), calls=1))
                directory = self.root / status
                with patch.object(Solver, "research", fail_after_initial):
                    await run(config, self.questions, directory)
                await grade(directory, self.labels, self.root / (status + "-eval"), oracle=True)
                rows = json.loads((self.root / (status + "-eval/grades.json")).read_text())[
                    "grades"
                ]
                self.assertTrue(all(g["status"] == status and not g["correct"] for g in rows))
                arithmetic = next(g for g in rows if g["question_id"] == "synthetic-arithmetic-1")
                factual = next(g for g in rows if g["question_id"] == "synthetic-reference-1")
                self.assertTrue(arithmetic["oracle_correct"])
                self.assertFalse(factual["oracle_correct"])
                self.assertEqual(diagnostics(rows)["oracle_labeled_count"], 4)
                self.assertEqual(diagnostics(rows)["oracle_selection_gap"], 0.75)

    async def test_prepared_split_hash_is_checked_before_dispatch(self):
        split_path = self.questions.parent / "split.json"
        memberships = json.loads(split_path.read_text())
        memberships["development"] = [memberships["heldout"][0]]
        split_path.write_text(json.dumps(memberships))
        with patch.object(Solver, "solve", new_callable=AsyncMock) as solve:
            for split in ("heldout", "full"):
                with self.subTest(split=split), self.assertRaisesRegex(ValueError, "split hash"):
                    await run(Config(), self.questions, self.root / split, split=split)
            solve.assert_not_awaited()
        self.assertFalse((self.root / "heldout").exists())

    async def test_split_structure_disjointness_and_coverage_are_required(self):
        split_path = self.questions.parent / "split.json"
        ids = json.loads(split_path.read_text())["heldout"]
        manifest_path = self.questions.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        for membership in (
            {"development": [ids[0]], "heldout": ids},
            {"development": [], "heldout": ids[:-1]},
            {"development": [], "heldout": [*ids, "unknown"]},
            {"development": [], "heldout": [*ids, ids[0]]},
            {"development": [], "heldout": ids, "extra": []},
            {"development": [], "heldout": "not a list"},
            {"development": [], "heldout": [*ids, 123]},
        ):
            with self.subTest(membership=membership):
                split_path.write_text(json.dumps(membership))
                manifest_path.write_text(json.dumps({**manifest, "split_hash": digest(membership)}))
                with self.assertRaisesRegex(ValueError, "split"):
                    await run(
                        Config(), self.questions, self.root / "invalid-split", split="heldout"
                    )

    async def test_valid_development_and_heldout_splits_select_the_declared_ids(self):
        prepare(self.root / "split-data", "", Path("tests/fixtures/tasks.jsonl"), dev_count=1)
        questions = self.root / "split-data/solver/questions.jsonl"
        memberships = json.loads((questions.parent / "split.json").read_text())
        for split, ids in memberships.items():
            await run(Config(arm="B0", track="closed"), questions, self.root / split, split=split)
            manifest, predictions = finalized_predictions(self.root / split)
            self.assertEqual(set(manifest["declared_ids"]), set(ids))
            self.assertEqual({p["question_id"] for p in predictions}, set(ids))

    async def test_baselines_and_jev_ablation_matrix(self):
        for arm in ("b0", "b1", "b2", "j2", "j3", "j23", "jfull", "m"):
            with self.subTest(arm=arm):
                config = Config.load(f"configs/{arm}.synthetic.json")
                directory = self.root / arm
                await run(config, self.questions, directory)
                result = await grade(
                    directory, self.labels, self.root / ("eval-" + arm), oracle=True
                )
                self.assertEqual(result["count"], 4)
                self.assertEqual(result["correct"], 3 if arm in {"b0", "b1"} else 4)
                store = Store(directory / "events.sqlite3")
                kinds = dict(store.db.execute("SELECT kind,COUNT(*) FROM calls GROUP BY kind"))
                if arm in {"b0", "b1"}:
                    self.assertEqual(set(kinds), {"model"})
                    self.assertEqual(kinds["model"], 4 if arm == "b0" else 12)
                if arm == "b2":
                    self.assertNotIn("jev", kinds)
                store.close()

    async def test_solver_does_not_open_reference_storage(self):
        original = builtins.open

        def guarded(path, *args, **kwargs):
            if isinstance(path, (str, Path)) and "evaluator" in str(path):
                raise AssertionError("solver accessed labels")
            return original(path, *args, **kwargs)

        with patch("builtins.open", side_effect=guarded):
            await run(Config(), self.questions, self.root / "run")
        self.assertEqual(len(finalized_predictions(self.root / "run")[1]), 4)

    async def test_resume_is_idempotent_and_config_is_frozen(self):
        config = Config()
        directory = self.root / "run"
        await run(config, self.questions, directory)
        store = Store(directory / "events.sqlite3")
        count = store.db.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
        store.close()
        first = (directory / "predictions.json").read_bytes()
        await run(config, self.questions, directory, resume=True)
        self.assertEqual(first, (directory / "predictions.json").read_bytes())
        store = Store(directory / "events.sqlite3")
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM calls").fetchone()[0], count)
        store.close()
        with self.assertRaisesRegex(ValueError, "resume manifest differs"):
            await run(replace(config, seed=99), self.questions, directory, resume=True)

    async def test_interrupted_run_resumes_without_repeating_finalized_item(self):
        config = replace(Config(), limits=replace(Limits(), concurrency=1))
        directory = self.root / "run"
        original = Solver.solve

        async def interrupt_after_first(solver, q):
            if q.id != "synthetic-arithmetic-1":
                raise asyncio.CancelledError()
            return await original(solver, q)

        with patch.object(Solver, "solve", interrupt_after_first):
            with self.assertRaises(asyncio.CancelledError):
                await run(config, self.questions, directory)
        with self.assertRaises(ValueError):
            finalized_predictions(directory)
        store = Store(directory / "events.sqlite3")
        count = store.db.execute(
            "SELECT COUNT(*) FROM calls WHERE item='synthetic-arithmetic-1'"
        ).fetchone()[0]
        store.close()
        await run(config, self.questions, directory, resume=True)
        store = Store(directory / "events.sqlite3")
        self.assertEqual(
            store.db.execute(
                "SELECT COUNT(*) FROM calls WHERE item='synthetic-arithmetic-1'"
            ).fetchone()[0],
            count,
        )
        self.assertEqual(len(store.predictions()), 4)
        store.close()

    async def test_partial_item_replays_cached_model_and_tool_calls(self):
        # Fail after the initial call has been cached but before finalization.
        directory = self.root / "partial"
        original = Solver.research
        attempts = 0

        async def cancel_once(solver, q, candidate):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise asyncio.CancelledError()
            return await original(solver, q, candidate)

        config = replace(Config(), limits=replace(Limits(), concurrency=1))
        with patch.object(Solver, "research", cancel_once):
            with self.assertRaises(asyncio.CancelledError):
                await run(config, self.questions, directory)
        await run(config, self.questions, directory, resume=True)
        store = Store(directory / "events.sqlite3")
        initial_events = [
            json.loads(r[0])
            for r in store.db.execute(
                "SELECT data FROM events WHERE item='synthetic-arithmetic-1' AND kind='model_replay'"
            )
        ]
        self.assertGreaterEqual(len(initial_events), 1)
        store.close()

    async def test_timeout_and_budget_failures_remain_in_denominator(self):
        config = replace(Config(), limits=replace(Limits(), calls=1))
        directory = self.root / "budget"
        await run(config, self.questions, directory)
        result = await grade(directory, self.labels, self.root / "eval")
        self.assertEqual(result["count"], 4)
        data = json.loads((self.root / "eval/grades.json").read_text())
        self.assertEqual(summary(data["grades"])["failure_rate"], 1)
        slow = replace(Config(), limits=replace(Limits(), deadline_s=0.01))

        async def block(*args):
            await asyncio.Event().wait()

        with patch.object(MockBackbone, "generate", block):
            await run(slow, self.questions, self.root / "timeout")
        _, predictions = finalized_predictions(self.root / "timeout")
        self.assertTrue(all(p["status"] == "timeout" for p in predictions))

    async def test_modified_predictions_cannot_be_graded(self):
        directory = self.root / "run"
        await run(Config(), self.questions, directory)
        rows = json.loads((directory / "predictions.json").read_text())
        rows[0]["answer"] = "changed"
        (directory / "predictions.json").write_text(json.dumps(rows))
        with self.assertRaisesRegex(ValueError, "changed"):
            finalized_predictions(directory)

    async def test_sanitized_export_cannot_publish_questions_or_slice_injections(self):
        directory = self.root / "run"
        await run(replace(Config(), scope="SECRET_QUESTION_MARKER"), self.questions, directory)
        await grade(directory, self.labels, self.root / "eval", oracle=True)
        artifact = self.root / "eval/grades.json"
        data = json.loads(artifact.read_text())
        data["grades"][0]["slices"]["subject"] = "SECRET_QUESTION_MARKER"
        data["manifest"]["declared_ids"].append("SECRET_QUESTION_MARKER")
        data["usage"]["question"] = "SECRET_QUESTION_MARKER"
        data["usage"]["attempts_by_kind"]["SECRET_QUESTION_MARKER"] = 1
        data["manifest"]["config"]["limits"]["private_question"] = "SECRET_QUESTION_MARKER"
        data["manifest"]["contamination_audit"] = {
            "exposed_ids": ["SECRET_QUESTION_MARKER"],
            "comment": "SECRET_QUESTION_MARKER",
        }
        artifact.write_text(json.dumps(data))
        export_report(artifact, self.root / "public")
        for path in (self.root / "public").iterdir():
            content = path.read_text()
            self.assertNotIn("SECRET_QUESTION_MARKER", content)
            self.assertNotIn("What is 6", content)
            self.assertNotIn("candidate_answers", content)

    async def test_contamination_flags_keep_all_items(self):
        directory = self.root / "run"
        await run(Config(), self.questions, directory)
        flags = self.root / "flags.json"
        flags.write_text('["synthetic-arithmetic-1"]')
        self.assertEqual(audit(directory, flags)["exposed_count"], 1)
        await grade(directory, self.labels, self.root / "eval")
        rows = json.loads((self.root / "eval/grades.json").read_text())["grades"]
        self.assertEqual(len(rows), 4)
        self.assertEqual(summary(rows)["contaminated_count"], 1)

    async def test_component_results_include_negative_cases(self):
        result = await components(
            Config(), Path("tests/fixtures/components.jsonl"), self.root / "components"
        )
        self.assertEqual(result["metrics"]["J2"]["count"], 2)
        self.assertEqual(result["metrics"]["J3"]["accuracy"], 0.5)

    async def test_extended_frozen_corpus_is_versioned_and_used(self):
        source = self.root / "documents.jsonl"
        source.write_text(
            json.dumps(
                {
                    "url": "https://reference.example.org/a",
                    "title": "Fictional reference",
                    "text": "The synthetic cobalt code is 27.",
                    "license": "CC0",
                    "ingested_at": "2026-10-28",
                }
            )
            + "\n"
        )
        corpus_file = self.root / "corpus.json"
        policy = Policy(Path("protocol/upstream/blocklist.json"))
        built = build_corpus(source, corpus_file, policy, "fixture-v1")
        corpus = Corpus(corpus_file, policy)
        self.assertEqual(built["passages"], 1)
        self.assertIn("cobalt", corpus.retrieve("cobalt code", hybrid=True)[0].text)
        config = replace(
            Config(), arm="R", track="extended", corpus=str(corpus_file), retrieval="hybrid-jev"
        )
        await run(config, self.questions, self.root / "r")
        result = await grade(self.root / "r", self.labels, self.root / "eval")
        self.assertEqual(result["correct"], 4)
        content = json.loads(corpus_file.read_text())
        content["passages"][0]["text"] = "tampered"
        corpus_file.write_text(json.dumps(content))
        with self.assertRaises(ValueError):
            Corpus(corpus_file, policy)


class ControllerRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.solver_count = 0

    def solver(self, config):
        self.solver_count += 1
        store = Store(self.root / f"{self.solver_count}.sqlite3")
        self.addCleanup(store.close)
        solver = Solver(config, store, "regression")
        self.addAsyncCleanup(solver.close)
        return solver

    def three_queries(self, solver, contexts):
        original = MockBackbone.generate

        async def generate(backbone, q, context, schema):
            response = await original(backbone, q, context, schema)
            if context["task"] == "independent initial solution":
                candidate = json.loads(response["text"])
                candidate["queries"] = ["cobalt fact one", "cobalt fact two", "cobalt fact three"]
                response["text"] = json.dumps(candidate)
            else:
                contexts.append(context)
            return response

        async def search(query):
            return [
                {"url": f"https://example.org/{digest(query)[:8]}/{i}", "title": "Reference"}
                for i in range(3)
            ]

        solver.web.backend.search = AsyncMock(side_effect=search)
        return patch.object(MockBackbone, "generate", generate)

    async def test_tool_caps_keep_evidence_and_allow_final_revision(self):
        for limits, expected in (
            (replace(Limits(), rounds=1), {"fetch": 8, "search": 3, "model": 2}),
            (replace(Limits(), rounds=1, search=1), {"fetch": 3, "search": 1, "model": 2}),
        ):
            with self.subTest(limits=limits):
                solver = self.solver(Config(arm="B2", limits=limits))
                contexts = []
                with self.three_queries(solver, contexts):
                    result = await solver.solve(
                        QuestionView("q", "What is the fictional cobalt code?")
                    )
                self.assertEqual(result.status, "completed")
                self.assertEqual(result.answer, "27")
                self.assertTrue(contexts[0]["evidence"])
                self.assertEqual(solver.budget.snapshot("q")["counts"], expected)

    async def test_cached_research_replays_after_fetch_cap_is_reached(self):
        config = Config(arm="B2", limits=replace(Limits(), rounds=1))
        solver = self.solver(config)
        generate = solver.gateway.generate

        async def interrupt_before_revision(q, context, phase, **kwargs):
            if phase == "revise-0":
                raise asyncio.CancelledError()
            return await generate(q, context, phase, **kwargs)

        contexts = []
        question = QuestionView("q", "What is the fictional cobalt code?")
        with self.three_queries(solver, contexts):
            with patch.object(solver.gateway, "generate", interrupt_before_revision):
                with self.assertRaises(asyncio.CancelledError):
                    await solver.solve(question)
            self.assertEqual(solver.budget.snapshot("q")["counts"]["fetch"], 8)
            resumed = Solver(config, solver.store, "regression")
            self.addAsyncCleanup(resumed.close)
            resumed.web.backend.search = AsyncMock(side_effect=AssertionError("search replay"))
            resumed.web.backend.fetch = AsyncMock(side_effect=AssertionError("fetch replay"))
            result = await resumed.solve(question)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.answer, "27")
        self.assertTrue(contexts[0]["evidence"])
        self.assertEqual(resumed.budget.snapshot("q")["counts"]["fetch"], 8)
        resumed.web.backend.search.assert_not_awaited()
        resumed.web.backend.fetch.assert_not_awaited()

    async def test_retry_exhausting_fetch_cap_keeps_earlier_evidence(self):
        solver = self.solver(Config(arm="B2", limits=replace(Limits(), rounds=1, fetch=2)))
        page = await solver.web.backend.fetch("https://example.org/source", solver.policy)
        solver.web.backend.fetch = AsyncMock(
            side_effect=[page, ProviderError("temporary failure", retryable=True)]
        )
        with self.three_queries(solver, []):
            result = await solver.solve(QuestionView("q", "What is the fictional cobalt code?"))
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.answer, "27")
        self.assertEqual(solver.budget.snapshot("q")["counts"]["fetch"], 2)

    async def test_research_still_halts_at_total_call_and_dollar_caps(self):
        for config in (
            Config(arm="B2", limits=replace(Limits(), rounds=1, calls=4)),
            Config(arm="B2", fetch_usd=0.7, limits=replace(Limits(), rounds=1, item_usd=1)),
        ):
            with self.subTest(config=config):
                solver = self.solver(config)
                with self.three_queries(solver, []):
                    result = await solver.solve(
                        QuestionView("q", "What is the fictional cobalt code?")
                    )
                self.assertEqual(result.status, "budget_exceeded")
                self.assertEqual(result.answer, "")

    async def test_persistent_constraints_reject_repair_and_unchecked_initial_candidates(self):
        for constraint in ("units", "scope", "assumptions", "consistency"):
            for candidates in (1, 3):
                with self.subTest(constraint=constraint, candidates=candidates):
                    solver = self.solver(
                        Config(
                            arm="Jfull",
                            adaptive=True,
                            limits=replace(Limits(), candidates=candidates, rounds=1),
                        )
                    )
                    checker = AsyncMock(return_value=[constraint])
                    with (
                        patch("jev_solver.controller.engine.route", AsyncMock(return_value="code")),
                        patch("jev_solver.controller.engine.constraints", checker),
                    ):
                        result = await solver.solve(
                            QuestionView("q", "What is 6 * 7? Include metres.")
                        )
                    self.assertEqual(result.status, "completed")
                    self.assertEqual(result.answer, "")
                    self.assertTrue(result.abstained)
                    self.assertIn("42", result.candidate_answers)
                    self.assertEqual(checker.await_args_list[1].args[-1].id, "repair-0")
                    self.assertEqual(checker.await_count, 2 if candidates == 1 else 3)
                    rejected = [
                        json.loads(row[0])
                        for row in solver.store.db.execute(
                            "SELECT data FROM events WHERE kind='candidate_rejected'"
                        )
                    ]
                    self.assertEqual(rejected[0]["constraint_failures"], [constraint])

    async def test_repair_that_passes_constraints_is_accepted(self):
        solver = self.solver(
            Config(arm="Jfull", adaptive=True, limits=replace(Limits(), candidates=1, rounds=1))
        )
        checker = AsyncMock(side_effect=[["units"], []])
        original = MockBackbone.generate

        async def repair_units(backbone, q, context, schema):
            response = await original(backbone, q, context, schema)
            if context.get("constraint_failures"):
                candidate = json.loads(response["text"])
                candidate["answer"] = "42 m"
                response["text"] = json.dumps(candidate)
            return response

        with (
            patch("jev_solver.controller.engine.route", AsyncMock(return_value="code")),
            patch("jev_solver.controller.engine.constraints", checker),
            patch.object(MockBackbone, "generate", repair_units),
        ):
            result = await solver.solve(QuestionView("q", "What is 6 * 7? Include metres."))
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.answer, "42 m")
        self.assertEqual(checker.await_count, 2)
        self.assertEqual(checker.await_args_list[1].args[-1].answer, "42 m")


class AnalysisTests(unittest.TestCase):
    def row(self, qid, correct, **extra):
        return {
            "question_id": qid,
            "correct": correct,
            "confidence": 0.8,
            "status": "completed",
            "cost_usd": 1,
            "latency_s": 2,
            "slices": {},
            "abstained": False,
            **extra,
        }

    def test_zero_discordance_does_not_claim_zero_required_samples(self):
        rows = [self.row("a", True)]
        self.assertIsNone(paired(rows, rows)["approximate_questions_for_80pct_power"])
        with self.assertRaises(ValueError):
            paired([], [])

    def test_paired_bootstrap_and_mcnemar(self):
        a = [self.row(str(i), True) for i in range(8)]
        b = [self.row(str(i), False) for i in range(8)]
        result = paired(a, b)
        self.assertEqual(result["difference_a_minus_b"], 1)
        self.assertEqual(result["difference_ci95"], [1, 1])
        self.assertAlmostEqual(result["mcnemar_exact_p"], 2 / 256)

    def test_repeats_cluster_by_question(self):
        a = [self.row("one", True), self.row("one", False), self.row("two", True)]
        b = [self.row("one", False), self.row("one", False), self.row("two", True)]
        result = paired(a, b)
        self.assertEqual(result["questions"], 2)
        self.assertEqual(result["difference_a_minus_b"], 0.25)
        self.assertIsNone(result["mcnemar_exact_p"])
        self.assertEqual(summary(a)["accuracy"], 0.75)

    def test_paired_analysis_refuses_dropped_failures(self):
        with self.assertRaises(ValueError):
            paired([self.row("a", True)], [self.row("b", True)])

    def test_abstention_and_error_count_as_incorrect(self):
        rows = [
            self.row("a", True),
            self.row("b", False, status="timeout", confidence=0, abstained=True),
        ]
        result = summary(rows)
        self.assertEqual(result["accuracy"], 0.5)
        self.assertEqual(result["coverage"], 0.5)
        self.assertEqual(result["covered_accuracy"], 1)
        self.assertEqual(result["failure_rate"], 0.5)
        self.assertAlmostEqual(result["brier"], 0.02)

    def test_official_prompt_is_read_from_pinned_source(self):
        prompt = official_prompt()
        self.assertIn("{correct_answer}", prompt)
        self.assertIn("{question}", prompt)
        self.assertEqual(len(digest(prompt)), 64)
