import unittest

from jev_solver.tools.structure import StructuredText
from jev_solver.retrieval.structure import structured_passages, display_cost
from jev_solver.models import digest


class StructuralViewsTests(unittest.TestCase):
    def page(self, text, **values):
        return dict(
            url="https://example.org",
            text=text,
            source_hash=digest(text),
            filter_version="v1",
            **values,
        )

    def test_table_cells_and_headers_map_to_canonical_spans(self):
        parser = StructuredText()
        parser.feed(
            "<article><table><tr><th>Command</th><th>Effect</th></tr>"
            "<tr><td>F</td><td>Move</td></tr></table></article>"
        )
        page = self.page(parser.text, structures=parser.structures)
        row = next(p for p in structured_passages(page, "command mapping") if "Move" in p.text)
        self.assertEqual(row.view["header_status"], "mapped")
        self.assertEqual([h["text"] for h in row.view["headers"]], ["Command", "Effect"])
        for cell in row.view["cells"] + row.view["headers"]:
            self.assertTrue(page["text"][cell["start"] : cell["end"]])
        self.assertEqual(page["text"][row.start : row.end], row.text)
        self.assertGreater(display_cost(row), len(row.text))

    def test_definition_theorem_bodies_and_formula_are_retained(self):
        page = self.page(
            "# Definition\n\nA regular object obeys x ≥ 0.\n\n# Theorem\n\nFor all n, f(n) ≤ n²."
        )
        views = structured_passages(page, "regularity and asymptotic behavior")
        self.assertTrue(any(p.view["kind"] == "definition" and "x ≥ 0" in p.text for p in views))
        self.assertTrue(any(p.view["kind"] == "theorem" and "n²" in p.text for p in views))
        for p in views:
            self.assertEqual(page["text"][p.start : p.end], p.text)

    def test_missing_layout_and_spanned_headers_remain_unavailable(self):
        parser = StructuredText()
        parser.feed(
            "<table><tr><th colspan='2'>Actions</th></tr><tr><td>F</td><td>Move</td></tr></table>"
        )
        views = structured_passages(self.page(parser.text, structures=parser.structures), "mapping")
        self.assertTrue(all(p.view["header_status"] == "unavailable" for p in views))
        saved = self.page(" | F | Move", structures=[{"kind": "table_row", "start": 0, "end": 11}])
        self.assertEqual(
            structured_passages(saved, "mapping")[0].view["header_status"], "unavailable"
        )
