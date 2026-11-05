"""Controlled component replay manifests and a ledger for reused versus fresh behavior."""

from copy import deepcopy

from ..models import digest
from .offline import FrozenResponses, OfflineDispatchForbidden

COMPONENTS = {"initial", "query", "search", "fetch", "J2", "J3", "audit", "revision", "selection"}
REMEDIATION_COMPONENTS = COMPONENTS | {
    "contract",
    "structure",
    "shortlist",
    "packet",
    "context",
    "decomposition",
    "support_aggregation",
    "applicability",
    "generation_recovery",
}


def validate_manifest(manifest):
    if (
        manifest.get("version") not in {1, 2}
        or manifest.get("split") != "development"
        or manifest.get("policy_frozen") is not True
    ):
        raise ValueError("replay requires a frozen development policy and supported version")
    components = COMPONENTS if manifest["version"] == 1 else REMEDIATION_COMPONENTS
    if manifest["version"] == 2:
        import math

        for key in (
            "baseline_revision",
            "historical_implementation_hash",
            "comparison_kind",
            "backend",
        ):
            if not isinstance(manifest.get(key), str) or not manifest[key]:
                raise ValueError(f"remediation manifest requires {key}")
        if manifest["backend"] not in {"mock", "brave", "perplexity"}:
            raise ValueError("block experiments by a single search backend")
        caps = manifest.get("spend_caps", {})
        if set(caps) != {"item_usd", "run_usd", "aggregate_usd"} or any(
            type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in caps.values()
        ):
            raise ValueError("freeze positive item/run/aggregate spend caps")
        if not caps["item_usd"] <= caps["run_usd"] <= caps["aggregate_usd"]:
            raise ValueError("inconsistent experiment spend caps")
    for key in ("experiment_id", "evidence_policy", "acceptance", "shared", "arms"):
        if not manifest.get(key):
            raise ValueError(f"missing replay manifest field: {key}")
    acceptance = manifest["acceptance"]
    if (
        type(acceptance.get("replications")) is not int
        or acceptance["replications"] < 1
        or not isinstance(acceptance.get("criteria"), str)
        or not acceptance["criteria"].strip()
    ):
        raise ValueError("predeclare replication and acceptance criteria")
    shared = manifest["shared"]
    for key in (
        "questions_hash",
        "initial_candidates_hash",
        "queries_hash",
        "results_hash",
        "pages_hash",
    ):
        if not isinstance(shared.get(key), str) or not shared[key]:
            raise ValueError("replay must identify shared initial inputs and source snapshots")
    arms = manifest["arms"]
    if not isinstance(arms, list) or len(arms) < 2 or len({a["id"] for a in arms}) != len(arms):
        raise ValueError("replay requires distinct paired arms")
    for arm in arms:
        if manifest["version"] == 2:
            import re

            if not re.fullmatch(r"[A-Za-z0-9_-]+", arm["id"]):
                raise ValueError("invalid experiment arm identifier")
        if any(not arm.get(k) for k in ("id", "config_hash", "implementation_hash", "components")):
            raise ValueError("arm requires configuration, implementation and component versions")
        if set(arm["components"]) != components or any(
            not isinstance(value, dict)
            or any(
                not value.get(k)
                for k in (
                    ("implementation", "model", "prompt", "schema")
                    if manifest["version"] == 2
                    else ("implementation", "model", "prompt")
                )
            )
            for value in arm["components"].values()
        ):
            raise ValueError("identify every component's implementation, model and prompt")
        changed = arm.get("changed_components", [])
        if not isinstance(changed, list) or not set(changed) <= components:
            raise ValueError("unknown intervention component")
        actual = {key for key in components if arm["components"][key] != arms[0]["components"][key]}
        if actual != set(changed):
            raise ValueError("declared intervention differs from component identities")
    return deepcopy(manifest)


