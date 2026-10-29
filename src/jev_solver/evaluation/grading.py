"""Separate evaluator entrypoint. Solver modules never import this module or labels."""

from __future__ import annotations

import ast
import asyncio
import json
import os
import sqlite3
import warnings
from functools import lru_cache
from pathlib import Path

from ..benchmarks.data import read_jsonl
from ..candidates.selection import normalize
from ..config import Config, verify_protocol
from ..controller.budget import Budget
from ..models import Grade, digest, probability, record
from ..providers.backbone import ProviderError, cost, upper_cost
from ..tracing.store import Store, atomic_json

GRADER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "extracted_final_answer": {"type": "string"},
        "reasoning": {"type": "string"},
        "correct": {"type": "string", "enum": ["yes", "no"]},
        "confidence": {"type": "integer"},
        "strict": {"type": "boolean", "enum": [True]},
    },
    "required": ["extracted_final_answer", "reasoning", "correct", "confidence", "strict"],
}


@lru_cache(maxsize=1)
def official_prompt() -> str:
    # Parse a pinned literal without importing upstream executable module-level code.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(Path("protocol/upstream/run_judge_results.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "JUDGE_PROMPT" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise ValueError("pinned official grader prompt missing")


def finalized_predictions(run: Path) -> tuple[dict, list[dict]]:
    db = sqlite3.connect(f"file:{(run / 'events.sqlite3').resolve()}?mode=ro", uri=True)
    try:
        row = db.execute("SELECT value FROM meta WHERE key='finalized'").fetchone()
        if not row or json.loads(row[0]) is not True:
            raise ValueError("predictions must be finalized before labels are joined")
        manifest = json.loads((run / "manifest.json").read_text())
        base_manifest = {k: v for k, v in manifest.items() if k not in {"run_hash", "created_at"}}
        stored_hash = json.loads(
            db.execute("SELECT value FROM meta WHERE key='run_hash'").fetchone()[0]
        )
        if digest(base_manifest) != manifest["run_hash"] or stored_hash != manifest["run_hash"]:
            raise ValueError("run manifest changed after finalization")
        stored = [
            json.loads(r[0])
            for r in db.execute(
                "SELECT prediction FROM items WHERE prediction IS NOT NULL ORDER BY id"
            )
        ]
        predictions = json.loads((run / "predictions.json").read_text())
        if digest(predictions) != digest(stored):
            raise ValueError("prediction file changed after durable finalization")
        ids = [p["question_id"] for p in predictions]
        if len(set(ids)) != len(ids) or set(ids) != set(manifest["declared_ids"]):
            raise ValueError("finalized predictions must cover the full declared set exactly once")
        flags_path = run / "contamination.json"
        if flags_path.exists():
            flags = json.loads(flags_path.read_text())
            if flags["run_hash"] != manifest["run_hash"]:
                raise ValueError("contamination audit belongs to a different run")
            exposed = set(flags["exposed_ids"])
            predictions = [
                {**p, "contaminated": p.get("contaminated", False) or p["question_id"] in exposed}
                for p in predictions
            ]
            manifest["contamination_audit"] = {k: v for k, v in flags.items() if k != "exposed_ids"}
        return manifest, predictions
    finally:
        db.close()


