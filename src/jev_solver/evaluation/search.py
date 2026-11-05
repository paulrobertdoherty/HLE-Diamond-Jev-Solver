"""Identical-query provider comparison. Replay is the default; no generative model is used."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from ..benchmarks.data import read_jsonl
from ..controller.budget import Budget, BudgetExceeded
from ..models import digest
from ..providers.backbone import ProviderError
from ..retrieval.evidence import rank_leads
from ..tools.policy import Blocked, Policy
from ..tools.web import AuditedWeb
from ..tracing.store import Store, atomic_json


def query_inputs(rows):
    required = ("id", "question", "missing_fact", "query")
    if not rows or any(
        any(not isinstance(row.get(k), str) or not row[k].strip() for k in required) for row in rows
    ):
        raise ValueError("fixed queries require id, question, missing_fact and query")
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("duplicate fixed query ID")
    return [{k: row[k] for k in required} for row in rows]


def allowed_results(policy, rows):
    allowed, audit = [], []
    for rank, row in enumerate(rows, 1):
        reason = ""
        try:
            policy.result(row)
        except Blocked as error:
            reason = error.rule
        audit.append({**row, "provider_rank": rank, "allowed": not reason, "block_reason": reason})
        if not reason:
            allowed.append(row)
    return allowed, audit


def retrieval_metrics(labels, results, fetches, ranks):
    if labels.get("status") != "adjudicated":
        return {
            "status": "unavailable",
            "useful_lead_recall": {str(k): None for k in ranks},
            "useful_page_recall": None,
            "extracted_fact_recall": None,
        }
    values = labels.get("values", {})
    useful = values.get("useful_urls")
    facts = values.get("needed_text")
    if useful is not None and (
        not isinstance(useful, list) or any(not isinstance(url, str) for url in useful)
    ):
        raise ValueError("useful_urls must be independently labeled URLs")
    if facts is not None and (
        not isinstance(facts, list) or any(not isinstance(t, str) or not t for t in facts)
    ):
        raise ValueError("needed_text must be independently labeled exact source text")
    useful = set(useful) if useful is not None else None
    complete = all(f["status"] != "unavailable_snapshot" for f in fetches)
    successful = {
        f["requested_url"]
        for f in fetches
        if f["status"] == "fetched" and f["page"]["text"].strip()
    }

    def ratio(n, d):
        return n / d if d else None

    return {
        "status": "available" if complete else "partial",
        "fetch_observations_complete": complete,
        "useful_urls": len(useful) if useful is not None else None,
        "needed_facts": len(facts) if facts is not None else None,
        "useful_lead_recall": {
            str(k): ratio(len(useful & {r["url"] for r in results[:k]}), len(useful))
            if useful is not None
            else None
            for k in ranks
        },
        "useful_page_recall": ratio(len(useful & successful), len(useful))
        if useful is not None and complete
        else None,
        "extracted_fact_recall": ratio(
            sum(
                any(text in f["page"]["text"] for f in fetches if f["status"] == "fetched")
                for text in facts
            ),
            len(facts),
        )
        if facts is not None and complete
        else None,
    }


async def search_comparison(
    config,
    queries: Path,
    output: Path,
    *,
    snapshot: Path | None = None,
    live=False,
    result_limit=20,
    fetch_budget=4,
    ranks=(1, 3, 5, 10),
    web_factory=AuditedWeb,
):
    rows = read_jsonl(queries)
    if rows and rows[0].get("version") == 1:
        from .labels import load_cases, provider_input

        by_id = {}
        for row in load_cases(queries):
            if row["component"] != "search":
                continue
            query = {**provider_input(row), "label": row["label"]}
            previous = by_id.get(query["id"])
            if previous:
                if query_inputs([previous]) != query_inputs([query]) or (
                    previous["label"]["status"] == query["label"]["status"] == "adjudicated"
                    and previous["label"]["values"] != query["label"]["values"]
                ):
                    raise ValueError("conflicting frozen query identity or labels")
                if query["label"]["status"] != "adjudicated":
                    continue
            by_id[query["id"]] = query
        rows = list(by_id.values())
    inputs = query_inputs(rows)
    if bool(snapshot) == bool(live):
        raise ValueError("choose a frozen snapshot or explicit live search")
    if live and config.search_usd <= 0:
        raise ValueError("live search requires a positive frozen search_usd price")
    if (
        not 1 <= result_limit <= 20
        or not 0 <= fetch_budget <= config.limits.fetch
        or any(type(k) is not int or k <= 0 for k in ranks)
    ):
        raise ValueError("invalid result, fetch or recall budget")
    policy = Policy(Path("protocol/upstream/blocklist.json"))
    identity = {
        "version": 1,
        "input_hash": digest(inputs),
        "policy_version": policy.version,
        "parser_version": config.parser_version,
        "result_limit": result_limit,
        "fetch_budget": fetch_budget,
    }
    frozen = json.loads(snapshot.read_text()) if snapshot else {**identity, "providers": {}}
    if any(frozen.get(k) != v for k, v in identity.items()):
        raise ValueError("search snapshot input/policy/budget contract differs")
    observations, usage = [], {}
    for backend in ("brave", "perplexity"):
        backend_data = (
            frozen["providers"].setdefault(backend, {})
            if live
            else frozen["providers"].get(backend, {})
        )
        store = Store(output / f"{backend}.sqlite3")
        cfg = replace(config, search_backend=backend)
        web = web_factory(cfg, store, Budget(store, cfg), policy) if live else None
        try:
            store.meta(
                "identity",
                {
                    **identity,
                    "backend": backend,
                    "config_hash": cfg.hash,
                    "live": live,
                    "snapshot_hash": digest(frozen) if not live else None,
                },
            )
            for row, query in zip(rows, inputs, strict=True):
                contract_hash = digest(query)
                if live:
                    try:
                        await web.search(query["id"], query["query"], query["question"])
                        # Raw provider responses are saved privately before the allowed-result filter.
                        key = digest(
                            {
                                "tool": "web_search",
                                "query": query["query"],
                                "question": digest(query["question"]),
                                "filter": policy.version,
                                "config": cfg.hash,
                            }
                        )
                        cached = store.cached(query["id"], key)
                        saved = {
                            "input_hash": contract_hash,
                            "results": cached["results"][:result_limit] if cached else [],
                            "pages": {},
                        }
                    except (ProviderError, BudgetExceeded) as error:
                        saved = {
                            "input_hash": contract_hash,
                            "results": [],
                            "pages": {},
                            "error": type(error).__name__,
                        }
                    backend_data[query["id"]] = saved
                else:
                    saved = backend_data.get(query["id"])
                    if not saved or saved.get("input_hash") != contract_hash:
                        raise ValueError("missing or changed fixed query snapshot")
                try:
                    policy.query(query["query"], query["question"])
                    allowed, raw = allowed_results(policy, saved["results"][:result_limit])
                except Blocked as error:
                    allowed, raw = [], []
                    saved["query_block"] = error.rule
                for order in ("provider", "local"):
                    ranked = (
                        rank_leads(allowed, query["missing_fact"]) if order == "local" else allowed
                    )
                    by_url = {}
                    for lead in ranked:
                        by_url.setdefault(lead["url"], lead)
                    unique = list(by_url.values())
                    fetches = []
                    for lead in unique[:fetch_budget]:
                        url = lead["url"]
                        if url not in saved["pages"] and live:
                            try:
                                page = await web.fetch(query["id"], url)
                                saved["pages"][url] = {
                                    "status": "fetched" if page else "blocked_or_empty",
                                    "page": page,
                                }
                            except (ProviderError, BudgetExceeded) as error:
                                saved["pages"][url] = {"status": type(error).__name__, "page": None}
                        fetched = saved["pages"].get(
                            url, {"status": "unavailable_snapshot", "page": None}
                        )
                        # Revalidate frozen full pages, redirects and destination before exposure.
                        if fetched["page"]:
                            try:
                                policy.page(fetched["page"])
                            except Blocked as error:
                                fetched = {"status": "blocked", "rule": error.rule, "page": None}
                        fetches.append({"requested_url": url, **fetched})
                    observations.append(
                        {
                            "id": query["id"],
                            "backend": backend,
                            "order": order,
                            "input_hash": contract_hash,
                            "raw_results": raw,
                            "ranked_urls": [r["url"] for r in unique],
                            "fetches": fetches,
                            "error": saved.get("error"),
                            "metrics": retrieval_metrics(
                                row.get("label", {}), unique, fetches, ranks
                            ),
                        }
                    )
            usage[backend] = store.usage_summary()
        finally:
            store.close()
    atomic_json(output / "search-snapshot.json", frozen)
    artifact = {
        "identity": identity,
        "mode": "live" if live else "replay",
        "observations": observations,
        "usage": usage,
        "generative_model_calls": 0,
        "development_only": True,
    }
    atomic_json(output / "search-comparison.json", artifact)
    return {
        "mode": artifact["mode"],
        "conditions": len(observations),
        "unlabeled_conditions": sum(r["metrics"]["status"] == "unavailable" for r in observations),
        "usage": usage,
        "generative_model_calls": 0,
    }
