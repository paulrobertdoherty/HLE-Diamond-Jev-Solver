# HLE-Diamond Jev Solver

An asynchronous Python research harness for testing whether Jev improves evidence handling beyond the same reasoning model with audited web and code tools. The research rationale and experimental gates are in [PLAN.md](PLAN.md).

**Status:** implemented and tested with synthetic tasks, mocked provider responses, and an isolated Docker sandbox. No paid model calls, gated benchmark downloads, or HLE-Diamond accuracy measurements have been performed. Adaptive policies and retrieval extensions are experimental; their existence does not establish a benefit.

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
| M | Independent configured OpenAI model variants under one shared budget |
| R | Extended track with a licensed frozen corpus and lexical or hybrid retrieval |

Each arm has a synthetic configuration in `configs/`. The live generative adapter uses OpenAI's Responses API; Jev uses `typesafe-sdk`'s `AsyncTypeSafeClient`. Additional provider protocols can implement the `Backbone` contract. Anthropic integration is not included.

The optional hybrid retrieval baseline fuses BM25 with deterministic hashed character features. It does not use learned semantic embeddings. It is labeled as an extended-track experiment and must pass retrieval diagnostics before promotion.

## Live runs and reproducibility

[The runbook](docs/RUNBOOK.md) covers authenticated dataset preparation, model and protocol pins, explicit dollar caps, sandbox construction, resume, isolated grading, paired comparisons, component diagnostics and contamination audits. [The implementation notes](docs/IMPLEMENTATION.md) map the plan to code and describe limits and acceptance gates that require real experiments.

`configs/live.template.json` and `configs/grader.template.json` intentionally fail validation until their placeholders are replaced. Example prices are illustrative. Set verified model IDs, capabilities and rates for your account, an exact dataset commit, and a sandbox image digest before launching a paid job. Credentials are read from environment variables; `.env.example` lists the names. Environment files are never loaded automatically.

The upstream tool protocol, blocklist, package requirements and grading source are pinned at commit `22ed3074b1e7b134bcbc09028d0ba320839b0655`; file hashes are verified before runs. This is an independent custom harness, not an official leaderboard submission.

## Checks

```bash
python -m unittest discover -s tests -v
ruff check src tests
ruff format --check src tests
```

The Docker integration test is enabled by setting `JEV_SANDBOX_IMAGE` to the digest of a locally built protocol image. CI runs synthetic and mocked API checks without credentials; paid benchmark evaluations are launched explicitly.

Original code is MIT licensed. Vendored upstream files retain their own [license](protocol/upstream/LICENSE) and [source manifest](protocol/manifest.json). Do not commit credentials, benchmark questions or labels, retrieved caches, or private traces.
