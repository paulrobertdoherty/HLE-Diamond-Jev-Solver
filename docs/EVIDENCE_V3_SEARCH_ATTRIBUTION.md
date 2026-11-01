**Perplexity v3 versus Brave v3: failure attribution and test design**

Analysis of the two completed 2026-11-01 development runs.

**The evidence does not support choosing Jev or the search provider as the single cause. Several specific failures are demonstrably in the repository's integration with the Sol backbone.** Both providers sometimes deliver useful evidence, and Jev sometimes correctly retains it and rejects unsupported claims. Correct answers can still be lost through citation formatting, selection validation, dependency classification, or fetch planning. Conversely, Sol's whole-answer and visual reviews sometimes pass answers that the reference grader marks wrong.

The strongest next step is to test those demonstrated boundaries, then evaluate Jev and search quality on identical, independently labeled inputs. Replacing Brave with Perplexity did not resolve the v3 coverage problem. Similar final scores also do not establish that either provider, or Jev, is working well overall.

This analysis supplements the [Perplexity v3 evaluation](PERPLEXITY_EVIDENCE_V3_EVALUATION.md) and [Brave v3 evaluation](BRAVE_EVIDENCE_V3_EVALUATION.md). Their saved predictions and grades are retained. The [earlier root-cause investigation](JEV_SEARCH_ROOT_CAUSE.md) describes v2; its empty-check acceptance defect should not be treated as an unchanged explanation of v3.

**What the comparison actually controls**

The manifests agree on all 50 development questions, dataset and split, implementation, dependency lock, protocol, Sol model/settings, Jev version, and limits. The only configuration difference is `search_backend`. Neither run evaluates the held-out split. The successful Perplexity run began after Brave; the separately preserved Perplexity network-failed attempt is excluded.

The runs do not share model samples or source snapshots. Among 49 questions with a valid initial draft in both runs, only 11 initial answer strings match, including five pairs of empty answers; no complete initial draft objects match. Only three literal query strings are shared for the same questions. Thus, different downstream outcomes can begin with different reasoning, queries, dependency inventories, or source requirements before a search provider is called. The configured random seed does not make the provider responses identical.

All statements about correctness below use the existing Astra reference grades. Intermediate candidates have not been independently graded. A draft matching another run's correct answer is a useful regression example, not a new candidate-level accuracy estimate.

| Measure | Brave v3 | Perplexity v3 |
| --- | ---: | ---: |
| Correct / all 50 questions | 16 (32%) | 15 (30%) |
| Wrong nonempty answers | 5 | 5 |
| Completed abstentions | 25 | 26 |
| Solver errors | 4 | 4 |
| Coverage | 42% | 40% |
| Accuracy among returned answers | 76.2% | 75.0% |
| Solver accounted cost | $8.0747 | $8.1660 |
| Mean item latency | 114.4 s | 115.7 s |

Perplexity gains three correct outcomes and loses four relative to Brave. The paired difference is −2 percentage points, with a question bootstrap 95% interval of [−12, +8] points and exact McNemar p = 1.0. This small, repeatedly inspected development set neither establishes a provider advantage nor demonstrates equivalence.

| Brave outcome | Perplexity correct | Perplexity wrong | Perplexity abstention | Perplexity error | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Correct | 12 | 0 | 3 | 1 | 16 |
| Wrong | 0 | 3 | 1 | 1 | 5 |
| Abstention | 2 | 1 | 21 | 1 | 25 |
| Error | 1 | 1 | 1 | 1 | 4 |
| Total | 15 | 5 | 26 | 4 | 50 |

The same broad tradeoff appears against v2: Brave falls from 22 to 16 correct and Perplexity from 26 to 15, while wrong answers fall from 17 and 15 respectively to five each. Those comparisons change the complete verification workflow, prompts, rounds, and budgets. They do not isolate a Jev effect.

**Who makes each decision**

“Search agent” needs to be separated into its actual components in this repository. Perplexity uses its Search API, returning URL/title/snippet records; it does not write the final answer.

