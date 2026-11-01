"""Bounded, replayable research with explicit outcomes for the verification planner."""

from __future__ import annotations

import math
from dataclasses import replace

from ..judgments.pipeline import rerank
from ..models import EvidencePassage, digest, record
from ..providers.backbone import ProviderError
from ..tools.policy import Blocked
from ..retrieval.evidence import (
    chunk_page,
    diverse_packet,
    lexical_rank,
    rank_leads,
    retrieval_shortlist,
)
from .budget import BudgetExceeded, CallLimitExceeded


async def research(solver, q, plan, round_no, previous):
    config = solver.config
    # Use logical attempts, not current database counts, to reconstruct identical
    # quotas on resume. The budget still enforces actual dispatches and retries.
    searches_used = sum(o["search_attempts"] for o in previous)
    fetches_used = sum(o["fetch_attempts"] for o in previous)
    searches_left = max(0, config.limits.search - searches_used)
    fetches_left = max(0, config.limits.fetch - fetches_used)
    rounds_left = max(1, config.limits.rounds - round_no)
    search_quota = max(1, math.ceil(searches_left / rounds_left)) if searches_left else 0
    attempted = {x["query"] for o in previous for x in o["searches"]}
    queries = [query for query in plan if query["query"] not in attempted][:search_quota]
    reserve = (
        min(config.followup_fetch_reserve, max(0, fetches_left - 1))
        if (rounds_left > 1 and searches_left > len(queries))
        else 0
    )
    fetch_slots = fetches_left - reserve
    identity = {
        "research_version": 3,
        "question": record(q),
        "queries": queries,
        "round": round_no,
        "previous": previous,
        "config_hash": config.hash,
        "filter_version": solver.policy.version,
    }
    key = digest(identity)
    cached = solver.store.cached(q.id, key)
    if cached is not None:
        # Revalidate complete cached pages through the original audited boundary.
        # Missing cache entries must not silently dispatch a new paid fetch.
        source_pages = {}
        for url in cached["source_requests"]:
            try:
                page = await solver.web.fetch(q.id, url, cache_only=True)
            except ProviderError:
                page = None
            if page:
                source_pages[(page["url"], page["source_hash"])] = page
        packet = []
        for row in cached["packet"]:
            p = EvidencePassage(**row)
            try:
                solver.policy.page({"url": p.url, "title": p.title, "text": p.text})
            except Blocked:
                continue
            source = source_pages.get((p.url, p.source_hash))
            if source and source["text"][p.start : p.end] == p.text:
                packet.append(p)
            elif solver.corpus and p.id in cached.get("corpus_ids", []):
                packet.append(p)
        outcome = cached["outcome"]
        safe_leads = []
        for lead in outcome["leads"]:
            try:
                solver.policy.result(lead)
            except Blocked:
                continue
            safe_leads.append(lead)
        outcome["leads"] = safe_leads
        outcome["packet_ids"] = [p.id for p in packet]
        if not packet:
            outcome["status"] = "no_evidence"
        solver.store.event(q.id, "research_replay", {"request_hash": key})
        return packet, outcome

    passages, pages, searches, leads, fetches = [], {}, [], [], []
    corpus_ids = set()
    attempts = 0
    budget_limited = False
    for query_no, query in enumerate(queries):
        if solver.corpus:
            corpus_passages = [
                replace(
                    p,
                    question=q.question,
                    subquestion=query["missing_fact"],
                    search_query=query["query"],
                    dependency_id=query["dependency_id"],
                )
                for p in solver.corpus.retrieve(
                    query["query"], hybrid=config.retrieval != "lexical"
                )
            ]
            passages.extend(corpus_passages)
            corpus_ids.update(p.id for p in corpus_passages)
        try:
            results = await solver.web.search(q.id, query["query"], q.question)
        except CallLimitExceeded as e:
            searches.append({**query, "status": "limit", "kind": e.kind})
            continue
        except ProviderError:
            searches.append({**query, "status": "unavailable"})
            solver.store.event(q.id, "search_unavailable", {"query": query["query"]})
            continue
        except BudgetExceeded:
            searches.append({**query, "status": "budget_limited"})
            budget_limited = True
            break
        searches.append(
            {**query, "status": "results" if results else "empty", "result_count": len(results)}
        )
        quota = math.ceil(fetch_slots / max(1, len(queries) - query_no))
        query_attempts, seen = 0, set()
        for result in rank_leads(results, query["missing_fact"]):
            url = result["url"]
            if url in seen:
                continue
            seen.add(url)
            lead = {
                "url": url,
                "title": result.get("title", "")[:300],
                "snippet": result.get("snippet", "")[:1000],
                "dependency_id": query["dependency_id"],
                "status": "not_fetched",
            }
            leads.append(lead)
            if url not in pages and query_attempts >= quota:
                continue
            try:
                if url not in pages:
                    attempts += 1
                    query_attempts += 1
                    fetch_slots -= 1
                    pages[url] = await solver.web.fetch(q.id, url)
                    fetches.append(
                        {"url": url, "status": "fetched" if pages[url] else "blocked_or_empty"}
                    )
                page = pages[url]
            except CallLimitExceeded as e:
                pages[url] = None
                lead["status"] = "limit"
                fetches.append({"url": url, "status": "limit", "kind": e.kind})
                continue
            except ProviderError:
                pages[url] = None
                lead["status"] = "unavailable"
                fetches.append({"url": url, "status": "unavailable"})
                solver.store.event(q.id, "source_unavailable", {"url": url})
                continue
            except BudgetExceeded:
                lead["status"] = "budget_limited"
                fetches.append({"url": url, "status": "budget_limited"})
                budget_limited = True
                continue
            lead["status"] = "fetched" if page else "blocked_or_empty"
            if page:
                passages.extend(
                    chunk_page(
                        page,
                        query["missing_fact"],
                        question=q.question,
                        search_query=query["query"],
                        dependency_id=query["dependency_id"],
                    )
                )

    shortlist = retrieval_shortlist(passages, config.relevance.shortlist)
    if config.arm in {"J2", "J23", "Jfull", "M"} or config.retrieval == "hybrid-jev":
        try:
            ranked = await rerank(solver.jev, q.id, shortlist, config.relevance)
        except BudgetExceeded:
            # Preserve fetched material for review; absence of J2 is explicit.
            ranked = [
                replace(p, relevance_status="unavailable")
                for p in lexical_rank(shortlist)
                if p.score > 0
            ]
            budget_limited = True
    else:
        ranked = [
            replace(p, relevance_status="not_applicable")
            for p in lexical_rank(shortlist)
            if p.score > 0
        ]
    packet = diverse_packet(
        ranked,
        config.evidence_chars,
        config.relevance.packet,
        alternative_slots=config.relevance.alternative_slots,
    )
    outcome = {
        "round": round_no,
        "status": "budget_limited" if budget_limited else "evidence" if packet else "no_evidence",
        "search_attempts": len(searches),
        "fetch_attempts": attempts,
        "reserved_followup_fetches": reserve,
        "searches": searches,
        "leads": leads[:20],
        "fetches": fetches,
        "passage_count": len(passages),
        "shortlisted_ids": [p.id for p in shortlist],
        "packet_ids": [p.id for p in packet],
        "excluded_ids": [p.id for p in shortlist if p.id not in {p.id for p in packet}],
    }
    solver.store.event(q.id, "research_outcome", outcome)
    solver.store.event(
        q.id,
        "retrieval_summary",
        {
            "queries": [x["query"] for x in queries],
            "available_pages": sum(p is not None for p in pages.values()),
            "passage_count": len(passages),
            "packet": [
                {"id": p.id, "score": p.score, "relevance_status": p.relevance_status}
                for p in packet
            ],
        },
    )
    solver.store.cache(
        q.id,
        key,
        {
            "packet": [record(p) for p in packet],
            "outcome": outcome,
            "source_requests": [url for url, page in pages.items() if page],
            "corpus_ids": sorted(corpus_ids),
        },
    )
    return packet, outcome
