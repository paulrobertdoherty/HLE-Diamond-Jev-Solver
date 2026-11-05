"""Fail closed on cache misses during attribution replay, including swallowed errors."""

from contextlib import ExitStack, contextmanager
from copy import deepcopy
from unittest.mock import patch

from ..models import digest


class OfflineDispatchForbidden(BaseException):
    """Not an Exception: provider/controller fallback handlers must not swallow it."""


@contextmanager
def offline_dispatch_guard():
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append("external_dispatch")
        raise OfflineDispatchForbidden("uncached dispatch forbidden in offline attribution")

    with ExitStack() as stack:
        for target in (
            "jev_solver.controller.budget.Budget.execute",
            "jev_solver.providers.backbone.make_backbone",
            "jev_solver.providers.jev.Jev._call",
            "jev_solver.tools.web.LiveWeb.search",
            "jev_solver.tools.web.LiveWeb.fetch",
            "jev_solver.tools.web.PerplexityWeb.search",
            "socket.create_connection",
            "socket.socket.connect",
            "socket.socket.connect_ex",
            "subprocess.Popen",
            "asyncio.create_subprocess_exec",
        ):
            stack.enter_context(patch(target, forbidden))
        yield attempts
        if attempts:
            raise OfflineDispatchForbidden("an offline dispatch attempt was intercepted")


class FrozenResponses:
    """Input-contract cache, intentionally independent of configuration-scoped run caches."""

    def __init__(self, rows=()):
        self.responses = {}
        self.replays = []
        for row in rows:
            contract = row["contract"]
            key = digest(contract)
            if row.get("input_hash", key) != key or key in self.responses:
                raise ValueError("changed or duplicate frozen input contract")
            self.responses[key] = deepcopy(row["response"])

    def replay(self, contract):
        key = digest(contract)
        if key not in self.responses:
            raise OfflineDispatchForbidden(f"frozen input contract miss: {key}")
        self.replays.append(key)
        return deepcopy(self.responses[key])