| Decision | Owner in these J23 runs | Relevant implementation |
| --- | --- | --- |
| Initial answer, missing dependencies, queries, criticality, factual/derived/visual classification | Sol backbone | [Backbone](../src/jev_solver/providers/backbone.py), [verification audit](../src/jev_solver/judgments/verification.py) |
| Search results | Brave or Perplexity Search | [Web adapters](../src/jev_solver/tools/web.py) |
| URL filtering, lead ordering, fetching, chunking, shortlisting, packet limits | Repository code and source availability | [Research controller](../src/jev_solver/controller/research.py), [evidence selection](../src/jev_solver/retrieval/evidence.py) |
| J2 passage relevance; J3 source entailment | Jev | [Judgment pipeline](../src/jev_solver/judgments/pipeline.py) |
| Derivation, image and whole-answer review; revision | Sol backbone, with artifact checks in code | [Verification audit](../src/jev_solver/judgments/verification.py), [solver](../src/jev_solver/controller/engine.py) |
| Eligibility and citation/ID validity | Repository code | [Solver](../src/jev_solver/controller/engine.py), [selection](../src/jev_solver/candidates/selection.py), [models](../src/jev_solver/models.py) |
| Final candidate choice and selection explanation | Sol backbone | [Selection](../src/jev_solver/candidates/selection.py) |

J1 routing, J4 constraints, J5 selection and J6 continuation are inactive in these configurations. Jev does not inspect the original images. The separate verification request uses the same Sol model as the solver; it is a separate review request, not an independent model or proof system.

**What differs in retrieval and verification**

| Recorded activity | Brave v3 | Perplexity v3 |
| --- | ---: | ---: |
| Questions receiving a search | 35 | 37 |
| Accounted search calls | 60 | 62 |
| Searches with nonempty allowed results | 56 | 62 |
| Accounted fetch attempts | 124 | 134 |
| Settled fetch calls | 79 | 104 |
| Failed/uncertain fetch calls | 45 | 30 |
| Research rounds | 76 | 77 |
| Rounds with no query | 16 | 15 |
| Rounds producing a nonempty evidence packet | 21 | 25 |
| Rounds with fetched text but an empty packet | 25 | 28 |
| J2 passage judgments | 456 | 568 |
| Passages excluded by relevance policy | 395 | 486 |
| Passages admitted by relevance policy but excluded by packet constraints | 18 | 30 |
| Passage placements in returned research packets | 43 | 52 |
| J3 judgments: supported / insufficient / contradicted | 82 / 11 / 1 | 70 / 11 / 1 |
| Jev outages | 0 | 0 |

Fetch counts come from the call ledger. Logical fetch entries can also include cache hits and blocks before dispatch, so they have different denominators. Packet placements count passages per round, not distinct relevant facts. All 1,024 J2 requests were reconstructed from the saved pages, original question, missing fact, query, and request hash; exclusions were then separated into relevance-policy and packet-constraint decisions.

Perplexity supplies more fetched material and more retained passages, without a corresponding full-set accuracy gain. This is evidence that downstream decisions matter, not proof that additional material is useless. The roughly 9% retention of judged passages is not a relevance error rate: many passages are background or unrelated, and the runs lack independent relevance labels. Successful HTTP retrieval likewise does not establish that the needed fact was present.

**Confirmed failures and informative cases**

**1. Useful evidence and a corrected answer can be lost solely at citation validation.** In the repeated art-history case, both v3 backends fetch the same decisive passage that v2 discarded. Jev assigns it normalized relevance scores of 0.8867 with Brave and 0.9867 with Perplexity; both packets retain it. Both runs then revise their initial wrong guess to the same answer. Their final dependency audits pass, including Jev support for the corrected factual claim.

Perplexity returns that answer and is graded correct. Brave abstains because all three corrected drafts cite invalid character offsets. Their quoted sentence exists exactly in the retained passage at offsets [1100, 1268); the drafts supply [1087, 1252), [1087, 1254), and [1087, 1255). The exact-span validator rejects them and leaves no eligible candidate. Its trace label `fabricated_span` denotes an offset mismatch here, not an invented quotation.

