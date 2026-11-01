# Implementation and research gates

The architecture is an explicit asynchronous state machine with typed records and private local artifacts. Implementation enables experiments; acceptance gates that depend on dataset access, account capabilities, calibrated prompts, external labels or measured improvements are not asserted as complete.

| Plan area | Implementation |
| --- | --- |
| Benchmark preparation and isolation | `benchmarks/data.py`: authenticated revision-pinned preparation; strict solver allowlist; original images and IDs; content/schema hashes; local stratified splits |
| Provider boundaries | `providers/backbone.py`, `providers/openrouter.py`: OpenAI Responses, OpenRouter Chat Completions and synthetic adapters, explicit capabilities, structured candidate validation, returned-model and usage checks |
| Verification coverage | `judgments/verification.py`: independent dependency discovery and completeness review, criticality, explicit check statuses and artifact validation |
| Jev contracts | `providers/jev.py`, `judgments/pipeline.py`: typed SDK Choice/Noul/Score, normalized ordered scores, local state, exact spans before support judgments, explicit outages and baseline fallback |
| Controller and accounting | `controller/engine.py`, `controller/research.py`, `controller/budget.py`: bounded phases, feedback-driven research outcomes, independent candidates, global concurrency, monetary reservations, retries, cancellation and finalization |
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
| Operations | `cli.py`: validate, prepare, estimate, run, resume, grade, compare, export, audit, component-eval, workflow-eval and corpus-build |

## Fixed workflow and adaptive controls

B0 makes exactly one structured backbone call. B1 generates the configured number of independent samples and aggregates with strict normalized equality; no equivalence judge or extra inference is hidden in this baseline. Case, punctuation, units and significant digits remain distinct.

B2 starts with one candidate and a separate backbone verification audit, even when the draft declares no gaps. The audit inventories necessary factual, derived, numerical and visual dependencies independently of source use; checks for omitted premises; classifies every original gap; and plans neutral factual searches. Candidate declarations cannot replace the audit. `not_run`, `not_applicable`, `unavailable`, `passed` and `failed` are explicit, and coverage is recorded separately from candidate eligibility.

Factual dependencies require actual fetched passages. Derived dependencies can pass a separate review of their concise proof/calculation without citations. Numerical dependencies require successful untruncated real execution artifacts linked by code hash; synthetic fixture output or generated code does not qualify. Visual dependencies identify original images reviewed by the backbone. These are model reviews and artifact checks, not a guarantee of semantic completeness, source reliability or correctness.

Research ranks audited snippet/title leads against the neutral missing fact, balances fetch quotas across queries, and reserves capacity for a later round. Search outcomes, failed fetches, unused leads and packet exclusions reach revision and verification planning. Snippets remain discovery hints. New queries and repaired code can run in the next round, within shared search/fetch/code limits. Cached research revalidates complete cached source pages before exposure and never silently replaces a missing replay source with a new fetch.

Passages carry the original question, neutral missing fact, literal query and dependency ID separately. The configurable shortlist alternates between facts and sources. Packets retain source/host/character limits. J2's rubric explicitly includes disconfirming evidence; its experimental policy reserves a bounded uncertain alternative alongside ordinarily useful passages. Default/new profiles judge at most 12 passages per round, retain up to six and reserve one alternative. Thresholds are development policy, not calibrated correctness probabilities. See [the full v3 guide](EVIDENCE_V3.md) for exact settings and account steps.

Every candidate retains `source_claims` and exact citations for critical facts it uses from passages, plus a separate dependency inventory. Revisions receive actual evidence, tool artifacts, dependency checks and research outcomes. The last round permits one bounded prose/citation repair; all generated candidates are assessed. Raw rejected drafts remain available only to offline oracle evaluation. All earlier candidates are reassessed against the final evidence and artifacts before selection, so their earlier acceptance cannot bypass new contradictions.

The default `auto` selector keeps deterministic voting for B0/B1 and uses the backbone in tool arms, including runs with no tool revision. The chooser receives anonymized distinct answers, actual checks, cited-source provenance, the current evidence packet and tool artifacts. Its structured reason and dependency references must cover all actual passed critical checks. It can select a validated earlier derivation, a newly generated correction or none-supported. Revisions do not become independent votes. Explicit `vote` remains a deterministic ablation over the eligible pool.

The item evidence ledger retains passages for citation checking even after packets change. Private `research_outcome`, `retrieval_summary`, `candidate_checks`, `candidate_rejected`, `selection_basis`, `candidate_selection` and replay events preserve decisions. Implementation, prompt, config and dependency hashes prevent resuming historical runs under new code. No reference labels enter solving.

