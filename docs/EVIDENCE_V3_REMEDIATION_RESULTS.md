# Evidence v3 remediation implementation

The comparison baseline is **`9a7a1aa9090960fa353ecb836f96c9da3b2b2c6a`**, committed and pushed to `main` before implementation. The original historical solver remains a separate frozen source snapshot with implementation hash `51b6b4ab4ced7b4c9160b2f401014e6aa53c5889dd23efb84529df8ef78a6d0d`. Historical artifacts and expected outcomes were preserved.

Implementation and deterministic validation are complete. **Semantic promotion, fresh paid comparisons, and adjudication remain pending.** No benchmark accuracy improvement is established, and no paid evaluation was launched.

## Changes and policy selection

| Step | Commit | Behavior |
| --- | --- | --- |
| R0 | `a3c5bdf` | Comparison/environment/artifact identities, isolated historical reproduction, boundary accounting |
| R1 | `f9b32ef` | Exact quote resolution, source identity binding, legacy citation adapter |
| R2 | `864be46` | Conservative context construction, identified excerpts, durable one-per-item complete generation recovery |
| R3 | `07fe527` | Anchored question contracts, stable logical premises, graph validation and invalidation |
| R4a | `afcd6c3` | Canonical definition/theorem/table views and source coordinates |
| R4b | `ffc0686` | Structural shortlist reservations with source/query rotation |
| R4c | `a4ad08d` | Dependency coverage packets, hostname preference, immutable evidence ledger |
| R5 | `6ce5462` | Local subfact relevance and family-separated adjudicated calibration |
| R6 | `6ea18aa` | Shared atomic support requests, typed verdicts, multi-source aggregation and conflicts |
| R7 | `d976807` | Independent final applicability and whole-answer gate |
| R8 | `1f2b706` | Engine orchestration, isolated comparison source execution, manifests, durable aggregate caps and private adapters |
| Trace correction | `a22f460` | Active policy versions and merged dependency associations in boundary metrics |

The `remediation` configuration object independently selects `citations`, `context`, `generation`, `contract`, `structure`, `shortlist`, `packet`, `relevance`, `support`, and `final`. Each accepts `legacy-v1` or `remediation-v1`; every default is `legacy-v1`. `structural_slots` defaults to four. Existing configuration files were not edited, and B0/B1 reject remediation activation.

New profiles are [remediation.synthetic.json](../configs/remediation.synthetic.json) and the four `configs/sol-low.remediation.{b2,j23}.{brave,perplexity}.json` development profiles. Live profiles preserve two searches, four fetches, two rounds, twelve dependencies, twelve shortlist slots, six passages, 12,000 evidence characters, and all original call/dollar/deadline reserves. Contract generation, decomposition, final checks, and recovery consume those allowances. J2 admission thresholds remain the control.

Contracts identify `citation-quotes-v1`, `bounded-context-v1`, `canonical-excerpts-v1`, `question-contract-v1`, `structured-views-v1`, `local-subfact-relevance-v1`, `atomic-source-support-v1`, and `whole-answer-v1`. Question text/images, premise/source/artifact identities, actual submitted contexts, and component/schema/model/prompt versions participate in validation or replay identity. Resume preserves corrections, reservations, and consumed recovery allowances.

## Validation results

Final full discovery: **250 tests, zero failures, one optional Docker integration skip**. The new remediation modules contain 50 tests, including the available private adapters. Required focused suites also passed: v3 regressions (17), historical private adapters (5), verification contracts (18), evidence workflow (17), and search attribution (22). Ruff lint, formatting, and `git diff --check` passed.

Frozen historical reproduction recovered **100/100 saved outcomes and 153/153 packet sequences**, with zero packet mismatches and zero external dispatches. All recorded immutable artifact hashes remained unchanged. Derived results are under ignored `private/v3-remediation/historical-final/`; comparison identities and environment are in `private/v3-remediation/comparison.json`.

Private deterministic diagnostics in `private/v3-remediation/diagnostics-final.json` found:

