"""Private T01–T05 adapters. A clone without saved artifacts skips these tests."""

import json
import os
import unittest
from pathlib import Path

from jev_solver.candidates.selection import selection_references
from jev_solver.config import Config
from jev_solver.evaluation.offline import offline_dispatch_guard
from jev_solver.judgments.pipeline import exact_citation
from jev_solver.models import Candidate, EvidencePassage, QuestionView
from jev_solver.providers.backbone import CANDIDATE_SCHEMA, input_envelope


class PrivateV3Adapters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = Path(os.environ.get("JEV_V3_PRIVATE_ROOT", "private"))
        required = [
            cls.private / name
            for name in (
                "v3-search-attribution-audit.json",
                "v3-search-attribution-cases.json",
                "sol-low-pilot-data/solver/questions.jsonl",
            )
        ]
        if not all(p.is_file() for p in required):
            raise unittest.SkipTest("private historical v3 artifacts unavailable")
        cls.audit = json.loads(required[0].read_text())
        cls.index = {case["alias"]: case for case in json.loads(required[1].read_text())["cases"]}
        cls.questions = {
            row["id"]: QuestionView.parse(row)
            for row in map(json.loads, required[2].read_text().splitlines())
        }

    def setUp(self):
        guard = offline_dispatch_guard()
        guard.__enter__()
        self.addCleanup(guard.__exit__, None, None, None)

    def items(self, alias):
        qid = self.index[alias]["question_id"]
        return [(backend, run["items"][qid]) for backend, run in self.audit["runs"].items()]

    def test_t01_historical_failed_spans_follow_passed_dependency_coverage(self):
        rejected = 0
        for _, item in self.items("art_citation_offsets"):
            evidence = {
                p["id"]: EvidencePassage(**p)
                for research in item["research"]
                for p in research["packet"]
            }
            for identifier, raw in item["candidates"].items():
                candidate = Candidate.parse(raw, identifier)
                checks = item["final_checks"].get(identifier, {})
                if candidate.citations and checks.get("coverage", {}).get("status") == "passed":
                    rejected += any(
                        not row["valid_span"]
                        for row in exact_citation(candidate, list(evidence.values()))
                    )
        self.assertGreaterEqual(rejected, 3)

    def test_t02_three_historical_id_failures_are_repaired_within_the_selected_scope(self):
        total = 0
        for run in self.audit["runs"].values():
            for failure in run["replay"]["selection_failures"]:
                capture = next(
                    c
                    for c in run["replay"]["requests"]
                    if c["request_hash"] == failure["request_hash"]
                )
                response, names = capture["response"], capture["context"]["candidates"]
                selected = response["selected"]
                dependencies = names[selected]["checks"]["dependencies"]
                required = {d["id"] for d in dependencies if d["critical"]}
                passed = {d["id"] for d in dependencies if d["status"] == "passed"}
                # Reproduce the original failed condition before checking recovery.
                self.assertFalse(required <= set(response["checked_dependencies"]) <= passed)
                repaired = selection_references(
                    response["checked_dependencies"], selected, names, passed
                )
                self.assertTrue(required <= set(repaired) <= passed)
                total += 1
        self.assertEqual(total, 3)

    def test_t03_original_envelopes_and_invalid_generation_remain_rejected(self):
        sizes, incomplete, malformed = [], 0, 0
        for backend, run in self.audit["runs"].items():
            provider = Config.load(f"configs/sol-low.evidence-v3.j23.{backend}.json").provider
            for capture in run["replay"]["requests"]:
                if capture["envelope"] > capture["max_envelope"]:
                    size = input_envelope(
                        self.questions[capture["item"]],
                        capture["context"],
                        CANDIDATE_SCHEMA,
                        provider,
                    )
                    self.assertEqual(size, capture["envelope"])
                    sizes.append(size)
                incomplete += (
                    capture.get("saved_incomplete_response", {}).get("finish_reason") == "length"
                )
            for item in run["items"].values():
                for invalid in item["events"].get("invalid_candidate", []):
                    with self.assertRaises((ValueError, TypeError, KeyError)):
                        Candidate.parse(invalid["response"], "historical-invalid")
                    malformed += 1
        self.assertEqual(sorted(sizes), [66969, 72977, 74274])
        self.assertEqual(incomplete, 1)
        self.assertEqual(malformed, 1)

    def test_t04_returned_lead_was_not_fetched_at_ranks_five_and_three(self):
        items = dict(self.items("missed_paper_lead"))
        rounds = items["perplexity"]["research"]
        common = set.intersection(
            *({lead["url"] for lead in r["outcome"]["leads"]} for r in rounds)
        )
        missed = {
            url
            for url in common
            if all(url not in {f["url"] for f in r["outcome"]["fetches"]} for r in rounds)
        }
        ranks = [
            [
                next(i + 1 for i, lead in enumerate(r["outcome"]["leads"]) if lead["url"] == url)
                for r in rounds
            ]
            for url in missed
        ]
        self.assertIn([5, 3], ranks)

    def test_t05_historical_reproduction_has_no_dispatches_and_separate_check_states(self):
        replayed = assessments = 0
        for run in self.audit["runs"].values():
            replayed += run["replay"]["items"]
            assessments += run["replay"]["assessment_checks"]
            self.assertEqual(run["replay"]["dispatches"], 0)
        self.assertEqual(replayed, 100)
        self.assertEqual(assessments, 521)
        self.assertEqual(len(self.index), 18)