Optional tools/J2 stop when their call/dollar reserves are reached, retaining available evidence for final verification and selection. These final phases still obey all hard caps. The new live profiles allow two rounds, two code executions and larger per-item/finalization reserves; each run retains its $10 total cap. Budget exhaustion during required checks remains a failed prediction rather than an unchecked answer.

J2 adds relevance judgments to the shared workflow. J3 adds semantic citation and factual-dependency entailment checks; J23 combines them. Jev never generates queries, prose or code. An unavailable required support check cannot become successful coverage. B2 uses the backbone audit and exact spans without Jev. Jfull adds independent initial candidates, routing, narrow constraints and continuation; those decisions now receive dependency context, and J4 receives actual passages and artifacts. Jev selection remains a separate experiment. These changes do not turn J23 into Jfull.

Component evaluation compares identical saved inputs without sending gold labels. It reports relevance decision accuracy and MAE, packet-budget recall, useful/contradictory exclusion rates and support confusion matrices. Offline workflow evaluation reports annotated claim-discovery/coverage recall and wrong-answer acceptance/correct-pool abstention rates. Missing label denominators remain unknown. Existing full-run evaluation reports all-item accuracy, answered-item accuracy, coverage and cost.

## Deliberate scope and remaining empirical work

Live backbone adapters support direct OpenAI Responses and OpenRouter Chat Completions, including multiple models from either transport in M. OpenRouter uses its own environment key, explicit model slugs, strict JSON Schema output, parameter-support and price filters, and an optional host pin. Native tools and output-changing plugins are disabled. The OpenRouter adapter has mocked HTTP, accounting, failure, baseline-run and resume tests, plus private live Sol solver and Astra grading pilots described in [SOL_PILOT.md](SOL_PILOT.md). Compatibility with other models and accounts still requires validation. Other direct provider protocols require additional adapters and contract tests.

The optional hybrid index uses fixed hashed character vectors. It provides a reproducible dense feature baseline without unaccounted embedding calls, and is explicitly labeled in extended reports. Learned semantic embeddings, a broad production corpus, specialist tools, knowledge graphs, and cross-run answer memory are not prerequisites of the initial evidence-handling experiment.

The HTML extractor is deterministic and preserves text boundaries; PDF extraction is text-only. Images in questions are preserved for the backbone, while fetched image/audio/video payloads and OCR are excluded. Extraction quality, equations and tables require source-level retrieval diagnostics; inaccessible or unparseable pages must not be replaced with authoritative-sounding snippet summaries.

Live search supports Brave and Perplexity Search. Perplexity uses the pinned official async SDK with a fixed endpoint and no SDK retries; its URL/title/snippet results pass through the same pre-query, per-result and cached-result policy checks. Direct fetching, evidence handling and candidate selection remain shared. Supervisor retries honor `Retry-After` while remaining subject to attempt, spend and item-deadline limits. Four `sol-low.evidence-v3.*` configurations provide B2/J23 controls with each backend and the same model settings and budget caps; the extra final selection call is accounted against those caps.

Budget accounting uses provider-reported tokens at frozen user-configured rates. OpenRouter also preserves reported cost and uses it when higher than the rate estimate. It does not query billing invoices. Missing responses retain their maximum reservation, so uncertain runs can overestimate spend. Charges above the declared price envelope stop further dispatch, and an incorrect price configuration can already have incurred an overrun. Actual model availability, rate limits, price schedules, image token envelopes and supported sampling options require account-specific validation before the held-out job.

No numerical result on HLE-Diamond, no claim of Jev improvement, and no adaptive-stage promotion follows from synthetic tests. External development labels, overlap checks, policy calibration, matched-cost experiments across multiple frozen budgets, blinded grader review, sample-size decisions, contamination adjudication and final publication are research activities to perform with this harness. Full semantic retrieval and heterogeneous providers remain conditional extensions in PLAN.md. The library does not invent their acceptance measurements.

## Upstream attribution

`protocol/manifest.json` records source links, exact upstream commit and SHA-256 hashes for the CAIS HLE tool rules, blocklist, sandbox requirements, grading source and license. Grading parses only the pinned prompt literal and adapts the structured response fields; importing the upstream script would create a client and is avoided.

API contracts were checked against [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses), [TypeSafe's Python SDK](https://docs.typesafe.ai/sdk/python), [System One](https://docs.typesafe.ai/api/system-one), and its [primitive model](https://docs.typesafe.ai/models). SDK versions and all optional dependency resolutions are committed in `uv.lock`.
