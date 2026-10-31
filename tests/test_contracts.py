import asyncio
import importlib.util
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from jev_solver.benchmarks.data import load_questions, prepare
from jev_solver.candidates.selection import clusters, normalize, vote
from jev_solver.config import Config, Limits, ProviderConfig, verify_protocol
from jev_solver.controller.budget import Budget, BudgetExceeded
from jev_solver.models import Candidate, QuestionView, record
from jev_solver.providers.backbone import Gateway, OpenAIBackbone, ProviderError
from jev_solver.providers.jev import Jev
from jev_solver.tracing.store import Store


class RecordTests(unittest.TestCase):
    @unittest.skipUnless(
        importlib.util.find_spec("datasets"), "optional dataset dependency not installed"
    )
    def test_auxiliary_image_columns_are_not_decoded_during_preparation(self):
        from datasets import Dataset, Image

        dataset = Dataset.from_list(
            [
                {
                    "id": str(i),
                    "question": "What is 1 + 1?",
                    "answer": "2",
                    "image": "data:image/png;base64,ORIGINAL",
                    "image_preview": {"bytes": b"not a decodable image", "path": None},
                    "rationale_image": {"bytes": b"also not decodable", "path": None},
                }
                for i in range(1000)
            ],
        )
        dataset = dataset.cast_column("image_preview", Image())
        dataset = dataset.cast_column("rationale_image", Image())
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict("os.environ", {"HF_TOKEN": "test-token"}),
            patch("datasets.load_dataset", return_value=dataset),
        ):
            root = Path(tmp)
            manifest = prepare(root, "a" * 40, dev_count=50)
            self.assertEqual(manifest["development_count"], 50)
            questions = load_questions(root / "solver/questions.jsonl")
            self.assertEqual(questions[0].images, ("data:image/png;base64,ORIGINAL",))
            self.assertEqual(set(record(questions[0])), {"id", "question", "images"})

    def test_solver_view_rejects_label_metadata(self):
        for field in ("answer", "partition", "rationale", "subject", "grading_metadata"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                QuestionView.parse({"id": "q", "question": "task", field: "secret"})

    def test_image_preserved_and_labels_separated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare(root / "data", "", Path("tests/fixtures/tasks.jsonl"), dev_count=2)
            questions = load_questions(root / "data/solver/questions.jsonl")
            self.assertEqual(len(questions), 4)
            raw = [
                json.loads(x) for x in Path("tests/fixtures/tasks.jsonl").read_text().splitlines()
            ]
            self.assertEqual(questions[-1].images, (raw[-1]["image"],))
            self.assertTrue((root / "data/evaluator/labels.jsonl").exists())
            self.assertEqual((root / "data/evaluator/labels.jsonl").stat().st_mode & 0o777, 0o600)
            for q in questions:
                self.assertEqual(set(record(q)), {"id", "question", "images"})
            split = json.loads((root / "data/solver/split.json").read_text())
            self.assertEqual(len(split["development"]), 2)
            self.assertFalse(set(split["development"]) & set(split["heldout"]))

    def test_stratified_split_is_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("a", "b"):
                prepare(root / name, "", Path("tests/fixtures/tasks.jsonl"), dev_count=2)
            self.assertEqual(
                (root / "a/solver/split.json").read_bytes(),
                (root / "b/solver/split.json").read_bytes(),
            )

    def test_duplicate_identifiers_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "questions.jsonl"
            row = '{"id":"q","question":"x"}\n'
            p.write_text(row * 2)
            with self.assertRaises(ValueError):
                load_questions(p)

    def test_malformed_candidate_confidence_rejected(self):
        base = {
            "answer": "x",
            "confidence": 0,
            "verification": "",
            "gaps": [],
            "queries": [],
            "code": "",
            "citations": [],
        }
        for value in (float("nan"), -0.1, 1.1, True, "0.5"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Candidate.parse({**base, "confidence": value}, "c")

    def test_conservative_clustering_is_consistent(self):
        answers = [" 1 m ", "1   m", "1 M", "1m", "1 m."]
        candidates = [Candidate(str(i), a, 0.9, "") for i, a in enumerate(answers)]
        self.assertEqual([len(g) for g in clusters(candidates)], [2, 1, 1, 1])
        self.assertEqual(vote(candidates).id, "0")
        self.assertNotEqual(normalize("A"), normalize("a"))
        self.assertIsNone(vote([Candidate("x", "", 0, "")]))


class ConfigTests(unittest.TestCase):
    def test_protocol_files_are_hash_pinned(self):
        self.assertEqual(len(verify_protocol("protocol/manifest.json")["upstream_commit"]), 40)

    def test_all_synthetic_configs_validate(self):
        for p in Path("configs").glob("*.synthetic.json"):
            with self.subTest(path=p):
                Config.load(p)

    def test_invalid_policies_fail_closed(self):
        cases = [
            replace(Config(), arm="B0"),
            replace(Config(), arm="B0", track="closed", selector="backbone"),
            replace(Config(), adaptive=True),
            replace(Config(), corpus="private/a"),
            replace(Config(), arm="M"),
            replace(Config(), selector="jev"),
            replace(Config(), limits=Limits(item_usd=0)),
            replace(Config(), limits=Limits(concurrency=0)),
            replace(Config(), limits=Limits(retries=-1)),
            replace(Config(), search_usd=float("nan")),
            replace(Config(), jev_failure="invent-success"),
            replace(Config(), evidence_chars=60001),
        ]
        for cfg in cases:
            with self.subTest(cfg=cfg), self.assertRaises(ValueError):
                cfg.validate()

    def test_live_templates_require_explicit_edits(self):
        with self.assertRaises(ValueError):
            Config.load("configs/live.template.json")

    def test_no_implicit_spend_caps_for_live_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.json"
            p.write_text(json.dumps({"provider": {"kind": "openai"}}))
            with self.assertRaisesRegex(ValueError, "explicit"):
                Config.load(p)


class BudgetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "events.sqlite3")
        self.config = replace(
            Config(), limits=Limits(item_usd=1, run_usd=1.1, finalization_usd=0, concurrency=4)
        )
        self.budget = Budget(self.store, self.config)

    async def asyncTearDown(self):
        self.store.close()
        self.tmp.cleanup()

    async def test_concurrent_reservations_cannot_oversubscribe_run(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def call():
            entered.set()
            await release.wait()
            return {"cost_usd": 0.4, "usage": {}}

        first = asyncio.create_task(self.budget.execute("a", "model", 0.6, call))
        await entered.wait()
        with self.assertRaises(BudgetExceeded):
            await self.budget.execute("b", "model", 0.6, call)
        release.set()
        await first
        self.assertAlmostEqual(self.store.cost(), 0.4)

    async def test_finalization_reserve(self):
        b = Budget(
            self.store,
            replace(self.config, limits=replace(self.config.limits, finalization_usd=0.3)),
        )
        with self.assertRaises(BudgetExceeded):
            await b.reserve("a", "model", 0.8)
        await b.reserve("a", "model", 0.8, final=True)

    async def test_uncertain_retry_costs_are_retained(self):
        calls = 0

        async def call():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ProviderError("temporary", retryable=True)
            return {"cost_usd": 0.1, "usage": {}}

        await self.budget.execute("a", "model", 0.2, call)
        self.assertEqual(calls, 2)
        self.assertAlmostEqual(self.store.cost(), 0.3)

    async def test_cancellation_keeps_reservation(self):
        started = asyncio.Event()

        async def call():
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(self.budget.execute("a", "model", 0.2, call))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertAlmostEqual(self.store.cost(), 0.2)
        self.assertEqual(self.budget.snapshot("a")["reserved_usd"], 0.2)

    async def test_overrun_is_recorded_and_halts(self):
        call = await self.budget.reserve("a", "model", 0.1)
        with self.assertRaises(BudgetExceeded):
            self.budget.settle(call, 1.2, {})
        with self.assertRaises(BudgetExceeded):
            await self.budget.reserve("a", "model", 0.01)
        self.assertAlmostEqual(self.store.cost(), 1.2)

    async def test_call_limits_include_failed_attempts(self):
        cfg = replace(self.config, limits=replace(self.config.limits, calls=1))
        b = Budget(self.store, cfg)
        await b.reserve("q", "model", 0)
        with self.assertRaises(BudgetExceeded):
            await b.reserve("q", "model", 0)

    async def test_invalid_cost_never_dispatches(self):
        for amount in (-1, float("nan"), float("inf")):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                await self.budget.reserve("q", "model", amount)


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "events.sqlite3")
        self.cfg = Config()
        self.budget = Budget(self.store, self.cfg)

    async def asyncTearDown(self):
        self.store.close()
        self.tmp.cleanup()

    async def test_complete_request_cache_is_item_scoped(self):
        gateway = Gateway(self.cfg, self.store, self.budget)
        q = QuestionView("a", "What is 6 * 7?")
        await gateway.generate(q, {}, "one")
        await gateway.generate(q, {}, "one")
        await gateway.generate(q, {}, "two")
        await gateway.generate(QuestionView("b", q.question), {}, "one")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM calls").fetchone()[0], 3)
        await gateway.close()

    async def test_malformed_response_still_accounts_for_usage(self):
        p = ProviderConfig(input_per_million=1, output_per_million=1)
        cfg = replace(self.cfg, provider=p)
        gateway = Gateway(cfg, self.store, Budget(self.store, cfg))
        from jev_solver.models import digest

        fake = SimpleNamespace(
            generate=AsyncMock(
                return_value={
                    "text": "not JSON",
                    "model": p.model,
                    "status": "completed",
                    "usage": {"input_tokens": 10, "output_tokens": 2},
                    "cost_usd": 0.000012,
                }
            ),
            close=AsyncMock(),
        )
        gateway.clients[digest(record(p))] = fake
        with self.assertRaises(json.JSONDecodeError):
            await gateway.generate(QuestionView("a", "question"), {}, "initial")
        self.assertAlmostEqual(self.store.cost(), 0.000012)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM cache").fetchone()[0], 0)

    async def test_openai_request_preserves_images_and_no_provider_tools(self):
        response = SimpleNamespace(
            output_text="{}",
            model="pinned-model",
            status="completed",
            usage=SimpleNamespace(model_dump=lambda: {"input_tokens": 10, "output_tokens": 2}),
        )
        client = SimpleNamespace(
            responses=SimpleNamespace(create=AsyncMock(return_value=response)), close=AsyncMock()
        )
        backbone = OpenAIBackbone(ProviderConfig(model="pinned-model"), client)
        image = "data:image/png;base64,ORIGINAL"
        await backbone.generate(QuestionView("q", "question", (image,)), {}, {"type": "object"})
        request = client.responses.create.call_args.kwargs
        self.assertFalse(request["store"])
        self.assertNotIn("tools", request)
        self.assertEqual(request["input"][0]["content"][-1]["image_url"], image)

    async def test_jev_score_scale_and_noul_no_confidence(self):
        jev = Jev(self.cfg, self.store, self.budget)
        judgments = await jev.request(
            "q",
            "J2",
            {"passage": "synthetic cobalt code"},
            {
                "relevance": {
                    "type": "score",
                    "instructions": "rate",
                    "criteria": ["a", "b", "c", "d"],
                },
                "need": {"type": "noul", "instructions": "needed?"},
            },
        )
        self.assertEqual(judgments["relevance"].value, 1)
        self.assertEqual(judgments["need"].value, 0.8)
        self.assertIsNone(judgments["need"].confidence)

    async def test_jev_outage_declared_fallback_is_not_a_judgment(self):
        cfg = replace(self.cfg, jev_failure="baseline")
        jev = Jev(cfg, self.store, Budget(self.store, cfg))
        jev._call = AsyncMock(side_effect=ProviderError("outage"))
        result = await jev.request(
            "q",
            "J3",
            {},
            {
                "s": {
                    "type": "choice",
                    "instructions": "support?",
                    "criteria": {"supported": "yes", "insufficient": "no"},
                }
            },
        )
        self.assertEqual(result, {})
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM events WHERE kind='jev_outage'").fetchone()[
                0
            ],
            1,
        )

    async def test_jev_rejects_wrong_primitive(self):
        jev = Jev(self.cfg, self.store, self.budget)
        jev._call = AsyncMock(
            return_value={
                "model": self.cfg.jev.model,
                "answers": {"n": {"type": "choice", "choice": "yes"}},
                "usage": {},
                "cost_usd": 0,
            }
        )
        with self.assertRaises(ValueError):
            await jev.request("q", "J1", {}, {"n": {"type": "noul", "instructions": "yes?"}})

    @unittest.skipUnless(importlib.util.find_spec("typesafe_sdk"), "optional SDK not installed")
    async def test_typesafe_sdk_contract_and_close(self):
        from typesafe_sdk import Score

        cfg = replace(
            self.cfg,
            jev=ProviderConfig(kind="typesafe", model="jev-1.14.0", input_per_million=0.042),
        )
        response = SimpleNamespace(
            model_dump=lambda: {
                "model": "jev-1.14.0",
                "answers": {"r": {"type": "score", "score": 1.5, "confidence": 0.7}},
                "usage": {"input_tokens": 10, "output_tokens": 1},
            }
        )
        client = SimpleNamespace(system_one=AsyncMock(return_value=response), aclose=AsyncMock())
        jev = Jev(cfg, self.store, Budget(self.store, cfg), client=client)
        result = await jev.request(
            "q",
            "J2",
            {},
            {"r": {"type": "score", "instructions": "rate", "criteria": ["a", "b", "c", "d"]}},
        )
        self.assertEqual(result["r"].value, 0.5)
        self.assertIsInstance(client.system_one.call_args.kwargs["questions"]["r"], Score)
        await jev.close()
        client.aclose.assert_awaited_once()
