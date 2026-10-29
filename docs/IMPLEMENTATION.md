# Implementation and research gates

The architecture is an explicit asynchronous state machine with typed records and private local artifacts. Implementation enables experiments; acceptance gates that depend on dataset access, account capabilities, calibrated prompts, external labels or measured improvements are not asserted as complete.

| Plan area | Implementation |
| --- | --- |
| Benchmark preparation and isolation | `benchmarks/data.py`: authenticated revision-pinned preparation; strict solver allowlist; original images and IDs; content/schema hashes; local stratified splits |
| Provider boundaries | `providers/backbone.py`: OpenAI Responses and synthetic adapters, explicit capabilities, structured candidate validation, returned-model and usage checks |
| Jev contracts | `providers/jev.py`, `judgments/pipeline.py`: typed SDK Choice/Noul/Score, normalized ordered scores, local state, exact spans before support judgments, explicit outages and baseline fallback |
| Controller and accounting | `controller/engine.py`, `controller/budget.py`: bounded phases, independent candidates, global concurrency, monetary reservations, retries, cancellation and finalization |
| Durable events and resume | `tracing/store.py`: SQLite WAL and durable transactions; item-scoped complete-request caches; immutable run identities and idempotent finalization |
| Audited external information | `tools/policy.py`, `tools/web.py`: pinned rule enforcement before exposure, result caps, decoded bypass and redirect checks, public-IP connections, cache revalidation, source audit |
| Isolated code | `tools/sandbox.py`, `protocol/Dockerfile`: version-checked, digest-pinned, non-root Docker execution with bounded resources and no network, host mounts or passed keys |
| Retrieval and provenance | `retrieval/evidence.py`: source hashes and offsets, lexical shortlist, compact diverse packets; `retrieval/corpus.py`: optional licensed frozen corpus and deterministic hybrid baseline |
| Candidate generation and selection | `candidates/selection.py`: independent samples, conservative equality clusters, voting, generative verifier and anonymized Jev selection including none-supported |
| Separate evaluation | `evaluation/grading.py`: finalized-prediction checks, separate grader key and budgets, upstream prompt/schema adaptation and optional offline candidate oracle |
| Paired statistics | `evaluation/analysis.py`: full-set metrics, clustered bootstrap intervals, exact McNemar, power approximation, Brier/reliability and coverage |
| Component experiments | `evaluation/components.py`: frozen J2/J3 cases against Jev, a lexical/quote baseline or a generative model, with labeled development expectations excluded from requests |
| Publication boundary | `evaluation/export.py`: aggregate allowlist, restricted slice identities, cost/latency/calibration metrics, Markdown and standalone SVG |
| Contamination review | `tracing/audit.py`: blocked/replayed call counts, cumulative private exposure flags, retained all-item outcomes and separate sensitivity analysis |
| Operations | `cli.py`: validate, prepare, estimate, run, resume, grade, compare, export, audit, component-eval and corpus-build |

## Fixed workflow and adaptive controls

B0 makes exactly one structured backbone call. B1 generates the configured number of independent samples and aggregates with strict normalized equality; no equivalence judge or extra inference is hidden in this baseline. Case, punctuation, units and significant digits remain distinct.

B2 starts with one candidate. Each bounded round uses at most three short queries and the first three allowed search results per query, subject to hard global search/fetch caps. Parsed pages become passages with exact offsets. A lexical shortlist has at most 20 passages; a diverse evidence packet has at most six passages, at most two per host, and a configured character budget. Code checks run only when supplied. The backbone revises; exact citation failures or missing citations trigger one repair. Persistent critical failures lead to abstention. No reference answer participates in these decisions.

Reaching a search or fetch call cap ends research with the evidence already collected, including cached evidence replayed after interruption. Revision and selection proceed within the remaining budget. Total-call limits, dollar limits and provider reservation overruns still halt the solve.

J2 replaces lexical ordering of the identical shortlist with Jev's ordered relevance judgments. J3 adds semantic support judgments after exact span checks. J23 combines them. Jev never creates queries, code or proof steps. Configured Jev fallback records an outage and follows the corresponding baseline policy; it never fabricates a successful judgment.

Jfull adds independent initial candidates, routing among enumerated actions, separate narrow constraint checks, anonymized selection with none-supported, and a bounded continuation decision. Its default 0.5 Noul flag threshold is an experimental setting requiring development validation. Selection uses candidate confidence rather than interpreting the probability of a Choice winner as whole-answer correctness. Each extra stage consumes the same shared call, token, time and dollar envelope. Jfull is not automatically promoted over J23.

Adaptive constraint checks run again after repair. Persistent failures reject the repaired answer. If selection chooses an initial candidate that has not passed those checks, it is checked before finalization and rejected if constraints remain unresolved.

## Deliberate scope and remaining empirical work

The live backbone adapter is OpenAI. Multiple pinned OpenAI model configurations are supported; Anthropic and other provider protocols are not silently treated as OpenAI-compatible. They require an additional adapter and provider-specific tests.

The optional hybrid index uses fixed hashed character vectors. It provides a reproducible dense feature baseline without unaccounted embedding calls, and is explicitly labeled in extended reports. Learned semantic embeddings, a broad production corpus, specialist tools, knowledge graphs, and cross-run answer memory are not prerequisites of the initial evidence-handling experiment.

The HTML extractor is deterministic and preserves text boundaries; PDF extraction is text-only. Images in questions are preserved for the backbone, while fetched image/audio/video payloads and OCR are excluded. Extraction quality, equations and tables require source-level retrieval diagnostics; inaccessible or unparseable pages must not be replaced with authoritative-sounding snippet summaries.

Budget accounting uses provider-reported tokens at frozen user-configured rates. It does not query billing invoices. Missing responses retain their maximum reservation, so uncertain runs can overestimate spend. Reservations above the declared price envelope stop further dispatch, and an incorrect price configuration can already have incurred an overrun. Actual model availability, rate limits, price schedules, image token envelopes and supported sampling options require account-specific validation before the held-out job.

No numerical result on HLE-Diamond, no claim of Jev improvement, and no adaptive-stage promotion follows from synthetic tests. External development labels, overlap checks, policy calibration, matched-cost experiments across multiple frozen budgets, blinded grader review, sample-size decisions, contamination adjudication and final publication are research activities to perform with this harness. Full semantic retrieval and heterogeneous providers remain conditional extensions in PLAN.md. The library does not invent their acceptance measurements.

## Upstream attribution

`protocol/manifest.json` records source links, exact upstream commit and SHA-256 hashes for the CAIS HLE tool rules, blocklist, sandbox requirements, grading source and license. Grading parses only the pinned prompt literal and adapts the structured response fields; importing the upstream script would create a client and is avoided.

API contracts were checked against [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses), [TypeSafe's Python SDK](https://docs.typesafe.ai/sdk/python), [System One](https://docs.typesafe.ai/api/system-one), and its [primitive model](https://docs.typesafe.ai/models). SDK versions and all optional dependency resolutions are committed in `uv.lock`.
