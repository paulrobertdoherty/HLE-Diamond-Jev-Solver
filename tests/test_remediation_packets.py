import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from jev_solver.models import EvidencePassage
from jev_solver.retrieval.evidence import diverse_packet, merge_associations
from jev_solver.retrieval.outcomes import boundary_rows
from jev_solver.evaluation.workflows import boundary_metrics
from jev_solver.tracing.store import Store


class CoveragePacketTests(unittest.TestCase):
    def passage(self, identifier, dependency="d", text=None, host="example.org", **changes):
        text = text or f"Complementary fact {identifier}."
        return EvidencePassage(
            identifier,
            f"https://{host}/{identifier}",
            "s",
            text,
            0,
            len(text),
            "now",
            "v1",
            dependency_id=dependency,
            dependency_ids=(dependency,),
            **changes,
        )

    def test_three_same_host_complementary_passages_survive(self):
        passages = [self.passage(str(i), str(i)) for i in range(3)]
        self.assertEqual(len(diverse_packet(passages, 12000, 6)), 2)
        packet = diverse_packet(passages, 12000, 6, policy="remediation-v1")
        self.assertEqual(len(packet), 3)
        self.assertEqual({d for p in packet for d in p.dependency_ids}, {"0", "1", "2"})

    def test_deduplication_preserves_dependency_associations_and_provenance(self):
        a, b = (
            self.passage("a", "identity", "Same fact."),
            self.passage("b", "scope", "Same fact.", "other.org"),
        )
        packet = diverse_packet([a, b], 12000, 6, policy="remediation-v1")
        self.assertEqual(len(packet), 1)
        self.assertEqual(set(packet[0].dependency_ids), {"identity", "scope"})
        self.assertEqual(len(packet[0].source_provenance), 2)
        repeated = merge_associations(
            [a, replace(a, dependency_id="scope", dependency_ids=("scope",))]
        )
        self.assertEqual(set(repeated[0].dependency_ids), {"identity", "scope"})

    def test_coverage_conflicts_and_actual_header_cost_are_bounded(self):
        passages = [self.passage(str(i)) for i in range(10)]
        conflict = self.passage("conflict", "critical", view={"contradictory": True})
        packet = diverse_packet(
            passages + [conflict],
            200,
            6,
            policy="remediation-v1",
            critical_dependencies=["critical"],
        )
        self.assertEqual(packet[0].id, "conflict")
        self.assertLessEqual(len(packet), 6)
        costly = self.passage("headers", view={"headers": "x" * 12000})
        trace = []
        self.assertEqual(diverse_packet([costly], 12000, policy="remediation-v1", trace=trace), [])
        self.assertEqual(trace[0]["reason"], "character_limit")

    def test_ledger_preserves_evicted_citations_and_rejects_identity_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "events.sqlite3")
            try:
                p = self.passage("p")
                store.passages("q", [p])
                self.assertEqual(store.passages("q")[0].text, p.text)
                with self.assertRaisesRegex(ValueError, "immutable"):
                    store.passages("q", [replace(p, text="changed")])
            finally:
                store.close()

    def test_boundary_counts_distinguish_occurrences_from_lost_unique_text(self):
        p = self.passage("p")
        rows = boundary_rows("packet", [p, p, self.passage("other", text=p.text)], [p])
        metrics = boundary_metrics(rows)["packet"]
        self.assertEqual(metrics["occurrences"], 3)
        self.assertEqual(metrics["unique_texts"], 1)
        self.assertEqual(metrics["lost_unique_texts"], 0)
