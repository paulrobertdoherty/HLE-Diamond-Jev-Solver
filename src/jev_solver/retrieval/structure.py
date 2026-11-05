"""Source-mapped structural views, derived after full-page policy filtering."""

import re

from ..models import EvidencePassage, digest

STRUCTURE_VERSION = "structured-views-v1"


def structural_spans(page):
    text = page["text"]
    spans = list(page.get("structures", []))
    headings = list(
        re.finditer(
            r"(?m)^(?:#{1,6}\s+[^\n]+|(?:Definition|Theorem|Lemma|Proposition)\b[^\n]*)", text
        )
    )
    for i, heading in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        label = heading.group().casefold()
        kind = (
            "definition"
            if "definition" in label
            else "theorem"
            if any(k in label for k in ("theorem", "lemma", "proposition"))
            else "heading"
        )
        spans.append(
            {"kind": kind, "start": heading.start(), "end": min(end, heading.start() + 2400)}
        )
    return [
        s
        for s in spans
        if type(s.get("start")) is int
        and type(s.get("end")) is int
        and 0 <= s["start"] < s["end"] <= len(text)
    ]


def structured_passages(page, subquestion, *, question="", search_query="", dependency_id=""):
    result = []
    for span in structural_spans(page):
        a, b = span["start"], span["end"]
        if b - a > 2400:
            b = a + 2400
        view = {
            **span,
            "version": STRUCTURE_VERSION,
            "canonical_start": a,
            "canonical_end": b,
            "labels_are_metadata": True,
        }
        if span["kind"] == "table_row" and "headers" not in span:
            view["header_status"] = "unavailable"
        result.append(
            EvidencePassage(
                digest([page["url"], page["source_hash"], a, b]),
                page["url"],
                page["source_hash"],
                page["text"][a:b],
                a,
                b,
                page.get("retrieved_at", ""),
                page["filter_version"],
                title=page.get("title", ""),
                subquestion=subquestion,
                question=question,
                search_query=search_query,
                dependency_id=dependency_id,
                dependency_ids=(dependency_id,) if dependency_id else (),
                view=view,
            )
        )
    return result


def display_cost(passage):
    """Repeated headers and labels consume the packet's character allowance."""
    from ..models import canonical

    return len(passage.text) + (len(canonical(passage.view)) if passage.view else 0)
