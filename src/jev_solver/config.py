from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .models import digest

ARMS = {"B0", "B1", "B2", "J2", "J3", "J23", "Jfull", "M", "R"}


@dataclass(frozen=True)
class ProviderConfig:
    kind: str = "mock"
    model: str = "synthetic-v1"
    input_per_million: float = 0
    output_per_million: float = 0
    max_input_tokens: int = 65536
    max_output_tokens: int = 4096
    image_token_reserve: int = 32768
    vision: bool = True
    structured_output: bool = True
    reasoning_effort: str = "medium"
    temperature: float | None = None
    openrouter_provider: str = ""
    request_timeout_s: float = 120


@dataclass(frozen=True)
class Limits:
    item_usd: float = 2
    run_usd: float = 20
    deadline_s: float = 600
    candidates: int = 3
    rounds: int = 2
    search: int = 6
    fetch: int = 8
    code: int = 3
    calls: int = 30
    retries: int = 1
    concurrency: int = 2
    finalization_usd: float = 0.1


@dataclass(frozen=True)
class Config:
    arm: str = "J23"
    track: str = "controlled"
    dataset: str = "synthetic"
    dataset_revision: str = "synthetic-v1"
    scope: str = "synthetic fixtures"
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    additional_providers: tuple[ProviderConfig, ...] = ()
    jev: ProviderConfig = field(default_factory=lambda: ProviderConfig(model="synthetic-jev-v1"))
    limits: Limits = field(default_factory=Limits)
    search_backend: str = "mock"
    search_usd: float = 0
    fetch_usd: float = 0
    code_usd: float = 0
    sandbox_image: str = ""
    protocol_manifest: str = "protocol/manifest.json"
    prompt_version: str = "evidence-v1"
    parser_version: str = "paragraph-v1"
    seed: int = 17
    jev_failure: str = "fail"
    selector: str = "vote"
    adaptive: bool = False
    evidence_chars: int = 18000
    corpus: str = ""
    retrieval: str = "lexical"
    primary_comparison: str = "J23-B2"
    departures: tuple[str, ...] = ()

    @property
    def hash(self) -> str:
        return digest(asdict(self))

    @property
    def live(self) -> bool:
        return self.provider.kind != "mock"

    def validate(self) -> Config:
        if self.arm not in ARMS or self.track not in {"closed", "controlled", "extended"}:
            raise ValueError("unknown arm or track")
        if (self.arm in {"B0", "B1"}) != (self.track == "closed"):
            raise ValueError("B0/B1 require closed track; tool arms require controlled/extended")
        if self.arm == "R" and (self.track != "extended" or not self.corpus):
            raise ValueError("R requires extended track and frozen corpus")
        if self.corpus and self.arm != "R":
            raise ValueError("persistent corpus experiments require the R arm")
        if self.retrieval != "lexical" and not self.corpus:
            raise ValueError("hybrid retrieval requires an explicitly frozen corpus")
        if self.corpus and self.track != "extended":
            raise ValueError("persistent corpus is allowed only in extended track")
        if self.retrieval not in {"lexical", "hybrid", "hybrid-jev"}:
            raise ValueError("unknown retrieval policy")
        if self.arm == "M" and self.limits.candidates < 1 + len(self.additional_providers):
            raise ValueError("M requires at least one independent sample per provider")
        if self.arm == "M" and not self.additional_providers:
            raise ValueError("M requires at least one additional provider")
        if self.additional_providers and self.arm != "M":
            raise ValueError("additional providers require the M arm")
        if self.adaptive and self.arm != "Jfull":
            raise ValueError("adaptive routing requires Jfull")
        if self.selector not in {"vote", "jev", "backbone"}:
            raise ValueError("unknown selector")
        if self.arm in {"B0", "B1"} and self.selector != "vote":
            raise ValueError("closed-book baselines use raw output or deterministic voting")
        if self.selector == "jev" and self.arm not in {"Jfull", "M", "R"}:
            raise ValueError("Jev selection is a later experiment")
        if self.jev_failure not in {"fail", "baseline"}:
            raise ValueError("unknown Jev fallback policy")
        if self.search_backend not in {"mock", "brave"}:
            raise ValueError("unknown search backend")
        lim = self.limits
        for key, val in asdict(lim).items():
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
                raise ValueError(f"invalid limit: {key}")
            if val < 0:
                raise ValueError(f"negative limit: {key}")
        for key in (
            "candidates",
            "rounds",
            "search",
            "fetch",
            "code",
            "calls",
            "retries",
            "concurrency",
        ):
            if type(getattr(lim, key)) is not int:
                raise ValueError(f"integer limit required: {key}")
        if (
            min(
                lim.item_usd,
                lim.run_usd,
                lim.deadline_s,
                lim.candidates,
                lim.calls,
                lim.concurrency,
            )
            <= 0
        ):
            raise ValueError(
                "positive spend caps, deadline, candidates, calls and concurrency required"
            )
        if lim.finalization_usd >= lim.item_usd:
            raise ValueError("finalization reserve must be smaller than item cap")
        if not 1 <= self.evidence_chars <= 60000:
            raise ValueError("evidence context must be within 1..60000 characters")
        for rate in (self.search_usd, self.fetch_usd, self.code_usd):
            if isinstance(rate, bool) or not math.isfinite(rate) or rate < 0:
                raise ValueError("tool charges must be finite and nonnegative")
        providers = (self.provider, self.jev, *self.additional_providers)
        for p in providers:
            if (
                isinstance(p.request_timeout_s, bool)
                or not isinstance(p.request_timeout_s, (int, float))
                or not math.isfinite(p.request_timeout_s)
                or p.request_timeout_s <= 0
            ):
                raise ValueError("positive finite provider request timeout required")
            if p.kind not in {"mock", "openai", "openrouter", "typesafe"}:
                raise ValueError("unsupported provider protocol")
            if p.kind not in {"mock", "openrouter"} and (
                not p.model or re.search(r"latest|preview|<|>", p.model, re.I)
            ):
                raise ValueError("explicit pinned model required")
            if p.kind not in {"mock", "openrouter"} and p.input_per_million <= 0:
                raise ValueError("explicit nonzero input price required for live providers")
            if any(
                not math.isfinite(v) or v < 0 for v in (p.input_per_million, p.output_per_million)
            ):
                raise ValueError("prices must be finite and nonnegative")
            if any(
                type(v) is not int or v <= 0
                for v in (p.max_input_tokens, p.max_output_tokens, p.image_token_reserve)
            ):
                raise ValueError("positive integer token limits required")
            if type(p.vision) is not bool or type(p.structured_output) is not bool:
                raise ValueError("provider capabilities must be booleans")
            if p.kind == "typesafe" and not re.fullmatch(r"jev-\d+\.\d+\.\d+", p.model):
                raise ValueError("use an exact versioned Jev model")
            if p.kind == "openai" and not re.search(r"-\d{4}-\d{2}-\d{2}$", p.model):
                raise ValueError("reported OpenAI experiments require a dated model snapshot")
            if p.kind == "openrouter":
                if (
                    not isinstance(p.model, str)
                    or not re.fullmatch(r"[\w.-]+/[\w.:-]+", p.model, re.ASCII)
                    or p.model.startswith("openrouter/")
                    or ":online" in p.model
                ):
                    raise ValueError(
                        "use an explicit OpenRouter author/model ID without web routing"
                    )
                if p.reasoning_effort not in {
                    "",
                    "none",
                    "minimal",
                    "low",
                    "medium",
                    "high",
                    "xhigh",
                    "max",
                }:
                    raise ValueError("unsupported OpenRouter reasoning effort")
            if not isinstance(p.openrouter_provider, str) or (
                p.openrouter_provider
                and (
                    p.kind != "openrouter"
                    or not re.fullmatch(r"[\w./-]+", p.openrouter_provider, re.ASCII)
                )
            ):
                raise ValueError("openrouter_provider requires an OpenRouter provider slug")
        if self.provider.kind == "typesafe" or any(
            p.kind == "typesafe" for p in self.additional_providers
        ):
            raise ValueError("Jev is a judge, not a generative backbone")
        if self.jev.kind not in {"mock", "typesafe"}:
            raise ValueError("Jev adapter requires typesafe or mock")
        if any(not p.structured_output for p in (self.provider, *self.additional_providers)):
            raise ValueError("backbone must support validated structured responses")
        if self.live:
            if self.dataset not in {
                "cais/hle-diamond",
                "independent/development",
            } or not re.fullmatch(r"[0-9a-f]{40}", self.dataset_revision):
                raise ValueError(
                    "live benchmark runs require cais/hle-diamond and exact dataset commit"
                )
            if not self.scope:
                raise ValueError("declare full benchmark, internal holdout, or subset scope")
            if (
                self.dataset == "independent/development"
                and self.scope != "independent-development"
            ):
                raise ValueError(
                    "external development data require an independent-development scope"
                )
            if any(p.kind == "mock" for p in self.additional_providers):
                raise ValueError("cannot mix synthetic and live backbones")
            if self.arm not in {"B0", "B1"}:
                if self.search_backend == "mock":
                    raise ValueError("live tool runs require live search")
                if not re.fullmatch(r"(?:[^\s]+@)?sha256:[0-9a-f]{64}", self.sandbox_image):
                    raise ValueError("pin built sandbox image by digest")
            needs_jev = (
                self.arm in {"J2", "J3", "J23", "Jfull", "M"}
                or self.selector == "jev"
                or self.retrieval == "hybrid-jev"
            )
            if needs_jev and self.jev.kind == "mock":
                raise ValueError("live Jev arms require live Jev")
        return self

    @classmethod
    def load(cls, path: str | Path) -> Config:
        row = json.loads(Path(path).read_text())
        for p in (row.get("provider", {}), *row.get("additional_providers", [])):
            if p.get("kind") == "openrouter" and not {
                "input_per_million",
                "output_per_million",
            } <= set(p):
                raise ValueError(
                    "OpenRouter requires explicit prices (zero is allowed for free models)"
                )
        if row.get("provider", {}).get("kind", "mock") != "mock":
            if not {"item_usd", "run_usd"} <= set(row.get("limits", {})):
                raise ValueError("live runs require explicit per-item and total-run dollar caps")
        for k in ("provider", "jev"):
            if k in row:
                row[k] = ProviderConfig(**row[k])
        if "limits" in row:
            row["limits"] = Limits(**row["limits"])
        for k in ("additional_providers",):
            if k in row:
                row[k] = tuple(ProviderConfig(**p) for p in row[k])
        if "departures" in row:
            row["departures"] = tuple(row["departures"])
        return cls(**row).validate()


def verify_protocol(path: str | Path) -> dict:
    manifest = json.loads(Path(path).read_text())
    if not re.fullmatch(r"[0-9a-f]{40}", manifest["upstream_commit"]):
        raise ValueError("protocol must pin an upstream commit")
    required = {
        "protocol/upstream/" + name
        for name in (
            "blocklist.json",
            "evaluation-with-tools.md",
            "requirements-tools.txt",
            "run_judge_results.py",
            "LICENSE",
        )
    }
    if set(manifest["files"]) != required:
        raise ValueError("protocol manifest must pin the complete upstream contract")
    for file, info in manifest["files"].items():
        if hashlib.sha256(Path(file).read_bytes()).hexdigest() != info["sha256"]:
            raise ValueError(f"protocol hash mismatch: {file}")
    if manifest["python"] != "3.11.16":
        raise ValueError("controlled sandbox requires Python 3.11.16")
    return manifest
