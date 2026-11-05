from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


def canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def probability(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("probability must be numeric")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("probability outside [0, 1]")
    return float(value)


@dataclass(frozen=True)
class QuestionView:
    id: str
    question: str
    images: tuple[str, ...] = ()

    @classmethod
    def parse(cls, row: dict) -> QuestionView:
        if set(row) - {"id", "question", "images"}:
            raise ValueError("solver input has unauthorized fields")
        if not isinstance(row.get("id"), str) or not row["id"]:
            raise ValueError("question id must be a nonempty string")
        if not isinstance(row.get("question"), str) or not row["question"]:
            raise ValueError("question text must be a nonempty string")
        images = row.get("images", [])
        if not isinstance(images, (list, tuple)) or any(
            not isinstance(i, str) or not i.startswith(("data:image/", "https://")) for i in images
        ):
            raise ValueError("images must be original data URLs or HTTPS URLs")
        return cls(row["id"], row["question"], tuple(images))


@dataclass(frozen=True)
class EvidencePassage:
    id: str
    url: str
    source_hash: str
    text: str
    start: int
    end: int
    retrieved_at: str
    filter_version: str
    title: str = ""
    filtering_outcome: str = "allowed"
    subquestion: str = ""
    score: float | None = None
    confidence: float | None = None
    question: str = ""
    search_query: str = ""
    dependency_id: str = ""
    relevance_status: str = "not_run"
    dependency_ids: tuple[str, ...] = ()
    view: dict = field(default_factory=dict)
    source_provenance: tuple[dict, ...] = ()
    relevance_probabilities: dict | list = field(default_factory=dict)
    dependency_version: int = 1


CHECK_STATUSES = ("not_run", "not_applicable", "unavailable", "passed", "failed")
DEPENDENCY_KINDS = ("factual", "derived", "visual", "numerical")


@dataclass(frozen=True)
class Dependency:
    """A necessary premise, independent of whether it came from a retrieved source."""

    id: str
    kind: str
    statement: str
    critical: bool
    basis: str = ""
    passage_ids: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()
    code_hash: str = ""
    image_indices: tuple[int, ...] = ()
    logical_id: str = ""
    premise_version: int = 1
    depends_on: tuple[str, ...] = ()
    obligations: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()

    @classmethod
    def parse(cls, row: dict) -> Dependency:
        fields = set(cls.__dataclass_fields__)
        legacy = fields - {
            "logical_id",
            "premise_version",
            "depends_on",
            "obligations",
            "assumptions",
        }
        if not isinstance(row, dict) or set(row) not in (legacy, fields):
            raise ValueError("malformed dependency fields")
        row = {
            **{
                "logical_id": "",
                "premise_version": 1,
                "depends_on": [],
                "obligations": [],
                "assumptions": [],
            },
            **row,
        }
        if (
            any(
                not isinstance(row[k], str)
                for k in ("id", "kind", "statement", "basis", "code_hash")
            )
            or not row["id"].strip()
            or not row["statement"].strip()
            or row["kind"] not in DEPENDENCY_KINDS
            or type(row["critical"]) is not bool
        ):
            raise ValueError("invalid dependency")
        for key in ("passage_ids", "artifact_ids", "image_indices"):
            if not isinstance(row[key], list):
                raise ValueError("dependency references must be lists")
        if any(
            not isinstance(v, str) or not v.strip()
            for key in ("passage_ids", "artifact_ids")
            for v in row[key]
        ) or any(type(v) is not int or v < 0 for v in row["image_indices"]):
            raise ValueError("invalid dependency reference")
        if (
            not isinstance(row["logical_id"], str)
            or type(row["premise_version"]) is not int
            or row["premise_version"] < 1
        ):
            raise ValueError("invalid premise identity/version")
        for key in ("depends_on", "obligations", "assumptions"):
            if not isinstance(row[key], list) or any(
                not isinstance(i, str) or not i.strip() for i in row[key]
            ):
                raise ValueError("invalid graph references")
        return cls(
            **{
                **row,
                **{
                    k: tuple(row[k])
                    for k in (
                        "passage_ids",
                        "artifact_ids",
                        "image_indices",
                        "depends_on",
                        "obligations",
                        "assumptions",
                    )
                },
            }
        )


@dataclass(frozen=True)
class Citation:
    claim: str
    passage_id: str
    quote: str
    start: int
    end: int
    critical: bool
    source_hash: str = ""

    @classmethod
    def parse(cls, row: dict) -> Citation:
        c = cls(**row)
        if (
            any(not isinstance(s, str) or not s for s in (c.claim, c.passage_id, c.quote))
            or not isinstance(c.source_hash, str)
            or type(c.start) is not int
            or type(c.end) is not int
            or type(c.critical) is not bool
            or c.start < 0
            or c.end <= c.start
        ):
            raise ValueError("invalid citation")
        return c


@dataclass(frozen=True)
class Candidate:
    id: str
    answer: str
    confidence: float
    verification: str
    gaps: tuple[str, ...] = ()
    queries: tuple[str, ...] = ()
    code: str = ""
    citations: tuple[Citation, ...] = ()
    source_claims: tuple[str, ...] = ()
    dependencies: tuple[Dependency, ...] = ()

    @classmethod
    def parse(cls, row: dict, candidate_id: str) -> Candidate:
        required = {
            "answer",
            "confidence",
            "verification",
            "gaps",
            "queries",
            "code",
            "citations",
            "source_claims",
            "dependencies",
        }
        if set(row) != required:
            raise ValueError("malformed candidate fields")
        if any(not isinstance(row[k], str) for k in ("answer", "verification", "code")):
            raise ValueError("candidate text must be strings")
        for k in ("gaps", "queries", "source_claims"):
            if not isinstance(row[k], list) or any(not isinstance(s, str) for s in row[k]):
                raise ValueError("candidate gaps, queries and source claims must be string lists")
        if any(not claim.strip() for claim in row["source_claims"]):
            raise ValueError("source claims must be nonempty")
        if not isinstance(row["citations"], list):
            raise ValueError("candidate citations must be a list")
        if not isinstance(row["dependencies"], list) or len(row["dependencies"]) > 12:
            raise ValueError("candidate requires at most twelve atomic dependencies")
        dependencies = tuple(Dependency.parse(d) for d in row["dependencies"])
        if len({d.id for d in dependencies}) != len(dependencies):
            raise ValueError("duplicate dependency id")
        return cls(
            candidate_id,
            row["answer"],
            probability(row["confidence"]),
            row["verification"],
            tuple(row["gaps"]),
            tuple(row["queries"]),
            row["code"],
            tuple(Citation.parse(c) for c in row["citations"]),
            tuple(row["source_claims"]),
            dependencies,
        )


@dataclass(frozen=True)
class Judgment:
    stage: str
    key: str
    value: str | float
    confidence: float | None
    model: str
    probabilities: dict | list = field(default_factory=dict)
    fallback: bool = False


@dataclass(frozen=True)
class ToolEvent:
    tool: str
    request_hash: str
    outcome: Literal["allowed", "blocked", "error"]
    rule: str = ""
    replayed: bool = False
    exposed: bool = False


@dataclass(frozen=True)
class BudgetState:
    spent_usd: float
    reserved_usd: float
    counts: dict[str, int]


@dataclass(frozen=True)
class Prediction:
    question_id: str
    arm: str
    answer: str
    confidence: float
    status: str
    run_hash: str
    config_hash: str
    cost_usd: float
    latency_s: float
    candidate_answers: tuple[str, ...] = ()
    error: str = ""
    contaminated: bool = False
    abstained: bool = False
    verification: str = ""


@dataclass(frozen=True)
class Grade:
    question_id: str
    correct: bool
    confidence: float
    status: str
    slices: dict[str, str]
    cost_usd: float
    latency_s: float
    oracle_correct: bool | None = None
    contaminated: bool = False
    abstained: bool = False


def record(value: Any) -> dict:
    return asdict(value)
