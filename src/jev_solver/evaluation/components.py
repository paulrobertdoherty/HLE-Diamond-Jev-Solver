"""Paired component judgments on frozen development evidence, independent of held-out solving."""

from __future__ import annotations

from pathlib import Path

from ..benchmarks.data import read_jsonl
from ..config import Config
from ..controller.budget import Budget
from ..models import QuestionView, digest
from ..providers.backbone import Gateway
from ..providers.jev import Jev
from ..retrieval.evidence import lexical_score
from ..tracing.store import Store, atomic_json


async def components(config: Config, cases: Path, output: Path, judge: str = "jev") -> dict:
    rows = read_jsonl(cases)
    if not rows or any(r.get("stage") not in {"J2", "J3"} for r in rows):
        raise ValueError("component evaluation requires labeled J2/J3 development cases")
    store = Store(output / "components.sqlite3")
    budget = Budget(store, config)
    jev = Jev(config, store, budget)
    gateway = Gateway(config, store, budget)
    result = []
    try:
        store.meta(
            "identity", {"config_hash": config.hash, "cases_hash": digest(rows), "judge": judge}
        )
        for row in rows:
            state = row["state"]
            from ..judgments.pipeline import RELEVANCE, SUPPORT

            spec = RELEVANCE if row["stage"] == "J2" else SUPPORT
            if judge == "jev":
                judged = await jev.request(row["id"], row["stage"], state, {"judgment": spec})
                value = judged["judgment"].value if "judgment" in judged else None
            elif judge == "backbone":
                value_schema = (
                    {"type": "number"}
                    if row["stage"] == "J2"
                    else {"type": "string", "enum": list(SUPPORT["criteria"])}
                )
                schema = {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"judgment": value_schema},
                    "required": ["judgment"],
                }
                response = await gateway.generate(
                    QuestionView(
                        row["id"],
                        "Assess the supplied development evidence against the judgment criteria.",
                    ),
                    {"state": state, "judgment": spec, "numeric_scale": "0 to 1"},
                    "component",
                    schema=schema,
                    final=True,
                )
                value = response["judgment"]
            else:
                if row["stage"] == "J2":
                    value = lexical_score(state["subquestion"], state["passage"])
                else:
                    value = (
                        "supported"
                        if state["claim"] in state["quote"]
                        and state["quote"] in state["source_context"]
                        else "insufficient"
                    )
            expected = row["expected"]
            result.append(
                {
                    "stage": row["stage"],
                    "correct": value == expected,
                    "absolute_error": abs(value - expected)
                    if isinstance(value, (float, int)) and isinstance(expected, (float, int))
                    else None,
                    "unavailable": value is None,
                }
            )
        from statistics import mean

        metrics = {}
        for stage in ("J2", "J3"):
            selected = [r for r in result if r["stage"] == stage]
            numeric = [r["absolute_error"] for r in selected if r["absolute_error"] is not None]
            metrics[stage] = {
                "count": len(selected),
                "accuracy": mean(r["correct"] for r in selected) if selected else None,
                "mean_absolute_error": mean(numeric) if numeric else None,
                "unavailable": sum(r["unavailable"] for r in selected),
            }
        artifact = {
            "judge": judge,
            "metrics": metrics,
            "cost_usd": store.cost(),
            "development_only": True,
        }
        atomic_json(output / "components.json", artifact)
        return artifact
    finally:
        await jev.close()
        await gateway.close()
        store.close()
