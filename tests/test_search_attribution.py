"""T06–T11 synthetic harness tests; scores here do not measure model quality."""

import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from jev_solver.config import Config, RelevancePolicy
from jev_solver.evaluation.components import components, packet_metrics, workflow_metrics
from jev_solver.evaluation.labels import (
    case_record,
    component_rows,
    extract_cases,
    load_cases,
    provider_input,
    validate_case,
)
from jev_solver.evaluation.offline import (
    FrozenResponses,
    OfflineDispatchForbidden,
    offline_dispatch_guard,
)
from jev_solver.evaluation.replay import (
    COMPONENTS,
    ControlledReplay,
    controlled_comparison,
    validate_manifest,
)
from jev_solver.evaluation.search import query_inputs, search_comparison
from jev_solver.models import digest
from jev_solver.tools.policy import Policy


class AttributionHarnessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.guard = offline_dispatch_guard()
        self.guard.__enter__()
        self.addCleanup(self.guard.__exit__, None, None, None)

    def write(self, name, rows):
        path = self.root / name
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return path

    def labeled_case(self):
        state = {
            "question": "Find the fictional code.",
            "missing_fact": "cobalt code",
            "search_query": "primary catalog",
            "passage": "The cobalt code is 27.",
        }
        row = case_record(
            "p",
            "J2",
            state,
            {"judgment": {"value": 1.0, "confidence": 0.9}},
            task_id="q/round-0/code",
            test_id="T07",
            passages=["p"],
        )
        return row

    def adjudicate(self, row, values):
        row = deepcopy(row)
        row["label"] = {
            "status": "adjudicated",
            "provenance": {
                "reviewer": "synthetic-expert",
                "method": "independent synthetic fixture",
                "timestamp": "2026-11-01",
            },
            "values": values,
        }
        return row

    async def test_t06_missing_independent_labels_are_unavailable_without_dispatch(self):
        row = self.labeled_case()
        result = await components(
            Config(), self.write("labels.jsonl", [row]), self.root / "components", "stored"
        )
        self.assertIsNone(result["metrics"]["J2"]["accuracy"])
        self.assertEqual(result["unresolved_cases"], 1)
        self.assertEqual(result["paid_calls_dispatched"], 0)

    async def test_t07_stored_judgments_use_labels_only_for_scoring(self):
        row = self.adjudicate(
            self.labeled_case(),
            {"expected": 1.0, "answer_bearing": True, "useful": True, "contradictory": False},
        )
        self.assertEqual(provider_input(row), row["input"])
        self.assertNotIn("expected", provider_input(row))
        result = await components(
            Config(), self.write("labels.jsonl", [row]), self.root / "components", "stored"
        )
        self.assertEqual(result["metrics"]["J2"]["accuracy"], 1)
        self.assertEqual(result["usage"]["attempts_by_kind"], {})
        self.assertEqual(len(component_rows([row])), 1)

    def test_t06_hash_provenance_and_stable_ids_are_validated(self):
        row = self.labeled_case()
        for change in (
            {"input_hash": "changed"},
            {"split": "heldout"},
            {"identities": {"claims": ["a", "a"], "passages": []}},
            {"label": {"status": "adjudicated", "values": {"expected": 1}, "provenance": {}}},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_case({**row, **change})
        reference = case_record(
            "reference",
            "reference",
            {"reference": "PRIVATE_REFERENCE"},
            {},
            task_id="q",
            test_id="T10",
        )
        with self.assertRaisesRegex(ValueError, "isolated grader"):
            provider_input(reference)

    def test_t07_survival_reports_earliest_exclusion_and_uses_round_groups(self):
        def result(identifier, text, score, fact="cobalt code", round_no=0):
            return {
                "row": {
                    "id": identifier,
                    "stage": "J2",
                    "task_id": "q",
                    "round": round_no,
                    "state": {
                        "question": "Find the code.",
                        "missing_fact": fact,
                        "passage": text,
                        "url": f"https://{identifier}.example.org/a",
                    },
                    "expected": 1.0,
                    "answer_bearing": True,
                    "useful": True,
                    "contradictory": False,
                },
                "value": score,
                "confidence": 0.9,
            }

        rows = [
            result("a", "cobalt code one", 1),
            result("b", "cobalt two", 0),
            result("c", "no overlap", 1),
        ]
        cfg = replace(Config(), relevance=RelevancePolicy(shortlist=2, packet=1))
        metrics = packet_metrics(cfg, rows, "stored")
        self.assertEqual(
            {row["id"]: row["reason"] for row in metrics["exclusions"]},
            {"a": "retained", "b": "relevance_policy", "c": "shortlist"},
        )
        self.assertEqual(
            [
                metrics["survival_checkpoints"][stage]["answer_bearing"]["retained"]
                for stage in (
                    "before_shortlist",
                    "after_shortlist",
                    "after_relevance",
                    "after_packet",
                )
            ],
            [3, 2, 1, 1],
        )
        rows.extend(
            [
                result("d", "cobalt code four", 1, round_no=1),
                result("e", "other missing fact", 1, fact="other missing fact"),
            ]
        )
        self.assertEqual(packet_metrics(cfg, rows, "stored")["packet_groups"], 3)

    def test_t07_packet_limits_and_missing_labels_have_explicit_denominators(self):
        rows = [
            {
                "row": {
                    "id": str(i),
                    "task_id": "q",
                    "state": {
                        "question": "q",
                        "missing_fact": "code",
                        "passage": f"code {i}",
                        "url": f"https://host{i}.example.org/a",
                    },
                    "expected": 1.0,
                    "useful": True,
                },
                "value": 1.0,
                "confidence": 0.9,
            }
            for i in range(3)
        ]
        cfg = replace(Config(), relevance=RelevancePolicy(packet=1))
        metrics = packet_metrics(cfg, rows, "stored")
        self.assertIsNone(metrics["answer_bearing_recall_at_packet_budget"])
        self.assertEqual(metrics["labeled_totals"]["answer_bearing"], 0)
        self.assertEqual(sum(r["reason"] == "packet_limit" for r in metrics["exclusions"]), 2)

    async def test_t08_support_confusion_separates_unavailable_and_false_support(self):
        states = {
            "claim": "The fictional count is 3.",
            "quote": "The count is 4.",
            "source_context": "The count is 4.",
        }
        rows = [
            {
                "id": "false-support",
                "stage": "J3",
                "state": states,
                "expected": "contradicted",
                "observed": {"value": "supported"},
            },
            {
                "id": "missing",
                "stage": "J3",
                "state": states,
                "expected": "supported",
                "observed": {},
            },
            {
                "id": "false-rejection",
                "stage": "J3",
                "state": states,
                "expected": "supported",
                "observed": {"value": "insufficient"},
            },
        ]
        result = await components(
            Config(), self.write("j3.jsonl", rows), self.root / "support", "stored"
        )
        metrics = result["metrics"]["J3"]
        self.assertEqual(metrics["false_support_count"], 1)
        self.assertEqual(metrics["false_rejection_count"], 1)
        self.assertEqual(metrics["unavailable"], 1)
        self.assertEqual(metrics["false_rejection_rate"], 0.5)

    def test_t06_entire_history_exposes_correct_candidate_rejection(self):
        rows = [
            {
                "stage": "eligibility",
                "candidate_ids": ["correct-rejected", "wrong-accepted", "wrong-rejected"],
                "correct_ids": ["correct-rejected"],
                "eligible_ids": ["wrong-accepted"],
            },
            {
                "stage": "selection",
                "candidate_ids": ["wrong-accepted"],
                "correct_ids": [],
                "selected_id": "wrong-accepted",
            },
        ]
        metrics = workflow_metrics(self.write("workflow.jsonl", rows), self.root / "workflow.json")
        self.assertEqual(metrics["assessed_candidate_count"], 3)
        self.assertEqual(metrics["eligibility_false_rejection"]["value"], 1)
        self.assertEqual(metrics["eligibility_false_acceptance"]["value"], 0.5)
        self.assertIsNone(metrics["correct_answer_rejection_rate"])

    def test_t06_audit_image_accuracy_and_classification_repeatability(self):
        gold = [
            {"id": "visual", "kind": "visual", "critical": True},
            {"id": "premise", "kind": "factual", "critical": True},
        ]
        observed = [{**gold[0], "status": "passed"}]
        rows = [
            {
                "stage": "audit",
                "input_hash": "same-frozen-input",
                "gold_dependencies": gold,
                "observed_dependencies": observed,
            },
            {
                "stage": "audit",
                "input_hash": "same-frozen-input",
                "gold_dependencies": gold,
                "observed_dependencies": [{**gold[0], "kind": "derived", "status": "passed"}],
            },
            {
                "stage": "visual",
                "original_image_hashes": ["original"],
                "reviewed_image_hashes": ["different"],
                "expected_observations": {"v1": "three vertices", "v2": "blue"},
                "observed_observations": {"v1": "four vertices", "v2": "blue"},
            },
        ]
        metrics = workflow_metrics(self.write("audit.jsonl", rows), self.root / "audit.json")
        self.assertEqual(metrics["audit_claim_discovery"]["value"], 0.5)
        self.assertEqual(metrics["audit_checked_coverage"]["value"], 0.5)
        self.assertEqual(metrics["dependency_kind_accuracy"]["value"], 0.5)
        self.assertEqual(metrics["classification_repeatability"]["value"], 0)
        self.assertEqual(metrics["visual_observation_accuracy"]["value"], 0.5)
        self.assertEqual(metrics["original_image_grounding"]["value"], 0)

    def test_t10_original_and_adjudicated_scores_remain_separate(self):
        rows = [
            {
                "stage": "reference",
                "original_correct": False,
                "adjudicated_correct": True,
                "disagreement": "reference_interpretation",
            },
            {"stage": "reference", "label_status": "unresolved"},
        ]
        metrics = workflow_metrics(self.write("grades.jsonl", rows), self.root / "reference.json")
        self.assertEqual(metrics["original_reference_accuracy"]["value"], 0)
        self.assertEqual(metrics["adjudicated_reference_accuracy"]["value"], 1)
        self.assertEqual(metrics["grader_agreement"]["value"], 0)
        self.assertEqual(metrics["unresolved_cases"], 1)

    def search_fixture(self, labeled=True):
        query = {
            "id": "q",
            "question": "Find the fictional code.",
            "missing_fact": "cobalt code",
            "query": "primary catalog",
        }
        target = "https://reference.example.org/target"
        distractor = "https://reference.example.org/distractor"
        if labeled:
            query["label"] = {
                "status": "adjudicated",
                "values": {"useful_urls": [target], "needed_text": ["The cobalt code is 27."]},
            }
        policy = Policy(Path("protocol/upstream/blocklist.json"))
        snapshot = {
            "version": 1,
            "input_hash": digest(query_inputs([query])),
            "policy_version": policy.version,
            "parser_version": Config().parser_version,
            "result_limit": 20,
            "fetch_budget": 1,
            "providers": {},
        }
        for backend in ("brave", "perplexity"):
            snapshot["providers"][backend] = {
                "q": {
                    "input_hash": digest(query_inputs([query])[0]),
                    "results": [
                        {
                            "url": "https://huggingface.co/blocked",
                            "title": "code",
                            "snippet": "blocked",
                        },
                        {"url": distractor, "title": "Navigation", "snippet": "Welcome"},
                        {"url": target, "title": "cobalt code", "snippet": "Code catalog"},
                        {
                            "url": target,
                            "title": "cobalt code duplicate",
                            "snippet": "Code catalog",
                        },
                    ],
                    "pages": {
                        distractor: {
                            "status": "fetched",
                            "page": {
                                "url": "https://reference.example.org/home",
                                "title": "Home",
                                "text": "Generic home page",
                                "redirects": ["https://reference.example.org/home"],
                            },
                        },
                        target: {
                            "status": "fetched",
                            "page": {
                                "url": target,
                                "title": "Catalog",
                                "text": "The cobalt code is 27.",
                                "redirects": [],
                            },
                        },
                    },
                }
            }
        path = self.root / "snapshot.json"
        path.write_text(json.dumps(snapshot))
        return query, path

    async def test_t09_identical_query_replay_separates_provider_and_local_order(self):
        query, snapshot = self.search_fixture()
        result = await search_comparison(
            Config(),
            self.write("queries.jsonl", [query]),
            self.root / "search",
            snapshot=snapshot,
            fetch_budget=1,
        )
        self.assertEqual(result["conditions"], 4)
        self.assertEqual(result["generative_model_calls"], 0)
        rows = json.loads((self.root / "search/search-comparison.json").read_text())["observations"]
        for row in rows:
            self.assertEqual(len(row["fetches"]), 1)
            self.assertEqual(len(row["ranked_urls"]), 2)
            self.assertFalse(row["raw_results"][0]["allowed"])
            self.assertEqual(
                row["metrics"]["useful_page_recall"], 1 if row["order"] == "local" else 0
            )
            self.assertEqual(
                row["metrics"]["extracted_fact_recall"], 1 if row["order"] == "local" else 0
            )

    async def test_t09_missing_labels_and_missing_fetch_snapshot_are_unavailable(self):
        query, path = self.search_fixture(labeled=False)
        snapshot = json.loads(path.read_text())
        for backend in snapshot["providers"].values():
            backend["q"]["pages"] = {}
        path.write_text(json.dumps(snapshot))
        result = await search_comparison(
            Config(),
            self.write("queries.jsonl", [query]),
            self.root / "search",
            snapshot=path,
            fetch_budget=1,
        )
        self.assertEqual(result["unlabeled_conditions"], 4)
        data = json.loads((self.root / "search/search-comparison.json").read_text())
        self.assertTrue(
            all(
                row["fetches"][0]["status"] == "unavailable_snapshot"
                for row in data["observations"]
            )
        )

    async def test_t09_changed_query_or_budget_cannot_reuse_snapshot(self):
        query, snapshot = self.search_fixture()
        query["query"] += " changed"
        with self.assertRaisesRegex(ValueError, "contract differs"):
            await search_comparison(
                Config(),
                self.write("queries.jsonl", [query]),
                self.root / "bad",
                snapshot=snapshot,
                fetch_budget=1,
            )
        with self.assertRaisesRegex(ValueError, "choose a frozen"):
            await search_comparison(
                Config(), self.write("queries2.jsonl", [query]), self.root / "bad2", fetch_budget=1
            )

    async def test_t09_unobserved_page_is_unknown_even_with_adjudicated_labels(self):
        query, path = self.search_fixture()
        snapshot = json.loads(path.read_text())
        for backend in snapshot["providers"].values():
            backend["q"]["pages"] = {}
        path.write_text(json.dumps(snapshot))
        await search_comparison(
            Config(),
            self.write("queries.jsonl", [query]),
            self.root / "search",
            snapshot=path,
            fetch_budget=1,
        )
        observations = json.loads((self.root / "search/search-comparison.json").read_text())[
            "observations"
        ]
        self.assertTrue(all(row["metrics"]["useful_page_recall"] is None for row in observations))

    async def test_t06_fresh_audit_harness_preserves_images_and_counts_failed_trials(self):
        from types import SimpleNamespace

        from jev_solver.evaluation.audits import audit_evaluation
        from jev_solver.models import Dependency
        from test_verification_contract import audit_result

        dep = Dependency(
            "v1", "visual", "Three vertices.", True, basis="Counted vertices.", image_indices=(0,)
        )
        row = case_record(
            "audit",
            "audit",
            {
                "question": {
                    "id": "q",
                    "question": "Count vertices.",
                    "images": ["data:image/png;base64,original"],
                },
                "context": {"draft": {"answer": "3"}},
            },
            {},
            task_id="q",
            test_id="T06",
            claims=["v1"],
        )
        row = self.adjudicate(
            row,
            {
                "gold_dependencies": [{"id": "v1", "kind": "visual", "critical": True}],
                "private_gold": "DO_NOT_SEND",
            },
        )
        gateway = SimpleNamespace(
            generate=AsyncMock(side_effect=[audit_result(dep), {}, audit_result(dep)]),
            close=AsyncMock(),
        )
        with patch("jev_solver.evaluation.audits.Gateway", return_value=gateway):
            result = await audit_evaluation(
                Config(), self.write("audits.jsonl", [row]), self.root / "audits", repeats=3
            )
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["metrics"]["audit_checked_coverage"]["value"], 2 / 3)
        for call in gateway.generate.await_args_list:
            self.assertEqual(call.args[0].images, ("data:image/png;base64,original",))
            self.assertEqual(call.args[1], row["input"]["context"])
            self.assertNotIn("DO_NOT_SEND", json.dumps(call.args[1]))

    def test_t06_extraction_is_unresolved_preserves_originals_and_never_overwrites_labels(self):
        import sqlite3

        q = {
            "id": "synthetic-q",
            "question": "Count.",
            "images": ["data:image/png;base64,original"],
        }
        requests = [
            {
                "item": q["id"],
                "phase": "audit-initial-0",
                "request_hash": "request",
                "context": {"draft": {"dependencies": []}, "evidence": []},
                "response": {"dependencies": []},
            }
        ]
        run = {
            "manifest": {},
            "items": {
                q["id"]: {
                    "research": [],
                    "candidates": {"initial-0": {"answer": "3"}},
                    "prediction": {"answer": "3"},
                    "grade": {"correct": False},
                }
            },
            "replay": {"requests": requests, "assessments": []},
        }
        audit = {"runs": {"brave": run}}
        index = {
            "implementation_hash": "frozen-v3",
            "cases": [{"alias": "synthetic", "question_id": q["id"]}],
        }
        audit_path = self.root / "audit.json"
        index_path = self.root / "index.json"
        audit_path.write_text(json.dumps(audit))
        index_path.write_text(json.dumps(index))
        db_path = self.root / "sol-low-evidence-v3-j23-brave/events.sqlite3"
        db_path.parent.mkdir()
        with sqlite3.connect(db_path) as db:
            db.execute("CREATE TABLE events(item TEXT, kind TEXT, data TEXT)")
        questions = self.write("questions.jsonl", [q])
        output = self.root / "extracted"
        result = extract_cases(audit_path, index_path, output, questions)
        self.assertEqual(result["cases"], 2)
        rows = load_cases(output / "label-cases.jsonl")
        self.assertTrue(all(r["label"]["status"] == "unresolved" for r in rows))
        self.assertEqual(rows[0]["input"]["question"]["images"], q["images"])
        self.assertEqual(rows[1]["observation"]["original_grade"], {"correct": False})
        with self.assertRaisesRegex(ValueError, "already exist"):
            extract_cases(audit_path, index_path, output, questions)

    async def test_t07_unexecuted_judgment_is_excluded_from_semantic_accuracy(self):
        row = self.adjudicate(self.labeled_case(), {"expected": 1.0, "answer_bearing": True})
        row["observation"] = {"judgment_executed": False, "exclusion": "shortlist"}
        row["observation_hash"] = digest(row["observation"])
        result = await components(
            Config(), self.write("not-run.jsonl", [row]), self.root / "not-run", "stored"
        )
        self.assertEqual(result["metrics"]["J2"]["not_run"], 1)
        self.assertEqual(result["metrics"]["J2"]["judged_count"], 0)
        self.assertIsNone(result["metrics"]["J2"]["accuracy"])

    def test_t11_report_includes_failures_abstentions_cost_and_paired_uncertainty(self):
        manifest = self.manifest()
        manifest["acceptance"]["replications"] = 1
        manifest["shared"]["questions_hash"] = digest(["q1", "q2"])

        def grade(q, correct, status="completed", abstained=False):
            return {
                "question_id": q,
                "correct": correct,
                "status": status,
                "abstained": abstained,
                "confidence": 0.5,
                "cost_usd": 0.01,
                "latency_s": 2,
            }

        grades = {
            "B2": [grade("q1", True), grade("q2", False, "error", True)],
            "J23": [grade("q1", False), grade("q2", False, abstained=True)],
        }
        result = controlled_comparison(manifest, grades)
        self.assertEqual(result["arms"]["B2"]["accuracy"], 0.5)
        self.assertEqual(result["arms"]["B2"]["failure_rate"], 0.5)
        self.assertEqual(result["arms"]["J23"]["coverage"], 0.5)
        self.assertEqual(result["arms"]["J23"]["wrong_answer_acceptance"]["value"], 1)
        self.assertEqual(result["paired_against_baseline"]["J23"]["difference_a_minus_b"], -0.5)
        self.assertIsNone(result["workflow"]["eligibility_false_rejection"]["value"])
        with self.assertRaisesRegex(ValueError, "declared question set|declared trials"):
            controlled_comparison(manifest, {**grades, "J23": grades["J23"][:1]})

    def test_t06_saved_native_audits_feed_workflow_metrics_without_new_judgments(self):
        from jev_solver.models import Dependency
        from test_verification_contract import audit_result

        dep = Dependency("d", "derived", "The sum is 42.", True, basis="6 * 7 = 42.")
        row = case_record(
            "saved-audit",
            "audit",
            {"question": {"id": "q", "question": "Compute.", "images": []}, "context": {}},
            {"response": audit_result(dep)},
            task_id="q",
            test_id="T06",
            claims=["d"],
        )
        row = self.adjudicate(
            row, {"gold_dependencies": [{"id": "d", "kind": "derived", "critical": True}]}
        )
        result = workflow_metrics(
            self.write("native-audit.jsonl", [row]), self.root / "native-audit.json"
        )
        self.assertEqual(result["audit_checked_coverage"]["value"], 1)
        self.assertIsNone(result["classification_repeatability"]["value"])
        row["label"]["status"] = "unresolved"
        result = workflow_metrics(
            self.write("unresolved-audit.jsonl", [row]), self.root / "unresolved-audit.json"
        )
        self.assertEqual(result["unresolved_cases"], 1)
        self.assertIsNone(result["audit_checked_coverage"]["value"])

    def test_t10_saved_native_reference_labels_score_entire_candidate_history(self):
        row = case_record(
            "saved-reference",
            "reference",
            {"candidate_history": {"correct-rejected": {}, "wrong-accepted": {}}},
            {
                "original_grade": {"correct": False},
                "assessments": {
                    "correct-rejected": {"eligible": False},
                    "wrong-accepted": {"eligible": True},
                },
                "selection": {"selected": "wrong-accepted"},
            },
            task_id="q",
            test_id="T10",
        )
        row = self.adjudicate(
            row,
            {
                "correct_ids": ["correct-rejected"],
                "adjudicated_correct": True,
                "disagreement": "reference_interpretation",
            },
        )
        result = workflow_metrics(
            self.write("native-reference.jsonl", [row]), self.root / "native-reference.json"
        )
        self.assertEqual(result["assessed_candidate_count"], 2)
        self.assertEqual(result["eligibility_false_rejection"]["value"], 1)
        self.assertEqual(result["wrong_answer_acceptance_rate"], 1)
        self.assertEqual(result["original_reference_accuracy"]["value"], 0)
        self.assertEqual(result["adjudicated_reference_accuracy"]["value"], 1)

    async def test_t09_native_queries_deduplicate_identical_frozen_inputs(self):
        query, snapshot = self.search_fixture()
        row = case_record(
            "source-a", "search", query_inputs([query])[0], {}, task_id="q", test_id="T09"
        )
        row = self.adjudicate(row, query["label"]["values"])
        duplicate = {**row, "id": "source-b"}
        result = await search_comparison(
            Config(),
            self.write("native-queries.jsonl", [row, duplicate]),
            self.root / "native-search",
            snapshot=snapshot,
            fetch_budget=1,
        )
        self.assertEqual(result["conditions"], 4)
        self.assertEqual(result["unlabeled_conditions"], 0)

    def manifest(self):
        baseline = {
            "id": "B2",
            "config_hash": "b2-config",
            "implementation_hash": "source-v1",
            "components": {
                c: {
                    "implementation": "v1",
                    "model": "none" if c in {"search", "fetch"} else "frozen-model",
                    "prompt": "v1",
                }
                for c in COMPONENTS
            },
            "changed_components": [],
        }
        intervention = deepcopy(baseline)
        intervention.update(id="J23", config_hash="j23-config", changed_components=["J2", "J3"])
        for component in ("J2", "J3"):
            intervention["components"][component]["model"] = "jev-frozen"
        return {
            "version": 1,
            "experiment_id": "synthetic-control",
            "split": "development",
            "policy_frozen": True,
            "evidence_policy": {"packet": 6},
            "acceptance": {
                "replications": 2,
                "criteria": "Report paired full-set accuracy including errors.",
            },
            "shared": {
                k: f"frozen-{k}"
                for k in (
                    "questions_hash",
                    "initial_candidates_hash",
                    "queries_hash",
                    "results_hash",
                    "pages_hash",
                )
            },
            "arms": [baseline, intervention],
        }

    async def test_t11_frozen_inputs_are_shared_but_changed_contracts_need_new_calls(self):
        manifest = self.manifest()
        replay = ControlledReplay(manifest)
        contract = replay.contract("B2", "initial", {"question": "Synthetic question"})
        replay.frozen = FrozenResponses([{"contract": contract, "response": {"answer": "42"}}])
        self.assertEqual(
            await replay.request("J23", "initial", contract["inputs"]), {"answer": "42"}
        )
        with self.assertRaises(OfflineDispatchForbidden):
            await replay.request("J23", "initial", {"question": "Changed input"})
        generate = AsyncMock(return_value={"judgment": 1})
        await replay.request("J23", "J2", {"passage": "Synthetic text"}, generate=generate)
        self.assertEqual(
            [r["behavior"] for r in replay.ledger], ["frozen", "unavailable", "new_call"]
        )
        generate.assert_awaited_once()

    def test_t11_manifests_require_predeclared_interventions_and_source_identity(self):
        manifest = self.manifest()
        self.assertEqual(validate_manifest(manifest), manifest)
        for change in (
            {"policy_frozen": False},
            {"split": "heldout"},
            {"shared": {}},
            {"acceptance": {}},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_manifest({**manifest, **change})
        manifest["arms"][1]["components"]["selection"]["prompt"] = "changed downstream prompt"
        with self.assertRaisesRegex(ValueError, "declared intervention"):
            validate_manifest(manifest)
