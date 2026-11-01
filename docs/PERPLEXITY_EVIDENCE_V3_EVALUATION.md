# Perplexity evidence-v3 evaluation — 2026-11-01

Evidence-v3 reduced wrong answers but lowered full-set accuracy from **52% to 30%** and increased solver cost **5.22×** in this 50-question development rerun. It does not demonstrate an overall accuracy improvement over evidence-v2.

The evaluation followed the Brave v3 procedure: J23 on the same 50 development questions, Sol low backbone, pinned Jev version, Perplexity Search, then Astra reference grading after every prediction was finalized. The held-out split was not evaluated. The v3 implementation, dependency lock, protocol and question hashes match the Brave v3 run; the only configuration difference is `search_backend`. Compared with v2, the complete workflow changed, including prompts, auditing, rounds, eligibility rules and per-item/finalization budgets. Fresh model samples and live sources also vary. No matched v3 B2 control or shared-initial/source replay was run.

| Measure | Evidence-v2 | Evidence-v3 |
| --- | ---: | ---: |
| Correct / full-set accuracy | 26/50 (52%) | 15/50 (30%) |
| Wrong nonempty answers | 15 | 5 |
| Completed abstentions | 9 | 26 |
| Solver errors | 0 | 4 |
| Timeouts / budget failures | 0 / 0 | 0 / 0 |
| Coverage | 82% | 40% |
| Accuracy among answered items | 63.4% | 75.0% |
| Solver accounted cost | $1.5633 | $8.1660 |
| Grading cost | $0.4375 | $0.2452 |
| Total solver + grading cost | $2.0008 | $8.4112 |
| Mean item latency | 50.3 s | 115.7 s |
| Grader errors | 0 | 0 |

All 50 questions remain in the denominator, including abstentions and failures. The $10 solver and $5 grading caps were respected. Costs use frozen harness rates and reported usage, with conservative reservations for uncertain attempts; they are not invoice reconciliations.

The paired change is **−22 percentage points**, bootstrap 95% interval **[−36, −8] pp**, exact McNemar **p = 0.0127**. Three previously incorrect outcomes became correct; fourteen previously correct outcomes became incorrect. This is a small, repeatedly inspected development set, and the statistical comparison is unadjusted for multiple comparisons. It does not establish a generalization effect or isolate the contribution of Jev, search quality or the new verification policy.

| Evidence-v2 outcome | v3 correct | v3 wrong answer | v3 abstention | v3 error | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Correct | 12 | 0 | 11 | 3 | 26 |
| Wrong answer | 2 | 4 | 8 | 1 | 15 |
| Abstention | 1 | 1 | 7 | 0 | 9 |
| Total | 15 | 5 | 26 | 4 | 50 |

Eight previous wrong answers became abstentions and one became a solver error. Eleven previous correct answers became abstentions and three became errors. Thus the reduction in wrong answers came with substantial suppression of correct answers. Fresh samples and source changes prevent assigning those transitions solely to the eligibility gate.

## What the traces establish

V3 recorded 204 candidate assessments, 100 candidate-rejection events and 20 structured selection bases, one per returned answer. Coverage statuses across assessments were 34 passed, 74 failed, 58 unavailable and 38 not run. These are repeated assessments, not question counts or independent labels of verification accuracy. Five selected answers were graded wrong, so passing the implemented checks remains insufficient to establish correctness.

| Accounted attempts | Evidence-v2 | Evidence-v3 |
| --- | ---: | ---: |
| Backbone | 129 | 358 |
| Jev | 519 | 650 |
| Perplexity searches | 32 | 62 |
| Fetches | 100 | 134 |
| Sandbox executions | 4 | 2 |

There were zero Jev outages. V3 recorded 104 settled fetches and 30 failed/uncertain fetch attempts, versus 84 and 16 in v2. These counts do not measure source usefulness. Backbone usage accounts for most of the cost increase: $7.8162 versus $1.3802. Mean item latency increased 2.30×.

All four solver errors were `ValueError` failures: two during revision and two during selection. The traces record exception type and phase but not the message, so their exact causes remain unconfirmed. No failed items were replaced or retested, and solver code was not changed during the evaluation.

## Comparison with Brave v3

| Measure | Brave v3 | Perplexity v3 |
| --- | ---: | ---: |
| Correct / full-set accuracy | 16/50 (32%) | 15/50 (30%) |
| Wrong nonempty answers | 5 | 5 |
| Completed abstentions | 25 | 26 |
| Solver errors | 4 | 4 |
| Coverage | 42% | 40% |
| Accuracy among answered items | 76.2% | 75.0% |
| Solver accounted cost | $8.0747 | $8.1660 |
| Mean item latency | 114.4 s | 115.7 s |

Both v3 runs show a similar coverage/cost tradeoff. The one-question accuracy difference does not establish that either search backend is better. These are separate live runs without shared stochastic initial responses or source caches. See the [Brave evaluation](BRAVE_EVIDENCE_V3_EVALUATION.md) for its comparison with v2.

## Interpretation and next work

V3 increased accuracy among returned answers while reducing full-set accuracy and substantially increasing cost. The implemented audits execute, but this evidence does not support presenting v3 as an overall improvement. Reproduce the revision and selection errors offline, record private diagnostic messages, and examine the eleven correct-to-abstention cases and five wrong selected answers before changing policy. Independent component labels and a matched B2/J23 study are needed to assess Jev's contribution. Use a separately identified run for any fixes and freeze policy before evaluating fresh questions.

Validation: 146 regression tests passed with one optional test skipped; lint and formatting checks passed. The initial restricted-network solver attempt failed before producing answers and was preserved separately under `private/sol-low-evidence-v3-j23-perplexity-network-failed`; it is excluded from these benchmark metrics. The successful run used a fresh output directory after network access was enabled. A regression-suite attempt also stalled under restricted networking; the completed suite ran with networking enabled. These checks establish implementation contracts, not benchmark correctness.

## Artifacts

The subsequent [v3 attribution analysis](EVIDENCE_V3_SEARCH_ATTRIBUTION.md) reproduces the error causes offline, compares evidence handling with Brave, and provides a test-design handoff.

Question IDs, predictions, references and source content remain in ignored private artifacts:

- Run: `private/sol-low-evidence-v3-j23-perplexity`
- Grading: `private/sol-low-evidence-v3-j23-perplexity-evaluation/grades.json`
- Paired comparison: `private/sol-low-evidence-v3-vs-v2-perplexity.json`
- Reconciled metrics and transitions: `private/sol-low-evidence-v3-perplexity-analysis.json`
- Reconciliation script: `private/analyze-v3-perplexity.py`
- Runner: `private/run-v3-perplexity.py`
- Configuration: `configs/sol-low.evidence-v3.j23.perplexity.json`