- Three exact citation spans recovered from the actual saved passages. New semantic eligibility and correctness remain unmeasured.
- All three historical rejected envelopes reconstructed exactly, then compacted from 66,969 / 74,274 / 72,977 to 61,342 / 63,047 / 61,731 conservative units. Original questions/images remain intact. No replacement generation was attempted on these historical inputs.
- The coverage packet variant admitted 31 additional unique-text occurrences across the 153 saved packet sequences with the frozen control judgments. These are occurrence diagnostics, not independent questions or accuracy gains.
- Three stronger-reviewed shortlist omissions were replayed against their saved round sources. The development structural shortlist retained none of their ten reviewed exact quote spans. Synthetic structural fixtures pass, but these private diagnostics show that the current deterministic reservation does not establish recovery of those omissions. The policy remains experimental.

An isolated synthetic test ran the exact preserved comparison source alongside the new engine. A separate integrated synthetic B2/J23 test checked shared inputs, complete outcomes, final verification, and resume. Both use mock providers and incur zero external cost.

The documented CLI workflow also completed eight synthetic trials with zero external cost. There are 26 frozen, private 50-question development manifests under `private/v3-remediation/manifests/`: four exact-baseline integrated comparisons, two matched B2/J23 comparisons, and ten independent policy interventions for each search backend. Matched comparisons remain blocked from paid launch until their required frozen snapshots are supplied.

The sandbox stalled some async test/subprocess jobs. Completed replacement validation ran outside those restrictions with mocked transports; all three stale jobs were subsequently stopped. No background paid job is running.

## Running a controlled comparison

An offline synthetic example, using a new private destination:

```bash
.venv/bin/python -m jev_solver prepare --fixture tests/fixtures/tasks.jsonl --output private/remediation-demo/data
.venv/bin/python -m jev_solver replay-freeze \
  --experiment-id remediation-synthetic \
  --arm control=configs/j23.synthetic.json \
  --arm remediation=configs/remediation.synthetic.json \
  --questions private/remediation-demo/data/solver/questions.jsonl \
  --baseline 9a7a1aa9090960fa353ecb836f96c9da3b2b2c6a \
  --historical-hash 51b6b4ab4ced7b4c9160b2f401014e6aa53c5889dd23efb84529df8ef78a6d0d \
  --aggregate-usd 40 --comparison generation \
  --output private/remediation-demo/experiment.json
.venv/bin/python -m jev_solver replay-run \
  --manifest private/remediation-demo/experiment.json \
  --arm control=configs/j23.synthetic.json \
  --arm remediation=configs/remediation.synthetic.json \
  --questions private/remediation-demo/data/solver/questions.jsonl \
  --output private/remediation-demo/run
```

To execute the exact comparison revision, extract `git archive 9a7a1aa` into an ignored directory and add `--source-root control=PATH` while freezing. Its original engine/configuration execute in an isolated Python process, with their actual hashes checked. The historical reproduction helper separately runs the original historical snapshot; it does not substitute the comparison commit for that snapshot.

Version-2 manifests bind original question text and images, component identities, snapshots, replications, acceptance criteria, and item/run/aggregate caps. The runner retains every declared trial, including unavailable snapshots and failed attempts. Generated responses can be shared only under matching complete contracts, with replications kept separate. Full inference artifacts stay private; grade separately with isolated evaluator labels and use `replay-report` for paired question-clustered reports.

`replay-run` defaults to frozen live responses and synthetic generation. Fresh paid calls require the explicit `--launch` flag and frozen caps. A `matched-j23` launch additionally requires frozen initial/query/search/fetch snapshots for the declared workload; unmatched routing or source requests remain unavailable. Contract changes before drafting require a declared generation intervention. Provider blocks and matched-cost comparisons remain separate experiments.

## Pending promotion gates

Fresh J2/J3 representation comparisons, adjudicated calibration/validation families, whole-history semantic rates, the complete matched 50-question B2/J23 runs, integrated paid comparisons, and a fresh evaluation after policy freeze remain unrun. Provisional reviewer annotations are not gold labels. Neither relevance score nor confidence is a calibrated correctness probability. Wide paired uncertainty or unavailable labels yields an inconclusive result.
