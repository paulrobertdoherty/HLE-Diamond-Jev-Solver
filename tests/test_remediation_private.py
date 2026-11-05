import json
import os
import tempfile
import unittest
from pathlib import Path

from jev_solver.config import Config
from jev_solver.evaluation.manifests import freeze_manifest
from jev_solver.evaluation.orchestration import run_experiment
from jev_solver.evaluation.remediation import verify_artifacts
from jev_solver.evaluation.remediation_private import private_diagnostics
from jev_solver.models import QuestionView


class PrivateRemediationTests(unittest.IsolatedAsyncioTestCase):
    def root(self):
        root = Path(os.environ.get("JEV_REMEDIATION_ROOT", Path.cwd()))
        if not (root / "private/v3-remediation/comparison.json").exists():
            self.skipTest("private remediation comparison artifacts unavailable")
        return root

    def test_frozen_artifacts_and_actual_saved_passage_coordinate_diagnostics(self):
        root = self.root()
        manifest = json.loads((root / "private/v3-remediation/comparison.json").read_text())
        verify_artifacts(manifest)
        with tempfile.TemporaryDirectory() as tmp:
            result = private_diagnostics(root, Path(tmp) / "diagnostics.json")
            self.assertEqual(result["recovered_spans"], 3)
            self.assertEqual(result["historical_envelopes"], 3)
            self.assertEqual(result["packet_sequences"], 153)
            self.assertEqual(result["stronger_reviewed_shortlist_cases"], 3)
            self.assertEqual(result["external_dispatches"], 0)
        verify_artifacts(manifest)

    async def test_exact_preserved_source_runs_in_isolation(self):
        root = self.root()
        source = root / "private/v3-remediation/comparison-source"
        if not (source / "src/jev_solver/controller/engine.py").exists():
            self.skipTest("preserved comparison source unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            questions = output / "questions.jsonl"
            questions.write_text(
                json.dumps(
                    {"id": "synthetic-arithmetic", "question": "Compute 6 * 7.", "images": []}
                )
                + "\n"
            )
            paths = {
                "baseline": root / "configs/j23.synthetic.json",
                "repairs": root / "configs/remediation.synthetic.json",
            }
            configs = {k: Config.load(p) for k, p in paths.items()}
            manifest = freeze_manifest(
                "isolated-synthetic-regression",
                configs,
                ["synthetic-arithmetic"],
                baseline_revision="9a7a1aa9090960fa353ecb836f96c9da3b2b2c6a",
                historical_implementation_hash="historical-snapshot-recorded-separately",
                aggregate_usd=40,
                source_roots={"baseline": source},
                config_paths=paths,
                question_views=[QuestionView("synthetic-arithmetic", "Compute 6 * 7.")],
            )
            result = await run_experiment(manifest, paths, questions, output / "experiment")
            self.assertEqual(result["trial_statuses"], {"completed": 2})
            self.assertEqual(result["actual_accounted_cost_usd"], 0)
            self.assertNotEqual(
                manifest["arms"][0]["implementation_hash"],
                manifest["arms"][1]["implementation_hash"],
            )
