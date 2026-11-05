from __future__ import annotations

import math
import re
from collections import Counter, deque
from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import urlsplit

from ..models import EvidencePassage, digest


def words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def chunk_page(
    page: dict,
    subquestion: str,
    size: int = 2400,
    *,
    question: str = "",
    search_query: str = "",
    dependency_id: str = "",
) -> list[EvidencePassage]:
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
            question=question,
            search_query=search_query,
            dependency_id=dependency_id,
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


def merge_associations(passages, *, text_identity=False):
    merged = {}
    for p in passages:
        key = digest(p.text) if text_identity else p.id
        dependencies = tuple(
            dict.fromkeys((*p.dependency_ids, *((p.dependency_id,) if p.dependency_id else ())))
        )
        provenance = p.source_provenance or (
            {
                "passage_id": p.id,
                "url": p.url,
                "source_hash": p.source_hash,
                "start": p.start,
                "end": p.end,
            },
        )
        if key in merged:
            old = merged[key]
            merged[key] = replace(
                old,
                dependency_ids=tuple(dict.fromkeys((*old.dependency_ids, *dependencies))),
                source_provenance=tuple(
                    {digest(v): v for v in (*old.source_provenance, *provenance)}.values()
                ),
                view=old.view or p.view,
            )
        else:
            merged[key] = replace(
                p, dependency_ids=dependencies, source_provenance=tuple(provenance)
            )
    return list(merged.values())


def retrieval_shortlist(
    passages: list[EvidencePassage], limit: int = 20, *, policy="legacy-v1", structural_slots=4
) -> list[EvidencePassage]:
    """Give each query and source a turn before admitting more chunks from a long page."""
    if policy == "remediation-v1":
        passages = merge_associations(passages)
        structures = [
            p for p in passages if p.view.get("kind") in {"definition", "theorem", "table_row"}
        ]
        reserved = retrieval_shortlist(structures, min(structural_slots, limit))
        reserved_ids = {p.id for p in reserved}
        lexical = retrieval_shortlist(
            [p for p in passages if p.id not in reserved_ids], limit - len(reserved)
        )
        return lexical + reserved
    if limit <= 0:
        return []
    queries = {}
    for passage in lexical_rank(passages):
        sources = queries.setdefault(passage.subquestion, {})
        sources.setdefault(passage.url, deque()).append(passage)
    query_queues = deque(deque(sources.values()) for sources in queries.values())
    result, seen = [], set()
    while query_queues and len(result) < limit:
        sources = query_queues.popleft()
        source = sources.popleft()
        passage = source.popleft()
        if passage.id not in seen:
            seen.add(passage.id)
            result.append(passage)
        if source:
            sources.append(source)
        if sources:
            query_queues.append(sources)
    return result


def diverse_packet(
    passages: list[EvidencePassage],
    chars: int,
    limit: int = 6,
    *,
    alternative_slots: int = 1,
    trace: list | None = None,
) -> list[EvidencePassage]:
    packet, seen, hosts = [], set(), Counter()
    used = 0
    # Reserve bounded room for uncertain alternatives before high scores can
    # exhaust either the character budget or the per-host allowance.
    alternatives = [p for p in passages if p.relevance_status == "uncertain"][:alternative_slots]
    ordered = alternatives + [p for p in passages if p.relevance_status != "uncertain"]
    queries = {}
    for passage in ordered:
        queries.setdefault(passage.subquestion, deque()).append(passage)
    queues = deque(queries.values())
    while queues:
        query = queues.popleft()
        passage = query.popleft()
        if query:
            queues.append(query)
        host = urlsplit(passage.url).hostname
        fingerprint = digest(passage.text)
        reason = (
            "passage_limit"
            if len(packet) == limit
            else "duplicate_text"
            if fingerprint in seen
            else "per_host_limit"
            if hosts[host] >= 2
            else "character_limit"
            if used + len(passage.text) > chars
            else "retained"
        )
        if trace is not None:
            trace.append({"passage_id": passage.id, "reason": reason})
        if reason != "retained":
            continue
        packet.append(passage)
        seen.add(fingerprint)
        hosts[host] += 1
        used += len(passage.text)
        if len(packet) == limit and trace is None:
            break
    return packet


def rank_leads(results: list[dict], missing_fact: str, *, preferred_urls=()) -> list[dict]:
    """Audited snippets prioritize fetches; they never become evidence passages."""
    return [
        row
        for _, row in sorted(
            enumerate(results),
            key=lambda pair: (
                preferred_urls.index(pair[1]["url"])
                if pair[1]["url"] in preferred_urls
                else len(preferred_urls),
                -lexical_score(
                    missing_fact, pair[1].get("title", "") + " " + pair[1].get("snippet", "")
                ),
                pair[0],
            ),
        )
    ]


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
