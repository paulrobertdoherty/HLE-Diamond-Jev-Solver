"""Run frozen paired interventions through the engine, without evaluator labels.

Live misses require an explicit launch. Frozen reuse is keyed by complete submitted
inputs and component/model/prompt/schema identity, never by a final prediction.
"""

from __future__ import annotations

import asyncio
import json
import fcntl
import os
from dataclasses import asdict
from pathlib import Path

from ..controller.budget import Budget, BudgetExceeded
from ..controller import engine
from ..models import digest, record
from ..providers.backbone import Gateway, CANDIDATE_SCHEMA, SYSTEM, input_envelope
from ..providers.jev import Jev
from ..tools.web import AuditedWeb
from ..tracing.store import Store, atomic_json, private_dir
from .offline import OfflineDispatchForbidden
from .replay import ControlledReplay, validate_manifest


def policy(config, name):
    return getattr(getattr(config, "remediation", None), name, "legacy-v1")


class ExperimentBudget(Budget):
    """One durable aggregate ledger, including uncertain reservations and failed trials."""

    def __init__(self, store, config, ledger, run_key, caps, lock):
        super().__init__(store, config)
        self.ledger, self.run_key, self.caps, self.aggregate_lock = ledger, run_key, caps, lock
        self.global_calls = {}

    async def reserve(self, item, kind, amount, final=False):
        async with self.aggregate_lock:
            if self.ledger.db.execute(
                "SELECT 1 FROM events WHERE kind='reservation_overrun' LIMIT 1"
            ).fetchone():
                raise BudgetExceeded("experiment halted after a provider reservation overrun")
            run_cost = self.ledger.db.execute(
                "SELECT COALESCE(SUM(COALESCE(billed,reserved)),0) FROM calls WHERE substr(item,1,?)=?",
                (len(self.run_key), self.run_key),
            ).fetchone()[0]
            if (
                self.ledger.cost() + amount > self.caps["aggregate_usd"] + 1e-12
                or run_cost + amount > self.caps["run_usd"] + 1e-12
            ):
                raise BudgetExceeded("frozen experiment spend cap")
            call = await super().reserve(item, kind, amount, final)
            cursor = self.ledger.db.execute(
                "INSERT INTO calls(item,kind,reserved,state) VALUES (?,?,?,'reserved')",
                (self.run_key + item, kind, amount),
            )
            self.global_calls[call] = cursor.lastrowid
            return call

    def settle(self, call, billed, usage):
        try:
            super().settle(call, billed, usage)
        finally:
            row = self.store.db.execute(
                "SELECT billed,usage,reserved FROM calls WHERE id=? AND state='settled'", (call,)
            ).fetchone()
            if row:
                self.ledger.db.execute(
                    "UPDATE calls SET billed=?,usage=?,state='settled' WHERE id=?",
                    (row[0], row[1], self.global_calls[call]),
                )
                if row[0] > row[2] + 1e-9:
                    self.ledger.event(
                        self.run_key, "reservation_overrun", {"reserved": row[2], "billed": row[0]}
                    )


def model_component(phase):
    if phase == "question-contract":
        return "contract"
    if phase.startswith("support-decomposition"):
        return "decomposition"
    if phase.startswith("whole-answer"):
        return "applicability"
    if phase.startswith("audit"):
        return "audit"
    if phase.startswith("initial"):
        return "initial"
    return "selection" if phase == "selection" else "revision"


async def replay_call(
    replay, arm, component, inputs, generate, *, allowed, budget, item, kind, final=False
):
    before = len(replay.ledger)
    response = await replay.request(arm, component, inputs, generate=generate if allowed else None)
    logical_key = "controlled-logical:" + digest([component, inputs])
    if (
        replay.ledger[before]["behavior"] in {"frozen", "generated_reuse"}
        and budget.store.cached(item, logical_key) is None
    ):
        # Reuse consumes the logical allowance; it creates no new paid charge.
        call = await budget.reserve(item, kind, 0, final)
        budget.settle(call, 0, {})
    budget.store.cache(item, logical_key, True)
    return response


