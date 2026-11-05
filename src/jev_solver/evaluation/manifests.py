"""Build explicit version-2 development manifests from independently selectable policies."""

from dataclasses import asdict

from ..controller.engine import implementation_hash
from ..models import digest, record
from ..providers.backbone import candidate_schema, SYSTEM
from .replay import REMEDIATION_COMPONENTS, validate_manifest


def component_identities(config, implementation=None):
    implementation = implementation or implementation_hash()
    policies = asdict(config.remediation)
    result = {}
    policy_key = {
        "initial": "citations",
        "revision": "citations",
        "J2": "relevance",
        "J3": "support",
        "audit": "contract",
        "decomposition": "support",
        "applicability": "final",
        "generation_recovery": "generation",
    }
    for name in sorted(REMEDIATION_COMPONENTS):
        key = policy_key.get(name, name)
        provider = config.jev if name in {"J2", "J3"} else config.provider
        active = name not in {"J2", "J3"} or config.arm in (
            {"J2", "J23", "Jfull", "M"} if name == "J2" else {"J3", "J23", "Jfull", "M"}
        )
        result[name] = {
            "implementation": digest([implementation, name, policies.get(key, "legacy-v1")]),
            "model": provider.model if active else "not_applicable",
            "prompt": digest([SYSTEM, name, policies.get(key, "legacy-v1")]),
            "schema": digest(candidate_schema(config))
            if name in {"initial", "revision"}
            else digest([name, policies.get(key, "legacy-v1")]),
            "provider_settings_hash": digest(asdict(provider)) if active else "not_applicable",
        }
    return result


def freeze_manifest(
    experiment_id,
    configs,
    question_ids,
    *,
    baseline_revision,
    historical_implementation_hash,
    aggregate_usd,
    replications=1,
    comparison_kind="integrated",
    frozen=(),
    source_roots=None,
    config_paths=None,
    question_views=(),
):
    if len(configs) < 2 or not question_ids or len(set(question_ids)) != len(question_ids):
        raise ValueError("declare distinct paired arms and unique questions")
    if not question_views or {q.id for q in question_views} != set(question_ids):
        raise ValueError("freeze original question text and images for every declared ID")
    first = next(iter(configs.values()))
    if any(
        c.search_backend != first.search_backend or c.limits != first.limits
        for c in configs.values()
    ):
        raise ValueError("paired profiles must share backend and all resource caps")
    components = {identifier: component_identities(c) for identifier, c in configs.items()}
    baseline = next(iter(components.values()))
    if comparison_kind == "matched-j23" and any(
        components[i]["contract"] != baseline["contract"]
        or components[i]["initial"] != baseline["initial"]
        for i in components
    ):
        raise ValueError("matched B2/J23 requires shared contract and initial-generation policies")

    def snapshots(component):
        return digest(
            sorted((digest(r) for r in frozen if r["contract"]["component"] == component))
        )

    manifest = {
        "version": 2,
        "experiment_id": experiment_id,
        "split": "development",
        "policy_frozen": True,
        "baseline_revision": baseline_revision,
        "historical_implementation_hash": historical_implementation_hash,
        "comparison_kind": comparison_kind,
        "backend": first.search_backend,
        "question_ids": list(question_ids),
        "spend_caps": {
            "item_usd": first.limits.item_usd,
            "run_usd": first.limits.run_usd,
            "aggregate_usd": aggregate_usd,
        },
        "acceptance": {
            "replications": replications,
            "criteria": "Higher full-set accuracy, no increase in wrong answered items, same caps; passing deterministic/regression controls and adjudicated component gates. Wide question-clustered uncertainty is inconclusive.",
        },
        "evidence_policy": {
            "shortlist": first.relevance.shortlist,
            "packet": first.relevance.packet,
            "characters": first.evidence_chars,
        },
        "shared": {
            "questions_hash": digest(sorted(question_ids)),
            "questions_content_hash": digest(
                [record(q) for q in sorted(question_views, key=lambda q: q.id)]
            )
            if question_views
            else None,
            "initial_candidates_hash": snapshots("initial"),
            "queries_hash": snapshots("query"),
            "results_hash": snapshots("search"),
            "pages_hash": snapshots("fetch"),
        },
        "snapshots_hash": digest(list(frozen)),
        "generation_intervention": len({c.remediation.contract for c in configs.values()}) > 1,
        "arms": [
            {
                "id": identifier,
                "config_hash": c.hash,
                "implementation_hash": implementation_hash(),
                "components": components[identifier],
                "changed_components": sorted(
                    k for k in REMEDIATION_COMPONENTS if components[identifier][k] != baseline[k]
                ),
            }
            for identifier, c in configs.items()
        ],
        "semantic_gates": "pending adjudicated labels and fresh model comparisons",
        "matched_cost_comparison": "separately declared; not inferred from equal caps",
    }
    for arm in manifest["arms"]:
        if (source_roots or {}).get(arm["id"]):
            from .snapshot_worker import snapshot_info

            source = source_roots[arm["id"]]
            info = snapshot_info(source, (config_paths or {})[arm["id"]])
            arm.update(info)
            arm["source_root"] = str(__import__("pathlib").Path(source).resolve())
            arm["components"] = component_identities(
                configs[arm["id"]], info["implementation_hash"]
            )
    baseline = manifest["arms"][0]["components"]
    for arm in manifest["arms"]:
        arm["changed_components"] = sorted(
            k for k in REMEDIATION_COMPONENTS if arm["components"][k] != baseline[k]
        )
    return validate_manifest(manifest)
