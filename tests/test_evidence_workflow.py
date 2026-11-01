"""Regression cases for the coverage loss observed in the development pilot."""

import asyncio
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from jev_solver.config import Config, Limits
from jev_solver.controller.engine import Solver
from jev_solver.judgments.pipeline import missing_source_claims, rerank
from jev_solver.models import Candidate, Citation, EvidencePassage, Judgment, QuestionView
from jev_solver.providers.backbone import MockBackbone, ProviderError
from jev_solver.retrieval.evidence import diverse_packet, retrieval_shortlist
from jev_solver.tracing.store import Store


QUOTE = "The synthetic cobalt code is 27."


def response(answer, **changes):
    return {
        "answer": answer,
        "confidence": 0.8 if answer else 0.1,
        "verification": "Independent calculation." if answer else "Unable to establish an answer.",
        "queries": [],
        "gaps": [],
        "code": "",
        "citations": [],
        "source_claims": [],
        "dependencies": [],
        **changes,
    }


def grounded(context):
    passage = next(p for p in context["evidence"] if QUOTE in p["text"])
    start = passage["text"].index(QUOTE)
    return response(
        "27",
        verification="The original reference supplies the missing fact.",
        source_claims=[QUOTE],
        citations=[
            {
                "claim": QUOTE,
                "passage_id": passage["id"],
                "quote": QUOTE,
                "start": start,
                "end": start + len(QUOTE),
                "critical": True,
            }
        ],
    )


def passage(identifier, text, query="cobalt code", url="https://reference.example.org/source"):
    return EvidencePassage(
        identifier, url, "source-hash", text, 0, len(text), "fixture", "fixture", subquestion=query
    )


class EvidencePolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_irrelevant_and_background_jev_levels_are_not_answer_evidence(self):
        for score in (0, 1 / 3):
            jev = SimpleNamespace(
                request=AsyncMock(
                    return_value={
                        "relevance": Judgment("J2", "relevance", score, 0.99, "fixture"),
                    }
                )
            )
            self.assertEqual(await rerank(jev, "q", [passage("p", QUOTE)]), [])
        jev.request.return_value["relevance"] = Judgment("J2", "relevance", 2 / 3, 0.5, "fixture")
        self.assertEqual(len(await rerank(jev, "q", [passage("p", QUOTE)])), 1)

    async def test_rerank_outage_uses_lexical_policy_without_inventing_relevance(self):
        jev = SimpleNamespace(request=AsyncMock(return_value={}))
        result = await rerank(jev, "q", [passage("good", QUOTE), passage("bad", "Tree roots.")])
        self.assertEqual([p.id for p in result], ["good"])
        self.assertIsNone(result[0].confidence)

    def test_shortlist_and_packet_cover_queries_and_sources_before_more_chunks(self):
        passages = [passage(str(i), "cobalt code " * 10) for i in range(30)]
        # A lexical bottleneck used to discard this semantically useful source
        # before Jev could see it. A second query also gets representation.
        passages.extend(
            [
                passage(
                    "other-source", "Atomic number reference.", url="https://other.example.org/a"
                ),
                passage("other-query", "Nickel code reference.", query="nickel code"),
            ]
        )
        shortlist = retrieval_shortlist(passages)
        self.assertEqual(len(shortlist), 20)
        self.assertTrue({"other-source", "other-query"} <= {p.id for p in shortlist})
        packet = diverse_packet(shortlist, 18000)
        self.assertEqual({p.subquestion for p in packet}, {"cobalt code", "nickel code"})

    def test_citation_requirements_follow_explicit_source_dependencies(self):
        independent = Candidate("c", "42", 0.8, "Arithmetic.")
        self.assertEqual(missing_source_claims(independent), [])
        dependent = replace(independent, source_claims=(QUOTE, "Another critical fact."))
        self.assertEqual(missing_source_claims(dependent), list(dependent.source_claims))
        citation = Citation(QUOTE, "p", QUOTE, 0, len(QUOTE), True)
        self.assertEqual(
            missing_source_claims(replace(dependent, citations=(citation,))),
            ["Another critical fact."],
        )
        self.assertEqual(
            missing_source_claims(
                replace(dependent, citations=(replace(citation, critical=False),))
            ),
            list(dependent.source_claims),
        )

    def test_source_dependency_schema_is_required_and_validated(self):
        for claims in (None, "claim", [""], ["   "], [42]):
            with self.subTest(claims=claims), self.assertRaises(ValueError):
                Candidate.parse(response("27", source_claims=claims), "c")
        missing = response("27")
        del missing["source_claims"]
        with self.assertRaises(ValueError):
            Candidate.parse(missing, "c")


class EvidenceWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.count = 0

    def solver(self, backend="brave", arm="J23", **changes):
        self.count += 1
        config = Config(
            arm=arm,
            search_backend=backend,
            search_usd=0.005,
            limits=replace(Limits(), rounds=1, search=2, fetch=4, retries=0),
        )
        config = replace(config, **changes).validate()
        store = Store(self.root / f"{self.count}.sqlite3")
        self.addCleanup(store.close)
        solver = Solver(config, store, "evidence-regression")
        self.addAsyncCleanup(solver.close)
        solver.web.backend.search = AsyncMock(
            return_value=[
                {
                    "url": "https://reference.example.org/source",
                    "title": "Reference",
                    "snippet": QUOTE,
                }
            ]
        )
        solver.web.backend.fetch = AsyncMock(
            side_effect=lambda url, policy: {
                "url": url,
                "title": "Reference",
                "text": QUOTE,
                "redirects": [],
            }
        )
        return solver

    def model(self, initial, revisions, chosen):
        original = MockBackbone.generate
        steps = iter(revisions)
        contexts, selections = [], []

        async def generate(backbone, question, context, schema):
            result = await original(backbone, question, context, schema)
            if "completeness" in schema.get("properties", {}):
                return result
            if "selected" in schema.get("properties", {}):
                selections.append(context)
                answer = chosen(context) if callable(chosen) else chosen
                name = next(
                    (k for k, c in context["candidates"].items() if c["answer"] == answer),
                    "none-supported",
                )
                data = {
                    "selected": name,
                    "reason": "Fixture choice using checked premises.",
                    "checked_dependencies": [
                        d["id"]
                        for d in context["candidates"]
                        .get(name, {})
                        .get("checks", {})
                        .get("dependencies", [])
                        if d["critical"]
                    ],
                }
            elif "previous" in context:
                contexts.append(context)
                step = next(steps)
                data = step(context) if callable(step) else step
            else:
                data = initial
            result["text"] = json.dumps(data)
            return result

        return patch.object(MockBackbone, "generate", generate), contexts, selections

    def events(self, solver, kind):
        return [
            json.loads(row[0])
            for row in solver.store.db.execute(
                "SELECT data FROM events WHERE kind=? ORDER BY rowid",
                (kind,),
            )
        ]

    async def test_independent_answer_needs_no_citation_even_with_relevant_passages(self):
        for backend in ("brave", "perplexity"):
            with self.subTest(backend=backend):
                solver = self.solver(backend)
                script, contexts, selections = self.model(
                    response("42", queries=["cobalt code"]),
                    [response("42")],
                    "42",
                )
                with script:
                    result = await solver.solve(QuestionView("q", "Compute 6 * 7."))
                self.assertEqual((result.status, result.answer), ("completed", "42"))
                self.assertTrue(contexts[0]["evidence"])
                self.assertEqual(len(contexts), 1)  # No blanket citation repair.
                self.assertEqual(len(selections), 1)
                self.assertFalse(self.events(solver, "candidate_rejected"))

    async def test_new_factual_evidence_can_replace_a_confident_wrong_answer(self):
        for backend in ("brave", "perplexity"):
            for arm in ("B2", "J23"):
                with self.subTest(backend=backend, arm=arm):
                    solver = self.solver(backend, arm)
                    script, contexts, selections = self.model(
                        response("28", confidence=0.99, queries=["cobalt code"]),
                        [grounded],
                        "27",
                    )
                    with script:
                        result = await solver.solve(
                            QuestionView("q", "Find the fictional element value.")
                        )
                    self.assertEqual((result.status, result.answer), ("completed", "27"))
                    self.assertEqual(result.candidate_answers, ("28", "27"))
                    self.assertEqual(
                        {c["answer"] for c in selections[0]["candidates"].values()}, {"27"}
                    )
                    self.assertIn(QUOTE, selections[0]["evidence"][0]["text"])
                    supported = next(
                        c for c in selections[0]["candidates"].values() if c["answer"] == "27"
                    )
                    self.assertTrue(supported["checks"]["accepted"])
                    self.assertEqual(
                        supported["citations"][0]["source"]["url"],
                        "https://reference.example.org/source",
                    )
                    if arm == "J23":
                        self.assertEqual(
                            supported["checks"]["citation_checks"][0]["support"], "supported"
                        )
                    self.assertTrue(
                        all("confidence" not in c for c in selections[0]["candidates"].values())
                    )
                    self.assertEqual(solver.budget.snapshot("q")["counts"]["model"], 6)

    async def test_missing_source_claims_reject_drafts_without_erasing_an_earlier_answer(self):
        for backend in ("brave", "perplexity"):
            with self.subTest(backend=backend):
                solver = self.solver(backend)
                invalid = response("43", source_claims=[QUOTE])
                script, contexts, selections = self.model(
                    response("42", queries=["cobalt code"]),
                    [invalid, invalid],
                    "42",
                )
                with script:
                    result = await solver.solve(QuestionView("q", "Compute 6 * 7."))
                self.assertEqual((result.status, result.answer), ("completed", "42"))
                self.assertEqual(contexts[1]["missing_source_claims"], [QUOTE])
                self.assertEqual(
                    [c["answer"] for c in selections[0]["candidates"].values()], ["42"]
                )
                self.assertEqual(len(self.events(solver, "candidate_rejected")), 2)
                self.assertIn(
                    "43", result.candidate_answers
                )  # Available only to offline oracle grading.

    async def test_search_outage_and_abstaining_revision_allow_evidence_aware_recovery(self):
        for backend in ("brave", "perplexity"):
            with self.subTest(backend=backend):
                solver = self.solver(backend)
                solver.web.backend.search.side_effect = ProviderError("Search unavailable")
                script, _, selections = self.model(
                    response("42", queries=["cobalt code"]),
                    [response("")],
                    "42",
                )
                with script:
                    result = await solver.solve(QuestionView("q", "Compute 6 * 7."))
                self.assertEqual((result.status, result.answer), ("completed", "42"))
                self.assertEqual(selections[0]["evidence"], [])
                self.assertTrue(self.events(solver, "search_unavailable"))
                solver.web.backend.fetch.assert_not_awaited()

    async def test_abstention_does_not_force_a_contradicted_earlier_answer_back_into_output(self):
        solver = self.solver()
        script, _, selections = self.model(
            response("28", queries=["cobalt code"]),
            [response("", verification="The source refutes the initial value of 28.")],
            None,
        )
        with script:
            result = await solver.solve(QuestionView("q", "Find the fictional element value."))
        self.assertEqual((result.status, result.answer, result.abstained), ("completed", "", True))
        self.assertEqual(selections, [])  # The contradicted old draft is ineligible.
        checks = self.events(solver, "candidate_checks")
        self.assertFalse(
            next(c for c in reversed(checks) if c["candidate_id"] == "initial-0")["eligible"]
        )
        self.assertIsNone(self.events(solver, "candidate_selection")[0]["selected"])

    async def test_semantically_contradicted_citations_are_never_selectable(self):
        solver = self.solver()
        request = solver.jev.request

        async def judge(item, stage, state, questions, **kwargs):
            if stage == "J3":
                return {"support": Judgment("J3", "support", "contradicted", 0.9, "fixture")}
            return await request(item, stage, state, questions, **kwargs)

        script, _, selections = self.model(
            response("42", queries=["cobalt code"]),
            [grounded, grounded],
            "42",
        )
        with script, patch.object(solver.jev, "request", judge):
            result = await solver.solve(QuestionView("q", "Compute 6 * 7."))
        self.assertEqual(result.answer, "42")
        self.assertEqual([c["answer"] for c in selections[0]["candidates"].values()], ["42"])
        self.assertEqual(len(self.events(solver, "candidate_rejected")), 2)

    async def test_failed_first_results_do_not_hide_a_fetchable_fourth_source(self):
        for backend in ("brave", "perplexity"):
            with self.subTest(backend=backend):
                solver = self.solver(backend)
                rows = [
                    {
                        "url": f"https://reference.example.org/{i}",
                        "title": "Reference",
                        "snippet": QUOTE,
                    }
                    for i in range(6)
                ]
                solver.web.backend.search.return_value = rows
                solver.web.backend.fetch.side_effect = [
                    ProviderError("unavailable"),
                    ProviderError("unavailable"),
                    ProviderError("unavailable"),
                    {"url": rows[3]["url"], "title": "Reference", "text": QUOTE},
                ]
                script, contexts, _ = self.model(
                    response("", queries=["cobalt code"]), [grounded], "27"
                )
                with script:
                    result = await solver.solve(
                        QuestionView("q", "Find the fictional element value.")
                    )
                self.assertEqual((result.status, result.answer), ("completed", "27"))
                self.assertEqual(contexts[0]["evidence"][0]["url"], rows[3]["url"])
                self.assertEqual(solver.web.backend.fetch.await_count, 4)
                self.assertEqual(solver.budget.snapshot("q")["counts"]["fetch"], 4)

    async def test_fetch_slots_and_evidence_are_shared_across_queries(self):
        solver = self.solver(arm="B2")

        async def search(query):
            return [
                {
                    "url": f"https://reference.example.org/{query[0]}/{i}",
                    "title": "Reference",
                    "snippet": "Safe text.",
                }
                for i in range(6)
            ]

        solver.web.backend.search.side_effect = search
        solver.web.backend.fetch.side_effect = lambda url, policy: {
            "url": url,
            "text": f"cobalt nickel code: {url}",
            "title": "Reference",
        }
        script, contexts, _ = self.model(
            response("42", queries=["cobalt code", "nickel code"]),
            [response("42")],
            "42",
        )
        with script:
            result = await solver.solve(QuestionView("q", "Compute 6 * 7."))
        self.assertEqual(result.answer, "42")
        self.assertEqual(
            [call.args[0].split("/")[-2] for call in solver.web.backend.fetch.await_args_list],
            ["c", "c", "n", "n"],
        )
        self.assertEqual(
            {p["subquestion"] for p in contexts[0]["evidence"]}, {"cobalt code", "nickel code"}
        )

    async def test_failed_query_leaves_its_fetch_slots_for_the_next_query(self):
        solver = self.solver()
        rows = [
            {"url": f"https://reference.example.org/{i}", "title": "Reference", "snippet": QUOTE}
            for i in range(4)
        ]
        solver.web.backend.search.side_effect = [ProviderError("unavailable"), rows]
        solver.web.backend.fetch.side_effect = [
            ProviderError("unavailable"),
            ProviderError("unavailable"),
            ProviderError("unavailable"),
            {"url": rows[3]["url"], "text": QUOTE, "title": "Reference"},
        ]
        script, _, _ = self.model(
            response("", queries=["cobalt code", "nickel code"]), [grounded], "27"
        )
        with script:
            result = await solver.solve(QuestionView("q", "Find the fictional element value."))
        self.assertEqual((result.status, result.answer), ("completed", "27"))
        self.assertEqual(solver.budget.snapshot("q")["counts"]["fetch"], 4)

    async def test_snippet_is_not_a_substitute_for_an_unavailable_source(self):
        solver = self.solver()
        solver.web.backend.fetch.side_effect = ProviderError("unavailable")
        script, contexts, selections = self.model(
            response("", queries=["cobalt code"]), [response("")], None
        )
        with script:
            result = await solver.solve(QuestionView("q", "Find the fictional element value."))
        self.assertEqual((result.status, result.answer), ("completed", ""))
        self.assertEqual(contexts[0]["evidence"], [])
        self.assertEqual(selections, [])

    async def test_resume_finds_cached_successes_after_uncached_failures_at_tool_caps(self):
        for failure in ("search", "fetch"):
            for backend in ("brave", "perplexity"):
                with self.subTest(failure=failure, backend=backend):
                    solver = self.solver(backend)
                    rows = [
                        {
                            "url": f"https://reference.example.org/{i}",
                            "title": "Reference",
                            "snippet": QUOTE,
                        }
                        for i in range(4)
                    ]
                    queries = ["cobalt code"]
                    if failure == "fetch":
                        solver.web.backend.search.return_value = rows
                        solver.web.backend.fetch.side_effect = [
                            ProviderError("unavailable"),
                            ProviderError("unavailable"),
                            ProviderError("unavailable"),
                            {"url": rows[3]["url"], "text": QUOTE, "title": "Reference"},
                        ]
                    else:
                        queries.append("nickel code")
                        solver.web.backend.search.side_effect = [
                            ProviderError("unavailable"),
                            rows[:1],
                        ]
                    generate = solver.gateway.generate

                    async def interrupt(question, context, phase, *, _generate=generate, **kwargs):
                        if phase == "revise-0":
                            raise asyncio.CancelledError()
                        return await _generate(question, context, phase, **kwargs)

                    question = QuestionView("q", "Find the fictional element value.")
                    script, contexts, _ = self.model(
                        response("", queries=queries), [grounded], "27"
                    )
                    with script:
                        with patch.object(solver.gateway, "generate", interrupt):
                            with self.assertRaises(asyncio.CancelledError):
                                await solver.solve(question)
                        counts = solver.budget.snapshot("q")["counts"]
                        resumed = Solver(solver.config, solver.store, "evidence-regression")
                        self.addAsyncCleanup(resumed.close)
                        resumed.web.backend.search = AsyncMock(
                            side_effect=AssertionError("search replay")
                        )
                        resumed.web.backend.fetch = AsyncMock(
                            side_effect=AssertionError("fetch replay")
                        )
                        result = await resumed.solve(question)
                    self.assertEqual((result.status, result.answer), ("completed", "27"))
                    self.assertTrue(contexts[0]["evidence"])
                    self.assertEqual(
                        resumed.budget.snapshot("q")["counts"][failure], counts[failure]
                    )
                    resumed.web.backend.search.assert_not_awaited()
                    resumed.web.backend.fetch.assert_not_awaited()

    async def test_previous_quote_remains_verifiable_after_packet_changes(self):
        solver = self.solver(
            evidence_chars=len(QUOTE), limits=replace(Limits(), rounds=2, retries=0)
        )
        solver.web.backend.search.side_effect = [
            [{"url": "https://first.example.org/a", "title": "Reference", "snippet": QUOTE}],
            [
                {
                    "url": "https://second.example.org/b",
                    "title": "Reference",
                    "snippet": "cobalt code",
                }
            ],
        ]
        solver.web.backend.fetch.side_effect = [
            {"url": "https://first.example.org/a", "title": "Reference", "text": QUOTE},
            {
                "url": "https://second.example.org/b",
                "title": "Reference",
                "text": "A cobalt code reference.",
            },
        ]
        first = None

        def first_revision(context):
            nonlocal first
            first = grounded(context)
            return {**first, "queries": ["cobalt code reference"]}

        def second_revision(context):
            self.assertNotIn(
                first["citations"][0]["passage_id"], [p["id"] for p in context["evidence"]]
            )
            return first

        script, contexts, selections = self.model(
            response("", queries=["cobalt code"]), [first_revision, second_revision], "27"
        )
        with script:
            result = await solver.solve(QuestionView("q", "Find the fictional element value."))
        self.assertEqual((result.status, result.answer), ("completed", "27"))
        self.assertEqual(len(contexts), 2)
        self.assertEqual(len(selections[0]["candidates"]), 1)  # Repeated drafts get one option.
        self.assertTrue(next(iter(selections[0]["candidates"].values()))["checks"]["accepted"])
