**Why retrieved findings did not reliably improve answers — investigation of `2a1565a`, 2026-11-01**

The main failure is in the evidence-use contract implemented by this repository. The initial answer determines what gets searched, the search query determines what Jev considers relevant, and the answer's optional source declarations determine what Jev verifies. An unverified factual guess can pass through all three stages and remain eligible for final selection. Useful evidence sometimes corrects answers, but the workflow does not reliably require unresolved facts to be checked or corrections to be made.

This investigation follows the [Brave audit](BRAVE_ERROR_ANALYSIS.md) and [Perplexity audit](PERPLEXITY_ERROR_ANALYSIS.md) in the last commit. Both offline audits were rerun successfully. The current Python implementation hash matches both recorded evidence-v2 runs. Additional checks reproduced the acceptance bypass and inspected classifier inputs, recorded uncertainty, and the consequences of blanket rejection rules. Existing predictions and Astra grades were retained; no new model/search calls or grading were performed. Public TypeSafe documentation was checked separately for the training question.

| Observed measure, same 50 development questions | Brave J23 | Perplexity J23 |
| --- | ---: | ---: |
| Correct / incorrect nonempty / abstained | 22 / 17 / 11 | 26 / 15 / 9 |
| Incorrect final answers with no source claims or citations | 17/17 | 15/15 |
| Incorrect answers textually identical to their own initial answer | 16/17 | 14/15 |
| Incorrect answers receiving no research | 8/17 | 7/15 |
| Incorrect answers retaining explicit gaps | 9/17 | 8/15 |
| Jev relevance / citation-support judgments | 497 / 6 | 512 / 7 |
| Active selector abstentions / nonempty-pool selector calls | 1/40 | 3/44 |
| Correct final answers also lacking source claims and citations | 17/22 | 20/26 |

The 32 incorrect results are run outcomes on overlapping questions, not 32 independent test cases. Neither run had a Jev outage or solver failure. The reported Perplexity gain is four correct answers overall; only two of its five gains have a clear within-run retrieval-driven correction. Three already had the eventual correct conclusion in the fresh initial response. The sole lost correct answer received no research. These runs do not isolate Jev's contribution; matched B2 controls have not been run.

**What Jev actually did.**

The [J23 configurations](../configs/sol-low.evidence-v2.j23.perplexity.json) use `adaptive: false`, `selector: backbone`, one initial candidate, one research/revision round, two search requests, four fetch attempts, and one code execution. The two configurations differ only in search backend after normalization.

| Operation | Owner in these runs | Important boundary |
| --- | --- | --- |
| Initial solution, gaps, queries, revision | Sol | Jev does not generate queries or corrected prose. |
| Search | Brave or Perplexity Search API | Returns URL/title/snippet records. Perplexity is not generating the final answer. |
| Fetch, chunk, shortlist, packet limits | Repository code | Only a bounded subset of fetched text reaches revision. |
| J2 relevance | Jev | Receives query, passage, URL and title; omits the original question. |
| J3 support | Jev | Runs for valid submitted citations; checks their claims against their source text. |
| J1 routing, J4 constraints, J6 continuation | Disabled | These stages do not explain the measured Jev judgments. |
| Final selection | Sol | Chooses an existing answer or `none-supported`; Jev J5 is not used. |

The adapter creates `Score`, `Choice` and `Noul` specifications at request time and sends them to `system_one`; there are no separately registered or trained J1–J6 classifiers in this implementation. See [`providers/jev.py`](../src/jev_solver/providers/jev.py), `Jev._call`, and [`judgments/pipeline.py`](../src/jev_solver/judgments/pipeline.py).

**1. Required factual checks are bypassed by empty source declarations — confirmed in code and all incorrect final candidates.**

[`providers/backbone.py`](../src/jev_solver/providers/backbone.py), `SYSTEM` at lines 55–69, defines `source_claims` as facts used from supplied passages. A fact recalled from model knowledge may therefore have no source claim, just like an independent mathematical derivation. [`models.py`](../src/jev_solver/models.py), `Candidate`, has no separate inventory of necessary factual premises or evidence establishing an independent derivation.