This locates the Brave loss after successful search, passage selection and factual support. It is a Sol citation-generation and repair/integration failure. It also supplies a positive Jev regression case: the historical v2 exclusion is absent in these v3 traces. The changed inputs and workflow prevent attributing that improvement to one prompt change alone.

**2. All eight item errors have reproducible causes outside Jev's semantic judgments.** Offline replay against the unchanged implementation reproduces all saved answers, abstentions, error types and candidate histories. The earlier evaluation reports could identify phases but not all exception messages. The replay resolves them:

| Reproduced cause | Brave | Perplexity | Boundary to test |
| --- | ---: | ---: | --- |
| Selector names a passed dependency as `candidate_0.d1` or `candidate_1:d1` rather than its actual `d1` ID | 1 | 2 | Sol output schema, dependency references and selection validation |
| Local conservative input-envelope guard rejects revision/repair before dispatch | 2 | 1 | Context construction and size management |
| Revision contains a nonempty citation with `start = end = 0` | 0 | 1 | Candidate parsing and bounded repair |
| Initial model response is incomplete with `finish_reason: length` | 1 | 0 | Backbone generation/output budget |

The three selection failures choose candidates with passed critical checks but qualify the dependency IDs with candidate names. The validator correctly refuses unmatched references; the workflow converts this recoverable contract mismatch into an item error. One Perplexity failure discards an answer identifying the same biological target as Brave's correct answer. Accepting the malformed reference blindly would weaken the contract; test structured references or an explicit validated repair.

The three rejected input envelopes are 66,969, 74,274 and 72,977 against the configured 65,536 limit. These are the harness's conservative byte-based text bound plus schema/system overhead and image reserves, **not measured model token counts**. One image task fails this guard in both runs. No model request is sent at that point.

Reproducing an execution failure does not establish that repairing it would yield a correct final answer. In particular, the Brave selection-error case becomes a graded wrong answer in Perplexity.

**3. Perplexity can return the needed research lead while the controller fails to fetch it.** In the Boolean-dimension case, Brave retrieves a relevant paper and returns a graded correct answer. Perplexity returns a lead to the same paper in both rounds, but the local lead ranking puts it fifth and third respectively. Three other first-round pages consume the initial fetch allocation. The audit then explicitly requests fetching the unused paper, but puts that instruction in `missing_fact` text. The controller has no structured fetch-URL action; it runs another search and applies lexical lead ordering. Its final fetch goes to a different paper.

This is a demonstrated planning-to-execution mismatch and missed investigation opportunity. Jev never receives the intended paper in that run, so it cannot be responsible for rejecting its decisive passage. Perplexity's retrieval is not sufficient either: the provider ranking/snippets interact with the local ranker. A replay of the actual results can isolate that interaction. Fetching the unused URL might still fail; the trace does not prove that another fetch would recover the answer.

**4. Identical answers can be treated differently because Sol changes what requires a source.** In a music-notation case, both runs begin with the same answer, and Brave's returned answer is graded correct. Brave's audit treats the basis as visual inspection plus arithmetic and accepts it without research. Perplexity expands the inventory to include notation conventions as critical factual dependencies, searches, and ultimately rejects every nonempty draft because those premises remain unverified. One intermediate source-support check is insufficient; several final premises have no source reference at all.

This is evidence of inconsistent verification scope. It does not establish that Jev's insufficient-support judgment was wrong. The relevant test is whether a fixed question and candidate receive a stable, justified dependency inventory, and which conventions legitimately require external sources under the intended policy. Indiscriminately requiring citations would suppress independently solvable answers.

The converse occurs in a lattice-image case: the initial factual premise is unverified, but a revision presents a geometric derivation and passes a visual review. Perplexity selects it and the reference grader marks it wrong. Test the derivation and image mapping, not merely whether the candidate has a citation. A change of dependency kind must have a checkable basis.

