import importlib.util
import json
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from jev_solver.config import Config
from jev_solver.controller.budget import Budget
from jev_solver.providers.backbone import ProviderError
from jev_solver.tools.policy import Policy
from jev_solver.tools.web import AuditedWeb, PerplexityWeb, retry_after_seconds
from jev_solver.tracing.store import Store


class PerplexityConfigTests(unittest.TestCase):
    def test_backend_requires_explicit_search_price(self):
        with self.assertRaisesRegex(ValueError, "positive search_usd"):
            replace(Config(), search_backend="perplexity").validate()
        replace(Config(), search_backend="perplexity", search_usd=0.005).validate()
        Config.load("configs/sol-low.jev-perplexity-pilot.json")

    def test_retry_after_accepts_seconds_and_http_dates(self):
        self.assertEqual(retry_after_seconds("15"), 15)
        future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=60))
        self.assertTrue(58 < retry_after_seconds(future) <= 60)
        for value in (None, "not a date"):
            self.assertEqual(retry_after_seconds(value), 0)
        for value in ("-1", "nan", "inf"):
            self.assertEqual(
                ProviderError("error", retry_after_s=retry_after_seconds(value)).retry_after_s, 0
            )


@unittest.skipUnless(
    importlib.util.find_spec("perplexity"), "optional Perplexity SDK not installed"
)
class PerplexityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import httpx

        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "events.sqlite3")
        self.cfg = replace(Config(), search_backend="perplexity", search_usd=0.005).validate()
        self.budget = Budget(self.store, self.cfg)
        self.policy = Policy(Path("protocol/upstream/blocklist.json"))
        self.requests = []
        self.status = 200
        self.headers = {}
        self.payload = {
            "id": "search-test",
            "results": [{"url": "https://example.org/source", "title": "Reference", "snippet": ""}],
        }

        def handle(request):
            self.requests.append(request)
            return httpx.Response(self.status, json=self.payload, headers=self.headers)

        self.backend = PerplexityWeb(transport=httpx.MockTransport(handle))
        self.web = AuditedWeb(self.cfg, self.store, self.budget, self.policy, self.backend)
        self.env = patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-secret"}, clear=True)
        self.env.start()

    async def asyncTearDown(self):
        self.env.stop()
        self.store.close()
        self.tmp.cleanup()

    async def test_request_shape_and_audited_cache_accounting(self):
        self.assertIsInstance(
            AuditedWeb(self.cfg, self.store, self.budget, self.policy).backend, PerplexityWeb
        )
        with patch.dict(os.environ, {"PERPLEXITY_BASE_URL": "https://unwanted.example"}):
            rows = await self.web.search("q", "short factual query", "question")
        self.assertEqual(rows, self.payload["results"])
        request = self.requests[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(str(request.url), "https://api.perplexity.ai/search")
        self.assertEqual(request.headers["authorization"], "Bearer test-secret")
        self.assertEqual(
            json.loads(request.content),
            {
                "query": "short factual query",
                "search_type": "web",
                "max_results": 20,
                "max_tokens": 20000,
                "max_tokens_per_page": 1024,
            },
        )
        self.assertEqual(await self.web.search("q", "short factual query", "question"), rows)
        self.assertEqual(len(self.requests), 1)
        self.assertAlmostEqual(self.store.cost(), 0.005)
        self.assertEqual(self.budget.snapshot("q")["counts"], {"search": 1})
        for table, column in (("events", "data"), ("cache", "value")):
            for (raw,) in self.store.db.execute(f"SELECT {column} FROM {table}"):
                self.assertNotIn("test-secret", raw)

    async def test_query_filter_precedes_network_and_result_filter_precedes_exposure(self):
        self.assertEqual(await self.web.search("q", "site:huggingface.co test", "question"), [])
        self.assertEqual(self.requests, [])
        self.payload["results"] = [
            {"url": f"https://example.org/{i}", "title": "Source", "snippet": "safe"}
            for i in range(25)
        ]
        self.payload["results"][0]["snippet"] = "Humanity's Last Exam answer"
        self.payload["results"][1]["url"] = "https://huggingface.co/blocked"
        rows = await self.web.search("q", "short factual query", "question")
        self.assertEqual(len(rows), 18)
        self.assertTrue(all(int(row["url"].rsplit("/", 1)[1]) in range(2, 20) for row in rows))
        key, raw = self.store.db.execute("SELECT key,value FROM cache").fetchone()
        cached = json.loads(raw)
        cached["results"][2]["snippet"] = "HLE-Diamond benchmark answers"
        self.store.cache("q", key, cached)
        self.assertEqual(len(await self.web.search("q", "short factual query", "question")), 17)
        self.assertEqual(len(self.requests), 1)

    async def test_missing_key_and_auth_failures_never_retry_or_echo_bodies(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "PERPLEXITY_API_KEY"):
                await self.backend.search("query")
        self.assertEqual(self.requests, [])
        for status in (401, 402, 403, 422):
            with self.subTest(status=status):
                self.status = status
                self.payload = {"error": "server echoed test-secret"}
                with self.assertRaises(ProviderError) as caught:
                    await self.web.search(str(status), "short factual query", "question")
                self.assertFalse(caught.exception.retryable)
                self.assertNotIn("test-secret", str(caught.exception))
        self.assertEqual(len(self.requests), 4)

    async def test_retry_after_is_honored_by_budget_without_hidden_sdk_retries(self):
        import httpx

        def handle(request):
            self.requests.append(request)
            if len(self.requests) == 1:
                return httpx.Response(429, headers={"Retry-After": "12"}, json={"error": "limited"})
            return httpx.Response(200, json=self.payload)

        self.web.backend = PerplexityWeb(transport=httpx.MockTransport(handle))
        with patch("jev_solver.controller.budget.asyncio.sleep", new_callable=AsyncMock) as sleep:
            await self.web.search("q", "short factual query", "question")
        sleep.assert_awaited_once_with(12)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.budget.snapshot("q")["counts"], {"search": 2})
        self.assertAlmostEqual(self.store.cost(), 0.01)  # Conservatively retain failed reservation.

    async def test_zero_retries_means_one_attempt(self):
        cfg = replace(self.cfg, limits=replace(self.cfg.limits, retries=0))
        web = AuditedWeb(cfg, self.store, Budget(self.store, cfg), self.policy, self.backend)
        self.status, self.headers = 429, {"Retry-After": "12"}
        with patch("jev_solver.controller.budget.asyncio.sleep", new_callable=AsyncMock) as sleep:
            with self.assertRaises(ProviderError):
                await web.search("q", "short factual query", "question")
        sleep.assert_not_awaited()
        self.assertEqual(len(self.requests), 1)

    async def test_empty_results_are_valid_but_malformed_results_fail_closed(self):
        self.payload["results"] = []
        self.assertEqual(await self.backend.search("query"), [])
        for payload in (
            {},
            {"id": "test", "results": None},
            {"id": "test", "results": [{"url": "https://example.org", "title": "Source"}]},
            {"id": "test", "results": [{"url": "", "title": "Source", "snippet": "text"}]},
        ):
            with self.subTest(payload=payload):
                self.payload = payload
                with self.assertRaises(ProviderError):
                    await self.backend.search("query")
