from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import os
import socket
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from ..config import Config
from ..controller.budget import Budget
from ..models import ToolEvent, digest, record
from ..providers.backbone import ProviderError
from ..tracing.store import Store
from .policy import Blocked, Policy
from .parsing import extract_pdf


class MainText(HTMLParser):
    """Deterministic main/article extraction with full text retained for filtering."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.title, self.main = [], [], []
        self.skip = self.main_depth = 0
        self.in_title = self.math_script = False

    def append(self, value):
        if self.skip:
            return
        self.parts.append(value)
        if self.main_depth:
            self.main.append(value)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"main", "article"}:
            self.main_depth += 1
        if tag == "script" and attrs.get("type", "").startswith("math/tex"):
            self.math_script = True
            self.append(" $$")
        elif tag in {"script", "style", "noscript"}:
            self.skip += 1
        if tag == "title":
            self.in_title = True
        if tag in {"p", "div", "section", "h1", "h2", "h3", "h4", "tr", "li", "br", "pre"}:
            self.append("\n\n")
        if tag in {"h1", "h2", "h3", "h4"}:
            self.append("#" * int(tag[1]) + " ")
        if tag in {"td", "th"}:
            self.append(" | ")
        if tag == "img" and attrs.get("alt"):
            self.append(attrs["alt"])

    def handle_endtag(self, tag):
        if tag == "script" and self.math_script:
            self.append("$$ ")
            self.math_script = False
        elif tag in {"script", "style", "noscript"}:
            self.skip = max(0, self.skip - 1)
        if tag in {"main", "article"}:
            self.main_depth = max(0, self.main_depth - 1)
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_title:
            self.title.append(data)
        else:
            self.append(data)

    @property
    def text(self):
        return "".join(self.main or self.parts)


class LiveWeb:
    async def search(self, query: str) -> list[dict]:
        import httpx

        if not os.environ.get("BRAVE_SEARCH_API_KEY"):
            raise ValueError("BRAVE_SEARCH_API_KEY required")
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": 20},
                headers={"X-Subscription-Token": os.environ["BRAVE_SEARCH_API_KEY"]},
            )
            if response.status_code != 200:
                raise ProviderError(
                    "search backend failed",
                    response.status_code == 429 or response.status_code >= 500,
                )
            rows = response.json().get("web", {}).get("results", [])
            return [
                {"url": r["url"], "title": r.get("title", ""), "snippet": r.get("description", "")}
                for r in rows[:20]
            ]

    async def fetch(self, url: str, policy: Policy) -> dict:
        import httpx

        redirects = []
        async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as client:
            for _ in range(6):
                policy.url(url)
                parts = urlsplit(url)
                host = parts.hostname
                addresses = await asyncio.to_thread(
                    socket.getaddrinfo,
                    host,
                    parts.port or (443 if parts.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
                ips = list(dict.fromkeys(a[4][0] for a in addresses))
                if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
                    raise Blocked("nonpublic_dns_resolution")
                # Connect to the validated IP; keep TLS hostname and Host header. No DNS rebind window.
                target = httpx.URL(url).copy_with(host=ips[0])
                async with client.stream(
                    "GET",
                    target,
                    headers={"Host": parts.netloc, "User-Agent": "jev-solver/0.1"},
                    extensions={"sni_hostname": host},
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        url = urljoin(url, response.headers["location"])
                        policy.url(url)
                        redirects.append(url)
                        continue
                    if response.status_code != 200:
                        raise ProviderError(
                            "source unavailable",
                            response.status_code == 429 or response.status_code >= 500,
                        )
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 8_000_000:
                            raise Blocked("source_byte_limit")
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    content_type = response.headers.get("content-type", "").lower()
                    if "pdf" in content_type:
                        parsed = await extract_pdf(body)
                        text, title = parsed["text"], parsed["title"]
                    elif "html" in content_type:
                        parser = MainText()
                        parser.feed(body.decode(response.encoding or "utf-8", errors="replace"))
                        text, title = parser.text, "".join(parser.title)
                    elif any(t in content_type for t in ("text/plain", "text/markdown")):
                        text, title = (
                            body.decode(response.encoding or "utf-8", errors="replace"),
                            "",
                        )
                    else:
                        raise Blocked("unsupported_media_type")
                    return {
                        "url": url,
                        "title": title,
                        "text": text,
                        "redirects": redirects,
                        "body_sha256": hashlib.sha256(body).hexdigest(),
                        "filter_text": "".join(parser.parts) if "html" in content_type else text,
                    }
        raise Blocked("redirect_limit")


class MockWeb:
    async def search(self, query: str) -> list[dict]:
        return [
            {
                "url": "https://reference.example.org/synthetic-elements",
                "title": "Synthetic reference",
                "snippet": "Fictional element codes for testing.",
            }
        ]

    async def fetch(self, url: str, policy: Policy) -> dict:
        return {
            "url": url,
            "title": "Synthetic reference",
            "text": "# Synthetic reference\n\nThe synthetic cobalt code is 27.\n\nThis is a fictional test reference.",
            "redirects": [],
        }


class AuditedWeb:
    def __init__(self, config: Config, store: Store, budget: Budget, policy: Policy, backend=None):
        self.config, self.store, self.budget, self.policy = config, store, budget, policy
        self.backend = backend or (MockWeb() if config.search_backend == "mock" else LiveWeb())

    def event(self, item: str, tool: str, key: str, outcome: str, rule="", replay=False):
        self.store.event(item, "tool", record(ToolEvent(tool, key, outcome, rule, replay)))

    async def search(self, item: str, query: str, question: str) -> list[dict]:
        key = digest(
            {
                "tool": "web_search",
                "query": query,
                "question": digest(question),
                "filter": self.policy.version,
                "config": self.config.hash,
            }
        )
        try:
            self.policy.query(query, question)
            cached = self.store.cached(item, key)
            replay = cached is not None
            if not replay:

                async def call():
                    try:
                        rows = await self.backend.search(query)
                    except (Blocked, ProviderError):
                        raise
                    except Exception as e:
                        raise ProviderError(
                            "search unavailable",
                            "Timeout" in type(e).__name__ or "Connect" in type(e).__name__,
                        ) from None
                    return {"results": rows[:20], "cost_usd": self.config.search_usd, "usage": {}}

                cached = await self.budget.execute(item, "search", self.config.search_usd, call)
                self.store.cache(item, key, cached)
            result = []
            for row in cached["results"][:20]:
                try:
                    self.policy.result(row)
                    result.append(row)
                except Blocked as e:
                    self.event(item, "web_search_result", digest(row), "blocked", e.rule, replay)
            self.event(item, "web_search", key, "allowed", replay=replay)
            self.store.event(
                item,
                "search_audit",
                {
                    "query": query,
                    "returned_hashes": [digest(r) for r in result],
                    "filter": self.policy.version,
                },
            )
            return result
        except Blocked as e:
            self.event(item, "web_search", key, "blocked", e.rule)
            return []

    async def fetch(self, item: str, url: str) -> dict | None:
        key = digest(
            {
                "tool": "web_fetch",
                "url": url,
                "filter": self.policy.version,
                "parser": self.config.parser_version,
                "config": self.config.hash,
            }
        )
        try:
            self.policy.url(url)
            cached = self.store.cached(item, key)
            replay = cached is not None
            if not replay:

                async def call():
                    try:
                        page = await self.backend.fetch(url, self.policy)
                    except (Blocked, ProviderError):
                        raise
                    except Exception as e:
                        raise ProviderError(
                            "source unavailable",
                            "Timeout" in type(e).__name__ or "Connect" in type(e).__name__,
                        ) from None
                    page["retrieved_at"] = datetime.now(timezone.utc).isoformat()
                    return {"page": page, "cost_usd": self.config.fetch_usd, "usage": {}}

                cached = await self.budget.execute(item, "fetch", self.config.fetch_usd, call)
                # Cache full content privately; filter again on every replay before truncation.
                self.store.cache(item, key, cached)
            page = cached["page"]
            self.policy.page(page)
            self.event(item, "web_fetch", key, "allowed", replay=replay)
            full = page["text"]
            return {
                **page,
                "text": full[:60000],
                "truncated": len(full) > 60000,
                "source_hash": hashlib.sha256(full.encode()).hexdigest(),
                "filter_version": self.policy.version,
            }
        except Blocked as e:
            self.event(item, "web_fetch", key, "blocked", e.rule)
            return None
