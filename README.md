# HLE-Diamond Jev Solver

An asynchronous Python research harness for testing whether Jev improves evidence handling beyond the same reasoning model with audited web and code tools. The research rationale and experimental gates are in [PLAN.md](PLAN.md).

**Status:** implemented and tested with synthetic tasks, mocked provider responses, and an isolated Docker sandbox. A private 50-question development pilot also completed: Sol low B0 scored 22/50 (44%), and a budget-limited J23 pipeline with Jev scored 16/50 (32%), using automatic Astra reference grading. These exploratory results do not establish a Jev benefit. Adaptive policies and retrieval extensions remain experimental.

## Known issues

Evidence reviewed through **7 November 2026**. The findings below describe observed development-run failures and remaining validation gaps. Some defects have implementation or offline replay repairs; those checks do not establish improved end-to-end accuracy.

- **No demonstrated held-out improvement or isolated Jev benefit.** The initial B0 baseline scored 22/50, and the strongest observed development pipeline, Perplexity evidence-v2, scored 26/50. These runs used the same repeatedly inspected development questions and automatic reference grading. The apparent gain does not establish performance on unseen questions or separate Jev's contribution from tools, extra model calls, and sampling. See the [pilot](docs/SOL_PILOT.md) and [Perplexity evaluation](docs/PERPLEXITY_EVIDENCE_V3_EVALUATION.md).
- **Correct drafts can be lost before final output.** The 6 November saved-draft audit found reference-matching answers for 22 of 50 questions in the verifier-v2 run, but only eight correct final answers. The fourteen lost cases ended in eleven abstentions, two errors, and one budget failure. Reference agreement does not establish a sound derivation or sufficient evidence, so these counts are neither fourteen proven verifier mistakes nor an achieved 22/50 solver result.
- **Verification scope and bookkeeping can block usable answers.** Recorded failures include requiring sources for independently solvable premises, treating an excluded interpretation as unresolved, retaining a positive proposition that a qualified answer explicitly denies, and mismatching dependency or gap identifiers. Some structural defects have been repaired in offline replay, but a reliable end-to-end gain from those repairs has not been demonstrated. See the [verification and integration analysis](docs/EVIDENCE_V3_SEARCH_ATTRIBUTION.md) and [failure analysis](docs/EVIDENCE_V3_FAILURE_ANALYSIS.md).
- **Useful evidence can be omitted or its benefit lost downstream.** Lexical shortlists, relevance rules, and packet limits have excluded useful fetched passages; returned research leads have also gone unfetched. In one recorded case, supplementary evidence corrected the answer, but invalid citation character offsets caused abstention even though the quoted sentence existed. These are distinct retrieval, selection, and integration failures. See the [source-attribution analysis](docs/EVIDENCE_V3_SEARCH_ATTRIBUTION.md).
- **More checking can reduce coverage and exhaust resources.** Evidence-v3 reduced wrong returned answers but lowered full-set accuracy from 44% to 32% with Brave and from 52% to 30% with Perplexity, while increasing accounted solver cost more than fivefold. Context limits, invalid structured responses, timeouts, and budget failures have also prevented completion. Abstentions and execution failures remain in the accuracy denominator. See the [Brave](docs/BRAVE_EVIDENCE_V3_EVALUATION.md) and [Perplexity](docs/PERPLEXITY_EVIDENCE_V3_EVALUATION.md) evaluations.
- **Source support is not whole-answer verification.** A supported quotation does not validate the answer's scope, derivation, image interpretation, or computational assumptions. Wrong answers have passed the implemented checks, and reviewer agreement or Jev confidence is not an independently adjudicated correctness label. Passing regression tests verifies implementation behavior, not semantic quality. See the [failure analysis](docs/EVIDENCE_V3_FAILURE_ANALYSIS.md) and [component review](docs/EVIDENCE_V3_EXPANDED_REVIEW.md).

