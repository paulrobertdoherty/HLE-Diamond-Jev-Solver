"""Fresh Sol audits on frozen inputs; independent labels never enter requests."""

from pathlib import Path

from ..config import Config
from ..controller.budget import Budget
from ..judgments.verification import AUDIT_SCHEMA, parse_audit
from ..models import QuestionView, digest
from ..providers.backbone import Gateway, ProviderError
from ..tracing.store import Store, atomic_json
from .labels import load_cases, provider_input
from .workflows import extra_workflow_metrics


async def audit_evaluation(config: Config, cases: Path, output: Path, repeats=1):
    if type(repeats) is not int or not 1 <= repeats <= 10:
        raise ValueError("audit repeats must be in [1,10]")
    rows = [row for row in load_cases(cases) if row["component"] == "audit"]
    if not rows:
        raise ValueError("no frozen audit inputs")
    store = Store(output / "audits.sqlite3")
    gateway = Gateway(config, store, Budget(store, config))
    observations, labeled = [], []
    try:
        store.meta(
            "identity", {"config_hash": config.hash, "cases_hash": digest(rows), "repeats": repeats}
        )
        for row in rows:
            inputs = provider_input(row)
            question = QuestionView.parse(inputs["question"])
            for repeat in range(repeats):
                observation = {
                    "case_id": row["id"],
                    "input_hash": row["input_hash"],
                    "repeat": repeat,
                }
                try:
                    raw = await gateway.generate(
                        question,
                        inputs["context"],
                        f"component-audit-{row['id']}-{repeat}",
                        schema=AUDIT_SCHEMA,
                        final=True,
                    )
                    observation["response"] = parse_audit(raw)
                    if (
                        row["label"]["status"] == "adjudicated"
                        and "gold_dependencies" in row["label"]["values"]
                    ):
                        labeled.append(
                            {
                                "stage": "audit",
                                "input_hash": row["input_hash"],
                                "gold_dependencies": row["label"]["values"]["gold_dependencies"],
                                "observed_dependencies": raw["dependencies"],
                            }
                        )
                except (ProviderError, ValueError, KeyError, TypeError) as error:
                    observation["error"] = type(error).__name__
                    if (
                        row["label"]["status"] == "adjudicated"
                        and "gold_dependencies" in row["label"]["values"]
                    ):
                        labeled.append(
                            {
                                "stage": "audit",
                                "input_hash": row["input_hash"],
                                "gold_dependencies": row["label"]["values"]["gold_dependencies"],
                                "observed_dependencies": [],
                            }
                        )
                observations.append(observation)
        artifact = {
            "observations": observations,
            "metrics": extra_workflow_metrics(labeled),
            "unresolved_cases": sum(row["label"]["status"] != "adjudicated" for row in rows),
            "errors": sum("error" in r for r in observations),
            "usage": store.usage_summary(),
            "development_only": True,
        }
        atomic_json(output / "audits.json", artifact)
        return {k: v for k, v in artifact.items() if k != "observations"}
    finally:
        await gateway.close()
        store.close()
