import asyncio
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import AsyncMock

from jev_solver.config import Config, Limits, RemediationPolicy
from jev_solver.controller.budget import BudgetExceeded
from jev_solver.controller.engine import implementation_hash
from jev_solver.evaluation.manifests import freeze_manifest
from jev_solver.evaluation.orchestration import run_experiment, ExperimentBudget, ReplayGateway
from jev_solver.evaluation.offline import OfflineDispatchForbidden
from jev_solver.evaluation.replay import ControlledReplay, validate_manifest
from jev_solver.models import QuestionView
from jev_solver.tracing.store import Store


class RemediationExperimentTests(unittest.IsolatedAsyncioTestCase):
    def configs(self):
        policies = {
            k: "remediation-v1" for k in asdict(RemediationPolicy()) if k != "structural_slots"
        }
        base = replace(
            Config(arm="B2"),
            remediation=RemediationPolicy(**policies),
            limits=replace(Limits(), calls=120),
        )
        return {"B2": base, "J23": replace(base, arm="J23")}

    def manifest(self, configs, ids=("arithmetic", "reference")):
        return freeze_manifest(
            "synthetic-paired-remediation",
            configs,
            list(ids),
            baseline_revision="9a7a1aa9090960fa353ecb836f96c9da3b2b2c6a",
            historical_implementation_hash="51b6b4ab4ced7b4c9160b2f401014e6aa53c5889dd23efb84529df8ef78a6d0d",
            aggregate_usd=40,
            replications=1,
            question_views=[
                QuestionView("arithmetic", "Compute 6 * 7."),
                QuestionView("reference", "What is the synthetic cobalt code?"),
            ],
        )

    async def test_complete_engine_orchestration_shares_identical_inputs_and_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            questions = root / "questions.jsonl"
            questions.write_text(
                "\n".join(
                    json.dumps(q)
                    for q in [
                        {"id": "arithmetic", "question": "Compute 6 * 7.", "images": []},
                        {
                            "id": "reference",
                            "question": "What is the synthetic cobalt code?",
                            "images": [],
                        },
                    ]
                )
                + "\n"
            )
            configs = self.configs()
            manifest = self.manifest(configs)
            result = await run_experiment(manifest, configs, questions, root / "run")
            self.assertEqual(result["declared_trials"], 4)
            self.assertEqual(result["trial_statuses"], {"completed": 4})
            self.assertEqual(result["actual_accounted_cost_usd"], 0)
            ledger = json.loads((root / "run/replay-ledger.json").read_text())
            self.assertTrue(any(r["behavior"] == "generated_reuse" for r in ledger))
            predictions = [
                json.loads(p.read_text())[0] for p in (root / "run").glob("*/*/*/predictions.json")
            ]
            self.assertEqual(sorted(p["answer"] for p in predictions), ["27", "27", "42", "42"])
            resumed = await run_experiment(manifest, configs, questions, root / "run", resume=True)
            self.assertEqual(resumed["declared_trials"], 4)

    def test_manifest_rejects_changed_component_backend_and_spend_identity(self):
        manifest = self.manifest(self.configs())
        self.assertEqual(validate_manifest(manifest), manifest)
        for key, value in (
            ("backend", "mixed"),
            ("spend_caps", {"item_usd": 3, "run_usd": 2, "aggregate_usd": 1}),
        ):
            with self.assertRaises(ValueError):
                validate_manifest({**manifest, key: value})
        manifest["arms"][1]["changed_components"] = []
        with self.assertRaisesRegex(ValueError, "declared intervention"):
            validate_manifest(manifest)

    async def test_live_snapshot_miss_never_dispatches_without_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "events.sqlite3")
            configs = self.configs()
            config = replace(
                configs["B2"],
                provider=replace(configs["B2"].provider, kind="openrouter", model="vendor/model"),
            )
            gateway = ReplayGateway(
                config,
                store,
                ExperimentBudget(
                    store, config, store, "r:", {"run_usd": 20, "aggregate_usd": 40}, asyncio.Lock()
                ),
            )
            gateway.replay = ControlledReplay(self.manifest(configs))
            gateway.arm_id, gateway.launch, gateway.comparison = "B2", False, "integrated"
            gateway.replicate = 0
            gateway.budget.execute = AsyncMock(
                side_effect=AssertionError("Forbidden external dispatch.")
            )
            try:
                with self.assertRaises(OfflineDispatchForbidden):
                    await gateway.generate(QuestionView("q", "Compute."), {}, "initial")
                gateway.budget.execute.assert_not_awaited()
            finally:
                store.close()

    async def test_uncertain_reservations_enforce_aggregate_cap_after_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "aggregate.sqlite3"
            ledger = Store(path)
            local = Store(Path(tmp) / "trial.sqlite3")
            try:
                budget = ExperimentBudget(
                    local,
                    Config(),
                    ledger,
                    "run:",
                    {"run_usd": 1, "aggregate_usd": 0.5},
                    asyncio.Lock(),
                )
                await budget.reserve("q", "model", 0.5, final=True)
                ledger.close()
                ledger = Store(path)
                budget.ledger = ledger
                with self.assertRaises(BudgetExceeded):
                    await budget.reserve("q2", "model", 0.01, final=True)
                self.assertEqual(ledger.cost(), 0.5)
            finally:
                local.close()
                ledger.close()

    async def test_invalid_billing_retains_reservation_and_overrun_halts_all_arms(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger, local = Store(Path(tmp) / "global.sqlite3"), Store(Path(tmp) / "local.sqlite3")
            try:
                budget = ExperimentBudget(
                    local,
                    Config(),
                    ledger,
                    "r:",
                    {"run_usd": 10, "aggregate_usd": 20},
                    asyncio.Lock(),
                )
                call = await budget.reserve("q", "model", 0.2, final=True)
                with self.assertRaises(ValueError):
                    budget.settle(call, -1, {})
                self.assertEqual(ledger.cost(), 0.2)
                with self.assertRaises(BudgetExceeded):
                    budget.settle(call, 0.3, {})
                another = ExperimentBudget(
                    Store(Path(tmp) / "other.sqlite3"),
                    Config(),
                    ledger,
                    "other:",
                    {"run_usd": 10, "aggregate_usd": 20},
                    asyncio.Lock(),
                )
                try:
                    with self.assertRaises(BudgetExceeded):
                        await another.reserve("q2", "model", 0.1, final=True)
                finally:
                    another.store.close()
            finally:
                local.close()
                ledger.close()

    def test_source_identity_is_explicit_for_every_component(self):
        manifest = self.manifest(self.configs())
        self.assertEqual(manifest["arms"][0]["implementation_hash"], implementation_hash())
        for arm in manifest["arms"]:
            self.assertTrue(
                all(
                    set(v) >= {"implementation", "schema", "model", "prompt"}
                    for v in arm["components"].values()
                )
            )

    async def test_matched_paid_launch_requires_snapshots_before_any_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            q = root / "questions.jsonl"
            q.write_text(json.dumps({"id": "q", "question": "Compute 6 * 7.", "images": []}) + "\n")
            configs = self.configs()
            manifest = freeze_manifest(
                "matched-no-snapshots",
                configs,
                ["q"],
                baseline_revision="9a7a1aa",
                historical_implementation_hash="original",
                aggregate_usd=40,
                comparison_kind="matched-j23",
                question_views=[QuestionView("q", "Compute 6 * 7.")],
            )
            with self.assertRaisesRegex(ValueError, "before any paid call"):
                await run_experiment(manifest, configs, q, root / "output", launch=True)
            self.assertFalse((root / "output/experiment.sqlite3").exists())
