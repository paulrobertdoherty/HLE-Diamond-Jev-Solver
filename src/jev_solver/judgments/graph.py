"""Persistent question obligations and versioned, candidate-scoped premise graphs."""

from copy import deepcopy

from ..models import Dependency, digest, record


def obj(properties):
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }


STRINGS = {"type": "array", "items": {"type": "string"}, "maxItems": 12}
OBLIGATION = obj(
    {
        "id": {"type": "string"},
        "kind": {
            "type": "string",
            "enum": [
                "output",
                "scope",
                "quantifier",
                "chronology",
                "qualification",
                "interpretation",
            ],
        },
        "text": {"type": "string"},
        "anchor": {"type": "string"},
        "image_indices": {"type": "array", "items": {"type": "integer"}},
    }
)
CONTRACT_SCHEMA = obj(
    {
        "obligations": {"type": "array", "items": OBLIGATION, "maxItems": 12},
        "alternatives": STRINGS,
    }
)
CONTRACT_TASK = """Propose a bounded question contract from the ORIGINAL input before solving.
Record every requested output, scope, quantifier, chronology, allowed qualification and answer-changing
interpretation/convention/construction assumption. Anchor each obligation in exact question text or original
image_indices. Keep unresolved interpretations in alternatives; do not choose one silently. At most 12
obligations. This contract is a fallible interpretation; final checks must compare it to the original input."""


def parse_contract(raw, q, version=1):
    if set(raw) != {"obligations", "alternatives"} or not isinstance(raw["obligations"], list):
        raise ValueError("invalid question contract")
    obligations = raw["obligations"]
    if not 1 <= len(obligations) <= 12 or len({o["id"] for o in obligations}) != len(obligations):
        raise ValueError("invalid contract bounds/identity")
    for o in obligations:
        if (
            set(o) != set(OBLIGATION["properties"])
            or any(
                not isinstance(o[k], str) or not o[k].strip() or len(o[k]) > 1000
                for k in ("id", "kind", "text")
            )
            or o["kind"] not in OBLIGATION["properties"]["kind"]["enum"]
            or not isinstance(o["anchor"], str)
            or (o["anchor"] and o["anchor"] not in q.question)
            or not isinstance(o["image_indices"], list)
            or any(type(i) is not int or not 0 <= i < len(q.images) for i in o["image_indices"])
            or not (o["anchor"] or o["image_indices"])
        ):
            raise ValueError("contract obligation is not anchored to original input")
    if not any(o["kind"] == "output" for o in obligations):
        raise ValueError("contract must include requested outputs")
    if (
        not isinstance(raw["alternatives"], list)
        or len(raw["alternatives"]) > 12
        or any(
            not isinstance(a, str) or not a.strip() or len(a) > 1000 for a in raw["alternatives"]
        )
    ):
        raise ValueError("invalid alternative interpretations")
    body = {
        "schema": "question-contract-v1",
        "version": version,
        "question_hash": digest(record(q)),
        **raw,
    }
    return {**body, "hash": digest(body)}


def dependency_schema(base):
    return obj(
        {
            **deepcopy(base["properties"]),
            "logical_id": {"type": "string"},
            "premise_version": {"type": "integer"},
            "depends_on": STRINGS,
            "obligations": STRINGS,
            "assumptions": STRINGS,
        }
    )


def graph_fingerprint(dep):
    return digest(
        {
            "premise": {
                k: dep[k]
                for k in Dependency.__dataclass_fields__
                if k not in {"id", "premise_version"}
            },
            "artifact_identity": dep.get("artifact_identity"),
        }
    )


