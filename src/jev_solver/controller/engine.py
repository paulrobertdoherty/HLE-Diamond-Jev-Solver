"""Bounded asynchronous state machine, independent initial samples and private checkpoints."""

from __future__ import annotations

import asyncio
import fcntl
import json
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
    route,
    verify,
)
from ..models import Candidate, Prediction, QuestionView, digest, record
from ..providers.backbone import Gateway
from ..providers.jev import Jev
from ..retrieval.corpus import Corpus
from ..retrieval.evidence import diverse_packet
from ..retrieval.outcomes import boundary_rows, planner_outcomes
from ..judgments.verification import audit_dependencies
from ..judgments.citations import parse_candidate
from ..tools.policy import Policy
from ..tools.sandbox import Sandbox
from ..tools.web import AuditedWeb
from ..tracing.store import Store, atomic_json, private_dir
from .budget import Budget, BudgetExceeded
from .research import research


class Phase(str, Enum):
    CONTRACT = "contract"
    INITIAL = "initial"
    PLAN = "plan"
    ROUTE = "route"
    RESEARCH = "research"
    CODE = "code"
    REVISE = "revise"
    VERIFY = "verify"
    SELECT = "select"
    FINAL = "final"


TRANSITIONS = {
    None: {Phase.CONTRACT, Phase.INITIAL},
    Phase.CONTRACT: {Phase.INITIAL},
    Phase.INITIAL: {Phase.INITIAL, Phase.PLAN, Phase.SELECT},
    Phase.PLAN: {Phase.ROUTE, Phase.RESEARCH, Phase.CODE, Phase.SELECT},
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
        self.plans = {}
        self.round_numbers = {}
        self.research_outcomes = {}
        self.contracts, self.graphs, self.parents = {}, {}, {}
        self.last_admitted = {}

    async def question_contract(self, q):
        if self.config.arm in {"B0", "B1"} or self.config.remediation.contract != "remediation-v1":
            return
        from ..judgments.graph import CONTRACT_SCHEMA, CONTRACT_TASK, parse_contract

        self.transition(q.id, Phase.CONTRACT)
        corrected = self.store.db.execute(
            "SELECT data FROM events WHERE item=? AND kind='contract_corrected' ORDER BY seq DESC LIMIT 1",
            (q.id,),
        ).fetchone()
        if corrected:
            saved = json.loads(corrected[0])["contract"]
            restored = parse_contract(
                {k: saved[k] for k in ("obligations", "alternatives")}, q, saved["version"]
            )
            if restored["hash"] != saved["hash"]:
                raise ValueError("persisted question contract identity differs")
            self.contracts[q.id] = restored
            self.store.event(
                q.id, "contract_replay", {"hash": restored["hash"], "version": restored["version"]}
            )
            return
        raw = await self.gateway.generate(
            q, {"task": CONTRACT_TASK}, "question-contract", schema=CONTRACT_SCHEMA
        )
        contract = parse_contract(raw, q)
        self.contracts[q.id] = contract
        self.store.event(q.id, "question_contract", contract)

    def correct_contract(self, q, raw, reason):
        from ..judgments.graph import parse_contract

        if not reason.strip() or q.id not in self.contracts:
            raise ValueError("contract correction requires an existing contract and reason")
        old = self.contracts[q.id]
        corrected = parse_contract(raw, q, version=old["version"] + 1)
        self.contracts[q.id] = corrected
        self.store.event(
            q.id,
            "contract_corrected",
            {
                "previous": old["hash"],
                "contract": corrected,
                "reason": reason,
                "invalidated_candidates": list(self.graphs.get(q.id, {})),
            },
        )
        return corrected

    def parse_candidate(self, q, raw, identifier, evidence=()):
        candidate, traces = parse_candidate(
            raw, identifier, evidence, resolve=self.config.remediation.citations == "remediation-v1"
        )
        if traces:
            self.store.event(
                q.id, "citation_resolution", {"candidate_id": identifier, "resolutions": traces}
            )
        if self.config.remediation.contract == "remediation-v1":
            history = self.graphs.setdefault(q.id, {})
            self.parents.setdefault(q.id, {}).setdefault(
                identifier, next(reversed(history), None) if history else None
            )
        return candidate

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
                {
                    "task": "independent initial solution",
                    "sample": i,
                    **(
                        {"question_contract": self.contracts[q.id]}
                        if q.id in self.contracts
                        else {}
                    ),
                },
                f"initial-{i}",
                provider=providers[i % len(providers)],
                final=self.config.arm in {"B0", "B1"},
            )
            candidates.append(self.parse_candidate(q, response, f"initial-{i}"))
        return candidates

    async def research(self, q: QuestionView, candidate: Candidate):
        packet, outcome = await research(
            self,
            q,
            self.plans.get(q.id, []),
            self.round_numbers.get(q.id, 0),
            self.research_outcomes.setdefault(q.id, []),
        )
        self.research_outcomes[q.id].append(outcome)
        return packet

    async def assess(
        self, q: QuestionView, candidate: Candidate, evidence: list, artifacts=(), outcomes=()
    ) -> dict:
        if self.config.remediation.packet == "remediation-v1":
            refs = {c.passage_id for c in candidate.citations} | {
                i for d in candidate.dependencies for i in d.passage_ids
            }
            evidence = list(
                {
                    p.id: p
                    for p in [*evidence, *[p for p in self.store.passages(q.id) if p.id in refs]]
                }.values()
            )
        key = digest(
            {
                "assessment_version": 3,
                "question": record(q),
                "candidate": record(candidate),
                "evidence": [record(p) for p in evidence],
                "artifacts": list(artifacts),
                "outcomes": list(outcomes),
                "config_hash": self.config.hash,
                "contract": self.contracts.get(q.id),
                "previous_graph": self.graphs.get(q.id, {}).get(
                    self.parents.get(q.id, {}).get(candidate.id), []
                ),
            }
        )
        cached = self.store.cached(q.id, key)
        if cached is not None:
            self.store.event(
                q.id, "assessment_replay", {"candidate_id": candidate.id, "request_hash": key}
            )
            self.graphs.setdefault(q.id, {})[candidate.id] = cached["dependencies"]
            return cached
        semantic = self.config.arm in {"J3", "J23", "Jfull", "M"}
        self.store.event(
            q.id, "evidence_boundaries", boundary_rows("audit_context", evidence, evidence)
        )
        checks = await verify(
            self.jev, q.id, candidate, evidence, semantic, gateway=self.gateway, question=q
        )
        self.store.event(q.id, "citation_checks", checks)
        audit = await audit_dependencies(
            self.gateway,
            self.jev,
            q,
            candidate,
            evidence,
            list(artifacts),
            list(outcomes),
            semantic=semantic,
            contract=self.contracts.get(q.id),
            previous_graph=self.graphs.get(q.id, {}).get(
                self.parents.get(q.id, {}).get(candidate.id), []
            ),
        )
        constraint_checks = (
            await constraints(self.jev, q.id, q.question, candidate, evidence, artifacts, audit)
            if self.config.adaptive and candidate.answer.strip()
            else {"constraints": {"status": "not_applicable"}}
        )
        if self.config.remediation.final == "remediation-v1":
            from ..judgments.answer import final_answer_check

            audit, checks = await final_answer_check(
                self.gateway,
                q,
                candidate,
                evidence,
                artifacts,
                audit,
                checks,
                constraint_checks,
                self.contracts.get(q.id),
            )
        assessment = {
            "citation_checks": checks,
            "citation_failures": failures(checks),
            "missing_source_claims": missing_source_claims(candidate),
            "constraint_checks": constraint_checks,
            "constraint_failures": [
                k
                for k, v in constraint_checks.items()
                if v["status"] in {"failed", "unavailable", "not_run"}
            ],
            **audit,
        }
        assessment["eligible"] = (
            bool(candidate.answer.strip())
            and audit["coverage"]["status"] == "passed"
            and not any(
                assessment[k]
                for k in ("citation_failures", "missing_source_claims", "constraint_failures")
            )
            and not any(
                c["citation"]["critical"] and c["status"] != "passed" for c in checks if semantic
            )
        )
        assessment["accepted"] = assessment[
            "eligible"
        ]  # Legacy trace field, separate from coverage.
        self.store.event(q.id, "candidate_checks", {"candidate_id": candidate.id, **assessment})
        if candidate.answer.strip() and not assessment["eligible"]:
            self.store.event(
                q.id,
                "candidate_rejected",
                {
                    "candidate_id": candidate.id,
                    "reason": "unresolved critical dependencies or answer checks",
                    **assessment,
                },
            )
        self.store.cache(q.id, key, assessment)
        self.graphs.setdefault(q.id, {})[candidate.id] = assessment["dependencies"]
        if self.config.remediation.contract == "remediation-v1":
            self.store.event(
                q.id,
                "dependency_graph",
                {
                    "candidate_id": candidate.id,
                    "parent": self.parents.get(q.id, {}).get(candidate.id),
                    "contract_hash": self.contracts[q.id]["hash"],
                    "dependencies": assessment["dependencies"],
                    "events": audit.get("graph_events", []),
                },
            )
        return assessment

    async def solve(self, q: QuestionView) -> Prediction:
        previous = self.store.db.execute("SELECT state FROM items WHERE id=?", (q.id,)).fetchone()
        started = json.loads(previous[0])["started_at"] if previous and previous[0] else time.time()
        self.starts[q.id] = started
        self.research_outcomes[q.id] = []
        candidates, selected, status, error = [], None, "completed", ""
        assessments, evidence_ledger, artifacts = {}, {}, []
        evidence = []
        try:
            remaining = self.config.limits.deadline_s - (time.time() - started)
            if remaining <= 0:
                raise TimeoutError("item deadline")
            async with asyncio.timeout(remaining):
                await self.question_contract(q)
                candidates = await self.initial(q)
                initial_candidates = candidates[:]
                current = candidates[0]
                if self.config.arm not in {"B0", "B1"}:
                    self.transition(q.id, Phase.PLAN)
                    assessments[current.id] = await self.assess(q, current, [])
                    for round_no in range(self.config.limits.rounds):
                        assessment = assessments[current.id]
                        self.plans[q.id] = assessment["queries"]
                        self.round_numbers[q.id] = round_no
                        pending_code = current.code and not any(
                            a.get("code_hash") == digest(current.code) for a in artifacts
                        )
                        if assessment["eligible"] and not (self.plans[q.id] or pending_code):
                            break
                        action = "search"
                        if self.config.adaptive:
                            self.transition(q.id, Phase.ROUTE)
                            counts = self.budget.snapshot(q.id)["counts"]
                            actions = []
                            if (
                                self.plans[q.id]
                                and counts.get("search", 0) < self.config.limits.search
                                and counts.get("fetch", 0) < self.config.limits.fetch
                            ):
                                actions.append("search")
                            if pending_code and counts.get("code", 0) < self.config.limits.code:
                                actions.append("code")
                            actions.append("finalize")
                            action = (
                                await route(
                                    self.jev,
                                    q.id,
                                    q.question,
                                    current,
                                    actions,
                                    dependency_checks=assessment,
                                )
                                if len(actions) > 1
                                else "finalize"
                            )
                            if action == "finalize":
                                break
                        if action == "search":
                            self.transition(q.id, Phase.RESEARCH, round=round_no)
                            findings = await self.research(q, current)
                            evidence_ledger.update((p.id, p) for p in findings)
                            if self.config.remediation.packet == "remediation-v1":
                                evidence_ledger.update(
                                    (p.id, p) for p in self.last_admitted.get(q.id, [])
                                )
                            cited = {c.passage_id for c in current.citations}
                            evidence = diverse_packet(
                                findings
                                + [p for p in evidence_ledger.values() if p.id in cited]
                                + evidence,
                                self.config.evidence_chars,
                                self.config.relevance.packet,
                                alternative_slots=self.config.relevance.alternative_slots,
                                policy=self.config.remediation.packet,
                                critical_dependencies=[
                                    d["id"]
                                    for d in assessment["dependencies"]
                                    if d["critical"] and d["status"] != "passed"
                                ],
                            )
                            self.store.event(
                                q.id,
                                "evidence_boundaries",
                                boundary_rows(
                                    "merged_revision_context",
                                    list(evidence_ledger.values()),
                                    evidence,
                                ),
                            )
                        if pending_code:
                            self.transition(q.id, Phase.CODE)
                            try:
                                artifacts.append(await self.sandbox.execute(q.id, current.code))
                            except BudgetExceeded:
                                self.store.event(
                                    q.id,
                                    "code_unavailable",
                                    {
                                        "status": "not_run",
                                        "code_hash": digest(current.code),
                                        "reason": "execution allowance or budget exhausted",
                                    },
                                )
                        elif action == "code":
                            self.transition(q.id, Phase.CODE)
                        context = {
                            "task": "Resolve the dependency checks against the original question and actual findings. Correct contradicted answers, including conclusions absent from earlier drafts. Explain the checkable basis of every critical dependency. Search failures and snippets do not establish or refute facts. Repaired code must be executed before relying on it.",
                            "previous": record(current),
                            "dependency_checks": assessment,
                            "evidence": [record(p) for p in evidence],
                            "tool_artifacts": artifacts,
                            "research_outcomes": planner_outcomes(self.research_outcomes[q.id]),
                            **(
                                {"question_contract": self.contracts[q.id]}
                                if q.id in self.contracts
                                else {}
                            ),
                        }
                        self.transition(q.id, Phase.REVISE)
                        response = await self.gateway.generate(
                            q, context, f"revise-{round_no}", final=True
                        )
                        revised = self.parse_candidate(
                            q, response, f"revised-{round_no}", list(evidence_ledger.values())
                        )
                        candidates.append(revised)
                        self.transition(q.id, Phase.VERIFY)
                        assessment = await self.assess(
                            q,
                            revised,
                            list(evidence_ledger.values()),
                            artifacts,
                            self.research_outcomes[q.id],
                        )
                        assessments[revised.id] = assessment
                        # Later rounds can search again or execute repaired code. At the last
                        # round allow one bounded prose/citation repair, still fully assessed.
                        if (
                            revised.answer.strip()
                            and not assessment["eligible"]
                            and round_no == self.config.limits.rounds - 1
                            and (
                                self.config.remediation.generation != "remediation-v1"
                                or self.store.allowance(q.id, "semantic_repair", revised.id)
                            )
                        ):
                            self.transition(q.id, Phase.REVISE)
                            repair_context = {
                                **context,
                                "previous": record(revised),
                                "dependency_checks": assessment,
                                "citation_failures": assessment["citation_failures"],
                                "constraint_failures": assessment["constraint_failures"],
                                "missing_source_claims": assessment["missing_source_claims"],
                                "task": "Repair the failed dependency, citation and answer checks using actual evidence/artifacts. Supply a corrected candidate before selection. A claim of independent reasoning is insufficient: supply its checkable basis. Newly generated code is unexecuted. Leave the answer empty if critical dependencies cannot be established.",
                            }
                            response = await self.gateway.generate(
                                q, repair_context, f"repair-{round_no}", final=True
                            )
                            revised = self.parse_candidate(
                                q, response, f"repair-{round_no}", list(evidence_ledger.values())
                            )
                            candidates.append(revised)
                            self.transition(q.id, Phase.VERIFY)
                            assessments[revised.id] = await self.assess(
                                q,
                                revised,
                                list(evidence_ledger.values()),
                                artifacts,
                                self.research_outcomes[q.id],
                            )
                        current = revised
                        if self.config.adaptive and round_no + 1 < self.config.limits.rounds:
                            counts = self.budget.snapshot(q.id)["counts"]
                            envelope = {
                                "rounds": self.config.limits.rounds - round_no - 1,
                                "search_calls": max(
                                    0, self.config.limits.search - counts.get("search", 0)
                                ),
                                "fetch_calls": max(
                                    0, self.config.limits.fetch - counts.get("fetch", 0)
                                ),
                                "code_calls": max(
                                    0, self.config.limits.code - counts.get("code", 0)
                                ),
                                "item_usd": max(
                                    0, self.config.limits.item_usd - self.store.cost(q.id)
                                ),
                                "time_s": max(
                                    0, self.config.limits.deadline_s - (time.time() - started)
                                ),
                            }
                            actions = ["finalize"]
                            if envelope["search_calls"] and envelope["fetch_calls"]:
                                actions.insert(0, "search")
                            if current.code and envelope["code_calls"]:
                                actions.insert(0, "code")
                            decision = (
                                await continuation(
                                    self.jev,
                                    q.id,
                                    current,
                                    envelope,
                                    actions,
                                    dependency_checks=assessments[current.id],
                                    research_outcomes=planner_outcomes(
                                        self.research_outcomes[q.id]
                                    ),
                                )
                                if len(actions) > 1
                                else "finalize"
                            )
                            if decision == "finalize":
                                break
                    # Every draft sees the same final evidence and artifacts. Identical
                    # rechecks replay from cache; stale acceptance never bypasses new facts.
                    for candidate in candidates:
                        assessments[candidate.id] = await self.assess(
                            q,
                            candidate,
                            list(evidence_ledger.values()),
                            artifacts,
                            self.research_outcomes[q.id],
                        )
                    pool = [c for c in reversed(candidates) if assessments[c.id]["eligible"]]
                else:
                    pool = candidates
                self.transition(q.id, Phase.SELECT)
                selector = self.config.selector
                if selector == "auto":
                    selector = "vote" if self.config.arm in {"B0", "B1"} else "backbone"
                if selector == "vote" and self.config.arm not in {"B0", "B1"}:
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
                    latest_verification=current.verification,
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
    *,
    solver_factory=None,
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
        solver = (solver_factory or Solver)(config, store, run_hash)
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
