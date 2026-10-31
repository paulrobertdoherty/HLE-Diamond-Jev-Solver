import importlib.util
import json
import os
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from jev_solver.benchmarks.data import prepare
from jev_solver.config import Config, ProviderConfig
from jev_solver.controller.budget import Budget, BudgetExceeded
from jev_solver.controller.engine import run
from jev_solver.evaluation.grading import finalized_predictions, grade
from jev_solver.models import QuestionView, digest
from jev_solver.providers.backbone import CANDIDATE_SCHEMA, Gateway, ProviderError, make_backbone
from jev_solver.providers.openrouter import OpenRouterBackbone
from jev_solver.tracing.store import Store


def provider(**kwargs):
    return replace(
        ProviderConfig(
            kind="openrouter",
            model="qwen/qwen3-235b-a22b-2507",
            input_per_million=1,
            output_per_million=2,
            reasoning_effort="",
        ),
        **kwargs,
    )


def config(**kwargs):
    return replace(
        Config(
            arm="B0",
            track="closed",
            dataset="cais/hle-diamond",
            dataset_revision="a" * 40,
            scope="full benchmark",
            provider=provider(),
        ),
        **kwargs,
    )


class OpenRouterConfigTests(unittest.TestCase):
    def test_model_slugs_and_free_models_do_not_require_openai_snapshots(self):
        for model in (
            "qwen/qwen3-235b-a22b-2507",
            "meta-llama/llama-3.3-70b-instruct:free",
            "google/gemini-model-preview",
        ):
            with self.subTest(model=model):
                config(provider=provider(model=model)).validate()
        config(provider=provider(input_per_million=0, output_per_million=0)).validate()
        config(provider=provider(openrouter_provider="google-vertex/us-east5")).validate()

    def test_invalid_model_routing_and_capabilities_rejected(self):
        for p in (
            provider(model="<AUTHOR/MODEL>"),
            provider(model="llama"),
            provider(model="openrouter/auto"),
            provider(model="openrouter/free"),
            provider(model="qwen/model:online"),
            provider(model="@preset/something"),
            provider(model="qwen/model\n"),
            provider(structured_output=False),
            provider(reasoning_effort="guess"),
            provider(openrouter_provider="bad slug"),
            provider(input_per_million=-1),
            provider(output_per_million=float("nan")),
            provider(request_timeout_s=0),
            provider(request_timeout_s=float("inf")),
            provider(request_timeout_s=True),
        ):
            with self.subTest(provider=p), self.assertRaises(ValueError):
                config(provider=p).validate()

    def test_openai_snapshot_requirement_preserved(self):
        with self.assertRaisesRegex(ValueError, "dated model snapshot"):
            config(provider=provider(kind="openai", model="gpt-5")).validate()
        with self.assertRaisesRegex(ValueError, "openrouter_provider"):
            config(provider=provider(kind="mock", openrouter_provider="host")).validate()

    def test_explicit_prices_and_caps_required_on_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            row = asdict(config())
            for key in ("input_per_million", "output_per_million"):
                invalid = asdict(config())
                del invalid["provider"][key]
                path.write_text(json.dumps(invalid))
                with self.assertRaisesRegex(ValueError, "explicit prices"):
                    Config.load(path)
            row["limits"].pop("run_usd")
            path.write_text(json.dumps(row))
            with self.assertRaisesRegex(ValueError, "dollar caps"):
                Config.load(path)
            path.write_text(json.dumps(asdict(config())))
            Config.load(path)
        with self.assertRaises(ValueError):
            Config.load("configs/openrouter.template.json")

    def test_mixed_openai_and_openrouter_backbones(self):
        cfg = config(
            arm="M",
            track="controlled",
            additional_providers=(provider(kind="openai", model="gpt-5-2025-08-07"),),
            jev=ProviderConfig(kind="typesafe", model="jev-1.14.0", input_per_million=0.042),
            search_backend="brave",
            sandbox_image="sha256:" + "b" * 64,
        )
        cfg.validate()
        with self.assertRaisesRegex(ValueError, "structured responses"):
            replace(cfg, additional_providers=(provider(structured_output=False),)).validate()


