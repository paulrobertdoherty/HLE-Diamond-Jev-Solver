from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .config import Config, verify_protocol


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Jev evidence-handling experiment harness")
    sub = p.add_subparsers(dest="command", required=True)
    for command in ("validate", "estimate"):
        s = sub.add_parser(command)
        s.add_argument("--config", type=Path, required=True)
        if command == "estimate":
            s.add_argument("--items", type=int, required=True)
    s = sub.add_parser("prepare")
    s.add_argument("--output", type=Path, required=True)
    s.add_argument("--revision", default="")
    inputs = s.add_mutually_exclusive_group()
    inputs.add_argument("--fixture", type=Path)
    inputs.add_argument("--development-file", type=Path)
    s.add_argument("--dev-count", type=int, default=0)
    s.add_argument("--seed", type=int, default=17)
    s.add_argument("--text-only", action="store_true")
    for command in ("run", "resume"):
        s = sub.add_parser(command)
        s.add_argument("--config", type=Path, required=True)
        s.add_argument("--questions", type=Path, required=True)
        s.add_argument("--output", type=Path, required=True)
        s.add_argument("--split", choices=["full", "development", "heldout"], default="full")
    s = sub.add_parser("grade")
    s.add_argument("--run", type=Path, required=True)
    s.add_argument("--labels", type=Path, required=True)
    s.add_argument("--output", type=Path, required=True)
    s.add_argument("--grader-config", type=Path)
    s.add_argument("--oracle", action="store_true")
    s = sub.add_parser("compare")
    s.add_argument("--arm-a", type=Path, nargs="+", required=True)
    s.add_argument("--arm-b", type=Path, nargs="+", required=True)
    s.add_argument("--output", type=Path, required=True)
    s.add_argument("--seed", type=int, default=17)
    s.add_argument("--target-gain", type=float, default=0.05)
    s = sub.add_parser("export")
    s.add_argument("--grades", type=Path, required=True)
    s.add_argument("--output", type=Path, required=True)
    s = sub.add_parser("audit")
    s.add_argument("--run", type=Path, required=True)
    s.add_argument("--flags", type=Path, help="private JSON list of exposed item IDs")
    s = sub.add_parser("corpus-build")
    s.add_argument("--documents", type=Path, required=True)
    s.add_argument("--output", type=Path, required=True)
    s.add_argument("--revision", required=True)
    s = sub.add_parser("component-eval")
    s.add_argument("--config", type=Path, required=True)
    s.add_argument("--cases", type=Path, required=True)
    s.add_argument("--output", type=Path, required=True)
    s.add_argument("--judge", choices=["jev", "backbone", "lexical"], default="jev")
    return p


def execute(args) -> dict:
    if args.command in {"validate", "estimate"}:
        config = Config.load(args.config)
        protocol = verify_protocol(config.protocol_manifest)
        if args.command == "validate":
            return {
                "valid": True,
                "config_hash": config.hash,
                "protocol_commit": protocol["upstream_commit"],
                "live": config.live,
            }
        if args.items <= 0:
            raise ValueError("positive item count required")
        from .providers.backbone import upper_cost

        return {
            "items": args.items,
            "paid_calls_dispatched": 0,
            "model_call_reservation_usd": upper_cost(config.provider),
            "jev_call_reservation_usd": upper_cost(config.jev),
            "item_cap_usd": config.limits.item_usd,
            "run_envelope_usd": min(config.limits.run_usd, args.items * config.limits.item_usd),
            "note": "Conservative envelope, not predicted billed spend. Unknown failures retain full reservation.",
        }
    if args.command == "prepare":
        from .benchmarks.data import prepare

        result = prepare(
            args.output,
            args.revision,
            args.fixture or args.development_file,
            args.dev_count,
            args.seed,
            args.text_only,
            development=bool(args.development_file),
        )
        return {k: v for k, v in result.items() if k != "schema"}
    if args.command in {"run", "resume"}:
        from .controller.engine import run

        def progress(info):
            print(json.dumps(info), file=sys.stderr, flush=True)

        return asyncio.run(
            run(
                Config.load(args.config),
                args.questions,
                args.output,
                args.command == "resume",
                args.split,
                progress,
            )
        )
    if args.command == "grade":
        from .evaluation.grading import grade

        return asyncio.run(
            grade(
                args.run,
                args.labels,
                args.output,
                Config.load(args.grader_config) if args.grader_config else None,
                args.oracle,
            )
        )
    if args.command == "compare":
        from .evaluation.analysis import diagnostics, paired, summary
        from .tracing.store import atomic_json

        a = [g for p in args.arm_a for g in json.loads(p.read_text())["grades"]]
        b = [g for p in args.arm_b for g in json.loads(p.read_text())["grades"]]
        result = {
            "paired": paired(a, b, args.seed, args.target_gain),
            "arm_a": summary(a, args.seed),
            "arm_b": summary(b, args.seed),
            "candidate_diagnostics_a": diagnostics(a),
            "candidate_diagnostics_b": diagnostics(b),
            "comparison": "Equal declared workload; use frozen budgets for matched-cost studies",
        }
        atomic_json(args.output, result)
        return result["paired"]
    if args.command == "export":
        from .evaluation.export import export_report

        return export_report(args.grades, args.output)
    if args.command == "audit":
        from .tracing.audit import audit

        return audit(args.run, args.flags)
    if args.command == "corpus-build":
        from .retrieval.corpus import build_corpus
        from .tools.policy import Policy

        return build_corpus(
            args.documents,
            args.output,
            Policy(Path("protocol/upstream/blocklist.json")),
            args.revision,
        )
    if args.command == "component-eval":
        from .evaluation.components import components

        return asyncio.run(
            components(Config.load(args.config), args.cases, args.output, args.judge)
        )
    raise ValueError("unknown operation")


def main():
    try:
        result = execute(parser().parse_args())
        print(json.dumps(result, indent=2, allow_nan=False))
    except KeyboardInterrupt:
        print("Interrupted; resume with the same frozen config and inputs.", file=sys.stderr)
        raise SystemExit(130) from None
    except (ValueError, KeyError, OSError, RuntimeError) as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        raise SystemExit(2) from None
