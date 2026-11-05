import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from jev_solver.config import Config, RemediationPolicy
from jev_solver.controller.budget import Budget
from jev_solver.models import QuestionView, digest
from jev_solver.providers.backbone import Gateway, ProviderError, CANDIDATE_SCHEMA, input_envelope
from jev_solver.providers.context import build_context
from jev_solver.tracing.store import Store


class ContextRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def gateway(self, **policies):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Store(Path(tmp.name) / "events.sqlite3")
        self.addCleanup(store.close)
        config = replace(Config(), remediation=RemediationPolicy(**policies))
        gateway = Gateway(config, store, Budget(store, config))
        gateway.clients[digest(asdict(config.provider))] = SimpleNamespace(close=AsyncMock())
        return gateway

    def output(self, **changes):
        data = dict(
            answer="42",
            confidence=0.8,
            verification="6 * 7.",
            gaps=[],
            queries=[],
            code="",
            citations=[],
            source_claims=[],
            dependencies=[],
        )
        data.update(changes)
        return dict(model="synthetic-v1", status="completed", text=json.dumps(data))

    def test_compaction_keeps_images_evidence_candidate_and_critical_checks(self):
        q = QuestionView("q", "Compute.", ("data:image/png;base64,original",))
        gateway = self.gateway(context="remediation-v1")
        evidence = {"id": "p", "source_hash": "s", "text": "Contradictory evidence."}
        context = {
            "evidence": [evidence, evidence],
            "previous": {"answer": "42"},
            "dependency_checks": {"critical": "unresolved"},
            "history": "x" * 8000,
        }

        def bound(c):
            return input_envelope(q, c, CANDIDATE_SCHEMA, gateway.config.provider)

        compacted, report = build_context(context, bound, bound(context) - 7000)
        self.assertEqual(compacted["evidence"], [evidence])
        self.assertEqual(compacted["previous"], context["previous"])
        self.assertEqual(compacted["dependency_checks"], context["dependency_checks"])
        self.assertEqual(report["coverage"], "complete")
        self.assertEqual(q.images[0], "data:image/png;base64,original")

    async def test_compactable_dispatch_and_irreducible_rejection(self):
        gateway = self.gateway(context="remediation-v1", generation="remediation-v1")
        gateway.budget.execute = AsyncMock(return_value=self.output())
        await gateway.generate(QuestionView("q", "Compute."), {"history": "x" * 80000}, "revise")
        self.assertEqual(gateway.budget.execute.await_count, 1)
        with self.assertRaisesRegex(ValueError, "envelope"):
            await gateway.generate(QuestionView("large", "x" * 80000), {}, "initial")
        self.assertEqual(gateway.budget.execute.await_count, 1)

    async def test_truncated_then_complete_is_fully_validated_and_resume_reuses_attempt(self):
        gateway = self.gateway(generation="remediation-v1")
        gateway.budget.execute = AsyncMock(
            side_effect=[
                {
                    "model": "synthetic-v1",
                    "status": "incomplete",
                    "finish_reason": "length",
                    "text": '{"answer":',
                },
                self.output(),
            ]
        )
        q = QuestionView("q", "Compute.")
        self.assertEqual((await gateway.generate(q, {}, "initial"))["answer"], "42")
        self.assertEqual((await gateway.generate(q, {}, "initial"))["answer"], "42")
        self.assertEqual(gateway.budget.execute.await_count, 2)
        self.assertFalse(gateway.store.allowance("q", "format_regeneration", "new-revision"))

    async def test_malformed_citations_never_enter_success_cache(self):
        gateway = self.gateway(generation="remediation-v1")
        response = self.output(
            citations=[
                dict(claim="claim", passage_id="p", quote="q", start=0, end=0, critical=True)
            ]
        )
        gateway.budget.execute = AsyncMock(return_value=response)
        with self.assertRaises(ProviderError):
            await gateway.generate(QuestionView("q", "Compute."), {}, "initial")
        self.assertEqual(gateway.budget.execute.await_count, 2)
        self.assertEqual(gateway.store.db.execute("SELECT COUNT(*) FROM cache").fetchone()[0], 0)
        with self.assertRaises(ProviderError):
            await gateway.generate(QuestionView("q", "Compute."), {}, "revision")
        self.assertEqual(gateway.budget.execute.await_count, 3)

    async def test_refusal_and_model_mismatch_do_not_regenerate(self):
        for change in ({"status": "refused"}, {"model": "different"}):
            gateway = self.gateway(generation="remediation-v1")
            gateway.budget.execute = AsyncMock(return_value={**self.output(), **change})
            with self.assertRaises(ProviderError):
                await gateway.generate(QuestionView("q", "Compute."), {}, "initial")
            self.assertEqual(gateway.budget.execute.await_count, 1)
