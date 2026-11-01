"""Bounded asynchronous state machine, independent initial samples and private checkpoints."""

from __future__ import annotations

import asyncio
import fcntl
import json
import math
import os
import time
from datetime import datetime, timezone
from dataclasses import asdict
from enum import Enum
from pathlib import Path

from ..benchmarks.data import load_questions, load_split
from ..candidates.selection import select
from ..config import Config, verify_protocol
from ..judgments.pipeline import (
    constraints,
    continuation,
    failures,
    missing_source_claims,
    rerank,
    route,
    verify,
)
from ..models import Candidate, Prediction, QuestionView, digest, record
from ..providers.backbone import Gateway, ProviderError
from ..providers.jev import Jev
from ..retrieval.corpus import Corpus
from ..retrieval.evidence import chunk_page, diverse_packet, lexical_rank, retrieval_shortlist
from ..tools.policy import Policy
from ..tools.sandbox import Sandbox
from ..tools.web import AuditedWeb
from ..tracing.store import Store, atomic_json, private_dir
from .budget import Budget, BudgetExceeded, CallLimitExceeded


class Phase(str, Enum):
    INITIAL = "initial"
    ROUTE = "route"
    RESEARCH = "research"
    CODE = "code"
    REVISE = "revise"
    VERIFY = "verify"
    SELECT = "select"
    FINAL = "final"


TRANSITIONS = {
    None: {Phase.INITIAL},
    Phase.INITIAL: {Phase.INITIAL, Phase.ROUTE, Phase.RESEARCH, Phase.CODE, Phase.SELECT},
    Phase.ROUTE: {Phase.RESEARCH, Phase.CODE, Phase.SELECT},
    Phase.RESEARCH: {Phase.CODE, Phase.REVISE},
    Phase.CODE: {Phase.REVISE},
    Phase.REVISE: {Phase.VERIFY},
    Phase.VERIFY: {Phase.REVISE, Phase.ROUTE, Phase.RESEARCH, Phase.CODE, Phase.SELECT},
    Phase.SELECT: {Phase.FINAL},
}


