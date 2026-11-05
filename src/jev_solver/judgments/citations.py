"""Exact quote resolution against immutable passages. No fuzzy or cross-source repair."""

from copy import deepcopy

from ..models import Candidate, Citation, record

QUOTE_VERSION = "citation-quotes-v1"


def resolve_citations(raw, evidence):
    value = deepcopy(raw)
    sources = {p.id: p for p in evidence}
    traces, resolved, unresolved_claims = [], [], []
    for row in value.get("citations", []):
        if not isinstance(row, dict):
            raise ValueError("invalid citation record")
        p = sources.get(row.get("passage_id"))
        quote = row.get("quote")
        start, end = row.get("start"), row.get("end")
        reason = ""
        if p is None:
            reason = "wrong_passage"
        elif row.get("source_hash") and row["source_hash"] != p.source_hash:
            reason = "source_identity_changed"
        elif not isinstance(quote, str) or not quote:
            reason = "absent_quote"
        elif (
            type(start) is int
            and type(end) is int
            and 0 <= start < end <= len(p.text)
            and p.text[start:end] == quote
        ):
            reason = "valid_explicit_span"
        else:
            matches, at = [], 0
            while True:
                at = p.text.find(quote, at)
                if at < 0:
                    break
                matches.append(at)
                at += 1
            if len(matches) == 1:
                start, end = matches[0], matches[0] + len(quote)
                reason = "unique_exact_quote"
            else:
                reason = "ambiguous_quote" if matches else "absent_quote"
        success = reason in {"valid_explicit_span", "unique_exact_quote"}
        traces.append(
            {
                "passage_id": row.get("passage_id"),
                "source_hash": p.source_hash if p else None,
                "original": {"start": row.get("start"), "end": row.get("end")},
                "resolved": {"start": start, "end": end} if success else None,
                "reason": reason,
                "version": QUOTE_VERSION,
            }
        )
        if success:
            resolved.append(
                record(
                    Citation.parse(
                        {**row, "start": start, "end": end, "source_hash": p.source_hash}
                    )
                )
            )
        elif row.get("critical"):
            unresolved_claims.append(row.get("claim", ""))
    value["citations"] = resolved
    # Failed output references are pending claims, never fabricated internal Citations.
    value["source_claims"] = list(dict.fromkeys(value.get("source_claims", []) + unresolved_claims))
    return value, traces


def parse_candidate(raw, identifier, evidence=(), *, resolve=False):
    value, traces = resolve_citations(raw, evidence) if resolve else (raw, [])
    return Candidate.parse(value, identifier), traces