def validate_graph(dependencies, contract):
    if len(dependencies) > 12:
        raise ValueError("incomplete coverage: more than twelve active premises")
    by_id = {d["id"]: d for d in dependencies}
    logical = {d["logical_id"] or d["id"] for d in dependencies}
    if len(by_id) != len(dependencies) or len(logical) != len(dependencies):
        raise ValueError("duplicate graph identity")
    obligations = {o["id"] for o in contract["obligations"]} if contract else set()
    visiting, complete = set(), set()

    def visit(identifier):
        if identifier in visiting:
            raise ValueError("dependency cycle")
        if identifier in complete:
            return
        if identifier not in by_id:
            raise ValueError("dangling premise reference")
        visiting.add(identifier)
        d = by_id[identifier]
        if contract and not set(d["obligations"]) <= obligations:
            raise ValueError("dangling contract obligation")
        for parent in d["depends_on"]:
            visit(parent)
        visiting.remove(identifier)
        complete.add(identifier)

    for identifier in by_id:
        visit(identifier)
    return by_id


def reconcile_graph(dependencies, previous, contract, dispositions=()):
    dependencies = deepcopy(dependencies)
    by_logical = {d["logical_id"] or d["id"]: d for d in dependencies}
    actions = {a["logical_id"]: a for a in dispositions}
    events, invalid = [], set()
    for old in previous:
        identity = old["logical_id"] or old["id"]
        current = by_logical.get(identity)
        if current is not None:
            current["critical"] = current["critical"] or old["critical"]
            current["assumptions"] = list(
                dict.fromkeys(old["assumptions"] + current["assumptions"])
            )
            current["obligations"] = list(
                dict.fromkeys(old["obligations"] + current["obligations"])
            )
            if graph_fingerprint(current) != graph_fingerprint(old):
                current["premise_version"] = max(
                    old["premise_version"] + 1, current["premise_version"]
                )
                invalid.add(current["id"])
                # Reclassification alone cannot erase the old factual basis.
                if old["kind"] == "factual" and current["kind"] != "factual":
                    current.update(
                        {
                            k: deepcopy(old[k])
                            for k in Dependency.__dataclass_fields__
                            if k not in {"id", "premise_version"}
                        }
                    )
                    current["status"], current["reason"] = (
                        "not_run",
                        "Factual basis retained until an independently checked replacement route.",
                    )
                events.append(
                    {
                        "logical_id": identity,
                        "event": "premise_changed",
                        "version": current["premise_version"],
                    }
                )
            continue
        action = actions.get(identity, {})
        replacement = [d for d in dependencies if d["id"] in action.get("replacement_ids", [])]
        checked_route = (
            action.get("action") == "independent_route"
            and bool(action.get("reason", "").strip())
            and bool(replacement)
            and all(
                d["kind"] == "derived" and d["status"] == "passed" and d["basis"].strip()
                for d in replacement
            )
            and set(old["obligations"]) <= {o for d in replacement for o in d["obligations"]}
            and not old["assumptions"]
        )
        optional_removed = (
            not old["critical"]
            and action.get("action") == "optional_removed"
            and action.get("reason", "").strip()
        )
        if checked_route or optional_removed:
            events.append({"logical_id": identity, "event": "discharged", **action})
        else:
            inherited = {
                **old,
                "status": "not_run",
                "reason": "Necessary earlier premise omitted; remains unresolved.",
            }
            dependencies.append(inherited)
            invalid.add(inherited["id"])
            events.append({"logical_id": identity, "event": "premise_retained"})
    by_id = validate_graph(dependencies, contract)
    changed = True
    while changed:
        changed = False
        for d in dependencies:
            if set(d["depends_on"]) & invalid and d["id"] not in invalid:
                invalid.add(d["id"])
                d["status"], d["reason"] = (
                    "not_run",
                    "Changed upstream premise invalidated this check.",
                )
                changed = True
    # The freshly executed checks of changed nodes may pass; descendants require
    # an explicit new check after upstream verification, performed by the final audit.
    return dependencies, events, by_id


def propagate_failures(dependencies):
    by_id = {d["id"]: d for d in dependencies}
    for _ in dependencies:
        for dep in dependencies:
            if any(by_id[i]["status"] != "passed" for i in dep["depends_on"]):
                dep["status"], dep["reason"] = "not_run", "An upstream premise is unresolved."
