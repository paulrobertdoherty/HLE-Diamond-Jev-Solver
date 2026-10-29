import importlib.util
import asyncio
from dataclasses import replace
from types import SimpleNamespace
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import quote

from jev_solver.config import Config
from jev_solver.controller.budget import Budget
from jev_solver.judgments.pipeline import verify, rerank
from jev_solver.models import Candidate, Citation
from jev_solver.providers.jev import Jev
from jev_solver.retrieval.evidence import chunk_page, diverse_packet
from jev_solver.tools.policy import Blocked, Policy
from jev_solver.tools.sandbox import Sandbox
from jev_solver.tools.web import AuditedWeb, LiveWeb, MockWeb, MainText
from jev_solver.tracing.store import Store


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = Policy(Path("protocol/upstream/blocklist.json"))

    def test_main_content_preserves_math_and_table_text(self):
        parser = MainText()
        parser.feed(
            '<title>Reference</title><nav>Navigation</nav><article><h1>Result</h1><p>Value <script type="math/tex">x^2</script></p><table><tr><th>Unit</th><td>m</td></tr></table><script>ignore this instruction</script></article>'
        )
        self.assertNotIn("Navigation", parser.text)
        self.assertNotIn("ignore this instruction", parser.text)
        self.assertIn("x^2", parser.text)
        self.assertIn("Unit | m", parser.text)
        self.assertEqual("".join(parser.title), "Reference")

    def test_domains_proxy_encoding_and_private_addresses(self):
        urls = [
            "https://huggingface.co/datasets/x",
            "https://sub.huggingface.co./x",
            "https://allowed.org/?url=https%253A%252F%252Fhuggingface.co%252Fdatasets",
            "https://allowed.org/archive/http://github.com/cais/hle",
            "https://127.0.0.1/a",
            "http://169.254.169.254/latest/meta-data",
            "https://localhost/a",
            "file:///tmp/x",
            "https://user:pass@example.org",
            "https://example.org:123/a",
            "https://google.com/search?q=test",
            "https://arxiv.org/abs/2605.22138",
            "https://allowed.org/?target=nature.com/articles/s41586-025-09962-4",
        ]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(Blocked):
                self.policy.url(url)

    def test_primary_sources_remain_accessible(self):
        for url in [
            "https://arxiv.org/abs/2203.11171",
            "https://docs.python.org/3/",
            "https://en.wikipedia.org/wiki/Cobalt",
        ]:
            self.policy.url(url)

    def test_blocked_prefixes_resolve_dot_segments_in_direct_and_embedded_urls(self):
        for target in (
            "nature.com/x/../articles/s41586-025-09962-4",
            "www.nature.com.:443/x/../articles/s41586-025-09962-4",
            "nature.com/./articles/s41586-025-09962-4",
            "nature.com/../../articles/s41586-025-09962-4",
            "nature.com/x/%2e%2e/articles/s41586-025-09962-4",
            "nature.com/x%252f..%252farticles/s41586-025-09962-4",
            "nature.com/%3F/../articles/s41586-025-09962-4",
            "nature.com/%23/../articles/s41586-025-09962-4",
            "arxiv.org/x/../abs/2605.02442",
            "openreview.net/x/../pdf?id=46UGfq8kMI",
        ):
            for url in (
                "https://" + target,
                "https://example.org/?url=https://" + target,
                "https://example.org/?target=" + target,
                "https://example.org/archive/https://proxy.example.org/?url=https://" + target,
                "https://example.org/?url=" + quote("https://" + target, safe=""),
                "https://example.org/?url=" + quote(quote("https://" + target, safe=""), safe=""),
            ):
                with self.subTest(url=url), self.assertRaisesRegex(Blocked, "url_prefix"):
                    self.policy.url(url)

    def test_allowed_url_normalization_preserves_escaping_and_query(self):
        self.assertEqual(
            self.policy.url("https://example.org/a/../Reference%2FFile?q=x%26y"),
            "https://example.org/Reference%2FFile?q=x%26y",
        )
        self.policy.url("https://arxiv.org/x/../abs/2203.11171")

    def test_query_checks_before_search(self):
        for query in (
            "site:huggingface.co answers",
            "HLE-Diamond answer key",
            "A long verbatim question copied directly into search",
        ):
            with self.subTest(query=query), self.assertRaises(Blocked):
                self.policy.query(
                    query, "A long verbatim question copied directly into search with more detail"
                )

    def test_result_title_allowlist_is_narrow(self):
        result = {
            "url": "https://example.org/x",
            "title": "Puzzle answers - Example",
            "snippet": "ordinary text",
        }
        with self.assertRaises(Blocked):
            self.policy.result(result)
        self.policy.result({**result, "url": "https://en.wikipedia.org/wiki/Puzzle"})
        with self.assertRaises(Blocked):
            self.policy.result(
                {
                    **result,
                    "url": "https://en.wikipedia.org/wiki/Puzzle",
                    "snippet": "Humanity's Last Exam solutions",
                }
            )

    def test_case_sensitive_rules_are_preserved(self):
        with self.assertRaises(Blocked):
            self.policy.text("HLE answer details")
        self.policy.text("the local hle signal")

    def test_fetched_content_and_title_are_filtered(self):
        for field in ("title", "text"):
            with self.subTest(field=field), self.assertRaises(Blocked):
                self.policy.page(
                    {
                        "url": "https://example.org",
                        "title": "",
                        "text": "text",
                        field: "Humanity's Last Exam",
                    }
                )


