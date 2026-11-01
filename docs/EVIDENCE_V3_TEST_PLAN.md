**Evidence v3 test plan for Jev, search and solver attribution**

Session handoff prepared 2026-11-01. Repository: `HLE-Diamond-Jev-Solver`.

Implement tests that distinguish failures in Jev's judgments, Brave/Perplexity retrieval, the repository's evidence-handling code, Sol's reasoning and verification, and reference grading. Begin with offline contract regressions and frozen evidence. Add live component evaluations where new judgments are necessary, then use controlled end-to-end comparisons to measure their effect.

This document contains the proposed suite and implementation handoff. The offline diagnostic scripts already exist; the additional tests and harness extensions below remain to be implemented. Creating this document has not changed solver behavior or launched a paid evaluation. The supporting [v3 attribution analysis](EVIDENCE_V3_SEARCH_ATTRIBUTION.md) contains the detailed findings; the specifications here can be used without the prior conversation.

**Evidence that motivates the tests**

Both runs used the same 50 development questions, implementation, Sol settings, Jev version and limits. Only the configured search backend differed, but model responses, queries and live sources were independently sampled. No matched B2 control or shared-initial/shared-source comparison was run.

| Recorded outcome | Brave v3 | Perplexity v3 |
| --- | ---: | ---: |
| Correct | 16/50 | 15/50 |
| Wrong nonempty answer | 5 | 5 |
| Completed abstention | 25 | 26 |
| Solver error | 4 | 4 |

The one-question difference does not identify a better backend. Every completed abstention arose from an empty eligible candidate pool. All wrong selected answers passed the implemented coverage and whole-answer checks. Offline replay reproduced all 100 run outcomes, including eight errors: three dependency-ID selection failures, three local input-envelope failures, one invalid citation response, and one truncated initial response. These are repeated runs on 50 questions, not 100 independent questions.

Two cases are particularly useful for attribution. In the art-history case, both backends retrieved the same decisive passage, Jev retained it, and both runs produced the same corrected answer; Brave rejected it because citation offsets were invalid. In the missed-paper case, Perplexity returned the relevant lead twice and Sol requested it, but local fetch ranking spent the remaining fetch on another paper. Neither case supports calling the observed loss a Jev relevance error.

**Component ownership and API usage**

Sol generates answers, dependency inventories, queries, revisions, visual reviews and final selections. Jev performs J2 passage relevance and J3 source entailment. Repository code handles filtering, fetching, chunking, shortlisting, packet limits, citation validity, eligibility and selection references. Brave and Perplexity return search results; Perplexity's Search API does not generate the final answer. J1/J4/J5/J6 are inactive in these J23 runs.

| Test activity | OpenRouter | Other new API usage | Implementation needed |
| --- | --- | --- | --- |
| Existing diagnostic replay and casebook generation | None | None | Already implemented |
| Contract regressions and frozen search/fetch replay | None | None | New tests and synthetic fixtures; some replay utilities |
| Offline metrics over independently labeled saved judgments | None | None | Labels, fixture extraction and some metric extensions |
| Fresh Jev J2/J3 judgments | None | TypeSafe | Mostly labeled cases using `component-eval` |
| Fresh Sol component judgments, audits, query plans, revisions or selections | Yes | None for fixed evidence | Existing backbone component mode; new audit/workflow harness where needed |
| Identical-query live search comparison | None | Brave/Perplexity; fetching source pages | New search comparison harness |
| New Astra reference grading | Yes | None | Existing isolated grading, plus an adjudication process |
| Matched live B2/J23 and component ablations | Yes | Search; TypeSafe for Jev-enabled arms | Shared-input/source replay and intervention manifests |

The recorded model settings are Sol `openai/gpt-6.1-sol` with low reasoning effort, Jev `jev-1.14.0`, and Astra `openai/gpt-6-astra` for grading. These identify the historical experiments. Replaying saved responses needs no credentials. New model calls measure fresh behavior and incur the configured provider's usage.

**Start here in the new session**

