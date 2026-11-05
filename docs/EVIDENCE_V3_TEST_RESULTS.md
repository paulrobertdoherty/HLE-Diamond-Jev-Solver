# Evidence v3 test-plan implementation results

Validation completed 2026-11-02. The original baseline was committed and pushed as `d40ae78` before implementation. The [usage guide](EVIDENCE_V3_TESTING.md) describes the new commands, schemas, offline guard and recovery behavior.

This document records the implementation-validation phase. The subsequent authorized Luna/Terra/Haiku labeling pilot is reported separately in [AI-label pilot results](EVIDENCE_V3_LABEL_PILOT.md); its provisional judgments do not supply expert adjudications for the quality metrics below. The subsequent [full Terra/Haiku component review](EVIDENCE_V3_EXPANDED_REVIEW.md) completed all 1,811 proposed records plus 41 independent Astra spot checks on 2026-11-05. Those results also remain provisional; the adjudicated semantic metrics and controlled final-answer experiment below remain unavailable.

## Historical baseline

Before changing implementation files, the original source hash `51b6b4ab4ced7b4c9160b2f401014e6aa53c5889dd23efb84529df8ef78a6d0d` matched. The offline analysis reproduced **100/100 saved outcomes**, reconstructed **1,024 J2 requests**, and reproduced **521 assessment invocations**, including cache replay. External dispatches: **0**. The casebook regenerated **18/18 cases**. These are repeated runs on 50 questions and establish reconstruction, not semantic accuracy.

The actual baseline source/configuration snapshot is retained under ignored `private/v3-test-plan-baseline/`. Original run databases and grades were preserved. Changed implementation, audit schema and research-cache identity are a separate experiment.

## Test status by plan ID

Counts below refer to the new contract/harness tests, including private adapters when available. Existing verification, evidence, adapter and experiment tests provide additional coverage. A passing harness is not a model-quality result.

| ID | Software validation | Quality / live status | Boundary measured |
| --- | --- | --- | --- |
| T01 | Passed, 4/4 | Answer recovery accuracy unavailable; no new model repair experiment | Historical span rejection; Unicode/repeated/absent quotes; source identity; one bounded repair with critical semantic recheck |
| T02 | Passed, 5/5 | Repaired serialization does not establish answer correctness | All three historical selection-ID failures recover within selected scope; foreign, unrun, missing and ambiguous IDs remain rejected |
| T03 | Passed, 3/3 | Context reduction not implemented; no fresh generation experiment | Exact 66,969 / 72,977 / 74,274 conservative envelopes; no rejected-envelope dispatch; malformed citations and incomplete output rejected |
| T04 | Passed, 5/5 | Historically unfetched page availability and resulting answer accuracy unavailable | Historical ranks five/three; direct intended lead fetch; four-fetch budget/reserve; duplicate, blocked, unknown, failed and redirected leads |
| T05 | Passed, 4/4 | Audit discovery quality unavailable without independent labels | Complete gap mapping, stable IDs, distinct premises, all check states and incidental gaps; existing tests cover factual/visual/execution artifacts |
| T06 | Passed, 7/7 harness tests | Unavailable: 0 independently adjudicated audit cases; 153 frozen audit inputs prepared | Saved/fresh audit adapter, full candidate history, image observations, classifications, failed-trial denominators, immutable extraction |
| T07 | Passed, 4/4 harness tests | Unavailable: 0 labeled relevance cases; 1,516 fetched passages prepared | Survival before/after shortlist, relevance, packet limits; exclusions and actual passage identity; unexecuted judgments excluded from semantic accuracy |
| T08 | Passed, 1/1 harness test | Unavailable: 0 labeled entailment cases; 142 original request-matched J3 cases prepared | Confusion, unavailable judgments, false support and false rejection; original source context preserved |
| T09 | Passed, 5/5 harness tests | Live comparison not run; 48 historical query records prepared, no matched historical provider control | Identical queries, provider/local ordering, blocks/duplicates/redirects, extraction, missing snapshots and label isolation |
| T10 | Passed, 2/2 harness tests | Unavailable: 0 expert adjudications; 36 reference/history cases prepared | Immutable original grades, separate adjudicated scores, grader agreement and whole-history eligibility loss |
| T11 | Passed, 3/3 utility tests | Matched end-to-end experiment not run; 0 paired controlled trials | Manifest/intervention validation, input-contract replay, fresh-call ledger, complete paired reporting with uncertainty |

An additional dispatch-guard regression passed, bringing the new suite to **44 tests**: 17 synthetic boundary/guard tests, five private adapters and 22 evaluation-harness tests. All tests in these three suites forbid unintended external dispatch.

## Labels, usage and errors

Final extraction at `private/v3-test-plan-implementation/cases/` contains **1,895 unresolved records**. It includes 153 audit records after removing 40 repeated cache invocations, 1,516 J2 passages, 142 J3 requests, 48 search records and 36 original-grade/history records. Of the J2 passages, 487 have saved judgments and 1,029 were lost before J2. Those 1,029 are not labeled Jev rejections. These records cover inspected development cases and are not independent benchmark questions.

Stored component evaluation reports **1,658 unresolved relevance/entailment records**, zero scored cases and null accuracy. Workflow evaluation reports **189 unresolved audit/reference records** and zero labeled denominators. Missing labels are unavailable measurements. No expert adjudications, fresh Sol/Jev/Astra judgments, source fetches or live search comparisons were fabricated.

During implementation validation, new external API/tool calls were **0** and new accounted external cost was **$0**. Final contract/harness failures: **0**. The historical eight solver errors remain part of the reproduced baseline. Synthetic incomplete/malformed responses, failed fetches and invalid references are intentional fixtures, with explicit error/outage counts and trace reasons.

## Integration checks

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_verification_contract.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_evidence_workflow.py' -v
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
```

Full regression discovery at the end of implementation: **190 tests, zero failures, one optional Docker execution test skipped**. Ruff lint and formatting checks passed. Existing mocked SDK tests needed execution outside the restricted sandbox because their asynchronous thread handling hung inside it; their HTTP transport remained mocked. No paid evaluation was launched during those checks.

The current implementation verifies the contracts and provides the labeling/evaluation tools. Fresh behavioral targets require independent labels, predeclared budgets/acceptance criteria and subsequent measured runs. T11 orchestration is exposed as a component utility and reporting interface; the controlled live arm experiment remains unrun as required by the plan's ordering.
