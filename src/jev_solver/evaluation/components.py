"""Paired component judgments on frozen development evidence, independent of held-out solving."""

from __future__ import annotations

from pathlib import Path
from dataclasses import replace

from ..benchmarks.data import read_jsonl
from ..config import Config
from ..controller.budget import Budget
from ..models import EvidencePassage, QuestionView, digest, probability
from ..providers.backbone import Gateway
from ..providers.jev import Jev
from ..retrieval.evidence import diverse_packet, lexical_rank, lexical_score, retrieval_shortlist
from ..tracing.store import Store, atomic_json


async def components(config: Config, cases: Path, output: Path, judge: str = "jev") -> dict:
    from ..judgments.pipeline import SUPPORT

    if judge not in {"jev", "backbone", "lexical", "stored"}:
        raise ValueError("unknown component judge")
    rows = read_jsonl(cases)
    unresolved = 0
    if rows and rows[0].get("version") == 1:
        from .labels import component_rows, load_cases

        labeled = load_cases(cases)
        rows = component_rows(labeled)
        unresolved = sum(
            row["component"] in {"J2", "J3"} and row["label"]["status"] != "adjudicated"
            for row in labeled
        )
        if not rows:
            artifact = {
                "judge": judge,
                "metrics": {
                    "J2": {"count": 0, "accuracy": None},
                    "J3": {"count": 0, "accuracy": None},
                },
                "unresolved_cases": unresolved,
                "cost_usd": 0,
                "paid_calls_dispatched": 0,
                "development_only": True,
            }
            atomic_json(output / "components.json", artifact)
            return artifact
    if not rows or any(r.get("stage") not in {"J2", "J3"} for r in rows):
        raise ValueError("component evaluation requires labeled J2/J3 development cases")
    if any(not isinstance(row.get("id"), str) or not row["id"] for row in rows) or len(
        {r["id"] for r in rows}
    ) != len(rows):
        raise ValueError("component rows require unique nonempty IDs")
    for row in rows:
        if not isinstance(row.get("state"), dict) or set(row["state"]) & {
            "expected",
            "label",
            "reference",
            "reference_answer",
            "adjudication",
        }:
            raise ValueError("component provider state must exclude scoring labels and references")
        if row["stage"] == "J2":
            probability(row.get("expected"))
        elif row.get("expected") not in SUPPORT["criteria"] or any(
            not isinstance(row["state"].get(k), str) or not row["state"][k].strip()
            for k in ("claim", "quote", "source_context")
        ):
            raise ValueError("invalid labeled source-entailment case")
        if any(
            key in row and type(row[key]) is not bool
            for key in ("useful", "answer_bearing", "contradictory")
        ):
            raise ValueError("packet relevance labels must be booleans")
        if row["stage"] == "J2" and any(
            not isinstance(row.get("state", {}).get(k), str) or not row["state"][k].strip()
            for k in ("question", "missing_fact", "search_query", "passage")
        ):
            raise ValueError(
                "J2 cases require original question, neutral missing_fact, search_query and passage"
            )
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
            confidence = None
            if judge == "stored":
                observed = row.get("observed", {})
                value, confidence = observed.get("value"), observed.get("confidence")
            elif judge == "jev":
                judged = await jev.request(row["id"], row["stage"], state, {"judgment": spec})
                value = judged["judgment"].value if "judgment" in judged else None
                confidence = judged["judgment"].confidence if "judgment" in judged else None
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
                    value = lexical_score(state["missing_fact"], state["passage"])
                else:
                    value = (
                        "supported"
                        if state["claim"] in state["quote"]
                        and state["quote"] in state["source_context"]
                        else "insufficient"
                    )
            expected = row["expected"]
            if row["stage"] == "J2":
                probability(expected)
                if value is not None:
                    probability(value)
                correct = value is not None and (value >= config.relevance.min_score) == (
                    expected >= config.relevance.min_score
                )
            else:
                if expected not in SUPPORT["criteria"] or (
                    value is not None and value not in SUPPORT["criteria"]
                ):
                    raise ValueError("invalid support label")
                correct = value == expected
            store.event(
                row["id"],
                "component_prediction",
                {"stage": row["stage"], "value": value, "confidence": confidence},
            )
            result.append(
                {
                    "row": row,
                    "value": value,
                    "confidence": confidence,
                    "stage": row["stage"],
                    "correct": correct,
                    "absolute_error": abs(value - expected)
                    if isinstance(value, (float, int)) and isinstance(expected, (float, int))
                    else None,
                    "unavailable": value is None,
                    "not_run": judge == "stored" and row.get("not_run", False),
                }
            )
        from statistics import mean

        metrics = {}
        for stage in ("J2", "J3"):
            all_rows = [r for r in result if r["stage"] == stage]
            selected = [r for r in all_rows if not r["not_run"]]
            numeric = [r["absolute_error"] for r in selected if r["absolute_error"] is not None]
            metrics[stage] = {
                "count": len(all_rows),
                "judged_count": len(selected),
                "not_run": len(all_rows) - len(selected),
                "accuracy": mean(r["correct"] for r in selected) if selected else None,
                "mean_absolute_error": mean(numeric) if numeric else None,
                "unavailable": sum(r["unavailable"] for r in selected),
            }
        metrics["J2"]["accuracy_definition"] = (
            "usefulness decision at configured threshold; not exact score equality"
        )
        metrics["J2"].update(
            packet_metrics(config, [r for r in result if r["stage"] == "J2"], judge)
        )
        confusion = {
            label: {prediction: 0 for prediction in (*SUPPORT["criteria"], "unavailable")}
            for label in SUPPORT["criteria"]
        }
        for r in result:
            if r["stage"] == "J3" and not r["not_run"]:
                confusion[r["row"]["expected"]][r["value"] or "unavailable"] += 1
        metrics["J3"]["confusion_matrix"] = confusion
        positives = sum(
            r["row"]["expected"] == "supported"
            for r in result
            if r["stage"] == "J3" and not r["not_run"]
        )
        negatives = metrics["J3"]["judged_count"] - positives
        metrics["J3"].update(
            {
                "false_support_count": sum(
                    confusion[label]["supported"]
                    for label in SUPPORT["criteria"]
                    if label != "supported"
                ),
                "false_support_rate": ratio(
                    sum(
                        confusion[label]["supported"]
                        for label in SUPPORT["criteria"]
                        if label != "supported"
                    ),
                    negatives,
                ),
                "false_rejection_count": sum(
                    confusion["supported"][label]
                    for label in SUPPORT["criteria"]
                    if label != "supported"
                ),
                "false_rejection_rate": ratio(
                    sum(
                        confusion["supported"][label]
                        for label in SUPPORT["criteria"]
                        if label != "supported"
                    ),
                    positives,
                ),
                "supported_label_count": positives,
                "non_supported_label_count": negatives,
            }
        )
        artifact = {
            "judge": judge,
            "metrics": metrics,
            "cost_usd": store.cost(),
            "development_only": True,
            "unresolved_cases": unresolved,
            "usage": store.usage_summary(),
        }
        atomic_json(output / "components.json", artifact)
        return artifact
    finally:
        await jev.close()
        await gateway.close()
        store.close()


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def packet_metrics(config, results, judge="jev"):
    """Labels remain here; only state was sent to the provider above."""
    from ..judgments.pipeline import filter_relevance

    groups = {}
    for result in results:
        row = result["row"]
        state = row["state"]
        group = (
            row.get("task_id", row["id"]),
            state.get("question"),
            row.get("round"),
            state.get("missing_fact"),
        )
        groups.setdefault(group, []).append(result)
    totals = {kind: 0 for kind in ("answer_bearing", "useful", "contradictory")}
    retained = dict.fromkeys(totals, 0)
    checkpoints = {
        stage: dict.fromkeys(totals, 0)
        for stage in ("before_shortlist", "after_shortlist", "after_relevance", "after_packet")
    }
    exclusions = []
    for rows in groups.values():
        passages = []
        for r in rows:
            state, row = r["row"]["state"], r["row"]
            passages.append(
                EvidencePassage(
                    row.get("passage_id", row["id"]),
                    state.get("url", f"https://fixture.invalid/{row['id']}"),
                    digest(state["passage"]),
                    state["passage"],
                    0,
                    len(state["passage"]),
                    "frozen",
                    "frozen",
                    subquestion=state.get("missing_fact", state.get("subquestion", "")),
                    score=r["value"],
                    confidence=r["confidence"],
                )
            )
        ids = {p.id for p in retrieval_shortlist(passages, config.relevance.shortlist)}
        shortlist = [p for p in passages if p.id in ids]
        if judge == "lexical" or any(p.score is None for p in shortlist):
            filtered = [
                replace(p, relevance_status="unavailable" if judge == "jev" else "not_applicable")
                for p in lexical_rank(shortlist)
                if p.score > 0
            ]
        else:
            filtered = filter_relevance(shortlist, config.relevance)
        packet = diverse_packet(
            filtered,
            config.evidence_chars,
            config.relevance.packet,
            alternative_slots=config.relevance.alternative_slots,
        )
        selected = {p.id for p in packet}
        filtered_ids = {p.id for p in filtered}
        for r in rows:
            row = r["row"]
            passage_id = row.get("passage_id", row["id"])
            labels = {
                kind: row.get(
                    kind,
                    row["expected"] >= config.relevance.min_score if kind == "useful" else None,
                )
                for kind in totals
            }
            if any(v is not None and type(v) is not bool for v in labels.values()):
                raise ValueError("packet relevance labels must be booleans")
            reason = (
                "shortlist"
                if passage_id not in ids
                else "relevance_policy"
                if passage_id not in filtered_ids
                else "packet_limit"
                if passage_id not in selected
                else "retained"
            )
            exclusions.append(
                {
                    "id": row["id"],
                    "passage_id": passage_id,
                    "task_id": row.get("task_id", row["id"]),
                    "reason": reason,
                }
            )
            for kind, label in labels.items():
                if label is None:
                    continue
                totals[kind] += label
                retained[kind] += label and passage_id in selected
                for stage, survived in (
                    ("before_shortlist", True),
                    ("after_shortlist", passage_id in ids),
                    ("after_relevance", passage_id in filtered_ids),
                    ("after_packet", passage_id in selected),
                ):
                    checkpoints[stage][kind] += bool(label and survived)
    return {
        "packet_policy": "lexical_nonzero"
        if judge == "lexical"
        else "configured_relevance_with_lexical_outage_fallback",
        "packet_groups": len(groups),
        "labeled_totals": totals,
        "survival_checkpoints": {
            stage: {
                kind: {
                    "retained": count,
                    "total": totals[kind],
                    "recall": ratio(count, totals[kind]),
                }
                for kind, count in counts.items()
            }
            for stage, counts in checkpoints.items()
        },
        "exclusions": exclusions,
        "answer_bearing_recall_at_packet_budget": ratio(
            retained["answer_bearing"], totals["answer_bearing"]
        ),
        "useful_exclusion_rate": ratio(totals["useful"] - retained["useful"], totals["useful"]),
        "contradictory_exclusion_rate": ratio(
            totals["contradictory"] - retained["contradictory"], totals["contradictory"]
        ),
    }