1. Inspect repository instructions and the working tree. V3 implementation files were modified or untracked when this handoff was written; a Git commit ID alone may not reproduce the baseline. Preserve those changes and capture the actual source/configuration snapshot before implementing fixes.
2. Verify the private artifacts below are present. They are ignored by Git and will not accompany a normal clone. If unavailable, implement synthetic contract tests and the harness, and mark historical replay/real-case evaluation unavailable until the artifacts are supplied. Do not substitute invented historical results.
3. Run the existing offline replay before changing implementation files. Its expected source hash is `51b6b4ab4ced7b4c9160b2f401014e6aa53c5889dd23efb84529df8ef78a6d0d`. It deliberately refuses a different implementation. Retain the matching source snapshot for historical reproduction; changes belong in a separately identified experiment.
4. Implement T01–T05 first, extending the current test utilities where useful. Use synthetic fixtures for committed tests and private fixtures for exact benchmark replay. Assert that no uncached model, Jev, search, fetch or sandbox dispatch can occur in the offline suite.
5. Prepare independent labels and matched input sets for T06–T10. Implement T11 only after component attribution is measurable. Choose live evaluation budgets and scope according to the new session's instructions; the historical configuration caps are not a cost estimate for this suite.

From the repository root, with the existing environment and artifacts:

```bash
.venv/bin/python private/analyze-v3-search-attribution.py
.venv/bin/python private/write-v3-attribution-casebook.py
```

The first command reads the original databases and uses temporary replay stores. Both commands regenerate derived private analysis files. Expected baseline validation: 100 reproduced outcomes, 1,024 reconstructed J2 requests, 521 assessment invocations including cache replays, zero new API/tool dispatches, and an 18-case index. These counts check reconstruction, not semantic accuracy.

**Private inputs and existing code**

| Resource | Purpose |
| --- | --- |
| `private/v3-search-attribution-casebook.md` | Readable examples and proposed test expectations |
| `private/v3-search-attribution-cases.json` | Maps the case aliases used below to question IDs, references, requests and trace events |
| `private/v3-search-attribution-audit.json` | Full saved candidates, assessments, request contexts, reconstructed passages and diagnostics |
| `private/analyze-v3-search-attribution.py` | Existing offline reproduction script |
| `private/write-v3-attribution-casebook.py` | Existing casebook generator and decisive-case assertions |
| `private/sol-low-evidence-v3-j23-{brave,perplexity}/` | Original manifests, predictions, SQLite traces and caches |
| `private/sol-low-evidence-v3-j23-{brave,perplexity}-evaluation/` | Original isolated reference grades |
| `private/sol-low-pilot-data/solver/questions.jsonl` | Original solver inputs, including image inputs |
| `private/sol-low-pilot-data/evaluator/labels.jsonl` | References for offline analysis/adjudication only |

Keep benchmark questions, references, source text, per-item predictions and real-case fixtures under ignored private paths. Use the aliases below in public tests/docs. The casebook covers every wrong answer and solver error in both runs, but its hypotheses are not independent semantic gold labels.

Reuse [verification contract tests](../tests/test_verification_contract.py), [evidence workflow tests](../tests/test_evidence_workflow.py), [Perplexity adapter tests](../tests/test_perplexity.py), [OpenRouter tests](../tests/test_openrouter.py), and the [component/workflow evaluators](../src/jev_solver/evaluation/components.py). New files such as `tests/test_evidence_v3_regressions.py` and `tests/test_search_attribution.py` are suggested destinations, not existing implementations. Extend existing coverage rather than duplicating equivalent assertions.

For each test, record the baseline observation separately from the desired behavior after a fix. Historical replay should reproduce the original failure. A regression intended to verify recovery should expose the defect until the relevant fix is implemented; merely asserting that the old error occurs does not establish recovery.

**T01 — Citation offsets and bounded repair. Priority P0; offline.**

Case: `art_citation_offsets`. Targets: `exact_citation` in [pipeline.py](../src/jev_solver/judgments/pipeline.py), candidate parsing, and revision/repair in [engine.py](../src/jev_solver/controller/engine.py).