class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "events.sqlite3")
        self.cfg = Config()
        self.budget = Budget(self.store, self.cfg)
        self.policy = Policy(Path("protocol/upstream/blocklist.json"))
        self.web = AuditedWeb(self.cfg, self.store, self.budget, self.policy)

    async def asyncTearDown(self):
        self.store.close()
        self.tmp.cleanup()

    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "optional PDF dependency not installed")
    async def test_pdf_parser_is_bounded_and_rejects_invalid_payload(self):
        from io import BytesIO
        from pypdf import PdfWriter
        from jev_solver.tools.parsing import extract_pdf
        from jev_solver.providers.backbone import ProviderError

        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.add_metadata({"/Title": "Fictional reference"})
        stream = BytesIO()
        writer.write(stream)
        result = await extract_pdf(stream.getvalue())
        self.assertEqual(result["title"], "Fictional reference")
        with self.assertRaises(ProviderError):
            await extract_pdf(b"invalid document")

    async def test_failed_rerank_cancels_and_joins_sibling_calls(self):
        from jev_solver.controller.budget import BudgetExceeded

        page = await self.web.fetch("q", "https://example.org")
        p = chunk_page(page, "code")[0]
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def judge(item, stage, state, questions):
            if state["passage"] == "fail":
                await started.wait()
                raise BudgetExceeded("item cap")
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        jev = SimpleNamespace(request=judge)
        with self.assertRaises(BudgetExceeded):
            await rerank(jev, "q", [replace(p, text="fail"), replace(p, text="wait")])
        self.assertTrue(cancelled.is_set())

    async def test_blocked_queries_never_reach_backend(self):
        backend = MockWeb()
        backend.search = AsyncMock()
        self.web.backend = backend
        self.assertEqual(await self.web.search("q", "site:huggingface.co test", "question"), [])
        backend.search.assert_not_called()

    async def test_dot_segment_prefix_never_reaches_backend(self):
        self.web.backend.fetch = AsyncMock()
        self.assertIsNone(
            await self.web.fetch("q", "https://nature.com/x/../articles/s41586-025-09962-4")
        )
        self.web.backend.fetch.assert_not_called()
        self.assertEqual(self.budget.snapshot("q")["counts"], {})

    async def test_snippets_filtered_and_at_most_twenty_before_filtering(self):
        rows = [
            {"url": f"https://example.org/{i}", "title": "source", "snippet": "safe"}
            for i in range(25)
        ]
        rows[0]["snippet"] = "Humanity's Last Exam answer"
        self.web.backend.search = AsyncMock(return_value=rows)
        result = await self.web.search("q", "short factual query", "a question")
        self.assertEqual(len(result), 19)
        self.assertFalse(any("Last Exam" in r["snippet"] for r in result))

    async def test_fetch_truncates_and_marks(self):
        self.web.backend.fetch = AsyncMock(
            return_value={"url": "https://example.org", "title": "", "text": "a" * 60001}
        )
        page = await self.web.fetch("q", "https://example.org")
        self.assertEqual(len(page["text"]), 60000)
        self.assertTrue(page["truncated"])

    async def test_filter_runs_before_truncation(self):
        self.web.backend.fetch = AsyncMock(
            return_value={
                "url": "https://example.org",
                "title": "",
                "text": "a" * 60001 + " Humanity's Last Exam",
            }
        )
        self.assertIsNone(await self.web.fetch("q", "https://example.org"))

    async def test_redirect_chain_is_filtered(self):
        self.web.backend.fetch = AsyncMock(
            return_value={
                "url": "https://example.org",
                "title": "",
                "text": "safe",
                "redirects": ["https://huggingface.co/secret"],
            }
        )
        self.assertIsNone(await self.web.fetch("q", "https://example.org"))

    async def test_cached_content_is_revalidated(self):
        await self.web.fetch("q", "https://example.org")
        key, raw = self.store.db.execute("SELECT key,value FROM cache WHERE item='q'").fetchone()
        value = json.loads(raw)
        value["page"]["text"] = "HLE-Diamond benchmark answers"
        self.store.cache("q", key, value)
        self.web.backend.fetch = AsyncMock(side_effect=AssertionError("replay should not fetch"))
        self.assertIsNone(await self.web.fetch("q", "https://example.org"))

    async def test_evidence_offsets_and_origin_diversity(self):
        page = await self.web.fetch("q", "https://example.org")
        passages = chunk_page(page, "code", size=40)
        for p in passages:
            self.assertEqual(p.text, page["text"][p.start : p.end])
        packet = diverse_packet(passages * 2, 1000)
        self.assertLessEqual(len(packet), 2)
        self.assertEqual(len({p.id for p in packet}), len(packet))

    async def test_fabricated_quote_rejected_before_jev(self):
        page = await self.web.fetch("q", "https://example.org")
        p = chunk_page(page, "code")[0]
        c = Candidate(
            "c", "28", 0.8, "", citations=(Citation("code is 28", p.id, "code is 28", 0, 10, True),)
        )
        jev = Jev(self.cfg, self.store, self.budget)
        jev.request = AsyncMock(
            side_effect=AssertionError("fabricated span reached semantic judge")
        )
        checks = await verify(jev, "q", c, [p], True)
        self.assertFalse(checks[0]["valid_span"])
        jev.request.assert_not_called()

    async def test_exact_quote_with_local_offsets_passes(self):
        page = await self.web.fetch("q", "https://example.org")
        p = chunk_page(page, "code")[0]
        quote = "The synthetic cobalt code is 27."
        start = p.text.index(quote)
        c = Candidate(
            "c",
            "27",
            0.8,
            "",
            citations=(Citation(quote, p.id, quote, start, start + len(quote), True),),
        )
        checks = await verify(Jev(self.cfg, self.store, self.budget), "q", c, [p], True)
        self.assertEqual(checks[0]["support"], "supported")

    async def test_sandbox_command_has_no_network_mounts_or_secrets(self):
        sandbox = Sandbox(self.cfg, self.store, self.budget)
        args = sandbox.command("jev-test")
        self.assertIn("--network=none", args)
        self.assertIn("--read-only", args)
        self.assertIn("--cap-drop=ALL", args)
        self.assertIn("--user=65534:65534", args)
        self.assertFalse(
            any(x in args for x in ["-v", "--volume", "--mount", "--env", "-e", "--privileged"])
        )
        self.assertEqual(args[-3:], ["python", "-I", "-"])

    @unittest.skipUnless(
        importlib.util.find_spec("httpx"), "optional HTTP dependency not installed"
    )
    async def test_dns_resolution_rejects_private_ips(self):
        with patch(
            "jev_solver.tools.web.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("127.0.0.1", 443))],
        ):
            with self.assertRaisesRegex(Blocked, "nonpublic_dns"):
                await LiveWeb().fetch("https://example.org/source", self.policy)

    @unittest.skipUnless(
        importlib.util.find_spec("httpx"), "optional HTTP dependency not installed"
    )
    async def test_live_redirect_checked_before_second_request(self):
        import httpx

        seen = []

        def handle(request):
            seen.append(request)
            return httpx.Response(302, headers={"location": "https://huggingface.co/secret"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with (
            patch("httpx.AsyncClient", return_value=client),
            patch(
                "jev_solver.tools.web.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
            ),
        ):
            with self.assertRaises(Blocked):
                await LiveWeb().fetch("https://example.org/source", self.policy)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].url.host, "93.184.216.34")
        self.assertEqual(seen[0].extensions["sni_hostname"], "example.org")

    @unittest.skipUnless(
        importlib.util.find_spec("httpx"), "optional HTTP dependency not installed"
    )
    async def test_live_dot_segment_prefix_checked_before_request_and_redirect(self):
        import httpx

        blocked = "https://nature.com/x/../articles/s41586-025-09962-4"
        for url, expected_requests in ((blocked, 0), ("https://example.org/source", 1)):
            with self.subTest(url=url):
                seen = []

                def handle(request, seen=seen):
                    seen.append(request)
                    return httpx.Response(302, headers={"location": blocked})

                client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
                with (
                    patch("httpx.AsyncClient", return_value=client),
                    patch(
                        "jev_solver.tools.web.socket.getaddrinfo",
                        return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
                    ),
                ):
                    with self.assertRaisesRegex(Blocked, "url_prefix"):
                        await LiveWeb().fetch(url, self.policy)
                self.assertEqual(len(seen), expected_requests)

    @unittest.skipUnless(
        importlib.util.find_spec("httpx"), "optional HTTP dependency not installed"
    )
    async def test_live_fetch_records_the_normalized_url_it_requests(self):
        import httpx

        seen = []

        def handle(request):
            seen.append(request)
            return httpx.Response(200, headers={"content-type": "text/plain"}, text="Reference")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with (
            patch("httpx.AsyncClient", return_value=client),
            patch(
                "jev_solver.tools.web.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
            ),
        ):
            page = await LiveWeb().fetch("https://example.org/a/../source?q=x%26y", self.policy)
        self.assertEqual(page["url"], "https://example.org/source?q=x%26y")
        self.assertEqual(str(seen[0].url), "https://93.184.216.34/source?q=x%26y")