[`judgments/pipeline.py`](../src/jev_solver/judgments/pipeline.py), `missing_source_claims` and `verify`, only examine declared source claims and citations. With empty lists, neither function discovers missing factual dependencies, and J3 is never called. [`controller/engine.py`](../src/jev_solver/controller/engine.py), `Solver.assess` at lines 193–223, skips J4 because `adaptive` is false. It accepts any nonempty answer whose three failure lists are empty. Explicit `gaps` and admissions of uncertainty in `verification` do not affect that Boolean.

An offline synthetic probe supplied a nonempty factual guess, an explicit necessary verification gap, no evidence and empty claims/citations. The actual `assess()` returned `accepted: true`, all check/failure lists empty, and zero Jev requests. The same path is recorded for all 17 Brave and 15 Perplexity wrong final answers. Initial candidates are assessed through this rule too, allowing an unsupported initial answer to remain selectable after research.

This is a coverage defect in verification. Even a perfect citation-support classifier would not fix facts it is never asked to check. J3's stated task is source entailment, so a positive J3 result also cannot establish source reliability, a complete derivation or correctness of an entire multipart answer. All 13 observed support judgments returned `supported`; these selected citations do not measure how reliably J3 detects contradictory or insufficient support on independently labeled negative cases.

Implementation requirement: inventory necessary dependencies independently of whether the model says it used a passage. Distinguish factual, derived, visual and numerical dependencies; record which are critical and which actual sources/check artifacts address them. A separate completeness check must be able to find omitted dependencies. Represent `not_run`, `not_applicable`, `unavailable`, `passed` and `failed` explicitly. Candidate eligibility should use these results and a declared coverage policy, rather than interpreting absence of failures as verification.

**2. The retrieval judgment receives a biased, incomplete task — confirmed evidence loss; exact remedy still needs measurement.**

`Solver.research` at lines 107–191 takes `candidate.queries[:3]`, or falls back to the first raw gap sentence. `chunk_page` stores that search string as `EvidencePassage.subquestion`. J2 receives it as the missing fact, without the original question, image interpretation, or a neutral statement of what must be established. Queries can therefore ask about an assumed answer, while generic gap sentences can retrieve material unrelated to the task.

In the repeated art-history case, both backends fetched the same article and the answer-bearing passage actually reached J2. It was discarded at normalized scores 0.3567 and 0.3533, below the hard 2/3 cutoff. A different passage matching the initial guessed feature survived at 0.7667 and 0.7833. The revision received only that surviving passage and acknowledged missing verification. Thus the loss occurred after successful source retrieval, inside the evidence selection pipeline.

The additional cache inspection shows `confidence: 0.0` on both discarded judgments, with probabilities spread across all four relevance levels. The cutoff turns those uncertain judgments into definitive exclusion without review. The retained passages' confidences were 0.30 and 0.33. This does not mean low confidence should automatically admit a passage; it means uncertain, potentially useful evidence needs an evaluated handling policy.

The division by three in `Jev.request` is consistent with TypeSafe's four-level Score contract. A Score is an expected position on ordered levels; neither the normalized score nor its confidence is a probability that the final answer is correct. The suspected issue is task definition and filtering policy, not an observed scale-conversion bug. See [TypeSafe Score documentation](https://docs.typesafe.ai/primitives/score).

Implementation requirement: keep the original question, a neutral missing fact and the actual search query as separate fields. Rank evidence for its ability to resolve the fact, including evidence contradicting the initial guess. The current rubric's “supports part” wording should explicitly cover disconfirming evidence or be separated from a support-direction judgment. Preserve bounded alternatives for uncertain cases and measure answer-bearing passage recall before choosing a threshold. No new Jev calls were made here, so adding context has not yet been demonstrated to repair this particular judgment.

**3. Research stops before it can use feedback — confirmed configuration and trace behavior.**

`Solver.solve` breaks before research when the candidate lists no queries, gaps or code (lines 241–243). This accounts for the eight Brave and seven Perplexity wrong answers receiving no research. Routing is downstream of that break, so even an adaptive router would not discover omissions on that path without changing the controller.

For researched wrong answers, eight of nine Brave cases and all eight Perplexity cases used only one of the two allowed searches. The one-round configuration allows several queries planned in advance, but cannot observe an inconclusive packet and then execute a newly planned query in another round. Five of those eight Perplexity cases still had one unused fetch slot; three had exhausted all four. Increasing search allowance alone would not resolve either stopping or fetch exhaustion.

