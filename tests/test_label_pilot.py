import copy
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from jev_solver.evaluation.label_pilot import (
    INSTRUCTIONS,
    MODELS,
    SCHEMAS,
    SYSTEM,
    comparison,
    prepare,
    review_request,
    run,
    select_sample,
    select_expanded,
    validate_review,
)
from jev_solver.evaluation.labels import case_record
from jev_solver.models import canonical, digest
from jev_solver.tracing.store import atomic_json


def source_case(component="J3"):
    inputs = (
        {
            "claim": "The year was 1999.",
            "quote": "The year was 1999.",
            "source_context": "The year was 1999.",
        }
        if component == "J3"
        else {
            "passage": "The year was 1999.",
            "question": "Which year?",
            "missing_fact": "The year",
        }
    )
    return case_record(
        "sample/brave/case",
        component,
        inputs,
        {"secret_judgment": "DO_NOT_SEND"},
        task_id="task",
        test_id="T08",
    )


def support_review(support="supported"):
    return {
        "support": support,
        "confidence": 0.7,
        "basis": "The passage explicitly gives the year.",
        "evidence_quotes": ["The year was 1999."],
    }


class LabelPilotTests(unittest.IsolatedAsyncioTestCase):
    def test_preparation_accepts_exact_decimal_prices_and_rejects_price_drift(self):
        row = source_case()
        catalog = {
            "data": [
                {
                    "id": model,
                    "canonical_slug": model + "-dated",
                    "pricing": {
                        "prompt": str(Decimal(str(input_rate)) / 1000000),
                        "completion": str(Decimal(str(output_rate)) / 1000000),
                    },
                    "supported_parameters": ["reasoning", "structured_outputs"],
                }
                for model, _, input_rate, output_rate in MODELS.values()
            ]
        }
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cases = root / "cases.jsonl"
            cases.write_text(json.dumps(row) + "\n")
            meta = root / "models.json"
            meta.write_text(json.dumps(catalog))
            with patch(
                "jev_solver.evaluation.label_pilot.select_sample",
                return_value=[{"case": row, "stratum": "test"}],
            ):
                plan = prepare(cases, root / "pilot", meta, 6)
                self.assertEqual(len(plan["sample"]), 1)
                self.assertGreater(plan["maximum_planned_cost_usd"], 0)
                catalog["data"][0]["pricing"]["prompt"] = "0.000001"
                meta.write_text(json.dumps(catalog))
                with self.assertRaisesRegex(ValueError, "price differs"):
                    prepare(cases, root / "changed-price", meta, 6)
                with self.assertRaisesRegex(ValueError, "cap"):
                    prepare(cases, root / "overspend", meta, 7)

    def test_review_hides_labels_and_historical_judgments(self):
        row = source_case()
        row["label"] = {
            "status": "adjudicated",
            "provenance": {"reviewer": "x", "method": "x", "timestamp": "x"},
            "values": {"secret_answer": "DO_NOT_SEND"},
        }
        messages, _, _ = review_request(row)
        self.assertNotIn("DO_NOT_SEND", canonical(messages))

    def test_audit_sends_actual_image_and_only_its_historical_audit(self):
        image = "data:image/png;base64,ZmFrZQ=="
        row = case_record(
            "sample/brave/audit",
            "audit",
            {"question": {"question": "Read the image", "images": [image]}, "context": {}},
            {"response": {"dependencies": []}, "private_grade": "DO_NOT_SEND"},
            task_id="task",
            test_id="T06",
        )
        before = copy.deepcopy(row)
        messages, _, bound = review_request(row)
        content = messages[1]["content"]
        self.assertEqual(content[1]["image_url"]["url"], image)
        self.assertNotIn("base64", content[0]["text"])
        self.assertNotIn("DO_NOT_SEND", canonical(messages))
        self.assertGreater(bound, 32768)
        self.assertEqual(row, before)

    def test_false_quotation_and_malformed_judgment_rejected(self):
        row = source_case()
        bad = support_review()
        bad["evidence_quotes"] = ["The year was 2000."]
        with self.assertRaisesRegex(ValueError, "absent"):
            validate_review("J3", bad, row["input"])
        for confidence in (True, float("nan"), 1.1):
            bad = support_review()
            bad["confidence"] = confidence
            with self.assertRaisesRegex(ValueError, "confidence"):
                validate_review("J3", bad, row["input"])

    def test_haiku_disagreement_does_not_override_terra_or_change_unresolved(self):
        terra = {"status": "completed", "review": support_review()}
        haiku = {"status": "completed", "review": support_review("insufficient")}
        before = copy.deepcopy(terra)
        result = comparison("J3", terra, haiku)
        self.assertEqual(result["status"], "disagreed")
        self.assertEqual(result["differing_fields"], ["support"])
        self.assertEqual(terra, before)
        self.assertEqual(
            comparison("J3", terra, {"status": "invalid_review"}), {"status": "unavailable"}
        )

    def test_sample_is_deterministic_distinct_and_stratified(self):
        rows = []
        for i in range(16):
            inputs = {"passage": f"passage {i}", "question": "question", "missing_fact": "fact"}
            observation = (
                {"judgment_executed": False}
                if i < 4
                else {"judgment": {"value": (i // 4 - 1) / 3 + 0.1}}
            )
            rows.append(
                case_record(
                    f"case{i}/brave/J2", "J2", inputs, observation, task_id=str(i), test_id="T07"
                )
            )
        for i in range(12):
            state = {"claim": str(i), "quote": str(i), "source_context": str(i)}
            support = "contradicted" if i == 0 else "insufficient" if i < 4 else "supported"
            rows.append(
                case_record(
                    f"case{i}/perplexity/J3",
                    "J3",
                    state,
                    {"response": {"answers": {"support": {"choice": support}}}},
                    task_id=str(i),
                    test_id="T08",
                )
            )
        for i in range(8):
            state = {
                "question": {
                    "question": str(i),
                    "images": ["data:image/png;base64,ZmFrZQ=="] if i < 4 else [],
                },
                "context": {},
            }
            rows.append(
                case_record(
                    f"case{i}/brave/audit",
                    "audit",
                    state,
                    {"response": {"dependencies": []}},
                    task_id=str(i),
                    test_id="T06",
                )
            )
        sample = select_sample(rows)
        self.assertEqual(len(sample), 36)
        self.assertEqual(sample, select_sample(list(reversed(rows))))
        self.assertEqual(
            len({(e["case"]["component"], e["case"]["input_hash"]) for e in sample}), 36
        )

    async def run_fake(self, root, *, cap=1, incomplete=False, expanded=False):
        row = source_case()
        messages, schema, bound = review_request(row)
        specs = {
            alias: {
                "model": values[0],
                "provider": values[1],
                "canonical_slug": values[0] + "-dated",
                "input_per_million": values[2],
                "output_per_million": values[3],
                "reasoning_effort": "medium",
            }
            for alias, values in MODELS.items()
        }
        if expanded:
            specs.pop("luna")
        plan = {
            "mode": "expanded" if expanded else "pilot",
            "prompt_hash": digest([SYSTEM, INSTRUCTIONS, SCHEMAS]),
            "budget_usd": cap,
            "primary_reviewer": "terra",
            "haiku_role": "disagreement_notes_only",
            "models": specs,
            "sample": [
                {
                    "case": row,
                    "stratum": "test",
                    "request_hash": digest([messages, schema]),
                    "input_bound": bound,
                    "output_tokens": 6144,
                }
            ],
        }
        path = root / "pilot-plan.json"
        atomic_json(path, plan)
        calls = []

        class FakeAdapter:
            def __init__(self, config, **kwargs):
                self.config = config

            async def complete(self, *args, **kwargs):
                calls.append(self.config.model)
                return {
                    "text": json.dumps(
                        support_review(
                            "insufficient"
                            if self.config.model.startswith("anthropic/")
                            else "supported"
                        )
                    ),
                    "model": self.config.model,
                    "cost_usd": 0.0001,
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 10,
                        "openrouter": {"cost": 0.0001},
                    },
                    "status": "incomplete" if incomplete else "completed",
                }

            async def close(self):
                pass

        first = await run(path, adapter_factory=FakeAdapter)
        second = await run(path, adapter_factory=FakeAdapter)
        return first, second, calls

    async def test_paid_resume_reuses_completed_attempts_and_never_applies_haiku(self):
        with tempfile.TemporaryDirectory() as d:
            first, second, calls = await self.run_fake(Path(d))
        self.assertEqual(len(calls), 3)
        self.assertAlmostEqual(first["usage"]["accounted_cost_usd"], 0.0003)
        self.assertEqual(first, second)
        case = first["cases"][0]
        self.assertEqual(case["primary_review"]["review"]["support"], "supported")
        self.assertEqual(case["haiku_vs_terra"]["status"], "disagreed")
        self.assertIsNone(first["ground_truth_accuracy"])
        self.assertEqual(case["label_status"], "provisional_ai_only")

    def test_expanded_keeps_duplicate_inputs_for_attribution(self):
        row = source_case()
        duplicate = copy.deepcopy(row)
        duplicate["id"] = "another/brave/case"
        selected = select_expanded([row, duplicate])
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected, select_expanded([duplicate, row]))

    async def test_expanded_two_reviewers_with_larger_cap_and_resume(self):
        with tempfile.TemporaryDirectory() as d:
            first, second, calls = await self.run_fake(Path(d), cap=15, expanded=True)
        self.assertEqual(len(calls), 2)
        self.assertEqual(set(first["models"]), {"terra", "haiku"})
        self.assertEqual(first, second)
        self.assertEqual(first["cases"][0]["luna_vs_terra"], {"status": "unavailable"})

    async def test_budget_blocks_dispatch_and_incomplete_responses_still_cost_money(self):
        with tempfile.TemporaryDirectory() as d:
            first, _, calls = await self.run_fake(Path(d), cap=0.000001)
            self.assertEqual(calls, [])
            self.assertTrue(
                all(r["statuses"] == {"budget_stopped": 1} for r in first["models"].values())
            )
        with tempfile.TemporaryDirectory() as d:
            first, _, calls = await self.run_fake(Path(d), incomplete=True)
            self.assertEqual(len(calls), 3)
            self.assertAlmostEqual(first["usage"]["accounted_cost_usd"], 0.0003)
            self.assertEqual(first["cases"][0]["haiku_vs_terra"], {"status": "unavailable"})


if __name__ == "__main__":
    unittest.main()
