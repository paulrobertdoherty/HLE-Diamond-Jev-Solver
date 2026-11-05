"""T01–T05 synthetic contracts. Historical reproduction is in the private adapter."""

import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from jev_solver.candidates.selection import select, selection_references
from jev_solver.config import Config, Limits
from jev_solver.controller.engine import Solver
from jev_solver.evaluation.offline import OfflineDispatchForbidden, offline_dispatch_guard
from jev_solver.judgments.pipeline import exact_citation
from jev_solver.judgments.verification import parse_audit
from jev_solver.models import (
    Candidate,
    Citation,
    Dependency,
    Judgment,
    QuestionView,
    digest,
    record,
)
from jev_solver.providers.backbone import CANDIDATE_SCHEMA, ProviderError, input_envelope
from jev_solver.retrieval.evidence import chunk_page, rank_leads

from test_verification_contract import audit_result, passage


class EvidenceV3Regressions(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.serial = 0
        self.guard = offline_dispatch_guard()
        self.attempts = self.guard.__enter__()
        self.addCleanup(self.guard.__exit__, None, None, None)

    def solver(self, **kwargs):
        from jev_solver.tracing.store import Store

        self.serial += 1
        store = Store(self.root / f"{self.serial}.sqlite3")
        self.addCleanup(store.close)
        solver = Solver(Config(**kwargs), store, "v3-contract")
        self.addAsyncCleanup(solver.close)
        return solver

    def draft(self, quote="Café Δ is blue.", **changes):
        citation = Citation("The fictional symbol is blue.", "p", quote, 0, len(quote), True)
        return Candidate(
            "draft",
            "blue",
            0.8,
            "Reference check.",
            citations=(citation,),
            source_claims=(citation.claim,),
            **changes,
        )

    async def test_t01_span_boundary_rejects_wrong_absent_and_unknown_quotes(self):
        p = passage(text="Prefix. Café Δ is blue. Suffix.")
        solver = self.solver()
        dep = Dependency(
            "d1",
            "factual",
            "The fictional symbol is blue.",
            True,
            basis="Checked the source.",
            passage_ids=("p",),
        )
        solver.gateway.generate = AsyncMock(side_effect=lambda *args, **kwargs: audit_result(dep))
        solver.jev.request = AsyncMock(
            return_value={"support": Judgment("J3", "support", "supported", 0.9, "fixture")}
        )
        for change in ({}, {"quote": "absent", "end": 6}, {"passage_id": "foreign"}):
            draft = self.draft()
            draft = replace(draft, citations=(replace(draft.citations[0], **change),))
            assessment = await solver.assess(QuestionView("q", "Which color?"), draft, [p])
            self.assertEqual(assessment["coverage"]["status"], "passed")
            self.assertFalse(assessment["eligible"])
            self.assertEqual(assessment["citation_checks"][0]["support"], "fabricated_span")

    def test_t01_nonascii_repeated_text_and_changed_source_identity(self):
        draft = self.draft()
        p = passage(text="xx Café Δ is blue. Café Δ is blue.")
        start = p.text.index(draft.citations[0].quote)
        valid = replace(
            draft,
            citations=(
                replace(draft.citations[0], start=start, end=start + len(draft.citations[0].quote)),
            ),
        )
        self.assertTrue(exact_citation(valid, [p])[0]["valid_span"])
        self.assertFalse(exact_citation(draft, [p])[0]["valid_span"])
        old = chunk_page(
            {
                "url": p.url,
                "source_hash": digest(p.text),
                "text": p.text,
                "filter_version": "fixture",
            },
            "color",
        )[0]
        new = chunk_page(
            {
                "url": p.url,
                "source_hash": digest(p.text + " changed"),
                "text": p.text + " changed",
                "filter_version": "fixture",
            },
            "color",
        )[0]
        cited = replace(valid, citations=(replace(valid.citations[0], passage_id=old.id),))
        self.assertFalse(exact_citation(cited, [new])[0]["valid_span"])

    async def test_t01_one_bounded_repair_rechecks_critical_semantic_support(self):
        for support, expected in (("supported", "blue"), ("contradicted", "")):
            solver = self.solver(limits=replace(Limits(), rounds=1))
            p = passage(text="Prefix. Café Δ is blue.")
            bad = self.draft()
            start = p.text.index(bad.citations[0].quote)
            good = replace(
                bad, citations=(replace(bad.citations[0], start=start, end=len(p.text)),)
            )
            dep = Dependency(
                "d1",
                "factual",
                bad.source_claims[0],
                True,
                basis="Checked source.",
                passage_ids=("p",),
            )
            phases = []

            async def generate(
                q, context, phase, phases=phases, dep=dep, good=good, bad=bad, **kwargs
            ):
                phases.append(phase)
                if phase.startswith("audit-"):
                    return audit_result(dep)
                if phase == "selection":
                    return {
                        "selected": next(iter(context["candidates"])),
                        "reason": "Checked critical support.",
                        "checked_dependencies": ["d1"],
                    }
                value = record(good if phase.startswith("repair-") else bad)
                value.pop("id")
                return json.loads(json.dumps(value))

            solver.gateway.generate = AsyncMock(side_effect=generate)
            solver.research = AsyncMock(return_value=[p])
            solver.jev.request = AsyncMock(
                return_value={"support": Judgment("J3", "support", support, 0.9, "fixture")}
            )
            prediction = await solver.solve(QuestionView("q", "Which color?"))
            self.assertEqual(prediction.answer, expected)
            self.assertEqual(sum(phase.startswith("repair-") for phase in phases), 1)
            self.assertTrue(
                any(
                    call.args[2].get("quote") == good.citations[0].quote
                    for call in solver.jev.request.await_args_list
                )
            )

    async def selection(self, refs, *, dependencies=None, eligible=True, choice="candidate_0"):
        solver = self.solver(arm="B2")
        candidate = Candidate("c", "42", 0.9, "6 * 7 = 42.")
        checks = {
            "eligible": eligible,
            "dependencies": dependencies or [{"id": "d1", "critical": True, "status": "passed"}],
        }
        solver.gateway.generate = AsyncMock(
            return_value={
                "selected": choice,
                "reason": "Completed checks.",
                "checked_dependencies": refs,
            }
        )
        return await select(
            solver.jev,
            solver.gateway,
            QuestionView("q", "Compute."),
            [candidate],
            "backbone",
            17,
            assessments={"c": checks},
        )

    async def test_t02_bare_and_qualified_selected_candidate_ids_recover(self):
        for refs in (["d1"], ["candidate_0.d1"], ["candidate_0:d1"]):
            self.assertEqual((await self.selection(refs)).id, "c")

    async def test_t02_missing_foreign_invented_unrun_and_abstention_references_fail(self):
        for refs, reason in (
            ([], "missing critical"),
            (["candidate_1:d1"], "unknown, unpassed"),
            (["invented"], "unknown, unpassed"),
        ):
            with self.subTest(refs=refs), self.assertRaisesRegex(ValueError, reason):
                await self.selection(refs)
        with self.assertRaisesRegex(ValueError, "unknown, unpassed"):
            await self.selection(
                ["d1"], dependencies=[{"id": "d1", "critical": True, "status": "not_run"}]
            )
        with self.assertRaisesRegex(ValueError, "ineligible"):
            await self.selection(["d1"], eligible=False)
        with self.assertRaisesRegex(ValueError, "abstention cannot cite"):
            await self.selection(["d1"], choice="none-supported")

    async def test_t02_overlapping_ids_stay_scoped_to_selected_candidate(self):
        solver = self.solver(arm="B2")
        candidates = [Candidate(i, i, 0.9, "Checked.") for i in ("a", "b")]
        checks = {
            i: {
                "eligible": True,
                "dependencies": [{"id": "d1", "critical": True, "status": "passed"}],
            }
            for i in ("a", "b")
        }

        async def response(q, context, phase, **kwargs):
            return {
                "selected": "candidate_0",
                "reason": "Checked.",
                "checked_dependencies": ["candidate_1:d1"],
            }

        solver.gateway.generate = AsyncMock(side_effect=response)
        with self.assertRaisesRegex(ValueError, "foreign candidate"):
            await select(
                solver.jev,
                solver.gateway,
                QuestionView("q", "Compute."),
                candidates,
                "backbone",
                17,
                assessments=checks,
            )

    def test_t02_ambiguous_qualification_cannot_choose_between_two_passed_ids(self):
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            selection_references(
                ["candidate_0.d1"], "candidate_0", ["candidate_0"], {"d1", "candidate_0.d1"}
            )

    async def test_t03_conservative_guard_counts_schema_system_images_and_outcomes(self):
        for size in (65535, 65536, 65537, 66969, 74274, 72977):
            solver = self.solver()
            provider = replace(
                solver.config.provider, max_input_tokens=65536, image_token_reserve=1000
            )
            solver.config = replace(solver.config, provider=provider)
            solver.gateway.config = solver.config
            q = QuestionView("q", "Review Δ.", ("data:image/png;base64,original",))
            context = {"research_outcomes": [""], "evidence": "required"}
            padding = size - input_envelope(q, context, CANDIDATE_SCHEMA, provider)
            self.assertGreater(padding, 0)
            context["research_outcomes"][0] = "x" * padding
            self.assertEqual(input_envelope(q, context, CANDIDATE_SCHEMA, provider), size)
            solver.gateway.clients[digest(asdict(provider))] = SimpleNamespace(close=AsyncMock())
            solver.gateway.budget.execute = AsyncMock(
                return_value={"model": provider.model, "status": "completed", "text": "{}"}
            )
            if size > 65536:
                with self.assertRaisesRegex(ValueError, f"{size} > 65536"):
                    await solver.gateway.generate(q, context, "revision")
                solver.gateway.budget.execute.assert_not_awaited()
            else:
                self.assertEqual(await solver.gateway.generate(q, context, "revision"), {})

    async def test_t03_incomplete_and_invalid_structured_output_are_never_cached(self):
        solver = self.solver()
        p = solver.config.provider
        q = QuestionView("q", "Compute.")
        solver.gateway.clients[digest(asdict(p))] = SimpleNamespace(close=AsyncMock())
        for response, error in (
            (
                {"status": "incomplete", "text": '{"answer":"42"', "finish_reason": "length"},
                ProviderError,
            ),
            ({"status": "completed", "text": "not json"}, json.JSONDecodeError),
            ({"status": "completed", "text": "[]"}, ValueError),
        ):
            solver.budget.execute = AsyncMock(return_value={"model": p.model, **response})
            with self.assertRaises(error):
                await solver.gateway.generate(q, {}, "initial")
            self.assertEqual(solver.store.db.execute("SELECT COUNT(*) FROM cache").fetchone()[0], 0)
        raw = record(self.draft())
        raw.pop("id")
        raw = json.loads(json.dumps(raw))
        raw["citations"][0].update(start=0, end=0)
        with self.assertRaisesRegex(ValueError, "invalid citation"):
            Candidate.parse(raw, "invalid")

    def cache_search(self, solver, query, results):
        key = digest(
            {
                "tool": "web_search",
                "query": query,
                "question": digest("Find the code."),
                "filter": solver.policy.version,
                "config": solver.config.hash,
            }
        )
        solver.store.cache("q", key, {"results": results})

    def cache_page(self, solver, url, text, destination=None):
        key = digest(
            {
                "tool": "web_fetch",
                "url": url,
                "filter": solver.policy.version,
                "parser": solver.config.parser_version,
                "config": solver.config.hash,
            }
        )
        solver.store.cache(
            "q",
            key,
            {
                "page": {
                    "url": destination or url,
                    "title": "Reference",
                    "text": text,
                    "redirects": [destination] if destination else [],
                }
            },
        )

    async def test_t04_requested_unused_lead_uses_last_fetch_without_repeating_search(self):
        solver = self.solver(arm="B2", limits=replace(Limits(), rounds=2, search=2, fetch=4))
        target = "https://reference.example.org/intended"
        distractors = [
            {
                "url": f"https://reference.example.org/{i}",
                "title": "cobalt code",
                "snippet": "cobalt code",
            }
            for i in range(4)
        ]
        intended = {"url": target, "title": "Primary paper", "snippet": "Name catalog"}
        self.assertEqual(rank_leads(distractors + [intended], "cobalt code").index(intended), 4)
        self.assertEqual(rank_leads(distractors[:2] + [intended], "cobalt code").index(intended), 2)
        solver.research_outcomes["q"] = [
            {
                "round": 0,
                "search_attempts": 1,
                "fetch_attempts": 3,
                "searches": [{"query": "catalog"}],
                "fetches": [{"url": d["url"]} for d in distractors[:3]],
                "leads": distractors + [intended],
            }
        ]
        solver.round_numbers["q"] = 1
        solver.plans["q"] = [
            {
                "dependency_id": "d",
                "missing_fact": "cobalt code",
                "query": "follow-up catalog query",
                "fetch_urls": [target],
            }
        ]
        self.cache_page(solver, target, "The synthetic cobalt code is 27.")
        packet = await solver.research(
            QuestionView("q", "Find the code."), Candidate("c", "", 0.1, "Pending.")
        )
        self.assertTrue(packet)
        outcome = solver.research_outcomes["q"][-1]
        self.assertEqual(outcome["search_attempts"], 0)
        self.assertEqual(outcome["fetch_attempts"], 1)
        self.assertEqual(outcome["fetches"][0]["url"], target)
        self.assertTrue(outcome["fetches"][0]["requested"])
        self.assertTrue(outcome["retained_sources"])

    async def test_t04_unknown_and_blocked_fetch_actions_cannot_dispatch(self):
        solver = self.solver(arm="B2", limits=replace(Limits(), rounds=2, search=1, fetch=4))
        blocked = "https://huggingface.co/blocked"
        unknown = "https://reference.example.org/invented"
        solver.research_outcomes["q"] = [
            {
                "round": 0,
                "search_attempts": 1,
                "fetch_attempts": 3,
                "searches": [{"query": "catalog"}],
                "fetches": [],
                "leads": [
                    {"url": blocked, "title": "Code", "snippet": "blocked", "status": "not_fetched"}
                ],
            }
        ]
        solver.round_numbers["q"] = 1
        solver.plans["q"] = [
            {
                "dependency_id": "d",
                "missing_fact": "code",
                "query": "follow-up",
                "fetch_urls": [blocked, unknown],
            }
        ]
        result = await solver.research(
            QuestionView("q", "Find the code."), Candidate("c", "", 0.1, "Pending.")
        )
        self.assertEqual(result, [])
        self.assertEqual(solver.research_outcomes["q"][-1]["fetch_attempts"], 0)
        self.assertEqual(
            solver.store.db.execute(
                "SELECT COUNT(*) FROM events WHERE kind='fetch_action_rejected'"
            ).fetchone()[0],
            2,
        )

    def test_t04_structured_fetch_actions_validate_shape_and_bounds(self):
        dep = Dependency("d", "derived", "Six times seven is 42.", True, basis="6 * 7.")
        for urls in ("https://example.org", ["x"] * 5, [None]):
            raw = audit_result(
                dep,
                queries=[
                    {
                        "dependency_id": "d",
                        "missing_fact": "Fact",
                        "query": "catalog",
                        "fetch_urls": urls,
                    }
                ],
            )
            with self.assertRaisesRegex(ValueError, "verification query"):
                parse_audit(raw)

    async def test_t04_duplicates_blocks_redirects_and_failed_fetches_remain_visible(self):
        solver = self.solver(arm="B2", limits=replace(Limits(), rounds=2, search=2, fetch=4))
        base = "https://reference.example.org"
        results = [
            {"url": base + path, "title": "cobalt code", "snippet": "The code is 99."}
            for path in ("/failed", "/redirect", "/redirect", "/unused")
        ]
        results.insert(
            0,
            {"url": "https://huggingface.co/blocked", "title": "cobalt code", "snippet": "answer"},
        )
        self.cache_search(solver, "catalog", results)
        self.cache_page(solver, base + "/redirect", "Generic home page.", base + "/home")
        self.cache_page(solver, base + "/unused", "General navigation.")
        original = solver.web.fetch

        async def fetch(item, url, **kwargs):
            if url.endswith("/failed"):
                raise ProviderError("frozen fetch failure")
            return await original(item, url, **kwargs)

        solver.web.fetch = AsyncMock(side_effect=fetch)
        solver.plans["q"] = [
            {"dependency_id": "d", "missing_fact": "cobalt code", "query": "catalog"}
        ]
        packet = await solver.research(
            QuestionView("q", "Find the code."), Candidate("c", "", 0.1, "Pending.")
        )
        outcome = solver.research_outcomes["q"][0]
        self.assertEqual(packet, [])
        self.assertEqual(outcome["reserved_followup_fetches"], 1)
        self.assertEqual(outcome["fetch_attempts"], 3)
        self.assertEqual(
            [f["status"] for f in outcome["fetches"]], ["unavailable", "fetched", "fetched"]
        )
        self.assertEqual(outcome["fetches"][1]["destination"], base + "/home")
        self.assertEqual(solver.web.fetch.await_count, 3)

    async def test_t05_gap_mapping_requires_exact_complete_indices_even_with_no_gaps(self):
        dep = Dependency("d", "derived", "Six times seven is 42.", True, basis="6 * 7 = 42.")
        gap = {
            "gap_index": 0,
            "critical": True,
            "dependency_ids": ["d"],
            "reason": "Check the product.",
        }
        for gaps, mappings in (
            ((), [gap]),
            (("Check",), []),
            (("Check",), [gap, gap]),
            (("Check",), [{**gap, "gap_index": 1}]),
        ):
            solver = self.solver(arm="B2")
            solver.gateway.generate = AsyncMock(
                return_value=audit_result(dep, gap_assessments=mappings)
            )
            result = await solver.assess(
                QuestionView("q", "Compute."), Candidate("c", "42", 0.9, "Checked.", gaps=gaps), []
            )
            self.assertFalse(result["eligible"])
            self.assertEqual(result["completeness"]["status"], "failed")

    async def test_t05_all_check_states_and_incidental_gap(self):
        dep = Dependency("d", "derived", "Six times seven is 42.", True, basis="6 * 7 = 42.")
        for status in ("not_run", "not_applicable", "unavailable", "passed", "failed"):
            solver = self.solver(arm="B2")
            solver.gateway.generate = AsyncMock(
                return_value=audit_result(
                    dep,
                    status,
                    gap_assessments=[
                        {
                            "gap_index": 0,
                            "critical": False,
                            "dependency_ids": [],
                            "reason": "Historical context is incidental.",
                        }
                    ],
                )
            )
            result = await solver.assess(
                QuestionView("q", "Compute."),
                Candidate("c", "42", 0.9, "Checked.", gaps=("History?",)),
                [],
            )
            self.assertEqual(result["dependencies"][0]["status"], status)
            self.assertEqual(result["eligible"], status == "passed")

    async def test_t05_stable_identity_accepts_paraphrase_without_merging_distinct_premises(self):
        original = Dependency(
            "d1",
            "factual",
            "The fictional code is blue.",
            True,
            basis="Source.",
            passage_ids=("p",),
        )
        paraphrase = replace(original, statement="Blue is the fictional code.")
        for same_id, expected in ((True, True), (False, False)):
            solver = self.solver(arm="B2")
            audited = paraphrase if same_id else replace(paraphrase, id="distinct")
            solver.gateway.generate = AsyncMock(return_value=audit_result(audited))
            citation = Citation(
                original.statement, "p", original.statement, 0, len(original.statement), True
            )
            candidate = Candidate(
                "c",
                "blue",
                0.8,
                "Source check.",
                dependencies=(original,),
                source_claims=(original.statement,),
                citations=(citation,),
            )
            result = await solver.assess(
                QuestionView("q", "Find the code."), candidate, [passage(text=original.statement)]
            )
            self.assertEqual(result["eligible"], expected)
            self.assertEqual(len(result["dependencies"]), 1 if same_id else 2)


class OfflineGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_uncached_dispatch_cannot_be_converted_to_a_solver_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            from jev_solver.tracing.store import Store

            store = Store(Path(tmp) / "events.sqlite3")
            solver = Solver(Config(), store, "offline")
            try:
                with self.assertRaises(OfflineDispatchForbidden), offline_dispatch_guard():
                    await solver.solve(QuestionView("q", "Compute."))
            finally:
                await solver.close()
                store.close()
