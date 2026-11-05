import unittest
from dataclasses import replace

from jev_solver.judgments.citations import resolve_citations
from jev_solver.judgments.pipeline import exact_citation, verify
from jev_solver.models import Candidate, EvidencePassage, Judgment
from unittest.mock import AsyncMock


class CitationResolutionTests(unittest.IsolatedAsyncioTestCase):
    def passage(self, text):
        return EvidencePassage("p", "https://example.org", "hash", text, 0, len(text), "now", "v1")

    def row(self, quote, **values):
        return {
            "citations": [
                {
                    "claim": "The code is red.",
                    "passage_id": "p",
                    "quote": quote,
                    "critical": True,
                    **values,
                }
            ],
            "source_claims": [],
        }

    def test_unicode_offsets_and_repeated_valid_span(self):
        p = self.passage("Δ🧪 blue and blue")
        raw, trace = resolve_citations(self.row("🧪", start=99, end=100), [p])
        self.assertEqual((raw["citations"][0]["start"], raw["citations"][0]["end"]), (1, 2))
        self.assertEqual(trace[0]["reason"], "unique_exact_quote")
        raw, trace = resolve_citations(self.row("blue", start=3, end=7), [p])
        self.assertTrue(raw["citations"])
        self.assertEqual(trace[0]["reason"], "valid_explicit_span")

    def test_unresolved_references_never_become_citations(self):
        for row, reason in [
            (self.row("blue"), "ambiguous_quote"),
            (self.row("absent"), "absent_quote"),
            (self.row("blue", source_hash="changed"), "source_identity_changed"),
            (self.row("blue", passage_id="other"), "wrong_passage"),
        ]:
            raw, trace = resolve_citations(row, [self.passage("blue blue")])
            self.assertFalse(raw["citations"])
            self.assertTrue(raw["source_claims"])
            self.assertEqual(trace[0]["reason"], reason)

    async def test_coordinate_recovery_does_not_establish_support(self):
        from jev_solver.models import Citation

        p = self.passage("The code is blue.")
        raw, _ = resolve_citations(self.row(p.text), [p])
        c = Candidate(
            "c", "red", 0.9, "check", citations=tuple(Citation.parse(r) for r in raw["citations"])
        )
        jev = AsyncMock()
        jev.request.return_value = {
            "support": Judgment("J3", "support", "contradicted", 0.99, "mock")
        }
        result = await verify(jev, "q", c, [p], True)
        self.assertTrue(result[0]["valid_span"])
        self.assertEqual(result[0]["status"], "failed")
        self.assertFalse(
            exact_citation(
                replace(c, citations=(replace(c.citations[0], source_hash="wrong"),)), [p]
            )[0]["valid_span"]
        )