The fetch loop follows provider result order within query quotas. It does not use snippets to prioritize URLs. A sixth allowed Perplexity result contained a potentially decisive name in its snippet, but four earlier fetch attempts consumed the allowance, with three failures. That lead was never fetched. A fetch might still have failed, and the snippet itself did not independently establish the fact. This is a missed investigation opportunity, not proof that another fetch would have produced a correct answer.

Search metadata and fetch failures are logged, but revision context receives only the evidence packet and code artifacts. A model seeing an empty packet cannot inspect the unused leads or distinguish the detailed causes of retrieval failure. See [`tools/web.py`](../src/jev_solver/tools/web.py), `PerplexityWeb.search` and `AuditedWeb.search`, and `Solver.research`/revision context.

Implementation requirement: add an explicit verification-planning step that can identify missing facts even when the initial draft declares no gaps. Generate neutral, specific queries, use filtered snippets as fetch leads, return structured research outcomes to the planner, and reserve fetch capacity for a bounded follow-up when justified. Continue to require fetched, audited passages for source support. Recompute call/cost reserves when adding rounds; the current cap is 45 calls, and J2 can judge 20 passages per round.

**4. Revision and selection preserve an answer without establishing its basis — observed behavior with a plausible anchoring mechanism.**

The revision and selection prompts emphasize preserving independently justified answers when research is inconclusive. The candidate structure and assessment do not establish which answers meet that condition. Consequently an accepted factual guess and a checked derivation look similar to the selector. Thirty of the 32 wrong final answer strings exactly match their own initial response; the other two retain the wrong conclusion. Prompt anchoring and correlated errors from the same Sol model are consistent explanations, but their individual causal effects have not been isolated.

[`candidates/selection.py`](../src/jev_solver/candidates/selection.py), `select`, supplies actual retained evidence and tool artifacts, so this is not a wholesale failure to pass findings to Sol. However, its output schema contains only a candidate ID. It cannot create a correction absent from the candidate pool, and records no reason why an answer is sufficiently established or why a gap is noncritical. It returned answers on 39/40 Brave and 41/44 Perplexity nonempty pools, including every wrong final answer. One Perplexity rejection also discarded an initial answer matching the reference.

Implementation requirement: make revisions resolve identified dependencies and contradictions, validate earlier candidates against the same evidence, and require a concise, structured selection basis tied to actual checks. If evidence warrants a new answer, create and assess that candidate before selecting. Evaluate both wrong-answer acceptance and correct-answer rejection; changing the selector to Jev would be a separate experiment, not a demonstrated remedy.

**5. Existing later-stage classifiers cannot simply be switched on to close these gaps — confirmed code limitations.**

`Config.validate` requires `Jfull` for `adaptive: true`, and forbids the Jev selector in J23. Moving to Jfull changes the experiment. Further, `constraints()` asks about consistency with verification artifacts but passes only the question and serialized candidate; it receives no actual evidence packet or code-result objects. Its units, scope, assumptions and consistency checks do not explicitly establish factual dependencies. These are additional implementation issues, not causes attributable to a stage that did not run.

Image interpretation and computational failures require suitable checks too. The backbone receives original images, while the current Jev request path does not. In a saved mechanics abstention, a repaired program was generated after execution failed, but the one-round/one-execution policy left it unexecuted. Search or text-classifier training alone does not validate a visual reading or run corrected code.

**What requires work outside this repository.**

