from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable

from ..config import Config
from ..models import BudgetState, record
from ..tracing.store import Store


class BudgetExceeded(RuntimeError):
    pass


class CallLimitExceeded(BudgetExceeded):
    def __init__(self, kind: str):
        super().__init__(f"{kind} call limit")
        self.kind = kind


class Budget:
    """Reservations survive crashes. Uncertain charges consume their full reservation."""

    def __init__(self, store: Store, config: Config):
        self.store = store
        self.config = config
        self.lock = asyncio.Lock()
        self.semaphore = asyncio.Semaphore(config.limits.concurrency)

    async def reserve(self, item: str, kind: str, amount: float, final: bool = False) -> int:
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("invalid reservation")
        limits = self.config.limits
        async with self.lock:
            with self.store.transaction():
                if self.store.db.execute(
                    "SELECT 1 FROM events WHERE kind='reservation_overrun' LIMIT 1"
                ).fetchone():
                    raise BudgetExceeded("run halted after provider reservation overrun")
                counts = dict(
                    self.store.db.execute(
                        "SELECT kind,COUNT(*) FROM calls WHERE item=? GROUP BY kind", (item,)
                    )
                )
                cap = getattr(limits, kind, limits.calls)
                if sum(counts.values()) >= limits.calls:
                    raise BudgetExceeded("call limit")
                if counts.get(kind, 0) >= cap:
                    raise CallLimitExceeded(kind)
                reserve = 0 if final else limits.finalization_usd
                if self.store.cost(item) + amount + reserve > limits.item_usd + 1e-12:
                    raise BudgetExceeded("item dollar cap")
                if self.store.cost() + amount > limits.run_usd + 1e-12:
                    raise BudgetExceeded("run dollar cap")
                cursor = self.store.db.execute(
                    "INSERT INTO calls(item,kind,reserved,state) VALUES (?,?,?,'reserved')",
                    (item, kind, amount),
                )
                return cursor.lastrowid

    def settle(self, call: int, billed: float, usage: dict) -> None:
        if not math.isfinite(billed) or billed < 0:
            raise ValueError("invalid billed cost")
        row = self.store.db.execute(
            "SELECT item,reserved FROM calls WHERE id=?", (call,)
        ).fetchone()
        self.store.db.execute(
            "UPDATE calls SET billed=?,usage=?,state='settled' WHERE id=?",
            (billed, __import__("json").dumps(usage), call),
        )
        if billed > row[1] + 1e-9:
            self.store.event(row[0], "reservation_overrun", {"reserved": row[1], "billed": billed})
            raise BudgetExceeded("provider billed above declared maximum; stop and correct pricing")

    def snapshot(self, item: str) -> dict:
        counts = dict(
            self.store.db.execute(
                "SELECT kind,COUNT(*) FROM calls WHERE item=? GROUP BY kind", (item,)
            )
        )
        rows = self.store.db.execute(
            "SELECT COALESCE(SUM(billed),0),COALESCE(SUM(CASE WHEN billed IS NULL THEN reserved ELSE 0 END),0) FROM calls WHERE item=?",
            (item,),
        ).fetchone()
        return record(BudgetState(rows[0], rows[1], counts))

    async def execute(
        self,
        item: str,
        kind: str,
        upper: float,
        operation: Callable[[], Awaitable[dict]],
        final: bool = False,
    ) -> dict:
        for attempt in range(self.config.limits.retries + 1):
            call = None
            try:
                async with self.semaphore:
                    call = await self.reserve(item, kind, upper, final)
                    result = await operation()
            except asyncio.CancelledError:
                self.store.event(
                    item,
                    "cancelled",
                    {"call": call, "uncertain_cost_usd": upper if call is not None else 0},
                )
                raise
            except Exception as e:
                self.store.event(
                    item,
                    "call_error",
                    {"call": call, "error_type": type(e).__name__, "attempt": attempt},
                )
                # No exception text: providers may include headers or task material.
                if attempt >= self.config.limits.retries or not getattr(e, "retryable", False):
                    raise
                await asyncio.sleep(min(2**attempt, 8))
            else:
                self.settle(call, result["cost_usd"], result.get("usage", {}))
                return result
        raise AssertionError("unreachable")
