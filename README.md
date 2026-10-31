# HLE-Diamond Jev Solver

An asynchronous Python research harness for testing whether Jev improves evidence handling beyond the same reasoning model with audited web and code tools. The research rationale and experimental gates are in [PLAN.md](PLAN.md).

**Status:** implemented and tested with synthetic tasks, mocked provider responses, and an isolated Docker sandbox. A private 50-question development pilot also completed: Sol low B0 scored 22/50 (44%), and a budget-limited J23 pipeline with Jev scored 16/50 (32%), using automatic Astra reference grading. These exploratory results do not establish a Jev benefit. Adaptive policies and retrieval extensions remain experimental.

## Run the offline example

Use Python 3.11 or newer and run commands from this repository's root. [uv](https://docs.astral.sh/uv/) installs the project and the locked optional SDK and development dependencies:

```bash
uv sync --locked --extra api --extra dev
source .venv/bin/activate
jev-solver validate --config configs/synthetic.json
jev-solver prepare --fixture tests/fixtures/tasks.jsonl --output private/demo/data
jev-solver estimate --config configs/synthetic.json --items 4
jev-solver run --config configs/synthetic.json --questions private/demo/data/solver/questions.jsonl --output private/demo/j23
jev-solver grade --run private/demo/j23 --labels private/demo/data/evaluator/labels.jsonl --output private/demo/evaluation --oracle
jev-solver export --grades private/demo/evaluation/grades.json --output reports/demo
```

The synthetic provider uses arithmetic and a fictional reference, with no credentials or external requests. Its code tool returns a clearly marked fixture result. Public report exports contain aggregate metrics and a standalone reliability plot. All question-bearing artifacts stay under ignored private directories.

## Implemented experiments

| Arm | Behavior |
| --- | --- |
| B0 | One backbone call, no tools |
| B1 | Independent same-model samples and conservative answer voting, no tools |
| B2 | Fixed search/code/revision workflow, lexical passage ranking and exact citation spans |
| J2 / J3 / J23 | B2 with Jev reranking / citation support checks / both |
| Jfull | Independent candidates, admissible routing, constraint checks, candidate selection and bounded continuation |
| M | Independent configured OpenAI/OpenRouter models under one shared budget |
| R | Extended track with a licensed frozen corpus and lexical or hybrid retrieval |

Each arm has a synthetic configuration in `configs/`. Live backbones support OpenAI's Responses API and OpenRouter's Chat Completions API, including open source models with structured-output support. Jev uses `typesafe-sdk`'s `AsyncTypeSafeClient`. Direct Anthropic integration is not included; supported Anthropic models can be used through OpenRouter.

The optional hybrid retrieval baseline fuses BM25 with deterministic hashed character features. It does not use learned semantic embeddings. It is labeled as an extended-track experiment and must pass retrieval diagnostics before promotion.

## Live runs and reproducibility

[The runbook](docs/RUNBOOK.md) covers authenticated dataset preparation, model and protocol pins, explicit dollar caps, sandbox construction, resume, isolated grading, paired comparisons, component diagnostics and contamination audits. [The implementation notes](docs/IMPLEMENTATION.md) map the plan to code and describe limits and acceptance gates that require real experiments.

`configs/live.template.json` and `configs/grader.template.json` intentionally fail validation until their placeholders are replaced. Example prices are illustrative. Set verified model IDs, capabilities and rates for your account, an exact dataset commit, and a sandbox image digest before launching a paid job. Credentials are read from environment variables; `.env.example` lists the names. Environment files are never loaded automatically.

The upstream tool protocol, blocklist, package requirements and grading source are pinned at commit `22ed3074b1e7b134bcbc09028d0ba320839b0655`; file hashes are verified before runs. This is an independent custom harness, not an official leaderboard submission.

For OpenRouter, copy [`configs/openrouter.template.json`](configs/openrouter.template.json) to `private/openrouter.json`, fill in the model ID, dataset revision, scope, capabilities and prices, and export `OPENROUTER_API_KEY`. The template runs B0 (one model call per question), which needs no Jev account, search key or Docker sandbox. Switch models by changing `provider.model` and its prices/capabilities, then use a new output directory. See [OpenRouter setup](docs/RUNBOOK.md#openrouter-models) for commands and provider options. Dataset preparation still requires `HF_TOKEN`; live grading supports OpenAI and OpenRouter with explicit evaluator credentials.

For a $27 account balance, the [Sol low pilot](docs/SOL_PILOT.md) provides a pinned configuration for a 50-question B0 development run with a $20 cap and no retries.

## Checks

```bash
python -m unittest discover -s tests -v
ruff check src tests
ruff format --check src tests
```

The Docker integration test is enabled by setting `JEV_SANDBOX_IMAGE` to the digest of a locally built protocol image. CI runs synthetic and mocked API checks without credentials; paid benchmark evaluations are launched explicitly.

Original code is MIT licensed. Vendored upstream files retain their own [license](protocol/upstream/LICENSE) and [source manifest](protocol/manifest.json). Do not commit credentials, benchmark questions or labels, retrieved caches, or private traces.
