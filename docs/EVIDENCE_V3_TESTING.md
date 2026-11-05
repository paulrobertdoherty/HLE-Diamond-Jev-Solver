# Evidence v3 attribution suite

The [test plan](EVIDENCE_V3_TEST_PLAN.md) is implemented with synthetic offline contracts, private historical adapters, labeled-case extraction, component/workflow metrics, fixed-query search comparison, and controlled replay utilities. [Recorded validation and remaining measurements](EVIDENCE_V3_TEST_RESULTS.md) distinguish passing software contracts from semantic-quality results.

## Offline contracts and historical reproduction

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_evidence_v3_regressions.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_evidence_v3_private.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_search_attribution.py' -v
```

The new suites reject uncached dispatch through the budget, provider, socket and subprocess boundaries. A dispatch violation inherits from `BaseException` so solver/provider fallback cannot silently turn it into an ordinary failed prediction. Tests supply explicit fake responses or audited cached pages. They require no keys or Docker execution.

Private adapters read the original audit, case index and question file under `private/`; set `JEV_V3_PRIVATE_ROOT` to use another artifact directory. A clone without these files skips the private adapter class. These adapters assert historical failures separately from recovery contracts. They never use reference answers to solve a question.

The original baseline was committed and pushed as `d40ae78` before implementation. The actual source/configuration snapshot is preserved locally at `private/v3-test-plan-baseline/`. Its implementation hash is `51b6b4ab4ced7b4c9160b2f401014e6aa53c5889dd23efb84529df8ef78a6d0d`. To reproduce the historical pipeline after modifying the working source, use that snapshot:

```bash
PYTHONPATH=private/v3-test-plan-baseline/src .venv/bin/python private/analyze-v3-search-attribution.py
.venv/bin/python private/write-v3-attribution-casebook.py
```

Those scripts regenerate derived private artifacts. Original databases stay read-only. Running the historical analysis against the changed implementation should still fail its source-identity check.

## Behavior covered by T01–T05

| Boundary | Contract and recovery |
| --- | --- |
| T01: citations | Wrong offsets, absent text, unknown passages and changed source identities fail. Repeated text needs a valid explicit span. Unicode offsets use Python character positions. One existing bounded repair can provide a corrected span; its critical claim still passes the semantic support and coverage checks. No automatic quote relocation was added. |
| T02: selection | Bare IDs and `candidate_0.d1` / `candidate_0:d1` resolve only within the selected candidate. Missing, ambiguous, foreign or unpassed references fail. Abstention cannot cite candidate checks. Trace events preserve raw references, resolved references and exact rejection conditions. |
| T03: envelopes/output | The conservative bound includes UTF-8 text, schema/system overhead and image reserves. Rejection occurs before dispatch, recording the bound and limit. Incomplete, malformed JSON and non-object outputs are not cached. Invalid candidate citations still fail parsing. Oversized contexts remain rejected; automatic context reduction is not implemented. |
| T04: fetching | Audit queries can include `fetch_urls: []`. A known allowed unused lead can be fetched directly, without another search. Unknown/blocked leads cannot dispatch. Search, fetch and follow-up reserves retain their shared limits. Traces distinguish provider/local/fetch ranks, request, destination, redirects, extraction and retained source IDs. |
| T05: verification | Every gap maps exactly once; failures name missing, extra and duplicate indices. Stable declared IDs connect equivalent wording to the original source claim. Distinct omitted premises remain unchecked. All five check states, critical bases, artifacts and incidental gaps retain explicit coverage rules. |

Current audit generation requires `fetch_urls` in each query object. Parsing accepts older saved query objects without that field for replay compatibility. Research caches use a new version; complete-request model caches and implementation hashes continue to isolate changed inputs.

## Private labels and saved evaluation

Extract into a **fresh** directory; extraction refuses to overwrite an existing label file:

```bash
.venv/bin/python -m jev_solver attribution-extract \
  --audit private/v3-search-attribution-audit.json \
  --index private/v3-search-attribution-cases.json \
  --questions private/sol-low-pilot-data/solver/questions.jsonl \
  --output private/new-v3-labels