These findings do not establish that supplementary information generally confuses the solver: saved cases include successful evidence-based corrections as well as rejected correct drafts. The immediate priority is to measure draft survival through verification and completion, with incorrect drafts as controls, and retrieve specific missing evidence where needed. A controlled comparison with and without supplementary sources is still needed to isolate retrieval-induced answer degradation.

## Experiment results and commits

Provenance checked on **7 November 2026** against Git history, saved run manifests, and isolated grades. Dates below are UTC run dates. **Source match** means the commit's Python files under `src/jev_solver` reproduce the run manifest's `implementation_hash`; it does not replace the separately pinned configuration, dataset, protocol, and environment. Fingerprints shown below are abbreviated SHA-256 identifiers, not Git commit IDs. A commit that only records a result is identified explicitly.

The completed solver runs all use the same **50-question HLE-Diamond development set**, Sol low reasoning, and automatic Astra reference grading. Scores include abstentions and execution failures. They are not full 1,000-question benchmark scores, held-out results, or controlled estimates of Jev's contribution.

| Date (UTC) | Completed solver experiment | Associated commit and source provenance | Correct / 50 |
| --- | --- | --- | ---: |
| 2026-10-30 | [B0: one model call, no tools](docs/SOL_PILOT.md) | Result recorded in [836854b](https://github.com/paulrobertdoherty/HLE-Diamond-Jev-Solver/commit/836854b); original source `32089a62d466` has no exact commit match | 22/50 (44%) |
| 2026-10-31 | [Initial J23 pilot, Brave](docs/SOL_PILOT.md#jev-evidence-pilot) | Source match: [836854b](https://github.com/paulrobertdoherty/HLE-Diamond-Jev-Solver/commit/836854b), `7a83009b1a30` | 16/50 (32%) |
| 2026-10-31 | [Evidence-v2 J23, Brave](docs/SOL_PILOT.md#evidence-v2-follow-up-implementation) | Source match: [2a1565a](https://github.com/paulrobertdoherty/HLE-Diamond-Jev-Solver/commit/2a1565a), `d54334154b2a` | 22/50 (44%) |
| 2026-11-01 | [Evidence-v2 J23, Perplexity](docs/PERPLEXITY_ERROR_ANALYSIS.md) | Source match: [2a1565a](https://github.com/paulrobertdoherty/HLE-Diamond-Jev-Solver/commit/2a1565a), `d54334154b2a` | 26/50 (52%) |
| 2026-11-01 | [Evidence-v3 J23, Brave](docs/BRAVE_EVIDENCE_V3_EVALUATION.md) | Source match: [d40ae78](https://github.com/paulrobertdoherty/HLE-Diamond-Jev-Solver/commit/d40ae78), `51b6b4ab4ced` | 16/50 (32%) |
| 2026-11-01 | [Evidence-v3 J23, Perplexity](docs/PERPLEXITY_EVIDENCE_V3_EVALUATION.md) | Source match: [d40ae78](https://github.com/paulrobertdoherty/HLE-Diamond-Jev-Solver/commit/d40ae78), `51b6b4ab4ced` | 15/50 (30%) |
| 2026-11-05 | Original R0–R8 remediation, Brave | Source match: [a22f460](https://github.com/paulrobertdoherty/HLE-Diamond-Jev-Solver/commit/a22f460), also preserved by [d4e91fe](https://github.com/paulrobertdoherty/HLE-Diamond-Jev-Solver/commit/d4e91fe), `d32f61ef564d` | 1/50 (2%) |
| 2026-11-06 | Verifier-v2 follow-up, Brave | Uncommitted follow-up to [d4e91fe](https://github.com/paulrobertdoherty/HLE-Diamond-Jev-Solver/commit/d4e91fe); source `ca2a88a75583` has no exact commit match | 8/50 (16%) |

**Verifier-v2 is a later verification repair, not evidence-v2.** Its 50-question run resumed after an interruption; two recorded timeouts were affected by that interruption. The score retains those failures, and its elapsed-time measurements are unsuitable for a speed comparison. The two latest completed runs are recorded in the private `sol-low-remediation-j23-brave-2026-11-05` and `sol-low-remediation-verifier-v2-dev50` manifests and corresponding evaluation directories.

The following experiments have different denominators or measure components rather than the complete solver. Their results must not be ranked alongside the 50-question solver scores above.

| Date (UTC) | Follow-up experiment | Associated commit / implementation | Recorded result |
| --- | --- | --- | --- |
| 2026-10-31 | B0 timeout retest | Source match: [836854b](https://github.com/paulrobertdoherty/HLE-Diamond-Jev-Solver/commit/836854b), `7a83009b1a30` | 0/1 correct; does not change the original 22/50 baseline |
| 2026-11-01 | Aborted Perplexity v3 transport attempt | Source match: [d40ae78](https://github.com/paulrobertdoherty/HLE-Diamond-Jev-Solver/commit/d40ae78), `51b6b4ab4ced` | No finalized predictions or benchmark score; the separate completed run is listed above |
| 2026-11-06 | Verifier-v2 smoke test | Uncommitted follow-up to [d4e91fe](https://github.com/paulrobertdoherty/HLE-Diamond-Jev-Solver/commit/d4e91fe); source `27bfb6027d5d` | Four selected failure cases: three abstentions and one error; no returned answers and no reference grading |
| 2026-11-07 | Frozen-source screening probe | Uncommitted experiment; screening-module hash `c4691508b940` | Current: 23/50 (46%); broader: 24/50 (48%); finer: 24/50 (48%); combined: 23/50 (46%). All 200 trials graded; only 25 questions had source packets |
| 2026-11-07 | Planned-retrieval answer probe | Uncommitted experiment; planned-retrieval-module hash `a4a35a6a619c` | Current: 16/50 attempts; planned Jev: 19/50; direct reading: 13/50. Unequal budget failures prevent a fair ranking; see below |
| 2026-11-07 | Verification-repaired solver run, stopped early | Uncommitted follow-up to [d4e91fe](https://github.com/paulrobertdoherty/HLE-Diamond-Jev-Solver/commit/d4e91fe); source `84670a9e2625` | Only 13/50 questions finalized: two correct, eight abstentions, three errors; 37 unfinished. The selected completed subset is 2/13, not a completed 50-question result |

The planned-retrieval probe uses **25 source-bearing questions with two answer attempts per approach**. Budget reservations blocked 29 of 150 answer attempts before dispatch: six current, five planned Jev, and eighteen direct. On the post-hoc subset with completed answers from every approach, current scored **9/27**, planned Jev **11/27**, and direct reading **11/27**, across 18 questions. The improvement consists of two attempts on one mathematics question; planned Jev and direct reading have identical correctness outcomes throughout that subset. Repeated questions and completion selection prevent treating this as a reliable gain or equivalence result. Both retrieval probes bypass the full solver's verification and eligibility gates.

**Offline experiments and implementation milestones:**

| Work | Associated commits | Benchmark result / diagnostic outcome |
| --- | --- | --- |
| Initial harness and review fixes | [fea75af](https://github.com/paulrobertdoherty/HLE-Diamond-Jev-Solver/commit/fea75af), [3c11d44](https://github.com/paulrobertdoherty/HLE-Diamond-Jev-Solver/commit/3c11d44) | No live HLE result at these milestones; synthetic, mocked-provider, and sandbox validation only |
| V3 attribution, labeling pilot, and expanded component review | Results and tooling recorded in [9a7a1aa](https://github.com/paulrobertdoherty/HLE-Diamond-Jev-Solver/commit/9a7a1aa) | No new solver score. Historical replay reproduced 100/100 saved outcomes; provisional component reviews do not establish adjudicated semantic accuracy |
| R0–R8 remediation components | [Commit series](https://github.com/paulrobertdoherty/HLE-Diamond-Jev-Solver/compare/9a7a1aa...a22f460); [per-step commit map](docs/EVIDENCE_V3_REMEDIATION_RESULTS.md#changes-and-policy-selection) | No isolated benchmark score for each component. The combined live configuration scored 1/50, as listed above |
| Saved-draft survival audit | Uncommitted analysis of verifier-v2 source `ca2a88a75583` | Correct saved draft available on 22/50; correct eligible and final answer on 8/50. The 22/50 is an oracle diagnostic, not achieved solver accuracy |
| Eligibility and graph-repair replays | Uncommitted follow-up work | Four saved variants across two questions become eligible; 26/31 graph-validation failures repaired over 157 saved audit responses. These are offline diagnostics; the later partial live run is listed separately |

The uncommitted experiments do not have a reproducible Git checkout yet; a related base commit is not their measured implementation. Frozen manifests, source/module fingerprints, predictions, and grades remain in ignored private storage, without publishing benchmark questions or answers. B1, standalone J2/J3, Jfull, M, R, and the matched B2/J23 controls have no completed live HLE score recorded here; implemented configurations and passing tests are not benchmark results.

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
| B2 | Dependency audits, bounded search/code/revision, lexical ranking and exact citation spans |
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

Live tool runs can select `search_backend: perplexity` with `PERPLEXITY_API_KEY` and an explicit `search_usd`. The official Perplexity Search SDK returns sources for the existing backbone and Jev pipeline. Both Brave and Perplexity now use evidence-v3: independent dependency audits, feedback-driven research, verification coverage, and selection tied to actual checks. See [Perplexity search setup](docs/RUNBOOK.md#perplexity-search) and the [new matched B2/J23 profiles and TypeSafe setup](docs/EVIDENCE_V3.md). The 50-question development reruns reduced wrong answers but lowered full-set accuracy and increased cost: [Brave v3 evaluation](docs/BRAVE_EVIDENCE_V3_EVALUATION.md) and [Perplexity v3 evaluation](docs/PERPLEXITY_EVIDENCE_V3_EVALUATION.md).

The [search root-cause investigation](docs/JEV_SEARCH_ROOT_CAUSE.md) traces the remaining verification bypass, evidence loss and research/selection limits to code and saved runs. Its repository fixes are implemented in [evidence-v3](docs/EVIDENCE_V3.md), which includes exact TypeSafe account steps, changed budgets and the remaining labeling/evaluation work. No customer Jev training or classifier registration is needed.

The [v3 attribution suite](docs/EVIDENCE_V3_TESTING.md) implements offline boundary regressions, private replay adapters, labeled-case extraction, evidence-survival/workflow metrics, fixed-query search replay and controlled comparison utilities. See [validation results and unrun quality measurements](docs/EVIDENCE_V3_TEST_RESULTS.md).

The [initial Luna/Terra/Haiku labeling pilot](docs/EVIDENCE_V3_LABEL_PILOT.md) records paid review costs, output-grounding failures, provisional Terra diagnoses and Haiku disagreement notes. It preserves unresolved gold-label status and does not change solver acceptance.

The [remediation implementation and validation](docs/EVIDENCE_V3_REMEDIATION_RESULTS.md) adds independently selectable citation, context, contract, retrieval, support, and final-answer policies plus controlled engine orchestration. Existing profiles retain their controls. Deterministic tests and historical replays pass; semantic promotion and paid comparisons remain pending.

## Checks

```bash
python -m unittest discover -s tests -v
ruff check src tests
ruff format --check src tests
```

The Docker integration test is enabled by setting `JEV_SANDBOX_IMAGE` to the digest of a locally built protocol image. CI runs synthetic and mocked API checks without credentials; paid benchmark evaluations are launched explicitly.

Original code is MIT licensed. Vendored upstream files retain their own [license](protocol/upstream/LICENSE) and [source manifest](protocol/manifest.json). Do not commit credentials, benchmark questions or labels, retrieved caches, or private traces.
