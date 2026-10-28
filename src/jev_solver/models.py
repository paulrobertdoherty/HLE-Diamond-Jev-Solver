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


@dataclass(frozen=True)
class Citation:
    claim: str
    passage_id: str
    quote: str
    start: int
    end: int
    critical: bool

    @classmethod
    def parse(cls, row: dict) -> Citation:
        c = cls(**row)
        if (
            any(not isinstance(s, str) for s in (c.claim, c.passage_id, c.quote))
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

    @classmethod
    def parse(cls, row: dict, candidate_id: str) -> Candidate:
        required = {"answer", "confidence", "verification", "gaps", "queries", "code", "citations"}
        if set(row) != required:
            raise ValueError("malformed candidate fields")
        if any(not isinstance(row[k], str) for k in ("answer", "verification", "code")):
            raise ValueError("candidate text must be strings")
        for k in ("gaps", "queries"):
            if not isinstance(row[k], list) or any(not isinstance(s, str) for s in row[k]):
                raise ValueError("candidate gaps and queries must be string lists")
        return cls(
            candidate_id,
            row["answer"],
            probability(row["confidence"]),
            row["verification"],
            tuple(row["gaps"]),
            tuple(row["queries"]),
            row["code"],
            tuple(Citation.parse(c) for c in row["citations"]),
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
