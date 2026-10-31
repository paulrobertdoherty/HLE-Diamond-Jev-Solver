# Running reproducible experiments

Run all commands from the repository root. Protocol files are intentionally explicit repository artifacts; this is a source-checkout harness. Python 3.11+ runs the supervisor. The controlled code sandbox uses exactly Python 3.11.16 and the pinned upstream packages.

## Installation and synthetic validation

```bash
uv sync --locked --extra api --extra dev
source .venv/bin/activate
python -m unittest discover -s tests -v
ruff check src tests
ruff format --check src tests
jev-solver --help
```

The core synthetic path uses only the standard library. Optional SDK contract tests run when the API dependencies are installed. Docker integration is opt-in. No test uses a paid model or accesses gated benchmark material.

Prepare the fixture once into a new output directory:

```bash
jev-solver prepare --fixture tests/fixtures/tasks.jsonl --output private/pilot/data
```

`solver/questions.jsonl` contains only original identifiers, question text and original image URLs or data URLs. `evaluator/labels.jsonl` contains references and reporting slices. Preparation rejects duplicate identifiers and unsupported image encodings. Directories use mode 0700 and files mode 0600. A local OS account that owns both directories can read both; deploy evaluation under a separate account or machine for a stronger administrative boundary. Models and task code have no filesystem tool to reach either directory.

## Dataset preparation

