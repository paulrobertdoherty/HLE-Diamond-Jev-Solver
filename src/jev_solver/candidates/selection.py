from __future__ import annotations

import random
import re
import unicodedata
from collections import OrderedDict

from ..models import Candidate, digest


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


async def select(jev, gateway, question, candidates: list[Candidate], policy: str, seed: int):
    if policy == "vote":
        return vote(candidates)
    shuffled = list(candidates)
    random.Random(seed + int(digest(question.id)[:8], 16)).shuffle(shuffled)
    names = {f"candidate_{i}": c for i, c in enumerate(shuffled)}
    state = {
        "question": question.question,
        "candidates": {
            k: {"answer": c.answer, "verification": c.verification} for k, c in names.items()
        },
    }
    if policy == "jev":
        result = await jev.request(
            question.id,
            "J5",
            state,
            {
                "selected": {
                    "type": "choice",
                    "instructions": "Select the best supported answer from anonymized candidates. No candidate may be adequately supported.",
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