Use an exact quotation whose supplied offsets are wrong, then add absent quotes, repeated quotes, non-ASCII characters, invalid passage IDs and changed source hashes. The historical quote is present at [1100, 1268); the three rejected drafts use different incorrect spans. Reproduce rejection at the citation boundary even though factual dependency checks pass.

For a repair implementation, require a valid exact span tied to the correct passage. A unique exact occurrence may support deterministic offset recovery; ambiguous or absent text requires disambiguation or a bounded repair. Preserve the critical claim and its semantic support check. Invalid quotes must remain ineligible. The negative cases are as important as recovering the valid quote. Any live repair model evaluation is separate from this offline contract test.

**T02 — Selection dependency references. Priority P0; offline.**

Cases: `selection_gene_id`, `selection_population_id`, `selection_clinical_id`. Target: `select` in [selection.py](../src/jev_solver/candidates/selection.py).

Supply a selected candidate with passed critical dependencies and responses using bare IDs, `candidate_0.d1`, `candidate_1:d1`, missing IDs, foreign IDs, and overlapping IDs across candidates. First reproduce the three historical selection validation failures.

Test an explicit reference representation or a validated repair that resolves only unambiguous references within the selected candidate. Every critical dependency must be cited and every cited dependency must actually have passed. Reject cross-candidate, invented or unrun references; an abstention must not cite a selected candidate's checks. Record the exact failed condition. A repaired selection is not automatically a correct answer.

**T03 — Input envelope, malformed output and incomplete generation. Priority P0; offline.**

Cases: `input_visual_program`, `input_large_image`, `malformed_revision_citation`, `truncated_initial`. Targets: [Gateway](../src/jev_solver/providers/backbone.py), [OpenRouter adapter](../src/jev_solver/providers/openrouter.py), [Candidate/Citation parsing](../src/jev_solver/models.py), and the controller.

Exercise contexts immediately below and above the conservative size guard, including schema/system overhead, original images and accumulated research outcomes. Reproduce the recorded envelopes of 66,969, 74,274 and 72,977 against a 65,536 limit. Treat these as conservative harness bounds, not measured token usage. Also supply a nonempty citation with `start = end = 0`, invalid structured output, and an incomplete response with `finish_reason: length`.

Assert no dispatch on a rejected envelope, no acceptance of incomplete output, and precise failure reasons. If implementing context reduction or recovery, preserve required evidence/image inputs and enforce call/cost/attempt limits. A fake provider can exercise all branches without OpenRouter. Do not weaken validation to make malformed responses pass.

**T04 — Planned lead becomes the intended fetch. Priority P1; offline first.**

Cases: `missed_paper_lead`, `aria_title`. Targets: [research.py](../src/jev_solver/controller/research.py), `rank_leads` and packet construction in [evidence.py](../src/jev_solver/retrieval/evidence.py), and [web.py](../src/jev_solver/tools/web.py).

Freeze the actual result list, provider order, locally ranked order, fetch outcomes and remaining quota. Include a requested unused URL, a lexical distractor, duplicates, blocked URLs, failed fetches, and a redirect to a generic page. Reproduce the missed-paper lead being ranked fifth and third despite an instruction to fetch it in the second round.

A proposed structured fetch action must dispatch the intended allowed lead within the same four-fetch budget and preserve the follow-up reserve. Log the distinction between request, attempted fetch, returned destination, extracted text and retained evidence. Use a frozen or synthetic page for the offline success branch; the historically unfetched page's live availability remains unknown. Search snippets must never become factual support merely because fetching fails.

**T05 — Dependency identities, gap mapping and eligibility. Priority P1; offline.**

Cases: `source_claim_identity`, `audit_music_scope`. Targets: [verification.py](../src/jev_solver/judgments/verification.py) and `Solver.assess`.

Use mocked audit results for zero declared gaps with extra gap indices, missing/duplicate indices, omitted critical premises, equivalent wording under stable IDs, and genuinely distinct claims. Include checked independent derivations, unverified factual memory, missing artifacts and incidental gaps. Verify all check states explicitly: `not_run`, `not_applicable`, `unavailable`, `passed`, `failed`.

