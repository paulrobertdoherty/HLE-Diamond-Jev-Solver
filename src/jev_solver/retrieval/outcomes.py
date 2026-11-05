"""Bounded planner views of the full, privately logged research outcomes."""

from ..models import digest


def boundary_rows(boundary, passages, selected, *, reasons=None, policy="legacy-v1", budgets=None):
    """Account for occurrences, retaining content identity and dependency associations."""
    retained = {p.id for p in selected}
    selected_by_id = {p.id: p for p in selected}
    reasons = reasons or {}
    return [
        {
            "boundary": boundary,
            "occurrence": i,
            "passage_id": p.id,
            "source_hash": p.source_hash,
            "url": p.url,
            "start": p.start,
            "end": p.end,
            "text_hash": digest(p.text),
            "dependency_ids": list(
                getattr(p, "dependency_ids", ()) or ((p.dependency_id,) if p.dependency_id else ())
            ),
            "selected": p.id in retained,
            "selected_dependency_ids": list(selected_by_id[p.id].dependency_ids)
            if p.id in retained and selected_by_id[p.id].dependency_ids
            else ([p.dependency_id] if p.id in retained and p.dependency_id else []),
            "reason": "retained" if p.id in retained else reasons.get(p.id, "not_selected"),
            "judgment_availability": p.relevance_status,
            "policy": policy,
            "budgets": budgets or {},
        }
        for i, p in enumerate(passages)
    ]


def planner_outcomes(outcomes):
    result = []
    for outcome in outcomes:
        leads = outcome.get("leads", [])
        # Unfetched, already-ranked leads are the most useful follow-up inputs.
        ordered = [x for x in leads if x["status"] != "fetched"] + [
            x for x in leads if x["status"] == "fetched"
        ]
        result.append(
            {
                **outcome,
                "leads": [
                    {**lead, "snippet": lead.get("snippet", "")[:400]} for lead in ordered[:8]
                ],
                "omitted_lead_count": max(0, len(leads) - 8),
            }
        )
    return result
