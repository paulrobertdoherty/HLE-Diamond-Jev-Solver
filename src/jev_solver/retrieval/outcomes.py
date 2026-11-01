"""Bounded planner views of the full, privately logged research outcomes."""


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
