from __future__ import annotations

import math
import os

from ..config import ProviderConfig
from ..models import QuestionView, canonical
from .backbone import SYSTEM, ProviderError, cost


def retryable(status: int) -> bool:
    return status in {408, 409, 429} or 500 <= status < 600


class OpenRouterBackbone:
    """Chat Completions transport; the supervisor owns retries and all tool execution."""

    def __init__(self, config: ProviderConfig, client=None, *, api_key: str | None = None):
        self.config = config
        if client is None:
            import httpx

            key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY")
            if not key or not key.strip():
                raise ValueError("OPENROUTER_API_KEY required for the OpenRouter backbone")
            client = httpx.AsyncClient(
                base_url="https://openrouter.ai/api/v1/",
                headers={"Authorization": f"Bearer {key}"},
                timeout=config.request_timeout_s,
                follow_redirects=False,
            )
        self.client = client

    async def generate(self, question: QuestionView, context: dict, schema: dict) -> dict:
        content = [
            {"type": "text", "text": question.question},
            {"type": "text", "text": canonical(context)},
        ]
        content.extend(
            {"type": "image_url", "image_url": {"url": image}} for image in question.images
        )
        return await self.complete(
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": content},
            ],
            schema,
        )

    async def complete(self, messages: list[dict], schema: dict, *, name="solver_result") -> dict:
        """Use a caller-supplied prompt, including the isolated evaluator's grading prompt."""
        import httpx

        p = self.config
        provider = {
            "require_parameters": True,
            "max_price": {"prompt": p.input_per_million, "completion": p.output_per_million},
        }
        if p.openrouter_provider:
            provider.update(only=[p.openrouter_provider], allow_fallbacks=False)
        request = {
            "model": p.model,
            "messages": messages,
            "max_tokens": p.max_output_tokens,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": name, "strict": True, "schema": schema},
            },
            "provider": provider,
            "usage": {"include": True},
            "reasoning": {"exclude": True},
            # Override account defaults that could bypass the audited workflow or mutate outputs.
            "plugins": [
                {"id": plugin, "enabled": False}
                for plugin in (
                    "web",
                    "file-parser",
                    "response-healing",
                    "context-compression",
                    "fusion",
                )
            ],
            "transforms": [],
        }
        if p.reasoning_effort:
            request["reasoning"]["effort"] = p.reasoning_effort
        if p.temperature is not None:
            request["temperature"] = p.temperature
        try:
            response = await self.client.post("chat/completions", json=request)
        except httpx.TransportError:
            raise ProviderError("OpenRouter connection failed", retryable=True) from None
        if not response.is_success:
            # Never echo response bodies: upstream errors can contain prompts or credentials.
            raise ProviderError(
                f"OpenRouter request failed (HTTP {response.status_code})",
                retryable(response.status_code),
            )
        try:
            data = response.json()
        except ValueError:
            raise ProviderError("OpenRouter returned invalid JSON") from None
        if not isinstance(data, dict):
            raise ProviderError("OpenRouter returned an invalid response")
        if data.get("error"):
            error = data["error"]
            status = error.get("code") if isinstance(error, dict) else None
            raise ProviderError(
                "OpenRouter returned an error", type(status) is int and retryable(status)
            )

        raw_usage = data.get("usage")
        if not isinstance(raw_usage, dict):
            raise ProviderError("OpenRouter did not report usage; reservation remains charged")
        usage = {
            "input_tokens": raw_usage.get("prompt_tokens"),
            "output_tokens": raw_usage.get("completion_tokens"),
            "input_tokens_details": raw_usage.get("prompt_tokens_details"),
            "output_tokens_details": raw_usage.get("completion_tokens_details"),
            "openrouter": raw_usage,
        }
        billed = cost(p, usage)
        reported_cost = raw_usage.get("cost")
        if reported_cost is not None:
            if (
                type(reported_cost) not in {int, float}
                or not math.isfinite(reported_cost)
                or reported_cost < 0
            ):
                raise ProviderError("OpenRouter reported invalid cost; reservation remains charged")
            # Keep conservative rate accounting, but never hide a higher reported charge.
            billed = max(billed, reported_cost)

        choices = data.get("choices")
        choice = choices[0] if isinstance(choices, list) and len(choices) == 1 else {}
        if not isinstance(choice, dict):
            choice = {}
        message = choice.get("message")
        if not isinstance(message, dict):
            message = {}
        text = message.get("content")
        completed = (
            choice.get("finish_reason") == "stop"
            and not choice.get("error")
            and not message.get("refusal")
            and not message.get("tool_calls")
            and isinstance(text, str)
            and bool(text.strip())
        )
        # Return failed completions too, so usage settles before Gateway rejects them.
        return {
            "text": text if isinstance(text, str) else "",
            "model": data.get("model"),
            "usage": usage,
            "cost_usd": billed,
            "status": "completed" if completed else "incomplete",
            "generation_id": data.get("id"),
            "provider": data.get("provider"),
            "finish_reason": choice.get("finish_reason"),
        }

    async def close(self) -> None:
        await self.client.aclose()
