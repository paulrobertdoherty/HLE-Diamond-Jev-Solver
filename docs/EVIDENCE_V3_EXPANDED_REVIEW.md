# Expanded Terra / Haiku saved-component review

Completed primary review on 2026-11-05. This follows the [initial pilot and handoff](EVIDENCE_V3_LABEL_PILOT.md). The user authorized a **$20 aggregate cap**. The component pass covered every proposed saved record; it did not repeat the solver experiment.

The evidence points to several distinct investigation targets: evidence lost before Jev, packet limits after relevance scoring, disputed source entailment, and Sol audits that may pass unchecked premises. These reviews do not establish a benchmark-wide Jev effect. Existing integration failures remain independently documented in the [trace-attribution report](EVIDENCE_V3_SEARCH_ATTRIBUTION.md).

The follow-up [citation failure analysis and harness changes](EVIDENCE_V3_FAILURE_ANALYSIS.md) traces these targets through individual sources and candidate histories. Its offline replay identifies the exact packet exclusions, documents a same-claim J3 discrepancy across citation contexts, and proposes bounded subquestion and verification routes. It preserves the provisional status of these reviews and separates implemented integration repairs from untested behavior changes.

## Scope and controls

Both reviewers independently received the same frozen evidence for **1,811 records**: 1,516 J2 passages, 142 J3 support checks and 153 historical audits, across 18 selected development-question aliases. All occurrences were retained, including one repeated component input (1,810 distinct inputs). They are not independent questions or a representative sample of the benchmark. The 48 search and 36 reference/history records were omitted explicitly.

Terra (`openai/gpt-6.1-terra`) was the provisional primary reviewer; Haiku (`anthropic/claude-haiku-5.5`) only recorded differences. Both used medium reasoning, provider restrictions and frozen rates. Original images were attached as images. Saved J2/J3 judgments, reference answers, grades and the other reviewer’s output were hidden. Audit reviewers saw the historical audit under review. No original labels were changed.

The expanded mode preserves the original 36-case, three-model pilot. A bounded pool of twelve workers limits clients and requests; durable reservations enforce the cap. There were no repairs, retries, provider errors, model mismatches, incomplete provider responses or uncertain charges in the primary pass. No fresh Jev calls, searches, fetches or solver arms were run.

## Output validity and cost

| Reviewer | Valid J2 / 1,516 | Valid J3 / 142 | Valid audits / 153 | Valid total / 1,811 | Reported cost | Conservative accounted cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Terra | 1453 | 141 | 151 | 1745 | $6.82698180 | $6.82857400 |
| Haiku | 1307 | 126 | 152 | 1585 | $1.23655260 | $1.23655260 |

**3,622 paid calls** produced 3,330 valid reviews and 292 invalid outputs. Primary reported cost was **$8.06353440**; conservative accounting was **$8.06512660**. The small difference reflects rate-based accounting versus reported charges. Calls used 9,112,101 input and 1,862,554 output tokens, including 1,275,527 reported reasoning tokens.

Terra had 58 source-quote mismatches and eight quote-format/length failures; Haiku had 221 source-quote mismatches and five quote-format/length failures. Invalid attempts and charges remain saved. Exact-substring validation applies to J2/J3; audit findings also pass their category/schema checks. Passing output validation does not establish semantic correctness.

## Independent comparison

| Component | Both valid | Main decision differs | Any labeled field differs | Pair unavailable |
| --- | ---: | ---: | ---: | ---: |
| J2 | 1261 / 1516 | 397 | 608 | 255 |
| J3 | 125 / 142 | 17 | 17 | 17 |
| audit | 150 / 153 | 97 | 117 | 3 |

Confidence or prose differences do not count. J2 additional fields are answer-bearing and contradiction; audit details include finding IDs/types. Different audit decomposition can create a detail disagreement without changing the diagnosis. Haiku never votes or overrides Terra.

## Provisional stage findings

**Before Jev:** 1,029 of the 1,516 J2 passages never received a saved judgment. Terra produced valid reviews for 980 of these, calling 12 direct and 144 partial. This is a shortlist/evidence-survival issue to inspect, not 156 Jev rejections. Another 49 lacked valid Terra reviews.

**Relevance policy and packet assembly:** among 367 valid Terra reviews of relevance-policy exclusions, Terra called five direct and 63 partial. Only four of those 68 had agreement on every labeled field with Haiku; 57 differed and seven had unavailable pairs. Partial evidence does not by itself prove that exclusion was erroneous. Separately, among 36 valid packet-limit reviews, Terra called ten direct and 21 partial. A packet-limit omission occurs after Jev and must not be counted as Jev rejection. Of 70 valid retained-passage reviews, Terra called 58 partial/direct, 11 background and one irrelevant.

**J3 source support:** Terra differed from 28 of 141 valid saved judgments: 24 supported → insufficient, two supported → contradicted, one insufficient → supported and one contradicted → supported. These concern nine aliases and eleven alias/backend pairs, not 28 independent question errors. Nine differences had complete labeled agreement with Haiku, eleven differed and eight lacked valid pairs. Ten occurred on historically correct final outcomes, demonstrating why a local difference is not automatically a lost answer.

**Sol audits:** of 151 valid Terra reviews, 96 were adequate, 53 under-restrictive, one over-restrictive and one unresolved. Haiku returned 64 adequate, 27 under-restrictive, 41 mixed and 20 unresolved among 152 valid reviews. The main diagnosis differed in 97 of 150 valid pairs. An under-restrictive premise check can occur inside an audit that ultimately rejects the whole answer; these counts are not wrong-answer acceptance rates.

## Stronger-model checks