```

`label-cases.jsonl` contains versioned records with `id`, `test_id`, `task_id`, `component`, development split, stable claim/passage IDs, `input`, `input_hash`, `observation`, `observation_hash`, and `label`. Inputs and saved observations are immutable; edit only the label. Original grades stay in the separate reference observations. Audit records are deduplicated by original request identity so cache replay does not become a new sample.

Every extracted label starts as `unresolved`. Independent adjudication sets `status: "adjudicated"`, adds nonempty `provenance.reviewer`, `provenance.method`, and `provenance.timestamp`, and fills `values`. Do not convert the casebook hypotheses or original model judgments into expert gold labels automatically.

| Component | Independently adjudicated `label.values` |
| --- | --- |
| J2 | `expected`: normalized score; optional Boolean `answer_bearing`, `useful`, `contradictory` |
| J3 | `expected`: `supported`, `contradicted` or `insufficient`, for the actual supplied claim/quote/context |
| Audit | `gold_dependencies`: objects with stable `id`, `kind`, `critical`; optional `visual` with `expected_observations` and independently reconciled `observed_observations` maps |
| Reference/history | `correct_ids`: independently labeled correct drafts across the entire candidate history; `adjudicated_correct`: Boolean for the final prediction; `disagreement`: `agreement`, `solver_error`, `reference_interpretation`, `grader_inconsistency` or `unresolved` |
| Search | `useful_urls` and `needed_text` exact source facts, prepared independently of the provider ordering being tested |

The format separates provider input from scoring labels. References cannot pass through the general provider-input adapter. The extractor preserves original images and actual Jev request context; it does not enrich historical prompts with newly discovered context. J3 reconstruction must match the original complete request hash. Intermediate drafts require their own correctness labels.

```bash
# Both commands are offline; unresolved labels yield unavailable metrics.
.venv/bin/python -m jev_solver component-eval --config configs/synthetic.json \
  --cases private/new-v3-labels/label-cases.jsonl --judge stored --output private/v3-stored-components
.venv/bin/python -m jev_solver workflow-eval \
  --cases private/new-v3-labels/label-cases.jsonl --output private/v3-workflow.json
```

The original component and workflow JSONL schemas remain supported. Component evaluation adds explicit before-shortlist, after-shortlist, after-relevance and after-packet recall counts, plus per-passage exclusions. Groups preserve backend/source snapshot, question, round and missing fact. Actual passage IDs preserve production tie ordering. Unexecuted judgments are `not_run`, excluded from semantic decision accuracy; a passage lost before J2 is not a Jev rejection. Missing positive labels produce null recall, with zero labeled denominator.

Workflow evaluation adds audit discovery/checked-coverage, kind/criticality consistency, repeatability, image-observation accuracy and image-reference grounding. Image grounding checks supplied/referenced image identities; it cannot prove the model visually understood the image. Eligibility false rejection uses **all independently correct drafts** as its denominator. Eligibility false acceptance uses all independently invalid drafts. Selection wrong-answer acceptance uses nonempty selections. Original/adjudicated reference scores and grader agreement remain separate.

## Capped AI-label pilot

For the proposed expanded Terra/Haiku review, start with the [next-session instructions](EVIDENCE_V3_LABEL_PILOT.md#next-session-instructions). The runner and commands below support the original 36-case, three-reviewer pilot with a maximum $6 cap; expanded scope and reviewer selection still require implementation.

`python -m jev_solver.evaluation.label_pilot` prepares and runs a small independent-review experiment. Preparation uses an explicitly saved OpenRouter model catalog (`GET /api/v1/models`) and makes no external calls:

```bash
.venv/bin/python -m jev_solver.evaluation.label_pilot \
  --cases private/v3-test-plan-implementation/cases/label-cases.jsonl \
  --catalog private/v3-label-pilot-2026-11-02/models-preflight.json \
  --output private/new-label-pilot --cap 6

# Paid calls require this explicit flag and an existing OPENROUTER_API_KEY.
# Check the first case before resuming all remaining cases.
.venv/bin/python -m jev_solver.evaluation.label_pilot \
  --output private/new-label-pilot --live --max-cases 1
.venv/bin/python -m jev_solver.evaluation.label_pilot \
  --output private/new-label-pilot --live
