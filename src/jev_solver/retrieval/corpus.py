"""Optional extended-track frozen corpus. Dense baseline uses fixed hashed character features."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from pathlib import Path

from ..benchmarks.data import read_jsonl
from ..models import EvidencePassage, digest
from ..tools.policy import Policy
from ..tracing.store import atomic_json
from .evidence import bm25, chunk_page

FEATURE_MODEL = "sha256-char-trigrams-256-v1"


def vector(text: str) -> list[float]:
    result = [0.0] * 256
    text = " ".join(text.casefold().split())
    for i in range(max(0, len(text) - 2)):
        h = hashlib.sha256(text[i : i + 3].encode()).digest()
        result[h[0]] += 1 if h[1] % 2 else -1
    norm = math.sqrt(sum(v * v for v in result)) or 1
    return [v / norm for v in result]


def build_corpus(source: Path, output: Path, policy: Policy, revision: str) -> dict:
    if output.exists():
        raise ValueError("frozen corpus output already exists")
    passages, provenance = [], []
    for doc in read_jsonl(source):
        if (
            set(doc) != {"url", "title", "text", "license", "ingested_at"}
            or not doc["license"]
            or not doc["ingested_at"]
        ):
            raise ValueError("corpus documents require explicit license and ingestion date")
        policy.page(doc)
        source_hash = digest(doc["text"])
        page = {**doc, "source_hash": source_hash, "filter_version": policy.version}
        passages.extend(asdict(p) for p in chunk_page(page, ""))
        provenance.append({k: v for k, v in page.items() if k != "text"})
    if not passages:
        raise ValueError("empty corpus")
    result = {
        "revision": revision,
        "chunking_version": "paragraph-v1",
        "feature_model": FEATURE_MODEL,
        "filter_version": policy.version,
        "source_hash": digest(read_jsonl(source)),
        "provenance": provenance,
        "passages": passages,
    }
    result["content_hash"] = digest(result)
    atomic_json(output, result)
    return {"revision": revision, "passages": len(passages), "content_hash": result["content_hash"]}


class Corpus:
    def __init__(self, path: Path, policy: Policy):
        self.data = json.loads(path.read_text())
        if (
            digest({k: v for k, v in self.data.items() if k != "content_hash"})
            != self.data["content_hash"]
        ):
            raise ValueError("frozen corpus hash mismatch")
        if (
            self.data["feature_model"] != FEATURE_MODEL
            or self.data["filter_version"] != policy.version
        ):
            raise ValueError(
                "corpus feature/filter version mismatch; rebuild and declare a new revision"
            )
        self.passages = [EvidencePassage(**p) for p in self.data["passages"]]
        for p in self.passages:
            policy.page({"url": p.url, "title": p.title, "text": p.text})
        self.vectors = [vector(p.text) for p in self.passages]

    def retrieve(self, query: str, hybrid: bool = False, limit: int = 20) -> list[EvidencePassage]:
        lexical = bm25(query, [p.text for p in self.passages])
        orders = [sorted(range(len(self.passages)), key=lambda i: (-lexical[i], i))]
        if hybrid:
            q = vector(query)
            dense = [sum(a * b for a, b in zip(q, v, strict=True)) for v in self.vectors]
            orders.append(sorted(range(len(self.passages)), key=lambda i: (-dense[i], i)))
        fused = [0.0] * len(self.passages)
        for order in orders:
            for rank, index in enumerate(order):
                fused[index] += 1 / (60 + rank + 1)
        from dataclasses import replace

        return [
            replace(self.passages[i], subquestion=query)
            for i in sorted(range(len(fused)), key=lambda i: (-fused[i], i))[:limit]
        ]