@unittest.skipUnless(importlib.util.find_spec("httpx"), "optional HTTPX not installed")
class OpenRouterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import httpx

        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "events.sqlite3")
        self.cfg = config()
        self.budget = Budget(self.store, self.cfg)
        self.requests = []
        self.http_status = 200
        self.error = None
        self.candidate = {
            "answer": "42",
            "confidence": 0.9,
            "verification": "Arithmetic.",
            "gaps": [],
            "queries": [],
            "code": "",
            "citations": [],
        }
        self.data = {
            "id": "gen-test",
            "model": self.cfg.provider.model,
            "provider": "Example Host",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(self.candidate),
                        "reasoning": "private reasoning must not be persisted",
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "completion_tokens_details": {"reasoning_tokens": 10},
                "prompt_tokens_details": {"cached_tokens": 30},
                "cost": 0.0001,
            },
        }

        def handler(request):
            self.requests.append(request)
            if self.error:
                raise self.error
            return httpx.Response(self.http_status, json=self.data)

        self.client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1/", transport=httpx.MockTransport(handler)
        )
        self.backbone = OpenRouterBackbone(self.cfg.provider, self.client)
        self.gateway = Gateway(self.cfg, self.store, self.budget)
        self.gateway.clients[digest(asdict(self.cfg.provider))] = self.backbone

    async def asyncTearDown(self):
        await self.gateway.close()
        self.store.close()
        self.tmp.cleanup()

    async def test_request_preserves_images_schema_and_audited_tool_boundary(self):
        images = ("https://example.com/image.png", "data:image/png;base64,ORIGINAL")
        result = await self.backbone.generate(
            QuestionView("q", "question", images), {"evidence": []}, CANDIDATE_SCHEMA
        )
        self.assertEqual(str(self.requests[0].url), "https://openrouter.ai/api/v1/chat/completions")
        request = json.loads(self.requests[0].content)
        self.assertEqual(request["model"], self.cfg.provider.model)
        self.assertEqual(request["max_tokens"], self.cfg.provider.max_output_tokens)
        self.assertFalse(request["stream"])
        self.assertEqual(
            [part["image_url"]["url"] for part in request["messages"][1]["content"][2:]],
            list(images),
        )
        self.assertEqual(request["response_format"]["json_schema"]["schema"], CANDIDATE_SCHEMA)
        self.assertTrue(request["response_format"]["json_schema"]["strict"])
        self.assertTrue(request["provider"]["require_parameters"])
        self.assertEqual(request["provider"]["max_price"], {"prompt": 1, "completion": 2})
        self.assertNotIn("models", request)
        self.assertNotIn("tools", request)
        self.assertNotIn("temperature", request)
        self.assertEqual(request["reasoning"], {"exclude": True})
        self.assertTrue(all(plugin["enabled"] is False for plugin in request["plugins"]))
        self.assertEqual(request["transforms"], [])
        self.assertEqual(result["usage"]["output_tokens_details"], {"reasoning_tokens": 10})
        self.assertEqual(result["usage"]["input_tokens_details"], {"cached_tokens": 30})
        self.assertEqual(result["usage"]["input_tokens"], 100)
        self.assertEqual(result["cost_usd"], 0.00014)
        self.assertNotIn("private reasoning", json.dumps(result))
        self.assertEqual(result["provider"], "Example Host")

    async def test_optional_host_reasoning_and_temperature(self):
        self.backbone.config = provider(
            openrouter_provider="fireworks", reasoning_effort="high", temperature=0
        )
        await self.backbone.generate(QuestionView("q", "question"), {}, CANDIDATE_SCHEMA)
        request = json.loads(self.requests[0].content)
        self.assertEqual(request["provider"]["only"], ["fireworks"])
        self.assertFalse(request["provider"]["allow_fallbacks"])
        self.assertEqual(request["reasoning"], {"exclude": True, "effort": "high"})
        self.assertEqual(request["temperature"], 0)

    async def test_credential_and_url_are_separate_from_openai_environment(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "unrelated"}, clear=True):
            with self.assertRaisesRegex(ValueError, "OPENROUTER_API_KEY"):
                make_backbone(self.cfg.provider)
        with (
            patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=True),
            patch("httpx.AsyncClient", return_value=self.client) as client,
        ):
            self.assertIsInstance(
                make_backbone(replace(self.cfg.provider, request_timeout_s=3600)),
                OpenRouterBackbone,
            )
            self.assertEqual(client.call_args.kwargs["headers"]["Authorization"], "Bearer test-key")
            self.assertEqual(client.call_args.kwargs["base_url"], "https://openrouter.ai/api/v1/")
            self.assertFalse(client.call_args.kwargs["follow_redirects"])
            self.assertEqual(client.call_args.kwargs["timeout"], 3600)

    async def test_gateway_accounts_and_caches_only_complete_answers(self):
        q = QuestionView("q", "question")
        self.assertEqual(await self.gateway.generate(q, {}, "initial"), self.candidate)
        self.assertEqual(await self.gateway.generate(q, {}, "initial"), self.candidate)
        self.assertEqual(len(self.requests), 1)
        self.assertAlmostEqual(self.store.cost(), 0.00014)
        await self.gateway.generate(q, {}, "revision")
        self.assertEqual(len(self.requests), 2)

    async def test_incomplete_refused_tool_and_changed_model_responses_are_charged(self):
        for i, (field, value) in enumerate(
            (
                ("finish_reason", "length"),
                ("refusal", "no"),
                ("tool_calls", [{}]),
                ("model", "other/model"),
            )
        ):
            with self.subTest(field=field):
                if field == "model":
                    self.data[field] = value
                elif field == "finish_reason":
                    self.data["choices"][0][field] = value
                else:
                    self.data["choices"][0]["message"][field] = value
                with self.assertRaises(ProviderError):
                    await self.gateway.generate(QuestionView(str(i), "question"), {}, "initial")
                self.assertAlmostEqual(self.store.cost(str(i)), 0.00014)
                self.data["model"] = self.cfg.provider.model
                self.data["choices"][0]["finish_reason"] = "stop"
                self.data["choices"][0]["message"].pop("refusal", None)
                self.data["choices"][0]["message"].pop("tool_calls", None)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM cache").fetchone()[0], 0)

    async def test_malformed_answer_is_charged_but_not_cached(self):
        self.data["choices"][0]["message"]["content"] = "not JSON"
        with self.assertRaises(json.JSONDecodeError):
            await self.gateway.generate(QuestionView("q", "question"), {}, "initial")
        self.assertAlmostEqual(self.store.cost(), 0.00014)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM cache").fetchone()[0], 0)

    async def test_invalid_usage_keeps_full_reservation(self):
        for i, usage in enumerate((None, {}, {"prompt_tokens": True, "completion_tokens": 1})):
            self.data["usage"] = usage
            with self.subTest(usage=usage), self.assertRaises((ValueError, ProviderError)):
                await self.gateway.generate(QuestionView(str(i), "question"), {}, "initial")
            self.assertAlmostEqual(self.store.cost(str(i)), 0.073728)

    async def test_reported_cost_above_reservation_halts_calls(self):
        self.data["usage"]["cost"] = 0.1
        with self.assertRaisesRegex(BudgetExceeded, "above declared maximum"):
            await self.gateway.generate(QuestionView("q", "question"), {}, "initial")
        self.assertAlmostEqual(self.store.cost(), 0.1)
        with self.assertRaisesRegex(BudgetExceeded, "halted"):
            await self.gateway.generate(QuestionView("r", "question"), {}, "initial")
        self.assertEqual(len(self.requests), 1)

    async def test_missing_cost_uses_rates_and_invalid_cost_is_rejected(self):
        self.data["usage"].pop("cost")
        result = await self.backbone.generate(QuestionView("q", "question"), {}, CANDIDATE_SCHEMA)
        self.assertAlmostEqual(result["cost_usd"], 0.00014)
        for value in (True, -1, "0.1"):
            self.data["usage"]["cost"] = value
            with self.subTest(cost=value), self.assertRaisesRegex(ProviderError, "invalid cost"):
                await self.backbone.generate(QuestionView("q", "question"), {}, CANDIDATE_SCHEMA)

    async def test_errors_redact_private_bodies_and_classify_retries(self):
        for status in (400, 401, 402, 403, 408, 429, 500, 503):
            with self.subTest(status=status):
                self.http_status = status
                self.data = {"error": {"message": "secret key and question"}}
                with self.assertRaises(ProviderError) as caught:
                    await self.backbone.generate(
                        QuestionView("q", "question"), {}, CANDIDATE_SCHEMA
                    )
                self.assertEqual(caught.exception.retryable, status in {408, 429, 500, 503})
                self.assertNotIn("secret", str(caught.exception))
        self.http_status = 200
        self.data = {"error": {"code": 503, "message": "secret"}}
        with self.assertRaises(ProviderError) as caught:
            await self.backbone.generate(QuestionView("q", "question"), {}, CANDIDATE_SCHEMA)
        self.assertTrue(caught.exception.retryable)
        self.assertNotIn("secret", str(caught.exception))

    async def test_transport_error_is_retryable_without_leaking_details(self):
        import httpx

        self.error = httpx.ReadTimeout("secret")
        with self.assertRaises(ProviderError) as caught:
            await self.backbone.generate(QuestionView("q", "question"), {}, CANDIDATE_SCHEMA)
        self.assertTrue(caught.exception.retryable)
        self.assertNotIn("secret", str(caught.exception))

    async def test_baseline_run_and_resume_without_jev_or_other_credentials(self):
        prepared = prepare(
            self.root / "data", "", Path("tests/fixtures/tasks.jsonl"), development=True
        )
        cfg = replace(
            self.cfg,
            dataset=prepared["dataset"],
            dataset_revision=prepared["revision"],
            scope="independent-development",
        )
        with (
            patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=True),
            patch("httpx.AsyncClient", return_value=self.client),
        ):
            await run(cfg, self.root / "data/solver/questions.jsonl", self.root / "run")
            manifest, predictions = finalized_predictions(self.root / "run")
            self.assertFalse(manifest["synthetic"])
            self.assertEqual(len(predictions), 4)
            self.assertTrue(all(p["status"] == "completed" for p in predictions))
            self.assertEqual(len(self.requests), 4)
            await run(
                cfg, self.root / "data/solver/questions.jsonl", self.root / "run", resume=True
            )
            self.assertEqual(len(self.requests), 4)

    async def test_isolated_grader_uses_explicit_key_prompt_schema_and_cache(self):
        import httpx

        prepared = prepare(
            self.root / "data", "", Path("tests/fixtures/tasks.jsonl"), development=True
        )
        cfg = replace(
            self.cfg,
            dataset=prepared["dataset"],
            dataset_revision=prepared["revision"],
            scope="independent-development",
        )
        with (
            patch.dict(os.environ, {"OPENROUTER_API_KEY": "solver-key"}, clear=True),
            patch("httpx.AsyncClient", return_value=self.client),
        ):
            await run(cfg, self.root / "data/solver/questions.jsonl", self.root / "run")
            with self.assertRaisesRegex(ValueError, "GRADER_OPENROUTER_API_KEY"):
                await grade(
                    self.root / "run",
                    self.root / "data/evaluator/labels.jsonl",
                    self.root / "evaluation",
                    cfg,
                )
        self.requests.clear()
        grader = replace(cfg, provider=provider(model="openai/gpt-6-astra"))
        self.data["model"] = grader.provider.model
        self.data["choices"][0]["message"]["content"] = json.dumps(
            {
                "extracted_final_answer": "42",
                "reasoning": "Matches the supplied reference.",
                "correct": "yes",
                "confidence": 90,
                "strict": True,
            }
        )

        def handler(request):
            self.requests.append(request)
            return httpx.Response(200, json=self.data)

        client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1/", transport=httpx.MockTransport(handler)
        )
        with (
            patch.dict(os.environ, {"GRADER_OPENROUTER_API_KEY": "grader-key"}, clear=True),
            patch("httpx.AsyncClient", return_value=client) as factory,
        ):
            result = await grade(
                self.root / "run",
                self.root / "data/evaluator/labels.jsonl",
                self.root / "evaluation",
                grader,
            )
            self.assertEqual(result["correct"], 4)
            self.assertEqual(result["grader_errors"], 0)
            self.assertEqual(
                factory.call_args.kwargs["headers"]["Authorization"], "Bearer grader-key"
            )
            self.assertEqual(len(self.requests), 4)
            request = json.loads(self.requests[0].content)
            self.assertEqual(len(request["messages"]), 1)
            self.assertEqual(request["messages"][0]["role"], "user")
            self.assertEqual(request["response_format"]["json_schema"]["name"], "official_grade")
            await grade(
                self.root / "run",
                self.root / "data/evaluator/labels.jsonl",
                self.root / "evaluation",
                grader,
            )
            self.assertEqual(len(self.requests), 4)


if __name__ == "__main__":
    unittest.main()