```

The frozen sample contains 16 J2 passage cases (four each unexecuted, low, middle and high saved scores), 12 J3 cases (eight supported, three insufficient, one contradicted), and eight audit cases (four with original images). Selection balances case aliases and saved search backends, deduplicates exact component inputs, and uses a fixed deterministic order. These diagnostic strata are deliberately selected development artifacts, not a random benchmark sample. The current extractor's saved artifacts are required to fill the strata.

The exact model IDs are `openai/gpt-6-luna`, `openai/gpt-6.1-terra`, and `anthropic/claude-haiku-5.5`, all at medium reasoning. Preparation verifies catalog rates/capabilities and records canonical model snapshots. Existing transport restricts providers to OpenAI or Anthropic, disables fallbacks/plugins/transforms, and enforces price ceilings. Every reviewer sees the same request and images, without other reviewers' outputs. J2/J3 original predictions stay hidden. Audit reviewers necessarily see the historical audit they are diagnosing. Reference answers and grades are excluded.

Terra is the **provisional** primary reviewer. Luna is compared with Terra; Haiku contributes **only disagreement notes**, without voting, overriding Terra or changing solver acceptance. Reports preserve categorical differences (including audit finding IDs/types), separate primary-decision disagreements, and unavailable pairs. Different wording/confidence alone is not counted as disagreement. Agreement is not accuracy; no expert gold is created and original unresolved labels remain untouched.

The initial-pilot runner refuses caps above $6. Before dispatch, durable SQLite reservations account for conservative UTF-8 text/image envelopes and bounded output (6,144 tokens for J2/J3; 12,288 for audits, including reasoning). The shared budget covers all three models. Retries are disabled. Incomplete and invalid reviews still retain their charges; source-quote mismatches are invalid reviews, never successful labels. Resuming requires the same plan, prompts and runner implementation. Completed attempts are reused, and dispatched attempts with uncertain results are not repeated automatically.

`pilot-plan.json`, `events.sqlite3`, and `pilot-results.json` remain private. Results include all responses, provenance, usage, reported/accounted costs and per-case Terra/Luna and Terra/Haiku comparisons. [Initial measured results](EVIDENCE_V3_LABEL_PILOT.md) distinguish disagreement and format/grounding failures from demonstrated model accuracy.

## Fresh component behavior and fixed queries

Existing `component-eval --judge jev`, `--judge lexical`, and `--judge backbone` evaluate identical adjudicated states. Jev uses TypeSafe, lexical is offline, and a live backbone uses its configured provider. Changing prompts or adding context is a new intervention.

`audit-eval --config CONFIG --cases LABEL_CASES --output FRESH_OUTPUT --repeats N` samples audits on frozen questions/images, candidates, evidence and artifacts, without sending labels. Repeats must be 1–10 and receive distinct request identities. Errors retain labeled trial denominators. Live calls obey the configured budget; no live model-quality threshold is implied by the synthetic tests.

`search-eval` accepts either a plain frozen query list with `id`, `question`, `missing_fact`, `query`, and optional `label`, or native extracted search cases. Identical native inputs are deduplicated. Both backends receive the same literal query, with provider order and the common local ranker evaluated separately:

```bash
# Replays saved results/pages. No search, fetch or model dispatch.
.venv/bin/python -m jev_solver search-eval --config configs/synthetic.json \
  --queries private/fixed-queries.jsonl --snapshot private/frozen-search.json \
  --fetch-budget 4 --output private/search-replay
