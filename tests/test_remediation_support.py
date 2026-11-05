import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

from jev_solver.config import Config, RemediationPolicy
from jev_solver.judgments.support import (
    parse_requirements,
    local_request,
    aggregate_support,
    support_claim,
)
from jev_solver.judgments.pipeline import verify
from jev_solver.models import Candidate, Citation, EvidencePassage, Judgment, QuestionView


class AtomicSupportTests(unittest.IsolatedAsyncioTestCase):
    def requirements(self, claim="A and B"):
        return {
            "coverage": True,
            "requirements": [
                {
                    "id": "a",
                    "statement": "A",
                    "kind": "identity",
                    "start": 0,
                    "end": 2,
                    "necessary": True,
                    "depends_on": [],
                },
                {
                    "id": "b",
                    "statement": "B",
                    "kind": "relation",
                    "start": 2,
                    "end": len(claim),
                    "necessary": True,
                    "depends_on": [],
                },
            ],
        }

    def source(self, identifier, text):
        return EvidencePassage(
            identifier,
            f"https://example.org/{identifier}",
            identifier + "hash",
            text,
            0,
            len(text),
            "now",
            "v1",
        )

    def test_omitted_conjunct_or_cycle_cannot_pass(self):
        raw = self.requirements()
        raw["requirements"] = raw["requirements"][:1]
        with self.assertRaisesRegex(ValueError, "omitted"):
            parse_requirements(raw, "A and B")
        raw = self.requirements()
        raw["requirements"][0]["depends_on"] = ["a"]
        with self.assertRaisesRegex(ValueError, "cyclic"):
            parse_requirements(raw, "A and B")

    def test_multisource_support_and_conflict_aggregation(self):
        requirements = parse_requirements(self.requirements(), "A and B")
        rows = [
            {
                "requirement_version": requirements[0]["version"],
                "verdict": "supported",
                "passage_id": "a",
            },
            {
                "requirement_version": requirements[1]["version"],
                "verdict": "insufficient",
                "passage_id": "a",
            },
        ]
        self.assertEqual(aggregate_support(requirements, rows)["support"], "insufficient")
        rows.append(
            {
                "requirement_version": requirements[1]["version"],
                "verdict": "supported",
                "passage_id": "b",
            }
        )
        self.assertEqual(aggregate_support(requirements, rows)["status"], "passed")
        rows.append(
            {
                "requirement_version": requirements[0]["version"],
                "verdict": "contradicted",
                "passage_id": "new",
            }
        )
        self.assertEqual(aggregate_support(requirements, rows)["support"], "contradicted")

    def test_local_identity_is_independent_of_unrelated_sources_and_binds_scope(self):
        for claim in (
            "For every n, f(n) < n².",
            "The phenotype is caused by mechanism X.",
            "No version before 2040 has feature F.",
            "The definition requires continuity.",
        ):
            raw = {
                "coverage": True,
                "requirements": [
                    {
                        "id": "r",
                        "statement": claim,
                        "kind": "qualification",
                        "start": 0,
                        "end": len(claim),
                        "necessary": True,
                        "depends_on": [],
                    }
                ],
            }
            requirement = parse_requirements(raw, claim)[0]
            p = self.source("p", "An example and a qualified definition.")
            state, _, key = local_request(requirement, p)
            self.assertEqual(
                (state, key), (local_request(requirement, p)[0], local_request(requirement, p)[2])
            )
            self.assertNotEqual(
                key, local_request(requirement, replace(p, source_hash="changed"))[2]
            )

    async def test_both_callers_use_identical_local_support_requests(self):
        claim = "A and B"
        q = QuestionView("q", "Find both.")
        p = self.source("p", claim)
        c = Candidate(
            "c",
            "A; B",
            0.9,
            "Checked.",
            citations=(Citation(claim, "p", claim, 0, len(claim), True),),
        )
        gateway = SimpleNamespace(
            config=replace(Config(), remediation=RemediationPolicy(support="remediation-v1")),
            generate=AsyncMock(return_value=self.requirements()),
        )
        requests = []

        async def request(item, stage, state, questions, **kwargs):
            requests.append((state, questions))
            return {k: Judgment(stage, k, "supported", 0.9, "mock") for k in questions}

        jev = SimpleNamespace(request=AsyncMock(side_effect=request))
        citation_result = await verify(jev, "q", c, [p], True, gateway=gateway, question=q)
        first = requests[:]
        requests.clear()
        dependency_result = await support_claim(gateway, jev, q, c, claim, [p])
        self.assertEqual(first, requests)
        self.assertEqual(citation_result[0]["support"], dependency_result["support"])