def workflow_metrics(cases: Path, output: Path):
    """Offline evaluation of independently labeled, saved coverage/selection decisions.

    Claim IDs must be reconciled by an annotator, not equated by a model seeing
    the gold labels. No labels enter solving and no provider calls are made.
    """
    rows = read_jsonl(cases)
    if not rows:
        raise ValueError("empty workflow labels")
    if rows[0].get("version") == 1:
        from .labels import load_cases, workflow_rows

        labeled = load_cases(cases)
        unresolved = sum(
            row["component"] in {"audit", "reference"} and row["label"]["status"] != "adjudicated"
            for row in labeled
        )
        rows = workflow_rows(labeled)
    else:
        unresolved = sum(row.get("label_status") == "unresolved" for row in rows)
        rows = [row for row in rows if row.get("label_status") != "unresolved"]
    required = discovered = checked = selected = wrong = answerable = rejected = 0
    coverage_count = selection_count = 0
    for row in rows:
        if row.get("stage") == "coverage":
            for key in ("required_claims", "discovered_claims", "checked_claims"):
                if not isinstance(row.get(key), list) or any(
                    not isinstance(i, str) for i in row[key]
                ):
                    raise ValueError("invalid coverage labels")
            gold = set(row["required_claims"])
            if not set(row["checked_claims"]) <= set(row["discovered_claims"]):
                raise ValueError("checked claims must be in the discovered inventory")
            required += len(gold)
            discovered += len(gold & set(row["discovered_claims"]))
            checked += len(gold & set(row["checked_claims"]))
            coverage_count += 1
        elif row.get("stage") == "selection":
            pool = row.get("candidate_ids")
            gold = row.get("correct_ids")
            choice = row.get("selected_id")
            if (
                not isinstance(pool, list)
                or not isinstance(gold, list)
                or any(not isinstance(i, str) for i in [*pool, *gold])
                or not set(gold) <= set(pool)
                or (choice is not None and (not isinstance(choice, str) or choice not in pool))
            ):
                raise ValueError("invalid selector labels")
            selected += choice is not None
            wrong += choice is not None and choice not in gold
            answerable += bool(gold)
            rejected += bool(gold) and choice is None
            selection_count += 1
        elif row.get("stage") not in {"audit", "visual", "eligibility", "reference"}:
            raise ValueError("unknown workflow stage")
    from .workflows import extra_workflow_metrics

    artifact = {
        "development_only": True,
        "paid_calls_dispatched": 0,
        "coverage_cases": coverage_count,
        "selection_cases": selection_count,
        "required_claims": required,
        "claim_discovery_recall": ratio(discovered, required),
        "claim_coverage_recall": ratio(checked, required),
        "wrong_answer_acceptance_rate": ratio(wrong, selected),
        "correct_answer_rejection_rate": ratio(rejected, answerable),
        "selected_count": selected,
        "wrong_selected_count": wrong,
        "answerable_count": answerable,
        "correct_pool_abstentions": rejected,
        "unresolved_cases": unresolved,
        **extra_workflow_metrics(rows),
    }
    atomic_json(output, artifact)
    return artifact
