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
        s.add_argument(
            "--question-id",
            action="append",
            default=[],
            help="select an original ID within the split; repeat for multiple IDs",
        )
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
    s.add_argument("--judge", choices=["jev", "backbone", "lexical", "stored"], default="jev")
    s = sub.add_parser("workflow-eval")
    s.add_argument("--cases", type=Path, required=True)
    s.add_argument("--output", type=Path, required=True)
    s = sub.add_parser("attribution-extract")
    s.add_argument("--audit", type=Path, required=True)
    s.add_argument("--index", type=Path, required=True)
    s.add_argument("--questions", type=Path, required=True)
    s.add_argument("--output", type=Path, required=True)
    s = sub.add_parser("audit-eval")
    s.add_argument("--config", type=Path, required=True)
    s.add_argument("--cases", type=Path, required=True)
    s.add_argument("--output", type=Path, required=True)
    s.add_argument("--repeats", type=int, default=1)
    s = sub.add_parser("search-eval")
    s.add_argument("--config", type=Path, required=True)
    s.add_argument("--queries", type=Path, required=True)
    s.add_argument("--output", type=Path, required=True)
    source = s.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot", type=Path)
    source.add_argument("--live", action="store_true")
    s.add_argument("--fetch-budget", type=int, default=4)
    s.add_argument("--result-limit", type=int, default=20)
    s = sub.add_parser("replay-validate")
    s.add_argument("--manifest", type=Path, required=True)
    s = sub.add_parser("remediation-freeze")
    s.add_argument("--baseline", required=True)
    s.add_argument("--historical", type=Path)
    s.add_argument("--artifact", type=Path, action="append", default=[])
    s.add_argument("--output", type=Path, required=True)
    s = sub.add_parser("replay-freeze")
    s.add_argument("--experiment-id", required=True)
    s.add_argument("--arm", action="append", required=True)
    s.add_argument(
        "--source-root",
        action="append",
        default=[],
        help="ARM_ID=frozen/source/tree for the exact comparison implementation",
    )
    s.add_argument("--questions", type=Path, required=True)
    s.add_argument("--baseline", required=True)
    s.add_argument("--historical-hash", required=True)
    s.add_argument("--aggregate-usd", type=float, required=True)
    s.add_argument("--replications", type=int, default=1)
    s.add_argument(
        "--comparison",
        choices=[
            "integrated",
            "generation",
            "matched-j23",
            "routing",
            "deterministic",
            "retrieval-j2",
            "support-j3",
            "verification",
            "matched-cost",
        ],
        default="integrated",
    )
    s.add_argument("--frozen", type=Path)
    s.add_argument("--output", type=Path, required=True)
    s = sub.add_parser("replay-run")
    s.add_argument("--manifest", type=Path, required=True)
    s.add_argument("--arm", action="append", required=True)
    s.add_argument("--questions", type=Path, required=True)
    s.add_argument("--output", type=Path, required=True)
    s.add_argument("--frozen", type=Path)
    s.add_argument(
        "--launch",
        action="store_true",
        help="explicitly launch fresh paid calls under the frozen caps",
    )
    s.add_argument("--resume", action="store_true")
    s = sub.add_parser("replay-report")
    s.add_argument("--manifest", type=Path, required=True)
    s.add_argument(
        "--arm",
        action="append",
        required=True,
        help="ARM_ID=private/grades.json; repeat for each declared arm",
    )
    s.add_argument("--workflow-cases", type=Path)
    s.add_argument("--output", type=Path, required=True)
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
            "rounds": config.limits.rounds,
            "maximum_j2_passages_per_round": config.relevance.shortlist,
            "finalization_call_reserve": config.limits.finalization_calls,
            "finalization_dollar_reserve": config.limits.finalization_usd,
            "finalization_model_calls_covered_by_dollar_reserve": int(
                config.limits.finalization_usd / upper_cost(config.provider)
            )
            if upper_cost(config.provider)
            else None,
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
                tuple(args.question_id),
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
    if args.command == "workflow-eval":
        from .evaluation.components import workflow_metrics

        return workflow_metrics(args.cases, args.output)
    if args.command == "attribution-extract":
        from .evaluation.labels import extract_cases

        return extract_cases(args.audit, args.index, args.output, args.questions)
    if args.command == "audit-eval":
        from .evaluation.audits import audit_evaluation

        return asyncio.run(
            audit_evaluation(Config.load(args.config), args.cases, args.output, args.repeats)
        )
    if args.command == "search-eval":
        from .evaluation.search import search_comparison

        return asyncio.run(
            search_comparison(
                Config.load(args.config),
                args.queries,
                args.output,
                snapshot=args.snapshot,
                live=args.live,
                result_limit=args.result_limit,
                fetch_budget=args.fetch_budget,
            )
        )
    if args.command == "replay-validate":
        from .evaluation.replay import validate_manifest
        from .models import digest

        manifest = validate_manifest(json.loads(args.manifest.read_text()))
        return {"valid": True, "manifest_hash": digest(manifest), "paid_calls_dispatched": 0}
    if args.command == "remediation-freeze":
        from .evaluation.remediation import freeze_comparison

        result = freeze_comparison(
            Path.cwd(),
            args.baseline,
            args.output,
            artifacts=args.artifact,
            historical=args.historical,
        )
        return {"baseline_revision": result["baseline_revision"], "paid_calls_dispatched": 0}
    if args.command in {"replay-freeze", "replay-run"}:
        configs = {}
        config_paths = {}
        for value in args.arm:
            identifier, separator, path = value.partition("=")
            if not separator or not identifier or identifier in configs:
                raise ValueError("provide each arm once as ARM_ID=config.json")
            configs[identifier] = Config.load(path)
            config_paths[identifier] = Path(path)
        frozen = json.loads(args.frozen.read_text()) if args.frozen else []
        if args.command == "replay-freeze":
            from .evaluation.manifests import freeze_manifest
            from .benchmarks.data import load_questions, load_split
            from .tracing.store import atomic_json

            if args.output.exists():
                raise ValueError("frozen experiment already exists; use a new identity")
            source_roots = {}
            for value in args.source_root:
                identifier, separator, path = value.partition("=")
                if not separator or identifier not in configs or identifier in source_roots:
                    raise ValueError("provide each isolated source as ARM_ID=PATH")
                source_roots[identifier] = Path(path)
            questions = load_questions(args.questions)
            if any(c.live for c in configs.values()):
                data_manifest = json.loads((args.questions.parent / "manifest.json").read_text())
                split = load_split(
                    args.questions.parent / "split.json", questions, data_manifest.get("split_hash")
                )
                questions = [q for q in questions if q.id in set(split["development"])]
            result = freeze_manifest(
                args.experiment_id,
                configs,
                [q.id for q in questions],
                baseline_revision=args.baseline,
                historical_implementation_hash=args.historical_hash,
                aggregate_usd=args.aggregate_usd,
                replications=args.replications,
                comparison_kind=args.comparison,
                frozen=frozen,
                source_roots=source_roots,
                config_paths=config_paths,
                question_views=questions,
            )
            atomic_json(args.output, result)
            return {"manifest": str(args.output), "paid_calls_dispatched": 0}
        from .evaluation.orchestration import run_experiment

        return asyncio.run(
            run_experiment(
                json.loads(args.manifest.read_text()),
                config_paths,
                args.questions,
                args.output,
                frozen=frozen,
                launch=args.launch,
                resume=args.resume,
            )
        )
    if args.command == "replay-report":
        from .evaluation.replay import controlled_comparison
        from .tracing.store import atomic_json

        grades = {}
        for value in args.arm:
            arm, separator, path = value.partition("=")
            if not separator or not arm or arm in grades:
                raise ValueError("provide each declared arm once as ARM_ID=grades.json")
            grades[arm] = json.loads(Path(path).read_text())["grades"]
        workflow = []
        if args.workflow_cases:
            from .benchmarks.data import read_jsonl
            from .evaluation.labels import load_cases, workflow_rows

            workflow = read_jsonl(args.workflow_cases)
            workflow = (
                workflow_rows(load_cases(args.workflow_cases))
                if workflow and workflow[0].get("version") == 1
                else [r for r in workflow if r.get("label_status") != "unresolved"]
            )
        result = controlled_comparison(
            json.loads(args.manifest.read_text()), grades, workflow_rows=workflow
        )
        atomic_json(args.output, result)
        return result
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
