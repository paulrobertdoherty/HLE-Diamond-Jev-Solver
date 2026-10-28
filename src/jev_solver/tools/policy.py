"""Pinned upstream blocklist plus conservative question-copy and network checks."""

from __future__ import annotations

import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ..models import digest


class Blocked(ValueError):
    def __init__(self, rule: str):
        super().__init__(rule)
        self.rule = rule


def normalized_url(url: str) -> str:
    return re.sub(r"^(?:https?://)?(?:www\.)?", "", url.strip(), flags=re.I).lower()


def decoded(text: str) -> str:
    for _ in range(8):
        new = unquote(text)
        if new == text:
            return text
        text = new
    if unquote(text) != text:
        raise Blocked("excessive_url_encoding")
    return text


def host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


class Policy:
    def __init__(self, path: Path):
        self.rules = json.loads(path.read_text())
        self.version = digest(self.rules)
        self.domains = tuple(d.lower().rstrip(".") for d in self.rules["domains"])
        self.patterns = [("url_patterns", re.compile(p, re.I)) for p in self.rules["url_patterns"]]
        self.patterns += [
            ("patterns_case_sensitive", re.compile(p))
            for p in self.rules["patterns_case_sensitive"]
        ]
        self.serp = [re.compile(p, re.I) for p in self.rules["serp_url_patterns"]]
        self.titles = [re.compile(p, re.I) for p in self.rules["answer_title_patterns"]]

    def text(self, text: str):
        for kind, pattern in self.patterns:
            if pattern.search(text):
                raise Blocked(kind + ":" + pattern.pattern)

    def query(self, query: str, question: str):
        if not query.strip() or len(query) > 1000:
            raise Blocked("invalid_query_length")
        self.text(decoded(query))
        for host in re.findall(r"\bsite:\s*([^\s/]+)", decoded(query), re.I):
            host = host.lower().rstrip(".")
            if any(host_matches(host, d) for d in self.domains):
                raise Blocked("blocked_site_query:" + host)
        qwords = re.findall(r"\w+", question.casefold())
        words = re.findall(r"\w+", query.casefold())
        n = min(8, len(qwords))
        if n >= 4:
            spans = {tuple(qwords[i : i + n]) for i in range(len(qwords) - n + 1)}
            if any(tuple(words[i : i + n]) in spans for i in range(len(words) - n + 1)):
                raise Blocked("verbatim_question_span")
        for quote in re.findall(r'["“](.{40,}?)["”]', query):
            if quote.casefold() in question.casefold():
                raise Blocked("verbatim_question_quote")

    def url(self, url: str) -> str:
        value = decoded(url).strip()
        if len(value) > 12000:
            raise Blocked("url_length_limit")
        if any(ord(c) < 32 for c in value) or "\\" in value:
            raise Blocked("malformed_url")
        parts = urlsplit(value)
        if (
            parts.scheme not in {"https", "http"}
            or not parts.hostname
            or parts.username
            or parts.password
        ):
            raise Blocked("invalid_url_scheme_or_authority")
        try:
            port = parts.port
            host = parts.hostname.encode("idna").decode().lower().rstrip(".")
        except (ValueError, UnicodeError):
            raise Blocked("invalid_host") from None
        if port is not None and port not in {80, 443}:
            raise Blocked("nonstandard_port")
        if (
            host in {"localhost", "localhost.localdomain"}
            or "." not in host
            or host.endswith((".local", ".internal"))
        ):
            raise Blocked("nonpublic_host")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not address.is_global:
                raise Blocked("nonpublic_ip")
        # Inspect hosts anywhere in decoded proxy/archive links, including scheme-less targets.
        hosts = {host}
        hosts.update(re.findall(r"(?:https?://|//)([^/:?&#\s]+)", value, re.I))
        hosts.update(re.findall(r"\b((?:[\w-]+\.)+[\w-]+)\b", value, re.I))
        for target in hosts:
            if any(host_matches(target.lower().rstrip("."), domain) for domain in self.domains):
                raise Blocked("blocked_domain:" + target)
        targets = [value] + re.findall(r"https?://[^\s<>\"']+", value, re.I)
        for target in targets:
            norm = normalized_url(target)
            for prefix in self.rules["url_prefixes"]:
                if norm.startswith(normalized_url(prefix)) or re.search(
                    r"(?:^|[/?=&])(?:https?://)?(?:www\.)?" + re.escape(normalized_url(prefix)),
                    value,
                    re.I,
                ):
                    raise Blocked("url_prefix:" + prefix)
            for pattern in self.serp:
                if pattern.search(norm):
                    raise Blocked("serp_url:" + pattern.pattern)
        self.text(value)
        return url

    def result(self, result: dict):
        self.url(result["url"])
        self.text(result.get("title", ""))
        self.text(result.get("snippet", ""))
        host = urlsplit(result["url"]).hostname.lower().rstrip(".")
        if not any(host_matches(host, d) for d in self.rules["answer_title_allow_hosts"]):
            title = result.get("title", "")
            titles = [title, re.split(r"\s+[|–—-]\s+", title)[0]]
            for title in titles:
                for pattern in self.titles:
                    if pattern.search(title):
                        raise Blocked("answer_title:" + pattern.pattern)

    def page(self, page: dict):
        self.url(page["url"])
        for url in page.get("redirects", []):
            self.url(url)
        self.text(page.get("title", ""))
        self.text(page["text"])
        self.text(page.get("filter_text", ""))
