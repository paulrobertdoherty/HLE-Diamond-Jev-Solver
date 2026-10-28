from __future__ import annotations

import math
import random
from collections import defaultdict
from statistics import mean


def quantile(values: list[float], q: float) -> float:
    if not values:
        return 0
    values = sorted(values)
    position = (len(values) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def cluster_values(grades: list[dict], field: str = "correct") -> dict[str, float]:
    groups = defaultdict(list)
    for row in grades:
        groups[row["question_id"]].append(float(row[field]))
    return {key: mean(values) for key, values in groups.items()}


def bootstrap(values: list[float], seed: int = 17, draws: int = 4000) -> list[float]:
    if not values:
        raise ValueError("empty declared evaluation set")
    if draws < 100:
        raise ValueError("at least 100 bootstrap draws required")
    rng = random.Random(seed)
    means = [mean(rng.choices(values, k=len(values))) for _ in range(draws)]
    return [quantile(means, 0.025), quantile(means, 0.975)]


def summary(grades: list[dict], seed: int = 17) -> dict:
    clustered = cluster_values(grades)
    if not clustered:
        raise ValueError("no graded items")
    n = len(grades)
    accuracy = mean(clustered.values())
    total_cost = sum(g["cost_usd"] for g in grades)
    latencies = [g["latency_s"] for g in grades]
    answered = [g for g in grades if g["status"] == "completed" and not g.get("abstained", False)]
    reliability = []
    for i in range(10):
        rows = [g for g in grades if min(9, int(g["confidence"] * 10)) == i]
        reliability.append(
            {
                "low": i / 10,
                "high": (i + 1) / 10,
                "count": len(rows),
                "confidence": mean(g["confidence"] for g in rows) if rows else None,
                "accuracy": mean(g["correct"] for g in rows) if rows else None,
            }
        )
    slices = defaultdict(list)
    for g in grades:
        for key, val in g.get("slices", {}).items():
            slices[f"{key}:{val}"].append(g)
    return {
        "questions": len(clustered),
        "trials": n,
        "accuracy": accuracy,
        "accuracy_ci95": bootstrap(list(clustered.values()), seed),
        "total_cost_usd": total_cost,
        "mean_cost_usd": total_cost / n,
        "cost_per_correct_usd": total_cost / sum(g["correct"] for g in grades)
        if any(g["correct"] for g in grades)
        else None,
        "latency_s": {
            "mean": mean(latencies),
            "p50": quantile(latencies, 0.5),
            "p95": quantile(latencies, 0.95),
            "p99": quantile(latencies, 0.99),
        },
        "failure_rate": sum(g["status"] != "completed" for g in grades) / n,
        "timeout_rate": sum(g["status"] == "timeout" for g in grades) / n,
        "grader_error_count": sum(g["status"] == "grader_error" for g in grades),
        "brier": mean((g["confidence"] - g["correct"]) ** 2 for g in grades),
        "confidence_mapping": "backbone's declared correctness probability; no fitted mapping",
        "coverage": len(answered) / n,
        "covered_accuracy": mean(g["correct"] for g in answered) if answered else None,
        "contaminated_count": sum(bool(g.get("contaminated")) for g in grades),
        "reliability": reliability,
        "slices": {
            key: {
                "questions": len(cluster_values(rows)),
                "accuracy": mean(cluster_values(rows).values()),
            }
            for key, rows in sorted(slices.items())
        },
    }


def paired(a: list[dict], b: list[dict], seed: int = 17, target_gain: float = 0.05) -> dict:
    av, bv = cluster_values(a), cluster_values(b)
    if not av or not bv:
        raise ValueError("paired analysis requires nonempty declared sets")
    if set(av) != set(bv):
        raise ValueError("paired arms must contain the same declared questions, including failures")
    keys = sorted(av)
    differences = [av[k] - bv[k] for k in keys]
    single = len(a) == len(av) and len(b) == len(bv)
    wins = sum(av[k] == 1 and bv[k] == 0 for k in keys) if single else None
    losses = sum(av[k] == 0 and bv[k] == 1 for k in keys) if single else None
    pvalue = None
    discordance = None
    if single:
        n = wins + losses
        if n == 0:
            pvalue = 1.0
        else:
            logs = [
                math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) - n * math.log(2)
                for k in range(min(wins, losses) + 1)
            ]
            m = max(logs)
            pvalue = min(1.0, 2 * math.exp(m) * sum(math.exp(v - m) for v in logs))
        discordance = n / len(keys)
    if not 0 < target_gain < 1:
        raise ValueError("target gain must be a fraction in (0,1)")
    return {
        "questions": len(keys),
        "difference_a_minus_b": mean(differences),
        "difference_ci95": bootstrap(differences, seed),
        "cluster": "question",
        "wins_a": wins,
        "wins_b": losses,
        "mcnemar_exact_p": pvalue,
        "discordance": discordance,
        "target_gain": target_gain,
        "approximate_questions_for_80pct_power": math.ceil(
            (1.96 + 0.84) ** 2 * max(0, discordance - target_gain**2) / target_gain**2
        )
        if discordance is not None and discordance >= target_gain and discordance > target_gain**2
        else None,
        "power_caveat": "normal approximation from pilot discordance, unadjusted for multiple comparisons; insufficient discordance gives no estimate",
        "mean_cost_difference_usd": mean(g["cost_usd"] for g in a) - mean(g["cost_usd"] for g in b),
    }


def diagnostics(grades: list[dict]) -> dict:
    labeled = [g for g in grades if g.get("oracle_correct") is not None]
    return {
        "oracle_labeled_count": len(labeled),
        "oracle_accuracy": mean(g["oracle_correct"] for g in labeled) if labeled else None,
        "selected_accuracy": mean(g["correct"] for g in labeled) if labeled else None,
        "oracle_selection_gap": mean(g["oracle_correct"] - g["correct"] for g in labeled)
        if labeled
        else None,
    }