**No customer Jev fine-tuning or classifier registration is required for the proposed fixes.** TypeSafe currently states that Jev has shared weights and does not offer customer fine-tuning or LoRA adaptation. Domain customization uses request `state`, `instructions` and `criteria`; the repository already supplies these at inference time. Changes to those inputs and to when judgments are invoked belong here. See [TypeSafe's customization guidance](https://docs.typesafe.ai/models#customizing-jev), checked 2026-11-01, and the [System One request contract](https://docs.typesafe.ai/api/system-one).

| Work | Where it belongs / dependency |
| --- | --- |
| Dependency accounting, relevance context, contradiction handling, fetch planning, continuation, selector basis, check-status logging | Repository implementation; no external training prerequisite. |
| Real relevance/support/criticality labels, including omitted facts, contradictory passages and correct independent solutions | Requires annotation and often subject expertise beyond a code change. Keep labeled cases private and separate from solver inputs. |
| Validate revised Jev questions and calibrate filtering/abstention policies | Harness changes can live here; new judgments require TypeSafe access/budget and independent labeled development cases. Saved responses cannot answer newly worded questions. |
| Measure end-to-end benefit with matched B2/J23 runs and fresh validation cases | Requires provider/search/grading calls, budget and a frozen evaluation design. Current inspected cases are useful regressions, not fresh evidence of generalization. |
| Optional learned reranker or correctness/continuation policy using Jev outputs | A separate downstream model could be trained locally and integrated here, but needs independent labels, feature generation and held-out validation. It is not training Jev's weights, and is not justified as the first fix by these traces. TypeSafe describes this option in its customization guidance above. |
| Specialist visual or computational verification | May require a suitable model, library or executable and environment support; choose based on demonstrated failure cases and the pinned tool protocol. |

Improving inactive J1/J4/J5/J6 question definitions would have no effect on the measured J23 workflow until invocation and context delivery change. There is no evidence here that a missing account-side training job caused the failures.

**Implementation order and validation handoff.**

1. Fix the dependency/check-status contract and the missing original-question/neutral-fact context together. Preserve independent derivations, and cover undeclared necessary facts. Define a separate verification-coverage decision instead of overloading `accepted`.
2. Add feedback-driven research within explicit limits, including snippet-informed fetch ordering and meaningful failure outcomes. Separate an unsuccessful search from evidence refuting a proposal.
3. Make revision and selection consume dependency results and actual artifacts. Add narrow visual/numerical checks where appropriate; distinguish generated code from successfully executed code.
4. Build component evaluation before deciding whether prompt changes, new thresholds or a downstream learned policy help. [`evaluation/components.py`](../src/jev_solver/evaluation/components.py) currently reports exact equality for J2's continuous scores plus mean absolute error; exact numeric equality is unsuitable as the main relevance decision metric. Add evidence recall at the packet budget, useful/contradictory-passage exclusion rates, claim-coverage recall, support confusion matrices, and selector error rates. The committed component fixtures are four synthetic cases, not domain validation.
5. Compare components on identical saved inputs, then run matched B2/J23 arms within each backend. Share initial candidates and cached sources where the experiment is intended to isolate judgment quality; cache keys currently include the whole configuration, so cross-arm replay needs an explicit design. Report full-set accuracy, answered-item accuracy, coverage and cost. Freeze policies before fresh evaluation.

Do not replace the bypass with a blanket citation or gap rule. On the saved outputs, rejecting every candidate without claims/citations would suppress 17 correct Brave answers and 20 correct Perplexity answers. Rejecting every candidate with any gap would suppress eight and nine correct answers respectively. These are offline counts, not predictions of a rerun after changing the policy. They show why necessary unresolved facts must be distinguished from incidental uncertainty and independent derivations.

Use the repeated filtered-passage case, the unfetched snippet lead, an undeclared factual guess with a critical gap, an independent derivation without citations, a contradicted earlier answer, and a generated-but-unexecuted code repair as regression scenarios. Retain the successful evidence-driven corrections too. Synthetic tests should establish routing and data contracts; real labels and new calls are needed to establish semantic judgment quality. The current audits retain the original grader outcomes, including cases where assumptions or answer formulation merit expert review.

**Reproduction and private evidence.**

From the repository root, at the investigated implementation revision:

```bash
.venv/bin/python private/validate-brave-error-audit.py
.venv/bin/python private/audit-perplexity-errors.py
.venv/bin/python private/check-jev-search-root-causes.py
```

The first two scripts reconcile the saved runs and reconstruct cached Jev requests. The new third script reproduces the unchecked-fact acceptance path without any provider, verifies the J4 input/configuration limitations, checks current implementation hashes, and computes the additional aggregate counts and decisive judgment uncertainty. It writes `private/jev-search-root-cause-validation.json`. The scripts regenerate derived audit files only; source run databases, predictions and grades are unchanged.

Exact question IDs, source excerpts, request hashes and candidate histories remain in `private/sol-low-evidence-v2-j23-{brave,perplexity}-error-analysis.md` and their audit JSON files. The scripts and private artifacts are ignored and must be transferred separately if a later session uses a different checkout. No solver behavior has been changed by this investigation.