class ControlledReplay:
    def __init__(self, manifest, frozen=()):
        self.manifest = validate_manifest(manifest)
        self.frozen = FrozenResponses(frozen)
        self.ledger = []
        self.generated = {}

    def contract(self, arm_id, component, inputs):
        arm = next((a for a in self.manifest["arms"] if a["id"] == arm_id), None)
        if arm is None or component not in arm["components"]:
            raise ValueError("unknown replay arm/component")
        return {
            "component": component,
            "identity": arm["components"][component],
            "inputs": inputs,
            "evidence_policy": self.manifest["evidence_policy"],
        }

    async def request(self, arm_id, component, inputs, *, generate=None):
        contract = self.contract(arm_id, component, inputs)
        entry = {"arm": arm_id, "component": component, "input_hash": digest(contract)}
        if digest(contract) in self.generated:
            self.ledger.append({**entry, "behavior": "generated_reuse"})
            return deepcopy(self.generated[digest(contract)]["response"])
        try:
            response = self.frozen.replay(contract)
            entry["behavior"] = "frozen"
        except OfflineDispatchForbidden:
            if generate is None:
                self.ledger.append({**entry, "behavior": "unavailable"})
                raise
            entry["behavior"] = "new_call"
            self.ledger.append(entry)
            try:
                response = await generate(deepcopy(inputs))
                self.generated[digest(contract)] = {
                    "contract": contract,
                    "response": deepcopy(response),
                }
                return response
            except BaseException:
                entry["failed"] = True
                raise
        self.ledger.append(entry)
        return response


def controlled_comparison(manifest, grades_by_arm, *, seed=17, workflow_rows=()):
    """Pair complete declared trials, including abstentions and solver failures."""
    from collections import defaultdict
    from statistics import mean

    from .analysis import paired, summary
    from .workflows import extra_workflow_metrics

    manifest = validate_manifest(manifest)
    ids = [arm["id"] for arm in manifest["arms"]]
    if set(grades_by_arm) != set(ids):
        raise ValueError("grades must cover exactly the declared arms")
    replications = manifest["acceptance"]["replications"]
    expected_trials = None
    reports, differences = {}, {}
    for arm in ids:
        rows = grades_by_arm[arm]
        trials = {(r["question_id"], r.get("replicate", 0)) for r in rows}
        questions = {r["question_id"] for r in rows}
        if (
            len(trials) != len(rows)
            or trials != {(q, rep) for q in questions for rep in range(replications)}
            or not rows
        ):
            raise ValueError("missing or duplicate declared question/replication trials")
        if digest(sorted(questions)) != manifest["shared"]["questions_hash"]:
            raise ValueError("grades differ from the declared question set")
        if expected_trials is not None and trials != expected_trials:
            raise ValueError("paired arms differ in declared trials, including failures")
        expected_trials = trials
        reports[arm] = summary(rows, seed)
        answered = [r for r in rows if r["status"] == "completed" and not r.get("abstained", False)]
        reports[arm]["wrong_answer_acceptance"] = {
            "numerator": sum(not r["correct"] for r in answered),
            "denominator": len(answered),
            "value": mean(not r["correct"] for r in answered) if answered else None,
        }
        if arm != ids[0]:
            differences[arm] = paired(rows, grades_by_arm[ids[0]], seed)
            clustered = defaultdict(list)
            baseline = defaultdict(list)
            for row in rows:
                clustered[row["question_id"]].append(row["correct"])
            for row in grades_by_arm[ids[0]]:
                baseline[row["question_id"]].append(row["correct"])
            differences[arm]["question_differences"] = {
                q: mean(clustered[q]) - mean(baseline[q]) for q in sorted(questions)
            }
    return {
        "manifest_hash": digest(manifest),
        "arms": reports,
        "paired_against_baseline": differences,
        "workflow": extra_workflow_metrics(workflow_rows),
        "workflow_by_arm": {
            arm: extra_workflow_metrics([row for row in workflow_rows if row.get("arm") == arm])
            for arm in ids
        },
        "development_only": True,
        "promotion": {
            arm: {
                "point_estimate_gate": reports[arm]["accuracy"] > reports[ids[0]]["accuracy"]
                and reports[arm]["wrong_answer_acceptance"]["numerator"]
                <= reports[ids[0]]["wrong_answer_acceptance"]["numerator"],
                "conclusion": "inconclusive"
                if differences[arm]["difference_ci95"][0] <= 0
                else "paired improvement; deterministic and semantic gates still required",
            }
            for arm in ids[1:]
        },
    }