class Solver:
    def __init__(self, config: Config, store: Store, run_hash: str):
        self.config, self.store, self.run_hash = config, store, run_hash
        self.budget = Budget(store, config)
        self.gateway = Gateway(config, store, self.budget)
        self.jev = Jev(config, store, self.budget)
        self.policy = Policy(Path("protocol/upstream/blocklist.json"))
        self.web = AuditedWeb(config, store, self.budget, self.policy)
        self.sandbox = Sandbox(config, store, self.budget)
        self.corpus = Corpus(Path(config.corpus), self.policy) if config.corpus else None
        self.phases = {}
        self.starts = {}

    def transition(self, item: str, phase: Phase, **state):
        old = self.phases.get(item)
        if phase not in TRANSITIONS.get(old, set()):
            raise RuntimeError(f"illegal state transition {old} -> {phase}")
        self.phases[item] = phase
        snapshot = {
            "phase": phase.value,
            "started_at": self.starts[item],
            "budget": self.budget.snapshot(item),
            **state,
        }
        self.store.checkpoint(item, snapshot)
        self.store.event(item, "phase", snapshot)

    async def initial(self, q: QuestionView) -> list[Candidate]:
        count = self.config.limits.candidates if self.config.arm in {"B1", "M", "Jfull"} else 1
        providers = (self.config.provider, *self.config.additional_providers)
        candidates = []
        for i in range(count):
            self.transition(q.id, Phase.INITIAL, sample=i)
            # Each sample sees only the question and its own sample instruction.
            response = await self.gateway.generate(
                q,
                {"task": "independent initial solution", "sample": i},
                f"initial-{i}",
                provider=providers[i % len(providers)],
                final=self.config.arm in {"B0", "B1"},
            )
            candidates.append(Candidate.parse(response, f"initial-{i}"))
        return candidates

    async def research(self, q: QuestionView, candidate: Candidate):
        passages, pages = [], {}
        queries = list(candidate.queries[:3]) or list(candidate.gaps[:1])
        # Logical quotas replay identically after interruption, even at the global
        # tool cap. Leave fetch capacity for the other planned queries.
        planned = min(len(queries), max(1, self.config.limits.search))
        fetch_slots = self.config.limits.fetch
        reached = set()

        def tool_limit(error):
            if error.kind not in {"search", "fetch"}:
                raise error
            if error.kind not in reached:
                self.store.event(q.id, "research_limit", {"kind": error.kind})
                reached.add(error.kind)

        try:
            for query_no, query in enumerate(queries):
                if self.corpus:
                    passages.extend(
                        self.corpus.retrieve(query, hybrid=self.config.retrieval != "lexical")
                    )
                try:
                    results = await self.web.search(q.id, query, q.question)
                except CallLimitExceeded as e:
                    tool_limit(e)
                    # A later query may have a cached response even when an
                    # earlier failed request has no cache entry on resume.
                    continue
                except ProviderError:
                    self.store.event(q.id, "search_unavailable", {"query": query})
                    continue
                fetch_quota = math.ceil(fetch_slots / max(1, planned - query_no))
                attempts = successes = 0
                seen_results = set()
                for result in results:
                    url = result["url"]
                    if url in seen_results:
                        continue
                    seen_results.add(url)
                    if url not in pages and attempts >= fetch_quota:
                        break
                    try:
                        if url not in pages:
                            attempts += 1
                            fetch_slots -= 1
                            pages[url] = await self.web.fetch(q.id, url)
                        page = pages[url]
                    except CallLimitExceeded as e:
                        tool_limit(e)
                        pages[url] = None
                        # Keep looking for cached successes after uncached
                        # failures. The supervisor prevents new dispatches.
                        continue
                    except ProviderError:
                        pages[url] = None
                        self.store.event(q.id, "source_unavailable", {"url": url})
                        continue
                    if page:
                        chunks = chunk_page(page, query)
                        passages.extend(chunks)
                        successes += bool(chunks)
                    if successes >= 3:
                        break
        except CallLimitExceeded as e:
            # Cache replays above remain available even at the tool cap. Keep
            # their evidence and use the remaining budget to revise and finalize.
            tool_limit(e)
        shortlist = retrieval_shortlist(passages)
        if self.config.arm in {"J2", "J23", "Jfull", "M"} or self.config.retrieval == "hybrid-jev":
            shortlist = await rerank(self.jev, q.id, shortlist)
        else:
            shortlist = [p for p in lexical_rank(shortlist) if p.score > 0]
        packet = diverse_packet(shortlist, self.config.evidence_chars)
        self.store.event(
            q.id,
            "retrieval_summary",
            {
                "queries": queries,
                "available_pages": sum(p is not None for p in pages.values()),
                "passage_count": len(passages),
                "packet": [{"id": p.id, "score": p.score} for p in packet],
            },
        )
        return packet

    async def assess(self, q: QuestionView, candidate: Candidate, evidence: list) -> dict:
        semantic = self.config.arm in {"J3", "J23", "Jfull", "M"}
        checks = await verify(self.jev, q.id, candidate, evidence, semantic)
        self.store.event(q.id, "citation_checks", checks)
        constraint_failures = (
            await constraints(self.jev, q.id, q.question, candidate)
            if self.config.adaptive and candidate.answer.strip()
            else []
        )
        assessment = {
            "citation_checks": checks,
            "citation_failures": failures(checks),
            "missing_source_claims": missing_source_claims(candidate),
            "constraint_failures": constraint_failures,
        }
        assessment["accepted"] = bool(candidate.answer.strip()) and not any(
            assessment[k]
            for k in ("citation_failures", "missing_source_claims", "constraint_failures")
        )
        self.store.event(q.id, "candidate_checks", {"candidate_id": candidate.id, **assessment})
        if candidate.answer.strip() and not assessment["accepted"]:
            self.store.event(
                q.id,
                "candidate_rejected",
                {
                    "candidate_id": candidate.id,
                    "reason": "unresolved critical evidence or answer constraints",
                    **assessment,
                },
            )
        return assessment

    async def solve(self, q: QuestionView) -> Prediction:
        previous = self.store.db.execute("SELECT state FROM items WHERE id=?", (q.id,)).fetchone()
        started = json.loads(previous[0])["started_at"] if previous and previous[0] else time.time()
        self.starts[q.id] = started
        candidates, selected, status, error = [], None, "completed", ""
        assessments, evidence_ledger, artifacts = {}, {}, []
        evidence = []
        try:
            remaining = self.config.limits.deadline_s - (time.time() - started)
            if remaining <= 0:
                raise TimeoutError("item deadline")
            async with asyncio.timeout(remaining):
                candidates = await self.initial(q)
                initial_candidates = candidates[:]
                if self.config.arm not in {"B0", "B1"}:
                    current = candidates[0]
                    for round_no in range(self.config.limits.rounds):
                        if not (current.queries or current.gaps or current.code):
                            break
                        action = "search"
                        if self.config.adaptive:
                            self.transition(q.id, Phase.ROUTE)
                            actions = []
                            counts = self.budget.snapshot(q.id)["counts"]
                            if (
                                (current.queries or current.gaps)
                                and counts.get("search", 0) < self.config.limits.search
                                and counts.get("fetch", 0) < self.config.limits.fetch
                            ):
                                actions.append("search")
                            if current.code and counts.get("code", 0) < self.config.limits.code:
                                actions.append("code")
                            actions.append("finalize")
                            action = (
                                await route(self.jev, q.id, q.question, current, actions)
                                if len(actions) > 1
                                else "finalize"
                            )
                            if action == "finalize":
                                break
                        if action == "search":
                            self.transition(q.id, Phase.RESEARCH, round=round_no)
                            findings = await self.research(q, current)
                            evidence_ledger.update((p.id, p) for p in findings)
                            # New findings get context first; earlier citations
                            # remain verifiable in the ledger even when a bounded
                            # packet cannot include their full passages again.
                            cited = {c.passage_id for c in current.citations}
                            evidence = diverse_packet(
                                findings
                                + [p for p in evidence_ledger.values() if p.id in cited]
                                + evidence,
                                self.config.evidence_chars,
                            )
                        round_artifacts = []
                        if current.code:
                            self.transition(q.id, Phase.CODE)
                            round_artifacts.append(await self.sandbox.execute(q.id, current.code))
                            artifacts.extend(round_artifacts)
                        elif action == "code":
                            self.transition(q.id, Phase.CODE)
                        context = {
                            "task": "Compare the previous answer with the findings and check artifacts. Retain a sound answer when findings add no useful evidence; correct it when warranted. Declare and cite only critical facts used from the supplied passages.",
                            "previous": record(current),
                            "evidence": [record(p) for p in evidence],
                            "tool_artifacts": round_artifacts,
                        }
                        self.transition(q.id, Phase.REVISE)
                        response = await self.gateway.generate(
                            q, context, f"revise-{round_no}", final=True
                        )
                        revised = Candidate.parse(response, f"revised-{round_no}")
                        candidates.append(revised)
                        self.transition(q.id, Phase.VERIFY)
                        assessment = await self.assess(q, revised, list(evidence_ledger.values()))
                        assessments[revised.id] = assessment
                        if revised.answer.strip() and not assessment["accepted"]:
                            self.transition(q.id, Phase.REVISE)
                            repair_context = {
                                **context,
                                "previous": record(revised),
                                "citation_failures": assessment["citation_failures"],
                                "constraint_failures": assessment["constraint_failures"],
                                "missing_source_claims": assessment["missing_source_claims"],
                                "task": "Repair the listed evidence or constraint failures. Cite each declared source claim with matching claim text and an exact quote. You may instead solve independently, explaining the independent verification. Do not invent support; leave the answer empty if it cannot be established.",
                            }
                            response = await self.gateway.generate(
                                q, repair_context, f"repair-{round_no}", final=True
                            )
                            revised = Candidate.parse(response, f"repair-{round_no}")
                            candidates.append(revised)
                            self.transition(q.id, Phase.VERIFY)
                            assessment = await self.assess(
                                q, revised, list(evidence_ledger.values())
                            )
                            assessments[revised.id] = assessment
                        # Invalid drafts remain in the private oracle history but
                        # never become a selectable answer or a trusted premise.
                        if revised.answer.strip() and not assessment["accepted"]:
                            revised = Candidate(
                                f"unresolved-{round_no}",
                                "",
                                0,
                                "The latest draft failed evidence or answer checks.",
                                gaps=revised.gaps,
                                queries=revised.queries,
                                code=revised.code,
                            )
                        current = revised
                        if self.config.adaptive:
                            counts = self.budget.snapshot(q.id)["counts"]
                            envelope = {
                                "item_usd": max(
                                    0, self.config.limits.item_usd - self.store.cost(q.id)
                                ),
                                "run_usd": max(0, self.config.limits.run_usd - self.store.cost()),
                                "time_s": max(
                                    0, self.config.limits.deadline_s - (time.time() - started)
                                ),
                                "rounds": self.config.limits.rounds - round_no - 1,
                                "search_calls": max(
                                    0, self.config.limits.search - counts.get("search", 0)
                                ),
                                "fetch_calls": max(
                                    0, self.config.limits.fetch - counts.get("fetch", 0)
                                ),
                            }
                            actions = (
                                ["search", "finalize"]
                                if envelope["rounds"]
                                and envelope["search_calls"]
                                and envelope["fetch_calls"]
                                else ["finalize"]
                            )
                            decision = (
                                await continuation(self.jev, q.id, current, envelope, actions)
                                if len(actions) > 1
                                else "finalize"
                            )
                            if decision == "finalize":
                                break
                    # Validate earlier candidates too. Checking an old citation
                    # against today's packet would wrongly lose its provenance;
                    # the item-scoped ledger retains every exposed passage.
                    for candidate in initial_candidates:
                        assessments[candidate.id] = await self.assess(
                            q, candidate, list(evidence_ledger.values())
                        )
                    pool = [c for c in reversed(candidates) if assessments[c.id]["accepted"]]
                else:
                    pool = candidates
                self.transition(q.id, Phase.SELECT)
                selector = self.config.selector
                if selector == "auto":
                    selector = (
                        "vote"
                        if self.config.arm in {"B0", "B1"}
                        or len(candidates) == len(initial_candidates)
                        else "backbone"
                    )
                if selector == "vote" and self.config.arm not in {"B0", "B1"}:
                    # Revisions are correlated, not independent votes. The
                    # deterministic ablation uses the latest validated draft.
                    pool = pool[:1] + [
                        c for c in pool[1:] if c.id in {i.id for i in initial_candidates[1:]}
                    ]
                selected = await select(
                    self.jev,
                    self.gateway,
                    q,
                    pool,
                    selector,
                    self.config.seed,
                    evidence=evidence,
                    evidence_ledger=list(evidence_ledger.values()),
                    tool_artifacts=artifacts,
                    assessments=assessments,
                    latest_verification=current.verification
                    if self.config.arm not in {"B0", "B1"}
                    else "",
                )
                self.store.event(
                    q.id,
                    "candidate_selection",
                    {
                        "policy": selector,
                        "eligible": [c.id for c in pool],
                        "selected": selected.id if selected else None,
                    },
                )
                self.transition(q.id, Phase.FINAL)
        except BudgetExceeded:
            status, error = "budget_exceeded", "budget limit reached"
        except TimeoutError:
            status, error = "timeout", "item deadline reached"
        except asyncio.CancelledError:
            self.store.event(q.id, "interrupted", {"resumable": True})
            raise
        except Exception as e:
            status, error = "error", type(e).__name__
            self.store.event(q.id, "item_error", {"error_type": error})
        answer = selected.answer if selected and status == "completed" else ""
        return Prediction(
            q.id,
            self.config.arm,
            answer,
            selected.confidence if selected and answer else 0,
            status,
            self.run_hash,
            self.config.hash,
            self.store.cost(q.id),
            time.time() - started,
            tuple(c.answer for c in candidates),
            error,
            abstained=not bool(answer),
            verification=selected.verification if selected else "",
        )

    async def close(self):
        await self.gateway.close()
        await self.jev.close()


