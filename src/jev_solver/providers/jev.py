from __future__ import annotations

from dataclasses import asdict

from ..config import Config
from ..controller.budget import Budget, BudgetExceeded
from ..models import Judgment, canonical, digest, probability, record
from ..tracing.store import Store
from .backbone import ProviderError, cost, upper_cost


class Jev:
    def __init__(self, config: Config, store: Store, budget: Budget, client=None):
        self.config, self.store, self.budget = config, store, budget
        self.client = client

    async def request(
        self, item: str, stage: str, state: dict, questions: dict
    ) -> dict[str, Judgment]:
        request = {
            "stage": stage,
            "state": state,
            "questions": questions,
            "provider": asdict(self.config.jev),
            "config_hash": self.config.hash,
        }
        key = digest(request)
        cached = self.store.cached(item, key)
        if cached is not None:
            self.store.event(item, "jev_replay", {"request_hash": key})
            return {k: Judgment(**v) for k, v in cached.items()}
        if len(canonical(request).encode()) > 64000:
            raise ValueError("Jev request exceeds conservative 64k token bound")
        for q in questions.values():
            if len(canonical({"state": state, "question": q}).encode()) > 32000:
                raise ValueError("Jev question exceeds conservative 32k token bound")
        try:
            response = await self.budget.execute(
                item, "jev", upper_cost(self.config.jev), lambda: self._call(state, questions)
            )
            self.store.event(item, "jev_response", {"request_hash": key, **response})
            if response["model"] != self.config.jev.model:
                raise ValueError("Jev returned a different model")
            if set(response["answers"]) != set(questions):
                raise ValueError("Jev response question keys differ")
            result = {}
            for name, spec in questions.items():
                answer = response["answers"][name]
                if answer.get("type") != spec["type"]:
                    raise ValueError("Jev returned the wrong primitive")
                if spec["type"] == "noul":
                    value, confidence = probability(answer["noul"]), None
                else:
                    confidence = probability(answer["confidence"])
                    value = answer[spec["type"]]
                    if spec["type"] == "score":
                        if (
                            not isinstance(value, (int, float))
                            or not 0 <= value <= len(spec["criteria"]) - 1
                        ):
                            raise ValueError("score outside ordered levels")
                        value = float(value) / (len(spec["criteria"]) - 1)
                    elif value not in spec["criteria"]:
                        raise ValueError("Choice selected an inadmissible action")
                result[name] = Judgment(
                    stage,
                    name,
                    value,
                    confidence,
                    response["model"],
                    answer.get("probabilities", {}),
                )
        except BudgetExceeded:
            raise
        except Exception as e:
            self.store.event(
                item,
                "jev_outage",
                {"error_type": type(e).__name__, "fallback": self.config.jev_failure},
            )
            if self.config.jev_failure == "fail":
                raise
            # Missing judgments stay explicitly missing; callers use the baseline policy.
            result = {}
        self.store.cache(item, key, {k: record(v) for k, v in result.items()})
        return result

    async def _call(self, state: dict, questions: dict) -> dict:
        p = self.config.jev
        if p.kind == "mock":
            answers = {}
            for name, spec in questions.items():
                kind = spec["type"]
                if kind == "score":
                    passage = str(state.get("passage", ""))
                    answers[name] = {
                        "type": kind,
                        "score": 3.0 if "cobalt code" in passage else 0.0,
                        "confidence": 0.9,
                    }
                elif kind == "noul":
                    answers[name] = {"type": kind, "noul": 0.8}
                else:
                    options = spec["criteria"]
                    value = (
                        "supported"
                        if "supported" in options
                        else (
                            "search"
                            if "search" in options
                            else ("finalize" if "finalize" in options else next(iter(options)))
                        )
                    )
                    if "none-supported" in options:
                        value = next(
                            (
                                k
                                for k, c in state.get("candidates", {}).items()
                                if c.get("answer", "").strip()
                            ),
                            "none-supported",
                        )
                    answers[name] = {"type": kind, "choice": value, "confidence": 0.9}
            usage = {"input_tokens": 100, "output_tokens": 10}
            return {
                "model": p.model,
                "answers": answers,
                "usage": usage,
                "cost_usd": cost(p, usage),
            }
        from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, RetryPolicy, Score

        if self.client is None:
            self.client = AsyncTypeSafeClient(retry=RetryPolicy(max_retries=0), timeout=120)
        classes = {"choice": Choice, "noul": Noul, "score": Score}
        specs = {
            k: classes[q["type"]](**{f: v for f, v in q.items() if f != "type"})
            for k, q in questions.items()
        }
        try:
            response = await self.client.system_one(model=p.model, state=state, questions=specs)
        except Exception as e:
            status = getattr(e, "status_code", None)
            raise ProviderError(
                "TypeSafe request failed",
                status == 429
                or (status is not None and status >= 500)
                or "Timeout" in type(e).__name__
                or "Connection" in type(e).__name__,
            ) from None
        raw = response.model_dump()
        raw["cost_usd"] = cost(p, raw["usage"])
        return raw

    async def close(self):
        if self.client:
            await self.client.aclose()
