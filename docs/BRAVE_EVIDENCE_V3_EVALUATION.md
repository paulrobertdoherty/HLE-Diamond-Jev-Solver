# Brave evidence-v3 evaluation — 2026-11-01

Evidence-v3 reduced wrong answers but lowered overall accuracy and increased cost in this 50-question development rerun. It does not demonstrate an accuracy improvement over evidence-v2.

Both runs used the same 50 development questions, Sol low backbone, Jev version, Brave Search backend and Astra reference-grader settings. All new predictions were finalized before references were joined. The held-out split was not evaluated. This is a descriptive comparison of complete pipelines: prompts, auditing, rounds, eligibility rules and per-item/finalization budgets changed; fresh model samples and live sources also vary. No matched v3 B2 control or shared-initial/source replay was run.

| Measure | Evidence-v2 | Evidence-v3 |
| --- | ---: | ---: |
| Correct / full-set accuracy | 22/50 (44%) | 16/50 (32%) |
| Wrong nonempty answers | 17 | 5 |
| Completed abstentions | 11 | 25 |
| Solver errors | 0 | 4 |
| Timeouts / budget failures | 0 / 0 | 0 / 0 |
| Coverage | 78% | 42% |
| Accuracy among answered items | 56.4% | 76.2% |
| Solver accounted cost | $1.4511 | $8.0747 |
| Grading cost | $0.4210 | $0.2667 |
| Total solver + grading cost | $1.8721 | $8.3414 |
| Mean item latency | 34.5 s | 114.4 s |
| Grader errors | 0 | 0 |

All 50 questions remain in the denominator, including abstentions and solver failures. The $10 solver and $5 grading caps were respected. Costs use the harness's frozen rates and reported usage, with conservative reservations for uncertain calls; they are not invoice reconciliations.

The paired change is **−12 percentage points**, bootstrap 95% interval **[−26, +2] pp**, exact McNemar **p = 0.146**. Three previously incorrect outcomes became correct; nine previously correct outcomes became incorrect. This small, repeatedly inspected development set does not establish a reliable generalization effect in either direction.

| Evidence-v2 outcome | v3 correct | v3 wrong answer | v3 abstention | v3 error | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Correct | 13 | 3 | 4 | 2 | 22 |
| Wrong answer | 1 | 2 | 12 | 2 | 17 |
| Abstention | 2 | 0 | 9 | 0 | 11 |
| Total | 16 | 5 | 25 | 4 | 50 |

Twelve of the seventeen previous wrong answers became abstentions and two became solver errors. Four previous correct answers became abstentions, two became errors and three became wrong answers. Thus the reduction in wrong answers includes suppressed correct answers and execution failures. Fresh samples and source changes prevent assigning those transitions solely to the new gate.

## What the traces establish

The previously missing verification paths now execute. The new run recorded 206 candidate assessments, 111 candidate-rejection events and 21 structured selection bases, one for every returned answer. Coverage statuses across assessment events were 39 passed, 75 failed, 55 unavailable and 37 not run. These are repeated candidate assessments, not question counts or independently labeled verification accuracy. Five selected answers were still graded wrong, so passing the implemented coverage and selection checks remains insufficient to establish correctness.

| Accounted attempts | Evidence-v2 | Evidence-v3 |
| --- | ---: | ---: |
| Backbone | 123 | 363 |
| Jev | 503 | 550 |
| Brave searches | 36 | 60 |
| Fetches | 106 | 124 |
| Sandbox executions | 3 | 3 |

There were zero Jev outages. V3 recorded 79 settled fetches and 45 failed/uncertain fetch attempts, versus 78 and 28 in v2. More searches/fetch attempts therefore produced almost the same number of settled fetches; this does not measure source usefulness. Research outcomes and selection reasons are present in the private traces. The new solver cost was **5.56×** v2's, and mean item latency was **3.32×** v2's. Most of the additional spend was backbone usage: $7.7405, versus $1.2495 before the changes.

Four item errors occurred: two `ValueError` failures during revision, one `ValueError` during selection, and one initial `ProviderError`. The provider failure is directly explained by the saved response: output was incomplete with `finish_reason: length`. The revision errors occurred before a new model-response event; the input-envelope guard is a plausible explanation, but the trace records only exception type, so the exact message is not established. The selector returned a candidate and three dependency references before its error; the current validator can reject a basis that does not match passed critical dependencies. Its exact failed condition also needs offline reproduction. These errors were retained, with no replacement retests or source changes during this evaluation.

## Interpretation and next work

V3 traded coverage for higher accuracy among returned answers, while worsening the observed full-set score and substantially increasing spend. It should not be presented as an overall improvement on this evidence. The earlier empty-check bypass is replaced by explicit audits, but the resulting verification policy remains fallible and can withhold correct answers.

First reproduce the four failures offline, add private diagnostic exception messages, and bound revision/audit context growth. Then examine the four correct-to-abstention cases and the five wrong selected answers to distinguish unavailable evidence, overly strict requirements, missed contradictions and mistaken derivation audits. Any changes should be tested in a separately identified development run. A matched B2/J23 study and independent component labels are needed before attributing gains or losses to Jev. Freeze policies before evaluating fresh questions.

Validation: 146 regression tests ran successfully with one optional Docker test skipped; lint and formatting checks passed. The pinned sandbox image was verified, and the live run made three sandbox execution attempts. These checks establish implementation contracts, not benchmark correctness.

## Artifacts

The subsequent [v3 attribution analysis](EVIDENCE_V3_SEARCH_ATTRIBUTION.md) reproduces the error causes offline, compares evidence handling with Perplexity, and provides a test-design handoff.

Aggregate comparison: this report. Private artifacts, including question IDs, predictions, references and source content, remain ignored:

- Run: `private/sol-low-evidence-v3-j23-brave`
- Grading: `private/sol-low-evidence-v3-j23-brave-evaluation/grades.json`
- Paired comparison: `private/sol-low-evidence-v3-vs-v2-brave.json`
- Reconciled metrics and transitions: `private/sol-low-evidence-v3-brave-analysis.json`
- Reconciliation script: `private/analyze-v3-brave.py`
- Configuration: `configs/sol-low.evidence-v3.j23.brave.json`

Historical findings remain in [the v2 Brave error analysis](BRAVE_ERROR_ANALYSIS.md) and [the root-cause investigation](JEV_SEARCH_ROOT_CAUSE.md).
