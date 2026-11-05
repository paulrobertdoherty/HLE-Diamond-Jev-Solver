"""Conservative request construction; canonical evidence remains in the private ledger."""

from copy import deepcopy

from ..models import digest

BUILDER_VERSION = "bounded-context-v1"


class IncompleteContext(ValueError):
    pass


def validate_schema(value, schema):
    kind = schema.get("type")
    valid = {
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: type(v) is int,
        "number": lambda v: type(v) in (int, float),
        "boolean": lambda v: type(v) is bool,
    }
    if kind in valid and not valid[kind](value):
        raise ValueError("structured output has the wrong type")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("structured output has an invalid category")
    if kind == "object":
        properties = schema.get("properties", {})
        if not set(schema.get("required", ())) <= set(value) or (
            schema.get("additionalProperties") is False and set(value) - set(properties)
        ):
            raise ValueError("structured output fields differ from schema")
        for key, item in value.items():
            if key in properties:
                validate_schema(item, properties[key])
    if kind == "array":
        if len(value) > schema.get("maxItems", float("inf")):
            raise ValueError("structured output exceeds array bound")
        for item in value:
            validate_schema(item, schema["items"])


def compact_records(value):
    if isinstance(value, dict):
        return {k: compact_records(v) for k, v in value.items()}
    if isinstance(value, list):
        result, seen = [], set()
        for item in value:
            if isinstance(item, dict):
                identity = digest(item)
                if identity in seen:
                    continue
                seen.add(identity)
            result.append(compact_records(item))
        return result
    return value


def evidence_ids(value):
    ids = set()
    if isinstance(value, dict):
        if "source_hash" in value and isinstance(value.get("id"), str):
            ids.add(value["id"])
        for item in value.values():
            ids.update(evidence_ids(item))
    elif isinstance(value, list):
        for item in value:
            ids.update(evidence_ids(item))
    return ids


def build_context(context, bound, limit):
    """Compact representation without dropping a required premise or source.

    Only incidental history/lead detail and repeated records are removed. Source
    excerpts are permitted only when the caller supplied explicit canonical spans;
    relevant conflicts must be included in those required spans by the caller.
    """
    original = bound(context)
    result, reasons = deepcopy(context), []
    if original > limit:
        result = compact_records(result)
        reasons.append("repeated_records")
    if bound(result) > limit:
        for key in ("history", "unused_leads", "previous_versions", "latest_verification"):
            if key in result:
                result.pop(key)
                reasons.append(key)
        if "research_outcomes" in result:
            result["research_outcomes"] = [
                {
                    k: v
                    for k, v in row.items()
                    if k
                    in {
                        "round",
                        "status",
                        "search_attempts",
                        "fetch_attempts",
                        "searches",
                        "fetches",
                    }
                }
                for row in result["research_outcomes"]
                if isinstance(row, dict)
            ]
            reasons.append("unused_lead_detail")
    if bound(result) > limit:
        # Repeated full evidence inside candidate checks can refer to the top-level
        # canonical block. References retain identity; citations/claims stay intact.
        canonical_sources = {
            p["id"]: p
            for p in result.get("evidence", [])
            if isinstance(p, dict) and "id" in p and "text" in p
        }

        def references(value, top=False):
            if isinstance(value, dict):
                source = canonical_sources.get(value.get("id"))
                if not top and source is not None and value == source:
                    return {"evidence_ref": source["id"], "source_hash": source["source_hash"]}
                return {k: references(v) for k, v in value.items()}
            if isinstance(value, list):
                return [references(v, top) for v in value]
            return value

        result = {k: references(v, k == "evidence") for k, v in result.items()}
        reasons.append("redundant_evidence_serialization")
    final = bound(result)
    report = {
        "version": BUILDER_VERSION,
        "original_bound": original,
        "final_bound": final,
        "limit": limit,
        "reasons": reasons,
        "retained_ids": sorted(evidence_ids(result)),
        "omitted_ids": sorted(evidence_ids(context) - evidence_ids(result)),
        "context_hash": digest(result),
        "coverage": "complete" if final <= limit else "incomplete",
    }
    return result, report
