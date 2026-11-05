"""Independent whole-answer verification after actual local check results exist."""

from copy import deepcopy

from ..models import digest, record
from ..providers.backbone import ProviderError
from .graph import STRINGS, obj
from .verification import CHECK_SCHEMA, STATUS_SCHEMA, check, validate_check
from .support import aggregate_support

WHOLE_ANSWER_SCHEMA = obj(
    {
        "whole_answer": CHECK_SCHEMA,
        "applicability": CHECK_SCHEMA,
        "obligation_checks": {
            "type": "array",
            "maxItems": 12,
            "items": obj(
                {
                    "id": {"type": "string"},
                    "status": STATUS_SCHEMA,
                    "reason": {"type": "string"},
                    "dependency_ids": STRINGS,
                }
            ),
        },
        "interpretation_checks": {
            "type": "array",
            "maxItems": 12,
            "items": obj(
                {
                    "alternative": {"type": "string"},
                    "status": STATUS_SCHEMA,
                    "reason": {"type": "string"},
                }
            ),
        },
        "derived_rechecks": {
            "type": "array",
            "maxItems": 12,
            "items": obj(
                {
                    "id": {"type": "string"},
                    "status": STATUS_SCHEMA,
                    "reason": {"type": "string"},
                    "basis": {"type": "string"},
                }
            ),
        },
        "source_scope": {
            "type": "array",
            "maxItems": 12,
            "items": obj(
                {
                    "passage_id": {"type": "string"},
                    "basis_dependency_id": {"type": "string"},
                    "basis_passage_id": {"type": "string"},
                    "source_hash": {"type": "string"},
                    "quote": {"type": "string"},
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                    "reason": {"type": "string"},
                }
            ),
        },
    }
)
WHOLE_ANSWER_TASK = """Perform the final independent WHOLE-ANSWER check AFTER all supplied local results.
Compare each requested output to the ORIGINAL question and images, and the fallible question contract.
Check scope, quantifiers, chronology (including already-completed procedures), qualifications, construction
and convention choices, every answer-changing assumption, entity identity and cross-source/version joins.
A conditional derivation does not establish its applicability. A source's entity need not be the intended
entity. A possible explanation requires defensible possibility; exact/unique identification requires identity
and exclusivity. Do not demand an exact causal mechanism when only possibility was requested.
Factual premises require fetched evidence; visual claims require these ORIGINAL images and image indices;
elementary symbolic calculations can be checked derivations; execution-dependent numerical results require
matching successful artifacts. Executing the wrong modeled algorithm does not solve the original question.
Use the ACTUAL verdicts in local_results; do not assume a check passed because it was requested. Do not
invent factual premises as derived facts or silently drop chronology or an unresolved interpretation.
List every obligation exactly once and its dependency IDs. Address each unresolved interpretation explicitly.
Derived descendants invalidated by a changed upstream premise need a fresh concise basis after their parents
pass; only derived_rechecks can supply that basis. A failed/unavailable factual check cannot be overruled.
Source_scope can exclude an older/inapplicable finding only with a precise recorded date/scope basis:
cite an exact canonical quote and a PASSED factual basis_dependency_id establishing that exclusion.
Unresolved relevant conflicts remain blocking. Empty answers cannot pass. Return concise check results."""


def obligations_for(q, contract):
    return contract or {
        "hash": digest(record(q)),
        "alternatives": [],
        "obligations": [
            {
                "id": "original-question",
                "kind": "output",
                "text": q.question,
                "anchor": q.question,
                "image_indices": list(range(len(q.images))),
            }
        ],
    }


def parse_whole_answer(raw, context):
    if set(raw) != set(WHOLE_ANSWER_SCHEMA["properties"]):
        raise ValueError("invalid whole-answer fields")
    for key in ("whole_answer", "applicability"):
        validate_check(raw[key])
    for key in ("obligation_checks", "interpretation_checks", "derived_rechecks", "source_scope"):
        if not isinstance(raw[key], list) or len(raw[key]) > 12:
            raise ValueError("invalid final check bounds")
    contract = context["question_contract"]
    expected = {o["id"] for o in contract["obligations"]}
    rows = raw["obligation_checks"]
    if len(rows) != len(expected) or {r["id"] for r in rows} != expected:
        raise ValueError("incomplete final obligation coverage")
    nodes = {d["id"]: d for d in context["local_results"]["dependencies"]}
    for row in rows:
        validate_check({k: row[k] for k in ("status", "reason")})
        if not isinstance(row["dependency_ids"], list) or any(
            i not in nodes for i in row["dependency_ids"]
        ):
            raise ValueError("final check references unknown premise")
        if row["status"] == "passed" and not row["dependency_ids"]:
            raise ValueError("final obligation lacks a checked basis")
    alternatives = contract["alternatives"]
    if len(raw["interpretation_checks"]) != len(alternatives) or {
        r["alternative"] for r in raw["interpretation_checks"]
    } != set(alternatives):
        raise ValueError("unresolved alternative interpretation omitted")
    for row in raw["interpretation_checks"]:
        validate_check({k: row[k] for k in ("status", "reason")})
    for row in raw["derived_rechecks"]:
        validate_check({k: row[k] for k in ("status", "reason")})
        if (
            row["id"] not in nodes
            or nodes[row["id"]]["kind"] != "derived"
            or not row["basis"].strip()
        ):
            raise ValueError("final recheck cannot relabel another verification kind")
    if len({r["id"] for r in raw["derived_rechecks"]}) != len(raw["derived_rechecks"]):
        raise ValueError("duplicate derived recheck")
    return raw


