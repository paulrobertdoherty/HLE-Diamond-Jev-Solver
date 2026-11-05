"""Read-only diagnostics on saved sources. These never produce new semantic outcomes."""

import hashlib
import json
import sqlite3
from pathlib import Path

from ..benchmarks.data import load_questions
from ..config import Config, RelevancePolicy
from ..judgments.citations import parse_candidate
from ..judgments.pipeline import exact_citation, filter_relevance
from ..models import Candidate, EvidencePassage
from ..providers.backbone import CANDIDATE_SCHEMA, input_envelope
from ..providers.context import build_context
from ..retrieval.evidence import chunk_page, diverse_packet, retrieval_shortlist
from ..retrieval.structure import structured_passages
from ..tools.policy import Policy
from ..tracing.store import atomic_json
from .offline import offline_dispatch_guard


def private_diagnostics(root, output):
    root, output = Path(root), Path(output)
    if output.exists():
        raise ValueError("diagnostic output already exists")
    private = root / "private"
    audit = json.loads((private / "v3-search-attribution-audit.json").read_text())
    index = {
        r["alias"]: r
        for r in json.loads((private / "v3-search-attribution-cases.json").read_text())["cases"]
    }
    questions = {
        q.id: q for q in load_questions(private / "sol-low-pilot-data/solver/questions.jsonl")
    }
    coordinates, envelopes, packets, shortlist_targets = [], [], [], []
    policy = Policy(root / "protocol/upstream/blocklist.json")
    with offline_dispatch_guard():
        for backend, run in audit["runs"].items():
            config = Config.load(root / f"configs/sol-low.evidence-v3.j23.{backend}.json")
            item = run["items"][index["art_citation_offsets"]["question_id"]]
            passages = {
                p["id"]: EvidencePassage(**p) for r in item["research"] for p in r["packet"]
            }
            for identifier, raw in item["candidates"].items():
                before = Candidate.parse(raw, identifier)
                after, traces = parse_candidate(
                    raw, identifier, list(passages.values()), resolve=True
                )
                coordinates.append(
                    {
                        "backend": backend,
                        "candidate_id": identifier,
                        "invalid_before": sum(
                            not c["valid_span"]
                            for c in exact_citation(before, list(passages.values()))
                        ),
                        "valid_after": sum(
                            c["valid_span"] for c in exact_citation(after, list(passages.values()))
                        ),
                        "recovered_spans": sum(t["reason"] == "unique_exact_quote" for t in traces),
                        "resolutions": traces,
                        "historical_coverage": item["final_checks"]
                        .get(identifier, {})
                        .get("coverage"),
                        "new_eligibility": None,
                        "new_correctness": None,
                    }
                )
            for capture in run["replay"]["requests"]:
                if capture["envelope"] <= capture["max_envelope"]:
                    continue
                q = questions[capture["item"]]

                def bound(context, q=q, provider=config.provider):
                    return input_envelope(q, context, CANDIDATE_SCHEMA, provider)

                assert bound(capture["context"]) == capture["envelope"]
                _, report = build_context(capture["context"], bound, capture["max_envelope"])
                envelopes.append(
                    {
                        "backend": backend,
                        "request_hash": capture["request_hash"],
                        **report,
                        "original_image_count": len(q.images),
                        "new_generation_attempted": False,
                    }
                )
            for qid, item in run["items"].items():
                for r in item["research"]:
                    ranked = filter_relevance(
                        [EvidencePassage(**x["passage"]) for x in r["judged"]],
                        RelevancePolicy(**run["manifest"]["config"]["relevance"]),
                    )
                    control = diverse_packet(ranked, config.evidence_chars, config.relevance.packet)
                    variant = diverse_packet(
                        ranked,
                        config.evidence_chars,
                        config.relevance.packet,
                        policy="remediation-v1",
                    )
                    packets.append(
                        {
                            "backend": backend,
                            "question_id": qid,
                            "round": r["outcome"]["round"],
                            "control_ids": [p.id for p in control],
                            "variant_ids": [p.id for p in variant],
                            "additional_unique_texts": len(
                                {p.text for p in variant} - {p.text for p in control}
                            ),
                            "judgments": "frozen control inputs; packet-policy diagnostic only",
                        }
                    )
        dossier = json.loads(
            (private / "v3-citation-failure-analysis-2026-11-05/evidence-dossier.json").read_text()
        )
        with (private / "v3-test-plan-implementation/cases/label-cases.jsonl").open() as handle:
            labels = {r["id"]: r for r in map(json.loads, handle)}
        for row in dossier:
            if not (
                row["component"] == "J2"
                and row["observation"].get("exclusion") == "shortlist"
                and row["astra"].get("review", {}).get("relevance") == "direct"
            ):
                continue
            alias, backend = row["id"].split("/")[:2]
            qid, state = index[alias]["question_id"], labels[row["id"]]["input"]
            round_snapshot = next(
                r
                for r in audit["runs"][backend]["items"][qid]["research"]
                if r["outcome"]["round"] == row["observation"]["round"]
            )
            fetched_urls = {
                f["url"] for f in round_snapshot["outcome"]["fetches"] if f["status"] == "fetched"
            }
            db = sqlite3.connect(
                f"file:{private}/sol-low-evidence-v3-j23-{backend}/events.sqlite3?mode=ro", uri=True
            )
            pages = []
            try:
                for (raw,) in db.execute("SELECT value FROM cache WHERE item=?", (qid,)):
                    page = json.loads(raw).get("page")
                    if page and (
                        page["url"] in fetched_urls
                        or any(u in fetched_urls for u in page.get("redirects", []))
                    ):
                        policy.page(page)
                        pages.append(
                            {
                                **page,
                                "source_hash": hashlib.sha256(page["text"].encode()).hexdigest(),
                                "text": page["text"][:60000],
                                "filter_version": policy.version,
                            }
                        )
            finally:
                db.close()
            candidates = []
            for query in round_snapshot["outcome"]["searches"]:
                query_urls = {
                    lead["url"]
                    for lead in round_snapshot["outcome"]["leads"]
                    if lead["dependency_id"] == query["dependency_id"]
                }
                for page in pages:
                    if page["url"] in query_urls:
                        candidates.extend(
                            chunk_page(
                                page, query["missing_fact"], dependency_id=query["dependency_id"]
                            )
                        )
                        candidates.extend(
                            structured_passages(
                                page, query["missing_fact"], dependency_id=query["dependency_id"]
                            )
                        )
            shortlist = retrieval_shortlist(candidates, 12, policy="remediation-v1")
            quotes = row["astra"]["review"].get("evidence_quotes", [])
            survival = [
                any(quote in p.text for p in shortlist if p.url == state["url"]) for quote in quotes
            ]
            locatable = [
                any(quote in page["text"] for page in pages if page["url"] == state["url"])
                for quote in quotes
            ]
            shortlist_targets.append(
                {
                    "record_id": row["id"],
                    "label_status": "provisional",
                    "quote_count": len(quotes),
                    "locatable_quote_count": sum(locatable),
                    "quotes_surviving": sum(survival),
                    "shortlisted_ids": [p.id for p in shortlist],
                    "status": "diagnostic" if any(locatable) else "unavailable_review_spans",
                    "new_J2_judgments": None,
                }
            )
    result = {
        "citation_coordinates": coordinates,
        "historical_rejected_envelopes": envelopes,
        "packet_diagnostics": packets,
        "stronger_reviewed_shortlist_diagnostics": shortlist_targets,
        "external_dispatches": 0,
        "new_semantic_judgments": 0,
        "new_benchmark_accuracy": None,
        "note": "Representation and deterministic policy diagnostics only. Fresh semantic comparisons and adjudication remain pending.",
    }
    atomic_json(output, result)
    return {
        "recovered_spans": sum(r["recovered_spans"] for r in coordinates),
        "historical_envelopes": len(envelopes),
        "compactable_envelopes": sum(r["coverage"] == "complete" for r in envelopes),
        "packet_sequences": len(packets),
        "stronger_reviewed_shortlist_cases": len(shortlist_targets),
        "external_dispatches": 0,
    }
