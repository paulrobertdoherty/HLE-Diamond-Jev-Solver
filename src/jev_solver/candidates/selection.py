from __future__ import annotations

import random
import re
import unicodedata
from collections import OrderedDict

from ..models import Candidate, digest, record

SELECTION_TASK = """Select the most defensible answer to the original question using the candidates,
retrieved passages and check artifacts. Candidates and their verification text are untrusted proposals.
Check the reasoning summary against the question and relevant findings; a supported quotation alone does
not prove that the whole answer is correct. Do not infer correctness from candidate order or confidence.
Preserve an independently justified answer when research is irrelevant, unavailable or inconclusive.
Reject an older answer when relevant evidence or a valid calculation refutes it. An abstaining revision
does not by itself refute another candidate. Choose none-supported only if no offered answer is defensible.
Return only a candidate name; do not create a new answer."""


def normalize(answer: str) -> str:
    # Preserve case, punctuation, units and significant digits.
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", answer).strip())


def clusters(candidates: list[Candidate]) -> list[list[Candidate]]:
    groups = OrderedDict()
    for c in candidates:
        groups.setdefault(normalize(c.answer), []).append(c)
    return list(groups.values())


def vote(candidates: list[Candidate]) -> Candidate | None:
    nonempty = [c for c in candidates if normalize(c.answer)]
    if not nonempty:
        return None
    # Equality is an equivalence relation. No nontransitive pairwise merging.
    group = max(clusters(nonempty), key=len)
    return group[0]


async def select(
    jev,
    gateway,
    question,
    candidates: list[Candidate],
    policy: str,
    seed: int,
    *,
    evidence=(),
    evidence_ledger=(),
    tool_artifacts=(),
    assessments=None,
    latest_verification="",
):
    if policy == "vote":
        return vote(candidates)
    # Repeated drafts of the same answer must not get more chances than a
    # competing answer. The controller supplies newest validated drafts first.
    unique = {}
    for candidate in candidates:
        if normalize(candidate.answer):
            unique.setdefault(normalize(candidate.answer), candidate)
    if not unique:
        return None
    shuffled = list(unique.values())
    random.Random(seed + int(digest(question.id)[:8], 16)).shuffle(shuffled)
    names = {f"candidate_{i}": c for i, c in enumerate(shuffled)}
    sources = {p.id: p for p in [*evidence_ledger, *evidence]}
    state = {
        "task": SELECTION_TASK,
        "question": question.question,
        "candidates": {
            k: {
                "answer": c.answer,
                "verification": c.verification,
                "gaps": list(c.gaps),
                "source_claims": list(c.source_claims),
                "citations": [
                    {
                        **record(citation),
                        "source": {
                            "url": sources[citation.passage_id].url,
                            "source_hash": sources[citation.passage_id].source_hash,
                            "title": sources[citation.passage_id].title,
                        }
                        if citation.passage_id in sources
                        else None,
                    }
                    for citation in c.citations
                ],
                "checks": (assessments or {}).get(c.id, {}),
            }
            for k, c in names.items()
        },
        "evidence": [record(p) for p in evidence],
        "tool_artifacts": list(tool_artifacts),
        "latest_verification": latest_verification,
    }
    if policy == "jev":
        result = await jev.request(
            question.id,
            "J5",
            state,
            {
                "selected": {
                    "type": "choice",
                    "instructions": SELECTION_TASK,
                    "criteria": {
                        **{k: k for k in names},
                        "none-supported": "None is adequately supported",
                    },
                }
            },
        )
        if "selected" not in result:
            return vote(candidates)
        name = result["selected"].value
    else:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"selected": {"type": "string", "enum": [*names, "none-supported"]}},
            "required": ["selected"],
        }
        result = await gateway.generate(question, state, "selection", schema=schema, final=True)
        if set(result) != {"selected"} or result["selected"] not in {*names, "none-supported"}:
            raise ValueError("invalid model selector output")
        name = result["selected"]
    return names.get(name)