class ReplayGateway(Gateway):
    async def generate(self, q, context, phase, provider=None, schema=None, final=False):
        p = provider or self.config.provider
        if schema is None:
            if hasattr(self.config, "remediation"):
                from ..providers.backbone import candidate_schema

                schema = candidate_schema(self.config)
            else:
                schema = CANDIDATE_SCHEMA
        submitted = context
        if policy(self.config, "context") == "remediation-v1":
            from ..providers.context import build_context

            submitted, _ = build_context(
                context, lambda c: input_envelope(q, c, schema, p), p.max_input_tokens
            )
        if input_envelope(q, submitted, schema, p) > p.max_input_tokens:
            raise ValueError("irreducible controlled input envelope")
        inputs = {
            "replicate": self.replicate,
            "question": record(q),
            "context": submitted,
            "schema": schema,
            "provider": asdict(p),
            "system": SYSTEM,
            "phase": phase,
            "context_builder": policy(self.config, "context"),
        }

        async def generate(_):
            return await super(ReplayGateway, self).generate(
                q, context, phase, provider, schema, final
            )

        result = await replay_call(
            self.replay,
            self.arm_id,
            model_component(phase),
            inputs,
            generate,
            allowed=(self.launch or not self.config.live)
            and not (
                self.comparison == "matched-j23"
                and model_component(phase) in {"initial", "contract"}
            ),
            budget=self.budget,
            item=q.id,
            kind="model",
            final=final,
        )
        # Frozen responses obey the same typed contract as new responses.
        from ..providers.context import validate_schema

        validate_schema(result, schema)
        if "answer" in schema["properties"]:
            from ..models import Candidate

            if policy(self.config, "citations") == "remediation-v1":
                from ..judgments.citations import parse_candidate
                from ..models import EvidencePassage

                parse_candidate(
                    result,
                    phase,
                    [EvidencePassage(**p) for p in context.get("evidence", [])],
                    resolve=True,
                )
            else:
                Candidate.parse(result, phase)
        if phase.startswith("audit") and self.comparison == "matched-j23":
            query_inputs = {
                "replicate": self.replicate,
                "question": record(q),
                "phase": phase,
                "contract": context.get("question_contract"),
                "dependency_ids": sorted(d["id"] for d in result["dependencies"]),
            }
            # Fixed routing never invents an unmatched query snapshot, even in a paid launch.
            result["queries"] = await self.replay.request(self.arm_id, "query", query_inputs)
        return result


class ReplayJev(Jev):
    async def request(self, item, stage, state, questions, *, final=False):
        submitted = state
        if policy(self.config, "context") == "remediation-v1":
            from ..providers.context import build_context
            from ..models import canonical

            submitted, _ = build_context(
                state,
                lambda s: max(
                    len(canonical({"state": s, "question": q}).encode()) for q in questions.values()
                ),
                32000,
            )
        inputs = {
            "replicate": self.replicate,
            "state": submitted,
            "questions": questions,
            "provider": asdict(self.config.jev),
            "context_builder": policy(self.config, "context"),
        }

        async def generate(_):
            result = await super(ReplayJev, self).request(
                item, stage, state, questions, final=final
            )
            return {k: record(v) for k, v in result.items()}

        response = await replay_call(
            self.replay,
            self.arm_id,
            stage if stage in {"J2", "J3"} else "selection",
            inputs,
            generate,
            allowed=self.launch or not self.config.live,
            budget=self.budget,
            item=item,
            kind="jev",
            final=final,
        )
        from ..models import Judgment

        result = {k: Judgment(**v) for k, v in response.items()}
        if set(result) != set(questions) or any(
            j.model != self.config.jev.model for j in result.values()
        ):
            raise ValueError("frozen Jev response differs from its contract")
        from ..models import probability

        for name, judgment in result.items():
            spec = questions[name]
            if judgment.stage != stage or judgment.key != name:
                raise ValueError("frozen judgment provenance differs")
            if spec["type"] in {"score", "noul"}:
                probability(judgment.value)
            elif judgment.value not in spec["criteria"]:
                raise ValueError("frozen judgment category differs")
            if judgment.confidence is not None:
                probability(judgment.confidence)
        return result


class ReplayWeb(AuditedWeb):
    async def search(self, item, query, question):
        self.policy.query(query, question)
        inputs = {
            "replicate": self.replicate,
            "query": query,
            "question": question,
            "backend": self.config.search_backend,
            "filter": self.policy.version,
            "search_usd": self.config.search_usd,
        }

        async def generate(_):
            return await super(ReplayWeb, self).search(item, query, question)

        rows = await replay_call(
            self.replay,
            self.arm_id,
            "search",
            inputs,
            generate,
            allowed=(self.launch or not self.config.live)
            and self.replay.manifest["comparison_kind"] != "matched-j23",
            budget=self.budget,
            item=item,
            kind="search",
        )
        for row in rows:
            self.policy.result(row)
        self.store.event(item, "controlled_search", {"input_hash": digest(inputs)})
        return rows

    async def fetch(self, item, url, *, cache_only=False):
        self.policy.url(url)
        inputs = {
            "replicate": self.replicate,
            "url": url,
            "backend": self.config.search_backend,
            "filter": self.policy.version,
            "parser": self.config.parser_version,
            "structure": policy(self.config, "structure"),
        }

        async def generate(_):
            return await super(ReplayWeb, self).fetch(item, url, cache_only=cache_only)

        page = await replay_call(
            self.replay,
            self.arm_id,
            "fetch",
            inputs,
            generate,
            allowed=(self.launch or not self.config.live)
            and not cache_only
            and self.replay.manifest["comparison_kind"] != "matched-j23",
            budget=self.budget,
            item=item,
            kind="fetch",
        )
        if page:
            if page.get("truncated") and not page.get("filter_text"):
                raise OfflineDispatchForbidden("full-page filter snapshot unavailable")
            self.policy.page(page)
        self.store.event(item, "controlled_fetch", {"input_hash": digest(inputs)})
        return page