async def grade(
    run: Path, labels_file: Path, output: Path, grader: Config | None = None, oracle: bool = False
) -> dict:
    manifest, predictions = finalized_predictions(run)
    labels = read_jsonl(labels_file)
    references = {r["id"]: r for r in labels}
    if len(references) != len(labels) or not set(manifest["declared_ids"]) <= set(references):
        raise ValueError("missing or duplicate reference IDs")
    if (
        manifest["dataset_manifest"]
        and manifest["dataset_manifest"]["dataset"] != manifest["config"]["dataset"]
    ):
        raise ValueError("unexpected dataset identity")
    preparation_path = labels_file.parent.parent / "manifest.json"
    if preparation_path.exists():
        preparation = json.loads(preparation_path.read_text())
        if preparation["labels_hash"] != digest(labels):
            raise ValueError("reference labels changed after authenticated preparation")
        if preparation["solver_hash"] != manifest["dataset_manifest"]["solver_hash"]:
            raise ValueError("reference labels belong to a different dataset preparation")
    elif not manifest["synthetic"]:
        raise ValueError("live grading requires a label preparation manifest")
    if not manifest["synthetic"]:
        if grader is None or grader.provider.kind != "openai":
            raise ValueError("live evaluation requires an explicit separate OpenAI grader config")
        if not os.environ.get("GRADER_OPENAI_API_KEY"):
            raise ValueError("GRADER_OPENAI_API_KEY required; solver credentials are not reused")
        grader.validate()
    verify_protocol("protocol/manifest.json")
    if output.resolve() == run.resolve() or run.resolve() in output.resolve().parents:
        raise ValueError("evaluator output must be outside the solver run directory")
    store = Store(output / "grading.sqlite3")
    eval_config = grader or Config(arm="B0", track="closed")
    budget = Budget(store, eval_config)
    client = None
    identity = {
        "run_hash": manifest["run_hash"],
        "prediction_hash": digest(predictions),
        "labels_hash": digest(labels),
        "grader_config_hash": eval_config.hash,
        "grader_prompt_hash": digest(official_prompt()),
        "oracle": oracle,
    }
    try:
        store.meta("identity", identity)
        if not manifest["synthetic"]:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                api_key=os.environ["GRADER_OPENAI_API_KEY"], max_retries=0, timeout=120
            )

        async def judge(qid: str, answer: str, confidence: float, verification: str = "") -> bool:
            if not answer:
                return False
            reference = references[qid]
            if manifest["synthetic"]:
                return normalize(answer) == normalize(reference["answer"])
            response_text = (
                f"Explanation: {verification}\nAnswer: {answer}\nConfidence: {confidence * 100}%"
            )
            prompt = official_prompt().format(
                question=reference["question"],
                correct_answer=reference["answer"],
                response=response_text,
            )
            key = digest(
                {
                    "prompt": prompt,
                    "provider": record(eval_config.provider),
                    "schema": GRADER_SCHEMA,
                }
            )
            cached = store.cached(qid, key)
            if cached is None:
                if len(prompt.encode()) + 2048 > eval_config.provider.max_input_tokens:
                    raise ValueError("grader input exceeds token envelope")

                async def call():
                    try:
                        response = await client.responses.create(
                            model=eval_config.provider.model,
                            store=False,
                            input=prompt,
                            **(
                                {"reasoning": {"effort": eval_config.provider.reasoning_effort}}
                                if eval_config.provider.reasoning_effort
                                else {}
                            ),
                            **(
                                {"temperature": eval_config.provider.temperature}
                                if eval_config.provider.temperature is not None
                                else {}
                            ),
                            max_output_tokens=eval_config.provider.max_output_tokens,
                            text={
                                "format": {
                                    "type": "json_schema",
                                    "name": "official_grade",
                                    "strict": True,
                                    "schema": GRADER_SCHEMA,
                                }
                            },
                        )
                    except Exception as e:
                        status = getattr(e, "status_code", None)
                        raise ProviderError(
                            "grader failed", status == 429 or (status is not None and status >= 500)
                        ) from None
                    usage = response.usage.model_dump()
                    return {
                        "text": response.output_text,
                        "model": response.model,
                        "status": response.status,
                        "usage": usage,
                        "cost_usd": cost(eval_config.provider, usage),
                    }

                raw = await budget.execute(
                    qid, "model", upper_cost(eval_config.provider), call, final=True
                )
                store.event(qid, "grader", raw)
                if raw["model"] != eval_config.provider.model or raw["status"] != "completed":
                    raise ValueError("grader model changed or incomplete response")
                cached = json.loads(raw["text"])
                if (
                    set(cached) != set(GRADER_SCHEMA["required"])
                    or cached["correct"] not in {"yes", "no"}
                    or cached["strict"] is not True
                    or type(cached["confidence"]) is not int
                    or not 0 <= cached["confidence"] <= 100
                ):
                    raise ValueError("invalid grader response")
                store.cache(qid, key, cached)
            return cached["correct"] == "yes"

        async def one(p):
            qid = p["question_id"]
            # Older final grades omitted oracle labels for failed solves.
            prior = store.cached(qid, "final_grade_v2")
            if prior is not None:
                return prior
            confidence = probability(p["confidence"])
            correct, oracle_correct, status = False, None, p["status"]
            try:
                if status == "completed":
                    correct = await judge(qid, p["answer"], confidence, p.get("verification", ""))
                if oracle:
                    oracle_correct = correct
                    for candidate in p["candidate_answers"]:
                        if not oracle_correct:
                            oracle_correct = await judge(qid, candidate, 0)
            except Exception as e:
                status = "grader_error"
                oracle_correct = None
                store.event(qid, "grader_error", {"error_type": type(e).__name__})
            g = record(
                Grade(
                    qid,
                    correct,
                    confidence,
                    status,
                    references[qid]["slices"],
                    p["cost_usd"],
                    p["latency_s"],
                    oracle_correct,
                    p.get("contaminated", False),
                    p.get("abstained", False),
                )
            )
            # Grader errors stay retryable on a later isolated grade invocation.
            if status != "grader_error":
                store.cache(qid, "final_grade_v2", g)
            return g

        semaphore = asyncio.Semaphore(eval_config.limits.concurrency)

        async def bounded(p):
            async with semaphore:
                return await one(p)

        grades = await asyncio.gather(*(bounded(p) for p in predictions))
        artifact = {
            "identity": identity,
            "manifest": manifest,
            "grades": grades,
            "grading_cost_usd": store.cost(),
            "usage": json.loads((run / "usage.json").read_text()),
            "grader": eval_config.provider.model if grader else "synthetic-exact-v1",
        }
        atomic_json(output / "grades.json", artifact)
        return {
            "count": len(grades),
            "correct": sum(g["correct"] for g in grades),
            "grading_cost_usd": store.cost(),
            "grader_errors": sum(g["status"] == "grader_error" for g in grades),
        }
    finally:
        if client:
            await client.close()
        store.close()