def apply_final_result(raw, audit, citations, evidence, candidate):
    audit, citations = deepcopy(audit), deepcopy(citations)
    nodes = {d["id"]: d for d in audit["dependencies"]}
    sources = {p.id: p for p in evidence}
    excluded = set()
    for scope in raw["source_scope"]:
        basis, p = nodes.get(scope["basis_dependency_id"]), sources.get(scope["basis_passage_id"])
        if (
            raw["applicability"]["status"] != "passed"
            or not basis
            or basis["kind"] != "factual"
            or basis["status"] != "passed"
            or not p
            or p.id not in basis["passage_ids"]
            or scope["passage_id"] not in sources
            or scope["source_hash"] != p.source_hash
            or type(scope["start"]) is not int
            or type(scope["end"]) is not int
            or not 0 <= scope["start"] < scope["end"] <= len(p.text)
            or p.text[scope["start"] : scope["end"]] != scope["quote"]
            or not scope["reason"].strip()
        ):
            raw["applicability"] = check(
                "failed", "Source exclusion lacks a passed date/scope basis."
            )
            continue
        excluded.add(scope["passage_id"])
    if excluded:

        def reevaluate(support):
            reqs = [r["requirement"] for r in support["requirements"]]
            return aggregate_support(
                reqs, [v for v in support["verdicts"] if v.get("passage_id") not in excluded]
            )

        for citation in citations:
            if citation.get("version") == "atomic-source-support-v1":
                citation.update(reevaluate(citation))
        for node in nodes.values():
            support = node.get("support_check")
            if support:
                node["support_check"] = reevaluate(support)
                node["status"] = (
                    node["support_check"]["status"]
                    if node["reason"].startswith("Atomic source support:")
                    else node["status"]
                )
    for recheck in raw["derived_rechecks"]:
        node = nodes[recheck["id"]]
        if all(nodes[i]["status"] == "passed" for i in node["depends_on"]):
            node.update({k: recheck[k] for k in ("status", "reason", "basis")})
            node["method"] = "independent_final_derivation"
    from .graph import propagate_failures

    if all(i in nodes for n in nodes.values() for i in n["depends_on"]):
        propagate_failures(list(nodes.values()))
    for obligation in raw["obligation_checks"]:
        if any(nodes[i]["status"] != "passed" for i in obligation["dependency_ids"]):
            obligation.update(check("not_run", "Required premise did not pass its actual check."))
    required = [
        audit["completeness"],
        raw["whole_answer"],
        raw["applicability"],
        *raw["obligation_checks"],
        *raw["interpretation_checks"],
        *[d for d in nodes.values() if d["critical"]],
    ]
    audit["discovery_answer_check"] = audit["answer_check"]
    audit["answer_check"] = raw["whole_answer"]
    audit["final_check"] = {
        **raw,
        "version": "whole-answer-v1",
        "candidate_id": candidate.id,
        "excluded_source_ids": sorted(excluded),
        "input_evidence_hash": digest([record(p) for p in evidence]),
    }
    audit["coverage"] = {
        **audit["coverage"],
        "status": "passed"
        if candidate.answer.strip() and all(r["status"] == "passed" for r in required)
        else "failed",
        "critical_passed": sum(d["critical"] and d["status"] == "passed" for d in nodes.values()),
    }
    return audit, citations


async def final_answer_check(
    gateway, q, candidate, evidence, artifacts, audit, citations, constraints, contract=None
):
    context = {
        "task": WHOLE_ANSWER_TASK,
        "question_contract": obligations_for(q, contract),
        "draft": record(candidate),
        "evidence": [record(p) for p in evidence],
        "tool_artifacts": list(artifacts),
        "local_results": {
            "dependencies": audit["dependencies"],
            "completeness": audit["completeness"],
            "citation_checks": citations,
            "constraint_checks": constraints,
        },
        "kind_policy": "fetched-factual/original-visual/elementary-derived/executed-numerical-v1",
    }
    try:
        raw = await gateway.generate(
            q, context, f"whole-answer-{candidate.id}", schema=WHOLE_ANSWER_SCHEMA, final=True
        )
        raw = parse_whole_answer(raw, context)
        return apply_final_result(raw, audit, citations, evidence, candidate)
    except (ProviderError, ValueError, TypeError, KeyError):
        audit = deepcopy(audit)
        audit["answer_check"] = check("unavailable", "Independent whole-answer check unavailable.")
        audit["coverage"]["status"] = "unavailable"
        audit["final_check"] = {"version": "whole-answer-v1", "status": "unavailable"}
        return audit, citations
