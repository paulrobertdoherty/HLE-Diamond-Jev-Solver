"""Immutable comparison identities and isolated historical reproduction (no paid calls)."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path

from ..models import digest
from ..tracing.store import atomic_json


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze_comparison(root, baseline_revision, output, *, artifacts=(), historical=None):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("comparison identity already exists")
    revision = subprocess.check_output(
        ["git", "rev-parse", "--verify", baseline_revision + "^{commit}"], cwd=root, text=True
    ).strip()
    names = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", revision], cwd=root, text=True
    ).splitlines()
    sources = {}
    for name in names:
        if name.startswith(("src/", "configs/", "protocol/")) or name in {
            "pyproject.toml",
            "uv.lock",
        }:
            body = subprocess.check_output(["git", "show", f"{revision}:{name}"], cwd=root)
            sources[name] = hashlib.sha256(body).hexdigest()
    private_hashes = {str(Path(p).resolve()): file_hash(p) for p in artifacts}
    historical_sources = None
    if historical:
        historical = Path(historical).resolve()
        historical_sources = {
            str(p.relative_to(historical)): file_hash(p)
            for p in sorted((historical / "src").rglob("*.py"))
        }
        if not historical_sources:
            raise ValueError("historical implementation is unavailable")
    manifest = {
        "version": "remediation-comparison-v1",
        "baseline_revision": revision,
        "baseline_files": sources,
        "baseline_content_hash": digest(sources),
        "historical_files": historical_sources,
        "historical_content_hash": digest(historical_sources) if historical_sources else None,
        "private_artifacts": private_hashes,
        "python": sys.version,
        "dependencies": sorted(
            (d.metadata["Name"], d.version) for d in importlib.metadata.distributions()
        ),
        "paid_execution": "pending explicit launch and frozen budget",
    }
    atomic_json(output, manifest)
    return manifest


def verify_artifacts(manifest):
    changed = [
        p for p, expected in manifest["private_artifacts"].items() if file_hash(p) != expected
    ]
    if changed:
        raise ValueError("immutable comparison artifacts changed")


def reproduce_historical(root, historical, output):
    """Run the original adapters with original source, redirecting derived writes only.

    This is deliberately separate from the remediated engine. It cannot turn new
    policies into old expected outcomes or dispatch through an uncached provider.
    """
    root, historical, output = map(lambda p: Path(p).resolve(), (root, historical, output))
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    scripts = [
        root / "private/analyze-v3-search-attribution.py",
        root / "private/v3-citation-failure-analysis-2026-11-05/analyze.py",
    ]
    guard_file = Path(__file__).with_name("offline.py")
    bootstrap = """import importlib.util, pathlib, sys
sys.path.insert(0, sys.argv[1])
spec = importlib.util.spec_from_file_location("jev_solver.evaluation.offline", sys.argv[2])
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
script, output = pathlib.Path(sys.argv[3]), pathlib.Path(sys.argv[4])
source = script.read_text()
source = source.replace('atomic_json(PRIVATE / "v3-search-attribution-audit.json", output)',
                        'atomic_json(pathlib_output / "historical-outcomes.json", output)')
source = source.replace('OUT = Path(__file__).resolve().parent', 'OUT = pathlib_output')
namespace = {"__file__": str(script), "__name__": "__main__", "pathlib_output": output}
with guard.offline_dispatch_guard() as attempts:
    exec(compile(source, str(script), "exec"), namespace)
assert not attempts
"""
    for i, script in enumerate(scripts):
        with (output / f"reproduction-{i}.log").open("w") as log:
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    bootstrap,
                    str(historical / "src"),
                    str(guard_file),
                    str(script),
                    str(output),
                ],
                cwd=root,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )
    return {"output": str(output), "external_dispatches": 0}