def install_replay(solver, replay, arm, launch, ledger, run_key, caps, lock, replicate=0):
    solver.budget = ExperimentBudget(solver.store, solver.config, ledger, run_key, caps, lock)
    solver.gateway = ReplayGateway(solver.config, solver.store, solver.budget)
    solver.jev = ReplayJev(solver.config, solver.store, solver.budget)
    for client in (solver.gateway, solver.jev):
        client.replay, client.arm_id, client.launch = replay, arm["id"], launch
        client.replicate = replicate
    solver.gateway.comparison = replay.manifest["comparison_kind"]
    solver.web = ReplayWeb(solver.config, solver.store, solver.budget, solver.policy)
    solver.web.replay, solver.web.arm_id, solver.web.launch = replay, arm["id"], launch
    solver.web.replicate = replicate
    solver.sandbox.budget = solver.budget
    if not launch and solver.config.live:

        async def unavailable_code(*args, **kwargs):
            raise OfflineDispatchForbidden("execution snapshot unavailable; live launch required")

        solver.sandbox.execute = unavailable_code
    return solver


async def run_experiment(
    manifest, configs, questions, output, *, frozen=(), launch=False, resume=False
):
    output = private_dir(Path(output))
    fd = os.open(output / "experiment.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("another process owns this experiment") from None
        return await _run_experiment(
            manifest, configs, questions, output, frozen=frozen, launch=launch, resume=resume
        )
    finally:
        os.close(fd)


async def _run_experiment(
    manifest, configs, questions, output, *, frozen=(), launch=False, resume=False
):
    manifest = validate_manifest(manifest)
    from ..config import Config

    config_paths = {k: Path(v).resolve() for k, v in configs.items() if isinstance(v, (str, Path))}
    configs = {k: Config.load(v) if isinstance(v, (str, Path)) else v for k, v in configs.items()}
    if manifest["version"] != 2:
        raise ValueError("engine orchestration requires manifest version 2")
    if digest(list(frozen)) != manifest.get("snapshots_hash"):
        raise ValueError("frozen response snapshot hash differs")
    if launch and manifest["comparison_kind"] == "matched-j23":
        present = {r["contract"]["component"] for r in frozen}
        if not {"initial", "query", "search", "fetch"} <= present:
            raise ValueError(
                "matched launch requires frozen initial/query/search/fetch snapshots before any paid call"
            )
        for component in ("initial", "query"):
            present_trials = {
                (
                    r["contract"]["inputs"].get("question", {}).get("id"),
                    r["contract"]["inputs"].get("replicate", 0),
                )
                for r in frozen
                if r["contract"]["component"] == component
            }
            expected_trials = {
                (q, rep)
                for q in manifest["question_ids"]
                for rep in range(manifest["acceptance"]["replications"])
            }
            if not expected_trials <= present_trials:
                raise ValueError(
                    "matched launch is missing declared question/replication snapshots"
                )
    output = private_dir(Path(output))
    identities = output / "experiment.json"
    if identities.exists() and (not resume or json.loads(identities.read_text()) != manifest):
        raise ValueError("experiment exists or resume identity differs")
    from ..benchmarks.data import load_questions

    parsed = {q.id: q for q in load_questions(Path(questions))}
    declared = manifest.get("question_ids", sorted(parsed))
    if (
        not set(declared) <= set(parsed)
        or digest(sorted(declared)) != manifest["shared"]["questions_hash"]
    ):
        raise ValueError("question set differs from frozen experiment")
    if digest([record(parsed[q]) for q in sorted(declared)]) != manifest["shared"].get(
        "questions_content_hash"
    ):
        raise ValueError(
            "original question text/images differ or are not bound by the frozen manifest"
        )
    if set(configs) != {a["id"] for a in manifest["arms"]}:
        raise ValueError("provide exactly the frozen arm configurations")
    for arm in manifest["arms"]:
        config = configs[arm["id"]]
        foreign = bool(arm.get("source_root"))
        if foreign:
            from .snapshot_worker import snapshot_info

            if arm["id"] not in config_paths:
                raise ValueError("isolated source snapshots require an original configuration file")
            info = snapshot_info(arm["source_root"], config_paths[arm["id"]])
            if any(info[k] != arm[k] for k in ("config_hash", "implementation_hash")):
                raise ValueError("isolated source/configuration identity differs")
        if (
            (
                not foreign
                and (
                    config.hash != arm["config_hash"]
                    or arm["implementation_hash"] != engine.implementation_hash()
                )
            )
            or config.search_backend != manifest["backend"]
            or config.limits.item_usd != manifest["spend_caps"]["item_usd"]
            or config.limits.run_usd != manifest["spend_caps"]["run_usd"]
        ):
            raise ValueError(
                "configuration, source, backend or spend cap differs from frozen identity"
            )
    atomic_json(identities, manifest)
    responses_path = output / "generated-responses.json"
    generated = json.loads(responses_path.read_text()) if resume and responses_path.exists() else []
    replay = ControlledReplay(manifest, [*frozen, *generated])
    ledger, lock = Store(output / "experiment.sqlite3"), asyncio.Lock()
    trials = []
    original_solver = engine.Solver
    try:
        for replicate in range(manifest["acceptance"]["replications"]):
            for arm in manifest["arms"]:
                config = configs[arm["id"]]
                run_key = digest([arm["id"], replicate]) + ":"

                def factory(c, store, run_hash, arm=arm, run_key=run_key, replicate=replicate):
                    return install_replay(
                        original_solver(c, store, run_hash),
                        replay,
                        arm,
                        launch,
                        ledger,
                        run_key,
                        manifest["spend_caps"],
                        lock,
                        replicate,
                    )

                for identifier in declared:
                    destination = output / arm["id"] / str(replicate) / digest(identifier)[:20]
                    entry = {"arm": arm["id"], "replicate": replicate, "question_id": identifier}
                    try:
                        if arm.get("source_root"):
                            from .snapshot_worker import foreign_trial

                            result = await foreign_trial(
                                {
                                    "source_root": arm["source_root"],
                                    "config": str(config_paths[arm["id"]]),
                                    "manifest": manifest,
                                    "arm": arm["id"],
                                    "replicate": replicate,
                                    "question_id": identifier,
                                    "experiment_output": str(output.resolve()),
                                    "questions": str(Path(questions).resolve()),
                                    "destination": str(destination.resolve()),
                                    "launch": launch,
                                    "resume": resume,
                                    "frozen": list(frozen),
                                },
                                output / "snapshot-job.json",
                            )
                            replay.ledger.extend(result["ledger"])
                            generated = json.loads(responses_path.read_text())
                            from .offline import FrozenResponses

                            replay.frozen.responses.update(FrozenResponses(generated).responses)
                            if result["status"] == "unavailable_snapshot":
                                raise OfflineDispatchForbidden("isolated snapshot miss")
                        else:
                            await engine.run(
                                config,
                                Path(questions),
                                destination,
                                resume=resume,
                                split="development" if config.live else "full",
                                question_ids=(identifier,),
                                solver_factory=factory,
                            )
                        prediction = json.loads((destination / "predictions.json").read_text())[0]
                        entry.update(
                            {
                                k: prediction[k]
                                for k in ("status", "abstained", "cost_usd", "latency_s")
                            }
                        )
                    except OfflineDispatchForbidden:
                        entry.update(status="unavailable_snapshot", abstained=True)
                    except (ValueError, OSError, RuntimeError) as error:
                        entry.update(
                            status="failed_attempt", error_type=type(error).__name__, abstained=True
                        )
                    trials.append(entry)
                    atomic_json(output / "trials.json", trials)
                    atomic_json(output / "replay-ledger.json", replay.ledger)
                    merged = {
                        digest(r["contract"]): r for r in [*generated, *replay.generated.values()]
                    }
                    atomic_json(responses_path, list(merged.values()))
        return {
            "manifest_hash": digest(manifest),
            "declared_trials": len(trials),
            "trial_statuses": dict(__import__("collections").Counter(t["status"] for t in trials)),
            "actual_accounted_cost_usd": ledger.cost(),
            "paid_launch": launch,
            "accuracy": None,
            "note": "Grade separately with isolated evaluator labels; unavailable snapshots are not new predictions.",
        }
    finally:
        ledger.close()
