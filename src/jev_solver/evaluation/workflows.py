"""Offline audit, image, eligibility and reference metrics with explicit denominators."""

from collections import defaultdict
from itertools import combinations


def fraction(numerator, denominator):
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def inventory(values):
    if (
        not isinstance(values, list)
        or any(
            not isinstance(d, dict)
            or not isinstance(d.get("id"), str)
            or d.get("kind") not in {"factual", "derived", "visual", "numerical"}
            or type(d.get("critical")) is not bool
            for d in values
        )
        or len({d["id"] for d in values}) != len(values)
    ):
        raise ValueError("invalid annotated dependency inventory")
    return {d["id"]: d for d in values}


def extra_workflow_metrics(rows):
    counts = defaultdict(int)
    repeats = defaultdict(list)
    for row in rows:
        stage = row.get("stage")
        if stage == "audit":
            gold, observed = (
                inventory(row["gold_dependencies"]),
                inventory(row["observed_dependencies"]),
            )
            for identifier, dep in gold.items():
                counts["claims"] += dep["critical"]
                found = observed.get(identifier)
                counts["discovered"] += bool(dep["critical"] and found)
                counts["checked"] += bool(
                    dep["critical"] and found and found.get("status") == "passed"
                )
                if found:
                    counts["classified"] += 1
                    counts["kind_correct"] += dep["kind"] == found["kind"]
                    counts["criticality_correct"] += dep["critical"] == found["critical"]
            if row.get("input_hash"):
                repeats[row["input_hash"]].append(
                    {i: (d["kind"], d["critical"]) for i, d in observed.items()}
                )
            counts["audit_cases"] += 1
        elif stage == "visual":
            expected, observed = row["expected_observations"], row["observed_observations"]
            if not isinstance(expected, dict) or not isinstance(observed, dict):
                raise ValueError("visual observations must map stable observation IDs to labels")
            original, reviewed = row["original_image_hashes"], row["reviewed_image_hashes"]
            if (
                not isinstance(original, list)
                or not isinstance(reviewed, list)
                or any(not isinstance(i, str) for i in original + reviewed)
            ):
                raise ValueError("invalid image hashes")
            counts["visual_cases"] += 1
            counts["visual_observations"] += len(expected)
            counts["visual_correct"] += sum(
                identifier in observed and observed[identifier] == value
                for identifier, value in expected.items()
            )
            counts["grounded_reviews"] += bool(original) and set(reviewed) == set(original)
        elif stage == "eligibility":
            history, correct, eligible = (
                row[k] for k in ("candidate_ids", "correct_ids", "eligible_ids")
            )
            if (
                any(
                    not isinstance(values, list)
                    or any(not isinstance(i, str) for i in values)
                    or len(values) != len(set(values))
                    for values in (history, correct, eligible)
                )
                or not set(correct) <= set(history)
                or not set(eligible) <= set(history)
            ):
                raise ValueError("eligibility labels require the entire assessed candidate history")
            counts["gate_cases"] += 1
            counts["all_candidates"] += len(history)
            counts["correct_candidates"] += len(correct)
            counts["invalid_candidates"] += len(history) - len(correct)
            counts["false_rejections"] += len(set(correct) - set(eligible))
            counts["false_acceptances"] += len(set(eligible) - set(correct))
        elif stage == "reference":
            if row.get("disagreement") not in {
                "solver_error",
                "reference_interpretation",
                "grader_inconsistency",
                "unresolved",
                "agreement",
            }:
                raise ValueError("invalid reference adjudication category")
            if (
                type(row.get("original_correct")) is not bool
                or type(row.get("adjudicated_correct")) is not bool
            ):
                raise ValueError(
                    "reference evaluation needs independent Boolean adjudicated labels"
                )
            counts["reference_cases"] += 1
            counts["original_correct"] += row["original_correct"]
            counts["adjudicated_correct"] += row["adjudicated_correct"]
            counts["grader_agrees"] += row["original_correct"] == row["adjudicated_correct"]
    stable = pairs = 0
    for samples in repeats.values():
        for left, right in combinations(samples, 2):
            pairs += 1
            stable += left == right
    return {
        "audit_cases": counts["audit_cases"],
        "audit_claim_discovery": fraction(counts["discovered"], counts["claims"]),
        "audit_checked_coverage": fraction(counts["checked"], counts["claims"]),
        "dependency_kind_accuracy": fraction(counts["kind_correct"], counts["classified"]),
        "criticality_accuracy": fraction(counts["criticality_correct"], counts["classified"]),
        "classification_repeatability": fraction(stable, pairs),
        "visual_cases": counts["visual_cases"],
        "visual_observation_accuracy": fraction(
            counts["visual_correct"], counts["visual_observations"]
        ),
        "original_image_grounding": fraction(counts["grounded_reviews"], counts["visual_cases"]),
        "eligibility_cases": counts["gate_cases"],
        "assessed_candidate_count": counts["all_candidates"],
        "eligibility_false_rejection": fraction(
            counts["false_rejections"], counts["correct_candidates"]
        ),
        "eligibility_false_acceptance": fraction(
            counts["false_acceptances"], counts["invalid_candidates"]
        ),
        "reference_cases": counts["reference_cases"],
        "original_reference_accuracy": fraction(
            counts["original_correct"], counts["reference_cases"]
        ),
        "adjudicated_reference_accuracy": fraction(
            counts["adjudicated_correct"], counts["reference_cases"]
        ),
        "grader_agreement": fraction(counts["grader_agrees"], counts["reference_cases"]),
    }