```

A snapshot has `version: 1`, `input_hash` over the allowlisted query list, `policy_version`, `parser_version`, `result_limit`, `fetch_budget`, and `providers`. For each backend (`brave`, `perplexity`), `providers[backend][query_id]` holds that query's `input_hash`, raw `results`, and `pages` mapping requested URLs to `{status, page}`. A page preserves the returned destination, redirects and extracted text. The harness writes this format as `search-snapshot.json`; synthetic examples are constructed in `test_search_attribution.py`.

Using `--live` instead of `--snapshot` explicitly enables new search and source fetches, requires positive frozen `search_usd`, and uses existing shared run/item/tool caps. It never calls OpenRouter. Each ordering condition has its own fetch budget; the union of pages fetched for both conditions may be up to twice that budget, with common fetches reused. Logs/accounting include all actual attempts. A missing replay page yields unavailable page/fact recall, not a demonstrated retrieval failure. Snippets remain lead metadata.

The historical runs used independently generated queries. Their artifacts do not supply an identical-query comparison for both providers; that measurement remains unrun.

## Controlled replay and paired reports

The [synthetic manifest example](../tests/fixtures/evidence_v3_replay.json) shows all required fields. Replace its synthetic identities and acceptance policy before an experiment. A manifest identifies the development question set, shared initial drafts/queries/results/pages, evidence policy, replication/acceptance criteria, and each arm's configuration, implementation and component model/prompt versions. The first arm is the baseline. Declared `changed_components` must match actual component-identity differences.

```bash
.venv/bin/python -m jev_solver replay-validate --manifest tests/fixtures/evidence_v3_replay.json
.venv/bin/python -m jev_solver replay-report --manifest private/control-manifest.json \
  --arm B2=private/control-b2/grades.json --arm J23=private/control-j23/grades.json \
  --workflow-cases private/control-workflow.jsonl --output private/control-report.json
```

`ControlledReplay` is a component orchestration utility. Frozen entries contain a complete `contract` and `response`; reuse requires matching component implementation/model/prompt, actual inputs and evidence policy. Changed downstream inputs cause a hard cache miss unless the caller explicitly supplies a generation callback. The ledger distinguishes `frozen`, `unavailable` and `new_call` behavior, including failed new calls. Configuration-scoped solver caches are not copied between arms. A full paid arm runner is not launched by manifest validation or reporting.

Reports require exactly the declared questions and replications in every arm, including errors and abstentions. `shared.questions_hash` is `digest(sorted(question_ids))`. Multiple replications need explicit zero-based `replicate` fields in grades. Reports include full-set accuracy, coverage, answered accuracy, wrong-answer acceptance, latency, accounted cost, paired question differences and question-clustered uncertainty. Optional workflow rows tagged with `arm` also produce per-arm gate metrics. Held-out validation remains separate from these inspected development cases.

### Expanded Terra/Haiku saved-component review

Use `--expanded` during preparation to include every available J2, J3 and historical
audit record and omit Luna. This mode requires an explicit `--cap`; the original
36-case pilot and its $6 limit remain available without `--expanded`.

```bash
.venv/bin/python -m jev_solver.evaluation.label_pilot \
  --expanded --cases private/v3-test-plan-implementation/cases/label-cases.jsonl \
  --catalog private/v3-label-expanded-2026-11-05-preparation/models-preflight.json \
  --output private/v3-label-expanded-review --cap 15
# Dispatch only after selecting the experiment's spending cap:
.venv/bin/python -m jev_solver.evaluation.label_pilot \
  --output private/v3-label-expanded-review --live
```

The example $15 cap is illustrative. The completed 2026-11-05 run used the user-authorized $20 aggregate cap; see the [expanded review report](EVIDENCE_V3_EXPANDED_REVIEW.md). Expanded reviews use twelve concurrent
provider calls (the original pilot uses three), independent identical inputs, immutable request/plan hashes, zero retries,
and durable reservations. Resume with the same plan; ambiguous dispatched attempts are
never automatically repeated. The ledger enforces the cap incrementally; the sum of all
maximum request reservations can exceed it. A cap below actual total usage can leave
records unavailable. Invalid reviews retain their charges and validation failure reason.

All 1,811 historical occurrences are retained, including one repeated component input
(1,810 distinct inputs); do not treat them as independent questions. The frozen plan
lists omitted search/reference records and a deterministic random ordering for later
agreement inspection. Before examining review outcomes, use the first five valid
agreements per component in that ordering as the agreement inspection sample, alongside
consequential disagreements and invalid outputs. Record adjudication separately; raw
reviews never become accepted gold automatically. Haiku only supplies disagreement notes.

On 2026-11-05 the expanded run completed all 3,622 Terra/Haiku calls and 41 independent
Astra spot checks. Actual charges were $10.49382690 within the approved $20 aggregate
cap. The full regression suite passed 200 tests with one optional Docker skip.
Preparation/draft directories remain separate from the completed artifacts at
`private/v3-label-expanded-2026-11-05/`. Original labels remain unresolved; this
component review did not run controlled solver arms.