Astra (`openai/gpt-6-astra`, medium reasoning) independently reviewed **41 records** without seeing the other reviews or saved J2/J3 verdicts. All 41 passed validation; there were no retries or uncertain charges. Its separately frozen $8 cap fit within the remaining aggregate allowance. Stronger-review accounting and reported cost were **$2.43029250**.

The selection comprised 15 predeclared agreement checks (five per component), six saved-J3 differences spanning different aliases, five J3 disagreements, five audit disagreements, three direct pre-Jev losses, three potentially direct relevance-policy exclusions, three invalid-output cases and the one potentially over-restrictive audit. Targeted cases are selected diagnostics, not a representative accuracy sample.

Astra agreed with every labeled field from Terra in **31 of 40** valid comparisons and differed in nine (eight main decisions); one Terra review was unavailable. In the 15 agreement checks, it matched fourteen and changed one J2 judgment from irrelevant to background. It matched Terra on all three selected direct pre-Jev losses, two of three selected direct relevance-policy exclusions, five of six saved-J3 differences, and the potential over-restrictive audit. It also rejected several Terra diagnoses. These are independent stronger-model checks, not human adjudications or accepted gold.

Concrete inspection targets are:

- **Instruction tables excluded by J2 policy:** two `input_visual_program/perplexity` passages explicitly map input/output commands to hue/lightness changes. Terra and Astra called both direct; Haiku called both partial. Saved Jev scores were **0.4833 and 0.4300**, below the **2/3** useful threshold. Their confidences **0.40 and 0.43** exceeded the **0.20** uncertain-alternative gate, so the historical policy excluded them. This links the source, judgment and exclusion mechanism; it does not prove that retaining them would repair the final answer.
- **Useful passages omitted before Jev:** Astra matched Terra on the three selected direct omissions, including theorem statements that supply the requested rank/field/quantifier parameters. These are shortlist losses, even when Jev judgments elsewhere are questionable.
- **Source entailment too permissive:** in `math_convention`, the supplied definition requires a finite factor-norm bound, while a saved supported claim says that only algebraic factorization is required. Terra and Astra both diagnosed explicit contradiction. Other stronger checks upheld concerns about unstated pathway-entry relationships, construction identification and transformed asymptotic notation; these remain scope-sensitive checks rather than question-level error counts.
- **Audit scope can also be too restrictive:** Astra agreed with Terra that one `selection_population_id/brave` audit blocked a qualified potential explanation by requiring a stronger terminology link than the candidate claimed. In a different audit from that alias, Astra rejected Terra’s under-restrictive diagnosis. Audit behavior must be reviewed per candidate, not assigned one verdict per question.
- **Terra is not a gold reviewer:** Astra found the `aria_title` audit adequate where Terra alleged a missing source link. On the checked `visual_lattice` audit, Astra agreed with Haiku’s adequate diagnosis against Terra’s unsupported-visual finding; that does not resolve the separate historical correctness grade. Astra also differed from Terra on some temporal-scope entailments. Keep these disputes unresolved.

**Total actual reported charge: $10.49382690; conservative accounted usage: $10.49541910**, across 3,663 paid review calls. The settled OpenRouter account usage change reconciled exactly to reported charges. All calls remained within the approved $20 aggregate cap.

## What the results establish

The expanded pass identifies specific evidence and verification decisions for investigation; it does not validate all diagnoses. Semantic false-support, false-rejection and audit-accuracy rates remain unavailable without adjudicated labels. All 1,895 original label records remain unchanged and unresolved. No human-checked calibration sample was created. Agreement, stronger-model reviews and self-reported confidence remain provisional evidence.

Saved trace joins identify candidate IDs, claim/passage identities and historical outcomes for each flagged record. They establish where a decision occurred and which saved outcome followed; they do not establish the counterfactual outcome had that decision changed. Historical citation-offset, selection-ID, context-envelope and fetch-planning defects remain separate from reviewer disagreement.

## Controlled comparison still required

The next causal experiment is a matched **B2/J23** comparison on all 50 development questions, blocking by search backend. Retain verification in both arms, use one implementation and identical solver settings, budgets, initial drafts, queries and saved source snapshots, and change only the relevance/support judge. If the component findings remain ambiguous, isolate J2 and J3 in separate arms. Test integration fixes as a separate intervention.

Reuse downstream responses only when the entire input contract matches. Changed evidence requires newly generated and accounted audit/revision/selection calls; old final outcomes cannot be relabeled as counterfactual trials. Predeclare all questions and replications, include every abstention/error, and report paired full-set accuracy, coverage, wrong answers, cost and uncertainty. The replay/report utilities exist, but the complete paid-arm runner and this causal experiment remain outstanding. Neither search-provider superiority nor a model-family explanation follows from this component pass.

## Artifacts and software validation

Private artifacts are in `private/v3-label-expanded-2026-11-05/`: the frozen plan, model/provider metadata, runner snapshot, request hashes, `events.sqlite3`, raw `pilot-results.json`, `analysis.json`, `terra-diagnoses.md`, `haiku-disagreements.md`, `trace-findings.json`, stronger-review provenance and accounting checks. The original pilot remains in its original directory.

The full regression suite ran **200 tests**, with zero failures and one optional Docker skip. The ten focused pilot/expanded tests cover isolation, actual image attachment, quote rejection, two-reviewer expanded mode, larger caps, deterministic sampling, retained duplicate occurrences, safe resume and Haiku’s note-only role. Repository-wide Ruff lint/format and `git diff --check` passed. The [usage guide](EVIDENCE_V3_TESTING.md#expanded-terrahaiku-saved-component-review) documents execution.
