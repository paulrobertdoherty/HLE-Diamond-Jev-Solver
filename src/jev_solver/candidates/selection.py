from __future__ import annotations

import random
import re
import unicodedata
from collections import OrderedDict

from ..models import Candidate, digest, record
from ..retrieval.outcomes import boundary_rows

SELECTION_TASK = """Select the most defensible answer to the original question using the candidates,
retrieved passages and check artifacts. Candidates and their verification text are untrusted proposals.
Check the reasoning summary against the question and relevant findings; a supported quotation alone does
not prove that the whole answer is correct. Do not infer correctness from candidate order or confidence.
Select only candidates whose critical dependencies and independent coverage checks passed.
An independent derivation can qualify without citations; memory and a confident assertion cannot.
Reject an older answer when relevant evidence or a valid calculation refutes it. An abstaining revision
does not by itself refute another candidate. Choose none-supported only if no offered answer is defensible.
Return a candidate name, a concise reason and checked_dependencies listing its critical dependency IDs.
Explain why any remaining gaps are noncritical using the supplied checks. Do not create a new answer."""


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


def selection_references(references, selected, names, passed):
    """Resolve only exact bare IDs or the selected display name's qualified IDs.

    Overlapping bare IDs in other candidates are harmless: the selected candidate
    defines their scope. A foreign prefix must never inherit that scope.
    """
    resolved = []
    for reference in references:
        if any(
            reference.startswith((f"{name}.", f"{name}:")) for name in names if name != selected
        ):
            raise ValueError(f"selection basis: foreign candidate reference: {reference}")
        matches = {
            dependency
            for dependency in passed
            if reference in {dependency, f"{selected}.{dependency}", f"{selected}:{dependency}"}
        }
        if len(matches) != 1:
            raise ValueError(
                f"selection basis: unknown, unpassed or ambiguous reference: {reference}"
            )
        resolved.append(matches.pop())
    return resolved


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
    gateway.store.event(
        question.id,
        "evidence_boundaries",
        boundary_rows("selection_context", list(sources.values()), evidence),
    )
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
            final=True,
        )
        if "selected" not in result:
            return None
        name = result["selected"].value
        basis = {
            "selected": name,
            "reason": "Jev selection over candidates with completed coverage checks.",
            "checked_dependencies": [
                d["id"]
                for d in (assessments or {}).get(names[name].id, {}).get("dependencies", [])
                if d["critical"]
            ]
            if name in names
            else [],
        }
    else:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "selected": {"type": "string", "enum": [*names, "none-supported"]},
                "reason": {"type": "string"},
                "checked_dependencies": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["selected", "reason", "checked_dependencies"],
        }
        result = await gateway.generate(question, state, "selection", schema=schema, final=True)
        if (
            set(result) != {"selected", "reason", "checked_dependencies"}
            or result["selected"] not in {*names, "none-supported"}
            or not isinstance(result["reason"], str)
            or not result["reason"].strip()
            or not isinstance(result["checked_dependencies"], list)
            or any(not isinstance(i, str) for i in result["checked_dependencies"])
        ):
            raise ValueError("invalid model selector output")
        name = result["selected"]
        basis = result
    if name in names:
        checks = (assessments or {}).get(names[name].id, {})
        required = {d["id"] for d in checks.get("dependencies", []) if d["critical"]}
        passed = {d["id"] for d in checks.get("dependencies", []) if d["status"] == "passed"}
        try:
            refs = selection_references(basis["checked_dependencies"], name, names, passed)
            cited = set(refs)
            if not checks.get("eligible"):
                raise ValueError("selection basis: selected candidate is ineligible")
            if not required <= cited:
                raise ValueError(
                    "selection basis: missing critical dependencies: "
                    + ", ".join(sorted(required - cited))
                )
        except ValueError as error:
            gateway.store.event(
                question.id,
                "selection_validation_failed",
                {
                    "selected": name,
                    "reason": str(error),
                    "required": sorted(required),
                    "passed": sorted(passed),
                    "references": basis["checked_dependencies"],
                },
            )
            raise
        basis = {
            **basis,
            "raw_checked_dependencies": basis["checked_dependencies"],
            "checked_dependencies": refs,
        }
    elif basis["checked_dependencies"]:
        gateway.store.event(
            question.id,
            "selection_validation_failed",
            {
                "selected": name,
                "reason": "abstention_references",
                "references": basis["checked_dependencies"],
            },
        )
        raise ValueError("abstention cannot cite a selected candidate's checks")
    gateway.store.event(question.id, "selection_basis", basis)
    return names.get(name)