Accept the [dataset conditions](https://huggingface.co/datasets/cais/hle-diamond), install `uv sync --locked --extra api --extra data --extra dev`, and set `HF_TOKEN` in the preparation environment. Pin an exact Hugging Face commit, not a moving branch:

```bash
jev-solver prepare --revision EXACT_40_CHARACTER_DATASET_COMMIT --output private/diamond
```

Preparation downloads `cais/hle-diamond`, split `test`, expects 1,000 original IDs, and records schema, solver content, private label, and split hashes. Dataset preparation is separate from solving. Original images are preserved without OCR or conversion. A text-only run requires `--text-only` and is recorded as a subset.

To preregister an internal development split, add `--dev-count 200 --seed 17` during preparation. Stratification uses partition labels only inside preparation. Run with `--split development` while tuning, then freeze configuration and use `--split heldout`. Split membership is solver-safe; partition labels are absent from solver inputs. Independent external development data remain preferable. A complete benchmark result after development on some Diamond items is descriptive, not untouched evaluation.

Before dispatch, prepared runs verify `split.json` against the preparation manifest's split hash and require unique, disjoint membership covering every prepared question. This check also applies to full-set runs. Internal split selection requires a preparation manifest.

For independent development tasks, use `prepare --development-file private/checked-tasks.jsonl --output private/development`. Rows use the same question/answer schema as the synthetic fixture but must contain independently checked tasks. Preparation identifies them as `independent/development` and pins their content revision. Set that dataset identity and revision in a live config with `scope: independent-development`. These runs are never exported as Diamond measurements.

## Build the controlled sandbox

```bash
docker build -f protocol/Dockerfile -t jev-solver-sandbox:protocol-22ed307 .
docker image inspect --format '{{.Id}}' jev-solver-sandbox:protocol-22ed307
```

Copy the resulting `sha256:...` image identifier into the live configuration's `sandbox_image`. A repository digest `image@sha256:...` is also accepted. The base image is pinned by digest; the final image digest fixes the resolved package environment. The Docker build context allowlists only the Dockerfile and package requirements.

To run the actual isolation test, set `JEV_SANDBOX_IMAGE` to that identifier:

```bash
python -m unittest discover -s tests -p test_sandbox_integration.py -v
```

The broker verifies the actual Python and required package versions on each execution. It starts a non-root container with no network, host mounts, passed credentials, Linux capabilities or writable root filesystem. Memory, CPUs, PIDs, output and time are bounded. A small temporary filesystem is available. Cancellation removes the container and kills its descendants. The supervisor retains credentials; task code receives only its code over stdin.

## Configure and run

Copy `configs/live.template.json` to an ignored private path and replace all placeholders. Declare the exact dataset revision and evaluation scope. Use an immutable backbone model ID available to your account, verify its image and structured-output support, pin Jev's version, and set verified prices and tool charges. Reasoning effort and optional temperature are explicit adapter settings. Responses must report the same model ID that was requested; a changed model, refusal, malformed output or missing usage becomes an accounted failure.

Before a live run, explicitly set `limits.item_usd` and `limits.run_usd`. SDK retries are disabled; the supervisor owns bounded retries and counts every attempt. It reserves the complete declared token envelope before dispatch, reconciles reported usage, and retains the full reservation for uncertain failed or cancelled attempts. The limits assume the configured rates and input envelope are correct. A provider charge above its reservation records an overrun and halts new calls; it cannot reverse an already incurred charge. Invoices are not exposed by these APIs, so `cost_usd` is usage-based accounting plus conservative uncertain charges, not an invoice reconciliation. Set rates accordingly, including any search, fetch and compute charges.

Set only the solver credentials in its environment:

- `OPENAI_API_KEY` for an OpenAI backbone, or `OPENROUTER_API_KEY` for an OpenRouter backbone (both if mixing them in M).
- `TYPESAFE_API_KEY` for Jev arms or Jev selection/retrieval.
- `BRAVE_SEARCH_API_KEY` for live tool arms.

No environment files are automatically sourced. `HF_TOKEN` is only needed for preparation. `GRADER_OPENAI_API_KEY` or `GRADER_OPENROUTER_API_KEY` belongs in the evaluator environment.

```bash
jev-solver validate --config private/live.json
jev-solver estimate --config private/live.json --items 800
jev-solver run --config private/live.json --questions private/diamond/solver/questions.jsonl --split heldout --output private/heldout-j23
```

`estimate` never calls a provider. It reports call reservations and the run's dollar envelope, not a prediction of actual spend. A live run is an explicit paid job; the quickstart and CI do not launch one.

Each run has a private SQLite event store, per-item request cache, checkpoints, manifest, aggregate usage ledger and finalized predictions. The run identity freezes configuration, prompts, implementation, dependency lock, dataset scope, protocol and optional corpus hashes. Source hashes, offsets, filter versions, returned models, tokens, reasoning-token usage when reported, cache replays and outages are retained. All external requests go through the supervisor. Private exception messages are not printed into provider-error logs.

Resume after interruption with the same command arguments and the `resume` operation:

```bash
jev-solver resume --config private/live.json --questions private/diamond/solver/questions.jsonl --split heldout --output private/heldout-j23
```

A run lock prevents simultaneous writers. Finalized items are never solved again; partial items deterministically replay cached calls and reapply filtering. An in-flight request interrupted before its response is durably cached may need another attempt; its original maximum charge remains in the budget. Deadlines start at the first attempt and include downtime. Changed inputs, code, dependencies or policies require a new run directory. Completed errors and abstentions remain part of the declared evaluation set.

### OpenRouter models

Install the existing API and dataset extras, prepare HLE-Diamond as described above, and make a private configuration:

```bash
uv sync --locked --extra api --extra data --extra dev
source .venv/bin/activate
mkdir -p private
cp configs/openrouter.template.json private/openrouter.json
read -rsp 'OpenRouter API key: ' OPENROUTER_API_KEY
export OPENROUTER_API_KEY
```

Edit `private/openrouter.json` before running:

- Set `provider.model` to an explicit OpenRouter `author/model` ID. Open source and preview models are accepted without OpenAI's dated-snapshot rule. Auto/free routers, presets and `:online` web variants are rejected; a specific model's `:free` variant is allowed. The returned model ID must match the configured ID; use the canonical ID if an alias returns a different name.
- Set `input_per_million` and `output_per_million` to verified USD rates per million tokens. Both fields are required; zero is allowed for free endpoints. These rates also set OpenRouter's provider price ceilings. Template rates are illustrative.
- Set token limits and `vision` for the model. The model and its host must support strict JSON Schema output (`structured_output: true`). The adapter requires parameter support rather than silently dropping schema constraints. For a text-only model, prepare with `--text-only`, set `vision: false`, and declare the subset in `scope`.
- Leave `reasoning_effort` as `""` to use the model's default, or set a supported effort such as `"low"`, `"medium"` or `"high"`. Unsupported settings fail at the API. Optional `temperature` is omitted unless configured. Reasoning tokens count toward output usage; allow enough output tokens for reasoning and the final JSON.
- For long reasoning requests, increase `provider.request_timeout_s` (default 120 seconds) along with `limits.deadline_s`. The request timeout controls HTTP inactivity; the item deadline bounds the whole solve including retries.
- Optionally set `openrouter_provider` to a host slug from the model's OpenRouter page to restrict requests to that host with fallbacks disabled. An empty string allows OpenRouter to route among hosts of the same model within your price ceilings. The responding host and generation ID are saved in private traces.
- Replace `dataset_revision` with the exact prepared commit and declare `scope`. Keep explicit item/run dollar caps appropriate for your pilot.

The template uses B0, so only `OPENROUTER_API_KEY` is needed during solving. B1 also requires no Jev, search key or sandbox. B2 adds Brave search and the pinned Docker sandbox; Jev arms additionally need `TYPESAFE_API_KEY`. You can use OpenRouter in the main `provider` and in M's `additional_providers`, including alongside direct OpenAI models.

With the dataset already prepared in `private/diamond`:

```bash
jev-solver validate --config private/openrouter.json
jev-solver estimate --config private/openrouter.json --items 1000
jev-solver run --config private/openrouter.json --questions private/diamond/solver/questions.jsonl --output private/openrouter-model-a
```

For another model, change the model, rates, token limits and capabilities, and choose a new run directory. Resume always requires the original configuration. Model slugs can change upstream even when their names stay the same; freeze versioned models and host settings where available for reported comparisons. Validation and estimation are offline and do not verify account access or model capabilities.

The adapter sends no native tools and explicitly disables web search, response healing, context compression and other output-changing plugins. Account or organization settings that prevent plugin overrides must also leave these disabled for controlled comparisons. It preserves original images, requests strict structured output, excludes reasoning text from returned artifacts, and rejects truncation, refusals, tool calls and changed models. Usage is settled before these completion failures are rejected. Missing or invalid usage retains the full reservation; transport failures use the supervisor's bounded retries. Accounting uses the larger of the configured token-rate estimate and OpenRouter's reported cost when present, so a higher reported charge triggers the existing overrun stop. This is conservative accounting, not invoice reconciliation.

Live grading supports `provider.kind: openai` or `openrouter` in a separate grader configuration. Set `GRADER_OPENAI_API_KEY` or `GRADER_OPENROUTER_API_KEY`, respectively, in the evaluator environment. The grader never implicitly reads solver credential variables. OpenRouter grading sends question text, reference answers and saved responses to the chosen external judge; authorize that disclosure before running it. Use the same provider fields, explicit prices and budget limits as other live configurations.

API contract references: [Chat Completions](https://openrouter.ai/docs/api/reference/overview), [structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs), [provider selection and price ceilings](https://openrouter.ai/docs/guides/routing/provider-selection), and [reasoning tokens](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens).

For an accuracy-first GPT-6 Astra B0 run, `configs/astra.openrouter.template.json` sets `openai/gpt-6-astra`, `max` effort, 128,000 output tokens, image support, no temperature override, a one-hour HTTP timeout and a 7,500-second item deadline. Input is bounded to 65,536 tokens, comfortably below the model's long-context price threshold. Same-model host routing stays enabled for availability. This is a suggested starting configuration, not a measured optimum on HLE-Diamond. It uses standard execution; the Chat Completions adapter does not configure OpenAI's Responses-only pro mode.

Prices checked on 2026-10-30: $10/M input and $50/M output, from [OpenRouter's model page](https://openrouter.ai/openai/gpt-6-astra); [official OpenAI documentation](https://developers.openai.com/api/docs/models/gpt-6-astra) confirms `max` effort and the 128,000 output limit. At those configured rates the harness reserves $7.05536 per attempt. The template's $16/item and $16,000/run caps accommodate 1,000 questions and one retry per item; these are conservative caps, not expected spend, and exclude separate grading. Copy to an ignored private path and set the dataset revision, scope and a budget you intend to use before running. A pilot should use a separately prepared development split and its own run directory/cap; do not report a full-set score from a run whose cap prevents finishing items. Compare `xhigh` and `max` on development data before freezing held-out settings.

## Grading and paired analysis

Move finalized predictions and their manifest to the evaluator environment, with reference storage unavailable to solver tools. Copy and configure `configs/grader.template.json`, with a separately pinned grader and explicit evaluator budgets. Set `GRADER_OPENAI_API_KEY` there for direct OpenAI grading. For OpenRouter, set `provider.kind: openrouter`, an explicit `author/model` ID and verified prices, and provide `GRADER_OPENROUTER_API_KEY`. Grading reads the official prompt literal from the hash-pinned upstream file without importing its executable code, and adapts the official structured grading fields to OpenAI Responses or OpenRouter Chat Completions. The solver system prompt is not used for grading. This is a documented custom transport adaptation, not the upstream CLI.

```bash
jev-solver grade --run private/heldout-j23 --labels private/diamond/evaluator/labels.jsonl --grader-config private/grader.json --output private/evaluation-j23 --oracle
```

Grading validates durable finalization, complete declared-ID coverage, prediction integrity and reference preparation hashes before joining labels. Solver failures and abstentions count as incorrect. Grader failures also remain in the denominator and are explicitly counted; rerun `grade` with the same inputs to retry unfinished grading within the original budget. `--oracle` also grades saved candidate answers offline, including candidates retained from budget failures, timeouts and solver errors. Failed final predictions still count as incorrect. Those results are never sent into inference.

For an explicitly requested single-question retest, `run` and `resume` accept repeatable `--question-id ORIGINAL_ID` arguments. Selection is restricted to the declared `--split`, and the selected question hash and IDs are frozen into the new run identity. Use a new output directory and declare the retest scope. Keep the original finalized predictions and grades; report an original score separately from any score with a retest substituted. Finish retesting before exposing reference labels to the evaluator.

Use identical grader configuration and evaluation membership for all arms. The same-model sampling baseline uses independent calls and deterministic voting. Fixed tool arms share workflow settings, and J2/J3 toggle only their respective judgments. Jfull and M have explicit additional samples and decisions, so compare their total spend as well as equal workload. The M adapter supports multiple OpenAI and/or OpenRouter model configurations under the same shared budget.

```bash
jev-solver compare --arm-a private/evaluation-j23/grades.json --arm-b private/evaluation-b2/grades.json --output private/comparison.json
jev-solver export --grades private/evaluation-j23/grades.json --output reports/j23
```

Multiple files after `--arm-a` and `--arm-b` represent repeated runs. Bootstrap resampling clusters by question; exact McNemar testing is reported only for one trial per item. Missing paired IDs are an error. Reports retain errors, timeouts, abstentions, cost, latency tails, Brier score, reliability bins, coverage and available slices. Primary comparisons and cost settings must be preregistered; exploratory comparisons need suitable multiplicity handling. The power estimate is an unadjusted normal approximation from pilot discordance, not a claim that a small pilot proves a small gain.

Exports contain aggregate JSON, Markdown and an SVG reliability plot. Private question IDs, source text, arbitrary slice labels, verification text and candidate answers are excluded. Audit exports before publication. `compare` output is a private analysis artifact; `export` is the publication boundary.

## Evidence diagnostics and optional retrieval

Evaluate J2 and J3 on identical frozen development evidence before interpreting end-to-end differences:

```bash
jev-solver component-eval --config configs/synthetic.json --cases tests/fixtures/components.jsonl --output private/components-jev --judge jev
jev-solver component-eval --config configs/synthetic.json --cases tests/fixtures/components.jsonl --output private/components-lexical --judge lexical
```

`--judge backbone` enables a generative verifier baseline with its charged calls. Component rows have `id`, `stage`, `state` and `expected`. Expected labels stay outside provider requests. J2 scores use a normalized 0–1 feature; they are not correctness probabilities. Noul has no separate confidence. The deliberately limited synthetic semantic judge fails the negative citation fixture, demonstrating that diagnostics report negative results too.

For an optional extended-track corpus, supply vetted JSONL documents with exactly `url`, `title`, `text`, `license`, and `ingested_at`:

```bash
jev-solver corpus-build --documents private/vetted-documents.jsonl --revision reference-v1 --output private/corpus.json
```

The corpus is filtered, immutable by hash, and records provenance, licensing, ingestion dates, chunking and feature-model versions. Set `track: extended`, a corpus path, and `retrieval: lexical`, `hybrid`, or `hybrid-jev`. Hybrid is BM25 plus fixed hashed character vectors and reciprocal-rank fusion, not a learned embedding system. Corpus screening must independently exclude question/answer mirrors and paraphrases. A blocklist alone cannot establish corpus independence. Do not promote a retrieval extension without independently labeled recall and end-to-end evidence.

## Contamination and experimental gates

The audited wrappers apply the pinned upstream rules to queries, domains, prefixes, snippets, titles, redirect chains, decoded proxy links, fetched content and cache hits. Long copied question spans are refused. Search returns at most 20 backend results before filtering. Fetch checks the full parsed content before a 60,000-character output cap and records truncation. Source bytes are bounded separately. Public-address validation and connection to the validated IP prevent direct private-network access and DNS rebinding.

Create an audit, or add privately discovered exposure flags using a JSON list of declared question IDs:

```bash
jev-solver audit --run private/heldout-j23 --flags private/exposed-ids.json
```

Flags accumulate and are included in later grading. All-item metrics retain exposed items; publication exports add a separately labeled clean sensitivity analysis. The audit does not silently overwrite predictions, erase flags or claim a repaired result. Repair and repin the filter, start a fresh run with fresh state under the preregistered rerun policy, and retain both run identities. Link and count such reruns in the publication record; automatic cross-run contamination adjudication is deliberately absent.

Phases requiring credentials, independent evidence labels, blinded grading review or actual held-out measurements remain research gates. Freeze policies before held-out evaluation and report measured results even when Jev hurts accuracy. Confidence uses the backbone's declared probability; no calibration mapping is fitted to held-out labels. A persistent semantic corpus, a new provider protocol or a learned calibration mapping should be introduced only as a separately declared, validated extension.
