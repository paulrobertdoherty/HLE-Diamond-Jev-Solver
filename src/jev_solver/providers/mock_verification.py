"""Deterministic synthetic audit; never a verifier for live tasks."""

import operator
import re

from ..models import Dependency, record


def synthetic_audit(question, context):
    draft = context["draft"]
    match = re.search(r"(-?\d+)\s*([+*\-/])\s*(-?\d+)", question.question)
    quote = "The synthetic cobalt code is 27."
    sources = [p["id"] for p in context["evidence"] if quote in p["text"]]
    if match:
        a, op, b = match.groups()
        value = {"+": operator.add, "-": operator.sub, "*": operator.mul, "/": operator.truediv}[
            op
        ](int(a), int(b))
        answer = str(int(value)) if float(value).is_integer() else str(value)
        status = "passed" if draft["answer"].split(" ")[0] == answer else "failed"
        dependency = record(
            Dependency(
                "calculation",
                "derived",
                f"{a} {op} {b} = {answer}",
                True,
                basis=f"Evaluated the given arithmetic expression: {a} {op} {b} = {answer}.",
            )
        )
    else:
        status = (
            "passed" if sources and draft["answer"] == "27" else "failed" if sources else "not_run"
        )
        statement = (
            quote
            if draft["answer"] in {"", "27"}
            else f"The synthetic cobalt code is {draft['answer']}."
        )
        dependency = record(
            Dependency(
                "reference",
                "factual",
                statement,
                True,
                basis="Checked the fictional reference." if sources else "",
                passage_ids=tuple(sources),
            )
        )
    dependencies = [
        {**dependency, "status": status, "reason": "Synthetic arithmetic or reference check."}
    ]
    # Preserve declared dependencies for deterministic contract tests.
    dependencies.extend(
        {**d, "status": "not_run", "reason": "Synthetic verifier cannot establish this premise."}
        for d in draft.get("dependencies", [])
        if d["id"] != dependency["id"]
    )
    for claim in draft["source_claims"]:
        if claim != dependency["statement"]:
            dependencies.append(
                {
                    **record(
                        Dependency(
                            "source-" + str(len(dependencies)),
                            "factual",
                            claim,
                            True,
                            basis="Fictional reference." if sources else "",
                            passage_ids=tuple(sources),
                        )
                    ),
                    "status": "passed" if sources and claim == quote else "not_run",
                    "reason": "Synthetic source check.",
                }
            )
    attempted = {s["query"] for o in context["research_outcomes"] for s in o["searches"]}
    queries = draft["queries"] or (["synthetic cobalt code"] if not match and not sources else [])
    return {
        "completeness": {
            "status": "passed",
            "reason": "Inventoried the synthetic task's required premise.",
        },
        "answer_check": {
            "status": status if draft["answer"] else "not_applicable",
            "reason": "Checked the answer against the synthetic task.",
        },
        "dependencies": dependencies,
        "gap_assessments": [
            {
                "gap_index": i,
                "critical": not bool(match),
                "dependency_ids": [dependency["id"]],
                "reason": "Synthetic dependency classification.",
            }
            for i, _ in enumerate(draft["gaps"])
        ],
        "queries": [
            {"dependency_id": dependency["id"], "missing_fact": query, "query": query}
            for query in queries
            if query not in attempted
        ][:3],
    }
