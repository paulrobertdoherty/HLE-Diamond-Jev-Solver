"""Publication export is an allowlist of aggregates, never arbitrary traces or metadata."""

from __future__ import annotations

import json
from pathlib import Path
from dataclasses import fields
from datetime import datetime
from ..config import Limits

from ..tracing.store import atomic_json
from .analysis import diagnostics, summary


def safe_summary(grades: list[dict], seed: int) -> dict:
    result = summary(grades, seed)
    # Slice labels come from private data. Export only recognized dimensions and bounded categories.
    allowed = {
        "partition:knowledge",
        "partition:reasoning",
        "modality:image",
        "modality:text",
        "answer_type:exactMatch",
        "answer_type:multipleChoice",
    }
    result["slices"] = {k: v for k, v in result["slices"].items() if k in allowed}
    return result


def public_usage(raw: dict) -> dict:
    fields = {
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "uncertain_cost_upper_usd",
        "accounted_cost_usd",
        "jev_outages",
        "retries_or_errors",
        "model_replays",
        "jev_replays",
    }
    result = {k: v for k, v in raw.items() if k in fields and type(v) in {int, float}}
    result["attempts_by_kind"] = {
        k: v
        for k, v in raw.get("attempts_by_kind", {}).items()
        if k in {"model", "jev", "search", "fetch", "code"} and type(v) is int
    }
    return result


def export_report(artifact: Path, output: Path) -> dict:
    data = json.loads(artifact.read_text())
    manifest = data["manifest"]
    config = manifest["config"]
    result = {
        "synthetic": manifest["synthetic"],
        "run_hash": manifest["run_hash"],
        "config_hash": manifest["config_hash"],
        "dataset": config["dataset"],
        "dataset_revision": config["dataset_revision"],
        "split": manifest["split"],
        "arm": config["arm"],
        "track": config["track"],
        "protocol_hash": manifest["protocol_hash"],
        "backbone": config["provider"]["model"],
        "jev": config["jev"]["model"],
        "grader": data["grader"],
        "budgets": {
            f.name: config["limits"][f.name]
            for f in fields(Limits)
            if type(config["limits"][f.name]) in {int, float}
        },
        "metrics": safe_summary(data["grades"], config["seed"]),
        "candidate_diagnostics": diagnostics(data["grades"]),
        "grading_cost_usd": data["grading_cost_usd"],
        "custom_harness": True,
        "primary_comparison": config["primary_comparison"],
        "measured_benchmark_result": not manifest["synthetic"]
        and config["dataset"] == "cais/hle-diamond",
        "date": manifest.get("created_at"),
        "implementation_hash": manifest["implementation_hash"],
        "dependency_lock_hash": manifest["lock_hash"],
        "usage": public_usage(data.get("usage", {})),
        "contamination_audit": {
            k: v
            for k, v in manifest.get("contamination_audit", {}).items()
            if k
            in {
                "attempted_calls",
                "blocked_calls",
                "replayed_calls",
                "exposed_count",
                "rerun_count",
            }
            and type(v) is int
        },
        "protocol_departures": ["custom-harness"]
        + (["persistent-corpus", "hashed-character-features"] if config["corpus"] else []),
        "contamination_sensitivity": safe_summary(
            [g for g in data["grades"] if not g.get("contaminated")], config["seed"]
        )
        if any(g.get("contaminated") for g in data["grades"])
        and any(not g.get("contaminated") for g in data["grades"])
        else None,
    }
    # Config strings can contain accidental question text. Export only constrained identity fields.
    import re

    for name in ("dataset", "dataset_revision", "backbone", "jev", "grader", "primary_comparison"):
        if not re.fullmatch(r"[A-Za-z0-9_./:+-]{1,160}", result[name]):
            raise ValueError(f"unsafe publication identity field: {name}")
    for key in (
        "run_hash",
        "config_hash",
        "protocol_hash",
        "implementation_hash",
        "dependency_lock_hash",
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", result[key]):
            raise ValueError("invalid publication hash")
    if result["date"]:
        result["date"] = datetime.fromisoformat(result["date"]).isoformat()
    if (
        result["arm"] not in {"B0", "B1", "B2", "J2", "J3", "J23", "Jfull", "M", "R"}
        or result["track"] not in {"closed", "controlled", "extended"}
        or result["split"] not in {"full", "development", "heldout"}
    ):
        raise ValueError("invalid publication track identity")
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(output / "report.json", result)
    metrics = result["metrics"]
    text = (
        f"# {'Synthetic fixture' if result['synthetic'] else 'Custom harness'} report\n\n"
        f"Arm: {result['arm']}; track: {result['track']}; questions: {metrics['questions']}.\n\n"
        f"Accuracy: {metrics['accuracy']:.1%}; 95% bootstrap interval: "
        f"{metrics['accuracy_ci95'][0]:.1%}–{metrics['accuracy_ci95'][1]:.1%}.\n\n"
        f"Solver cost: ${metrics['total_cost_usd']:.6f}; grading cost: ${data['grading_cost_usd']:.6f}.\n\n"
        "This is an independent custom harness. Synthetic fixtures are not benchmark measurements.\n"
    )
    (output / "report.md").write_text(text)
    # Standalone vector reliability plot without a plotting dependency or private strings.
    points = []
    for row in metrics["reliability"]:
        if row["count"]:
            points.append(
                f'<circle cx="{40 + 320 * row["confidence"]:.2f}" cy="{360 - 320 * row["accuracy"]:.2f}" r="5" fill="#2255aa"/>'
            )
    (output / "reliability.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="440" height="410" viewBox="0 0 440 410"><rect width="440" height="410" fill="white"/><path d="M40 40 V360 H360 M40 360 L360 40" fill="none" stroke="#888"/><text x="130" y="395">Declared confidence</text><text x="45" y="25">Observed accuracy</text>'
        + "".join(points)
        + "</svg>"
    )
    return {
        "questions": metrics["questions"],
        "synthetic": result["synthetic"],
        "files": ["report.json", "report.md", "reliability.svg"],
    }