**5. Source support is not whole-answer correctness.** The runs share three graded wrong answers. One image/algorithm case receives neither search nor any Jev request in either run; Sol's visual/derivation audits and selector accept it. That failure cannot be assigned to Brave, Perplexity, or an executed Jev decision. Other shared failures involve a mathematical factorization convention and an answer that argues a biological inference is underdetermined. Source entailment can correctly support background facts while the final answer still fails the question's requested scope or reference convention.

All five wrong selected answers in each run passed the implemented coverage and whole-answer checks. These are concrete review cases for the Sol verifier, dependency inventory and answer selection. Some dispute assumptions or give conditional answers; subject-matter adjudication should determine whether the solver, reference interpretation, or both need correction before using them as semantic gold labels. Existing benchmark scores remain unchanged.

**6. The coverage gate explains the abstention location, but not every abstention's validity.** Every completed abstention—25 Brave and 26 Perplexity—has an empty eligible pool. Neither run records a successful selector decision of `none-supported`. The selector is never called for these empty pools. Therefore, experiments aimed only at the selector's willingness to abstain would miss the observed mechanism.

Among the completed abstentions in each run, 16 have at least one nonempty rejected candidate with an unresolved critical factual dependency. These overlap with whole-answer, derivation and other failures; they are not 16 independently established search failures. Some candidates are unsupported, some lack the right passage, and some are held to more extensive requirements than their paired run.

Other contract issues worth preserving as test seeds are extra gap-assessment indices for gaps the draft never declared, and source claims reinserted as unresolved dependencies when the audit expresses the same premise with different wording. The audit-to-code mapping needs stable identities. Do not relax a genuine missing-dependency check simply to reduce abstentions.

**7. Some differences remain attributable only to the complete retrieval path.** In an aria-title case, Perplexity fetches a listing that supplies the full title, Jev retains it, and the answer is corrected. Brave fetches background material and follows a recording-label URL that redirects to a generic shop. This supports testing result usefulness, fetch destinations, extraction and lead ordering. Different initial answers and queries prevent treating it as a controlled Search API comparison.

The seven correctness disagreements comprise: Perplexity gains in the citation-offset case, aria-title case and a case where Brave's initial generation was truncated; Perplexity losses in the music-notation gate, missed paper lead, dependency-ID selection failure, and a legal-source case with incomplete scope verification. In the last case, saved sources mix different temporal scopes and the audits disagree over sufficient authority. That is a source-scope and coverage test seed; this analysis does not independently adjudicate the legal answer or label Jev's contradiction judgment incorrect.

**Tests this evidence supports**

Use the standalone [Evidence v3 test plan](EVIDENCE_V3_TEST_PLAN.md) for implementation in a new session. It contains test IDs, inputs, expected behavior, existing tools, new code requirements, API usage and artifact prerequisites. The table below is the analysis overview.

Start with deterministic contract checks and frozen component inputs. Keep every original trace and grade immutable. Cases below have private identifiers and request hashes in the accompanying casebook; public synthetic analogues can test the contracts without exposing benchmark material.

