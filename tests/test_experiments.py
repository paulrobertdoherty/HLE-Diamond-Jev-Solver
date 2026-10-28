import asyncio
import builtins
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from jev_solver.benchmarks.data import prepare
from jev_solver.config import Config, Limits
from jev_solver.controller.engine import Solver, run
from jev_solver.evaluation.analysis import paired, summary
from jev_solver.evaluation.components import components
from jev_solver.evaluation.export import export_report
from jev_solver.evaluation.grading import finalized_predictions, grade, official_prompt
from jev_solver.models import digest
from jev_solver.providers.backbone import MockBackbone
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