def implementation_hash() -> str:
    root = Path(__file__).resolve().parents[1]
    return digest({str(p.relative_to(root)): p.read_text() for p in sorted(root.rglob("*.py"))})


async def run(
    config: Config,
    question_file: Path,
    output: Path,
    resume: bool = False,
    split: str = "full",
    progress=None,
    question_ids: tuple[str, ...] = (),
) -> dict:
    config.validate()
    protocol = verify_protocol(config.protocol_manifest)
    questions = load_questions(question_file)
    full_hash = digest([record(q) for q in questions])
    manifest_path = question_file.parent / "manifest.json"
    data_manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    if config.live and data_manifest is None:
        raise ValueError("live runs require authenticated preparation manifest")
    if data_manifest:
        if (
            data_manifest["solver_hash"] != full_hash
            or data_manifest["dataset"] != config.dataset
            or data_manifest["revision"] != config.dataset_revision
        ):
            raise ValueError("dataset/config identity or content hash mismatch")
    if split not in {"full", "development", "heldout"}:
        raise ValueError("unknown internal split")
    memberships = None
    if data_manifest:
        memberships = load_split(
            question_file.parent / "split.json", questions, data_manifest.get("split_hash")
        )
    if split != "full":
        if memberships is None:
            raise ValueError("internal splits require a preparation manifest")
        ids = set(memberships[split])
        questions = [q for q in questions if q.id in ids]
    if not questions:
        raise ValueError("empty declared evaluation set")
    if question_ids:
        selected_ids = set(question_ids)
        if len(selected_ids) != len(question_ids):
            raise ValueError("duplicate selected question identifiers")
        if not selected_ids <= {q.id for q in questions}:
            raise ValueError("selected question identifiers must belong to the declared split")
        questions = [q for q in questions if q.id in selected_ids]
    manifest = {
        "config": asdict(config),
        "config_hash": config.hash,
        "question_hash": digest([record(q) for q in questions]),
        "declared_ids": [q.id for q in questions],
        "count": len(questions),
        "split": split,
        "dataset_manifest": data_manifest,
        "protocol_hash": digest(protocol),
        "implementation_hash": implementation_hash(),
        "lock_hash": digest(Path("uv.lock").read_text()),
        "corpus_hash": digest(Path(config.corpus).read_text()) if config.corpus else None,
        "synthetic": not config.live,
    }
    run_hash = digest(manifest)
    private_dir(output)
    fd = os.open(output / "run.lock", os.O_CREAT | os.O_RDWR, 0o600)
    store, solver = None, None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("another process owns this run") from None
        if (output / "events.sqlite3").exists() and not resume:
            raise ValueError("run exists; use resume")
        store = Store(output / "events.sqlite3")
        store.meta("run_hash", run_hash)
        store.meta("manifest", manifest)
        created_at = store.meta("created_at") or store.meta(
            "created_at", datetime.now(timezone.utc).isoformat()
        )
        atomic_json(
            output / "manifest.json", {**manifest, "run_hash": run_hash, "created_at": created_at}
        )
        solver = Solver(config, store, run_hash)
        semaphore = asyncio.Semaphore(config.limits.concurrency)

        async def one(q):
            async with semaphore:
                if store.prediction(q.id) is None:
                    prediction = await solver.solve(q)
                    store.finalize(q.id, record(prediction))
                    atomic_json(output / "predictions.json", store.predictions())
                    if progress:
                        progress(
                            {
                                "completed": len(store.predictions()),
                                "total": len(questions),
                                "status": prediction.status,
                            }
                        )

        tasks = [asyncio.create_task(one(q)) for q in questions]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        atomic_json(output / "predictions.json", store.predictions())
        atomic_json(output / "usage.json", store.usage_summary())
        store.meta("finalized", True)
        return {
            "run_hash": run_hash,
            "count": len(questions),
            "cost_usd": store.cost(),
            "synthetic": not config.live,
        }
    finally:
        if solver:
            await solver.close()
        if store:
            store.close()
        os.close(fd)