Require complete, valid mappings and a checked critical basis. An incidental gap should not reject a supported answer, while an undeclared necessary fact must still be discovered. Equivalent wording should not create an artificial unchecked duplicate when identity is established; text similarity alone must not erase a distinct premise. This suite checks the contract with fixed audit outputs. Whether Sol discovers or classifies the correct premises is evaluated in T06.

**T06 — Sol audit, reasoning and image accuracy. Priority P1; saved-label evaluation first, OpenRouter for new behavior.**

Cases: `audit_music_scope`, `visual_lattice`, `no_search_algorithm`, `math_convention`, `inference_underdetermined`, `subsumption_scope`, `selection_clinical_id`.

Freeze the original question/images, candidate, evidence and tool artifacts. Independently label necessary dependencies, criticality, derivability, image observations and whole-answer validity. Include correct independent solutions and wrong proposals, multipart answers, conditional answers and changes from factual to derived dependency kinds. Newly sampled audits must use identical inputs across comparisons; record repeatability as well as correctness.

Measure claim discovery/checked-coverage recall, false rejection of valid answers, false acceptance of invalid answers, and dependency-kind/criticality consistency. Reuse `workflow-eval` for labeled saved decisions. Include the entire assessed candidate history when measuring correct-answer rejection by the eligibility gate; using only the eligible pool hides that loss. Extend the metrics/harness for image grounding, classification stability and new audit calls. The no-search/no-Jev algorithm case is an attribution control: an unexecuted component cannot explain its recorded failure.

**T07 — Jev J2 relevance and evidence survival. Priority P1; TypeSafe for new Jev judgments.**

Use all competing passages for each frozen research task, including useful, irrelevant, answer-bearing and disconfirming material. Include `art_citation_offsets` as a positive control and sources from `missed_paper_lead` and `aria_title`. A passage never fetched by that run must not be labeled a J2 rejection.

Reuse `component-eval` with rows containing `id`, `stage: "J2"`, `task_id`, `state`, and normalized `expected`. State requires original `question`, neutral `missing_fact`, literal `search_query`, and `passage`; preserve URL/title and dependency context where available. Add independently adjudicated Boolean `answer_bearing`, `useful` and `contradictory` labels outside state. Group passages by the actual question/round/missing fact so unrelated rounds do not compete for one packet.

Compare Jev, lexical and Sol judgments on identical state and packet budgets. Jev-only evaluation uses TypeSafe; the lexical baseline is offline; Sol comparison uses OpenRouter. Existing metrics cover usefulness decisions and final packet recall/exclusions. Add explicit recall checkpoints before/after shortlisting, relevance filtering and packet limits, plus exclusion reasons. Evaluating stored decisions is offline; changed prompts require fresh judgments. Avoid treating raw exclusion counts or exact continuous-score agreement as semantic accuracy. Predeclare thresholds before evaluating fresh cases.

**T08 — Jev J3 source entailment. Priority P1; TypeSafe for new Jev judgments.**

Cases: `art_citation_offsets`, `source_temporal_scope`, `inference_underdetermined`, `malformed_revision_citation`. Prepare supported, contradicted and insufficient examples with independently labeled atomic claims, actual supplied quotations and source context. Include partial support, qualification, missing prerequisites and different temporal scopes.

Reuse `component-eval` with `stage: "J3"`, a `state` containing `claim`, `quote`, `source_context` and any original context fields, and `expected` set to the entailment label. Keep labels outside provider state. Preserve actual request shapes: a test that adds missing context is a separate intervention.

Report the existing confusion matrix, unavailable judgments, false support and false rejection. Separate invalid citation spans (T01/T03), source reliability/applicability, and whole-answer correctness (T06/T10). Jev can correctly identify what a source says while that source is inapplicable to the requested answer. Current support counts alone supply no semantic gold labels.

**T09 — Brave and Perplexity on identical queries. Priority P1; new search APIs, no OpenRouter for fixed queries.**

Use a frozen list of neutral queries and missing facts. Compare both providers on each identical query with fixed result and fetch budgets. Save raw and allowed results, provider rank, local rank, snippets, blocks, redirects, fetch failures and extracted text. Compare provider ordering and the same local ranker as separate conditions.

