"""Adjudicated family-separated development comparisons; no threshold auto-promotion."""

from ..models import probability


def relevance_validation(calibration, validation, thresholds):
    if not calibration or not validation:
        return {
            "status": "unavailable",
            "reason": "adjudicated calibration and validation required",
        }
    for row in [*calibration, *validation]:
        if row.get("label_status") != "adjudicated" or type(row.get("useful")) is not bool:
            raise ValueError("semantic calibration requires adjudicated labels")
        for key in ("question_family", "source_family", "input_hash"):
            if not isinstance(row.get(key), str) or not row[key]:
                raise ValueError(
                    "calibration must identify question/source families and fresh inputs"
                )
        probability(row["score"])
    for key in ("question_family", "source_family"):
        if {r[key] for r in calibration} & {r[key] for r in validation}:
            raise ValueError("calibration/validation family leakage")
    if {r["input_hash"] for r in calibration} & {r["input_hash"] for r in validation}:
        raise ValueError("repeated inputs cross calibration split")

    def measure(rows, threshold):
        useful = [r for r in rows if r["useful"]]
        false = [r for r in rows if not r["useful"]]
        return {
            "useful_recall": sum(r["score"] >= threshold for r in useful) / len(useful)
            if useful
            else None,
            "false_admissions": sum(r["score"] >= threshold for r in false),
            "useful_count": len(useful),
            "irrelevant_count": len(false),
        }

    candidates = [
        {"threshold": probability(t), "calibration": measure(calibration, t)} for t in thresholds
    ]
    if not candidates:
        raise ValueError("predeclare candidate thresholds")
    chosen = max(
        candidates,
        key=lambda c: (
            -(c["calibration"]["false_admissions"]),
            c["calibration"]["useful_recall"] or 0,
            c["threshold"],
        ),
    )
    control, variant = measure(validation, 2 / 3), measure(validation, chosen["threshold"])
    promotable = (
        control["useful_recall"] is not None
        and control["irrelevant_count"] > 0
        and variant["useful_recall"] > control["useful_recall"]
        and variant["false_admissions"] <= control["false_admissions"]
    )
    return {
        "status": "measured",
        "calibration": candidates,
        "selected_threshold": chosen["threshold"],
        "validation_control": control,
        "validation_variant": variant,
        "promotion_gate": promotable,
        "policy_changed": False,
    }
