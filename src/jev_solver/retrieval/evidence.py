from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import urlsplit

from ..models import EvidencePassage, digest


def words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def chunk_page(page: dict, subquestion: str, size: int = 2400) -> list[EvidencePassage]:
    text = page["text"]
    # Split at paragraph boundaries where possible; offsets always refer to stored source text.
    spans = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind("\n\n", start + size // 2, end)
            if boundary > start:
                end = boundary + 2
        spans.append((start, end))
        start = end
    now = page.get("retrieved_at") or datetime.now(timezone.utc).isoformat()
    return [
        EvidencePassage(
            digest([page["url"], page["source_hash"], a, b]),
            page["url"],
            page["source_hash"],
            text[a:b],
            a,
            b,
            now,
            page["filter_version"],
            title=page.get("title", ""),
            subquestion=subquestion,
        )
        for a, b in spans
        if text[a:b].strip()
    ]


def lexical_score(query: str, passage: str) -> float:
    q, p = Counter(words(query)), Counter(words(passage))
    return sum(min(n, p[w]) for w, n in q.items()) / max(1, sum(q.values()))


def lexical_rank(passages: list[EvidencePassage]) -> list[EvidencePassage]:
    return sorted(
        (replace(p, score=lexical_score(p.subquestion, p.text)) for p in passages),
        key=lambda p: (-(p.score or 0), p.id),
    )


def diverse_packet(
    passages: list[EvidencePassage], chars: int, limit: int = 6
) -> list[EvidencePassage]:
    packet, seen, hosts = [], set(), Counter()
    used = 0
    for passage in passages:
        host = urlsplit(passage.url).hostname
        fingerprint = digest(passage.text)
        if fingerprint in seen or hosts[host] >= 2 or used + len(passage.text) > chars:
            continue
        packet.append(passage)
        seen.add(fingerprint)
        hosts[host] += 1
        used += len(passage.text)
        if len(packet) == limit:
            break
    return packet


def bm25(query: str, texts: list[str]) -> list[float]:
    docs = [Counter(words(t)) for t in texts]
    n = len(docs)
    avg = sum(sum(d.values()) for d in docs) / max(1, n)
    scores = [0.0] * n
    for word in set(words(query)):
        df = sum(word in d for d in docs)
        idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
        for i, doc in enumerate(docs):
            tf = doc[word]
            if tf:
                scores[i] += (
                    idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * sum(doc.values()) / max(avg, 1)))
                )
    return scores