Measure useful-lead recall at fixed ranks, useful-page recall at the fetch budget, and whether needed facts survive extraction. Replay local ranking/fetch planning offline; new search results or source fetches are live observations. Keep query generation fixed to isolate the providers. Evaluating new Sol-generated query plans is a separate OpenRouter experiment. Retrieval benefits must be distinguished from shortlist, Jev and packet losses using T04/T07.

**T10 — Reference interpretation and grader behavior. Priority P1; expert review, OpenRouter only for new Astra calls.**

Cases: `selection_clinical_id`, `math_convention`, `no_search_algorithm`, `inference_underdetermined`, `subsumption_scope`, `source_temporal_scope`.

Have a qualified reviewer assess disputed assumptions, temporal scope, answer format, conditional answers and ambiguous questions. Record whether disagreement is a solver error, a reference interpretation issue, a grader inconsistency, or unresolved. Maintain adjudicated labels separately from the immutable original grades. Intermediate drafts need their own labels; a different run's final grade is not a universal label for all similar drafts.

Evaluate new Astra judgments only if that behavior is part of the experiment. Do not pass reference answers or adjudication labels into solver, search, Jev or revision requests. Report original and adjudicated scores separately; measure grader agreement rather than silently changing the historical benchmark.

**T11 — Controlled end-to-end attribution. Priority P2; new harness and live usage where uncached behavior is requested.**

After the component tests are informative, compare B2/J23 within each backend and separate J2/J3 interventions. B2 is the tool baseline without Jev J2/J3; it still uses the Sol audit workflow. The four existing v3 B2/J23 profiles provide matched settings, but not identical sampled inputs. A whole-pipeline live run measures a different effect from replacing one component on frozen inputs.

Implement an explicit replay manifest identifying initial drafts, frozen queries/results/pages, evidence policy, implementation/model versions and exactly which component changes. Share initial candidates and source snapshots when isolating judgment quality. Existing caches are configuration-scoped: copying them between arms does not establish a valid control. Reuse a frozen result only when its input contract matches; any changed downstream prompt/input requiring new generation must be recorded as a new call.

Measure full-set accuracy including failures/abstentions, coverage, answered-item accuracy, wrong-answer acceptance, correct-answer rejection, latency and accounted cost. Report paired question-level differences and uncertainty; predeclare replication and acceptance criteria. Tests on these inspected development cases establish regressions. Freeze policy before fresh validation and keep held-out questions separate from development labels.

**Implementation deliverables and completion checks**

1. An offline unittest suite for T01–T05, with synthetic public fixtures and private real-case adapters. Tests must distinguish current failure reproduction from verification of an implemented fix and must fail if an external dispatch is attempted.
2. A private labeled-case format and extraction path for T06–T10, with stable claim/passage IDs, input hashes, label provenance and unresolved-label status. Keep provider inputs separate from scoring labels.
3. Extensions to the existing evaluator for stage-by-stage evidence survival and audit/visual metrics; a fixed-query search harness; and, later, the controlled replay manifest for T11. These are the substantive new harness work.
4. An aggregate result document mapping each test ID to passed, failed, unavailable or not run, with denominators, errors, usage and the boundary implicated. Distinguish a contract test passing from a model meeting a semantic-quality target. Missing labels yield unavailable metrics, not perfect scores.

Use the repository's existing unittest conventions. Run focused tests while implementing; when integrating changes, run the documented regression and formatting checks appropriate to the changed code:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_verification_contract.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_evidence_workflow.py' -v
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
```

The new test files must also be included in discovery. Existing optional sandbox tests have their own environment requirements; the new offline contracts should use saved/fake artifacts and need no live Docker execution. Formatting and regression passes establish implementation behavior, not HLE-Diamond accuracy.

The [implementation guide](EVIDENCE_V3.md) documents existing `component-eval` and `workflow-eval` schemas and configurations. Preserve the original trace-based analysis, record changes under new identities, and base attribution on the earliest demonstrated failing boundary rather than the final answer alone.