| Priority and target | Test input and intervention | Required observation |
| --- | --- | --- |
| P0: citation generation and repair | Exact retained quotation with wrong offsets; absent quotation; repeated quotation; non-ASCII text | Correctly locate a unique exact quotation or request a bounded repair; reject absent/ambiguous spans. Preserve critical claim support. The art-history example must not be called a search miss. |
| P0: selection reference contract | Passed candidate with bare, candidate-qualified, missing and foreign dependency IDs | Resolve only unambiguous references within the selected candidate or repair explicitly. Do not accept invented/unchecked dependencies or turn a correctable ID format into an unexplained item error. |
| P0: request/output handling | Saved oversized contexts, invalid citation response, and truncated initial response | Predict input-envelope failure before dispatch; bound context or expose a precise failure. Exercise valid recovery within declared budgets and preserve incomplete-output status. These checks must make no paid calls. |
| P1: fetch planning | Frozen results containing an explicitly requested unused paper plus misleading lexical matches | Measure whether the controller fetches the intended allowed lead under the same four-fetch budget. Separate provider order, local order, redirects, and extraction. Do not presume the fetch succeeds. |
| P1: audit scope and identities | Fixed correct and incorrect drafts, independent derivations, recalled premises, zero declared gaps, and paraphrased source claims | Label necessary premises and criticality independently. Measure discovery/coverage recall, false rejection, unsupported acceptance, dependency-kind consistency and reference integrity. |
| P1: Jev J2 | Full frozen competing passage sets with original question, neutral fact, literal query and independent useful/answer-bearing/contradictory labels | Compare Jev, lexical and backbone judgments on identical inputs. Report recall before shortlist, after shortlist, after relevance filtering and after packet limits. Include the retained art-history passage as a positive control. |
| P1: Jev J3 | Frozen claims and supplied source text labeled supported, contradicted or insufficient, including qualified and temporally mismatched sources | Report a confusion matrix, false support and false rejection. Judge entailment from the supplied source; assess source authority and whole-answer validity separately. Current J3 counts are not accuracy labels. |
| P1: search APIs and extraction | Identical neutral queries to both providers; preserve raw/allowed results, rank, snippets, fetch status, redirect and extracted content | Measure useful-lead recall at fixed result/fetch budgets and whether the needed fact reaches extracted text. Keep query generation fixed; separately compare each backend with the same local ranker and with provider order. |
| P1: Sol reasoning and visual review | Shared wrong answers, image-mapping case, independent proofs, partial answers and conditional answers | Expert-labeled whole-answer acceptance/rejection, image grounding and assumption compliance. Include the case with zero Jev/search calls as a control. |
| P2: grading and end-to-end attribution | Adjudicated labels; matched B2/J23 within each backend, followed by separate J2/J3 ablations | Share initial drafts and source snapshots when isolating judgment effects. Keep whole-pipeline live comparisons distinct. Report accuracy over all questions, coverage, answered-item accuracy, errors, cost and latency. |

The existing [component/workflow evaluators](EVIDENCE_V3.md) provide part of this infrastructure. Synthetic contracts do not measure semantic Jev quality; labeled real passages and new judgments are needed for that. The configured B2/J23 profiles do not automatically share initial responses or caches, and copying configuration-scoped caches between arms is not a valid matched replay. Define the replay identities and intervention in a separate manifest.

Use the inspected development cases as regressions. Freeze the policy before fresh evaluation. A gain from better citation handling measures integration; a gain from oracle passage labels on the same fetched pages implicates selection; a gain from additional relevant pages under fixed downstream processing implicates retrieval. None of those interventions alone measures all of Jev or all of a search provider.

**Evidence and reproduction**

The analysis is offline. It makes no new model, Jev, search, fetch, sandbox or grading calls and changes no solver behavior. The implementation hash matches both recorded v3 runs. Source databases are opened read-only; replay uses disposable cache copies, explicitly forbids uncached dispatch, and recomputes assessment postprocessing from saved raw audit responses.

Validation reconciles 100 saved predictions and grades, reconstructs all 1,024 J2 requests, and reproduces 521 assessment invocations including original cache replays. It reproduces all final answers, abstentions, candidate histories and errors. Counts are two runs on the same 50 questions, not 100 independent questions. This validates trace attribution and contracts; it does not independently validate model judgments or reference answers.

```bash
.venv/bin/python private/analyze-v3-search-attribution.py
.venv/bin/python private/write-v3-attribution-casebook.py
```

Private artifacts are ignored and must accompany this document separately in a different checkout:

- `private/v3-search-attribution-audit.json`: reconstructed passages, judgments, candidates, assessments, exact request contexts and error diagnostics.
- `private/v3-search-attribution-casebook.md`: case aliases, question IDs, references, observed boundaries and test expectations.
- `private/v3-search-attribution-cases.json`: machine-readable case index into the audit and original traces.
- `private/sol-low-evidence-v3-j23-{brave,perplexity}`: original manifests, predictions, call ledgers and caches.
- `private/sol-low-evidence-v3-j23-{brave,perplexity}-evaluation`: original isolated reference grades.

Question text, references, source quotations and per-item predictions remain private. The casebook distinguishes trace-proven failures from semantic hypotheses that still require annotation.
