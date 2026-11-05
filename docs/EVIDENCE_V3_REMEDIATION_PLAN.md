# Evidence v3 remediation plan

Prepared 2026-11-05 from the [failure analysis](EVIDENCE_V3_FAILURE_ANALYSIS.md), the [expanded review](EVIDENCE_V3_EXPANDED_REVIEW.md), and the current implementation. The objective is to preserve useful evidence, verify claims at the scope their sources establish, and check that the resulting answer satisfies the original question.

**Status: implemented with independently selectable experimental policies.** The user-preserved comparison revision is `9a7a1aa9090960fa353ecb836f96c9da3b2b2c6a`, committed and pushed before implementation. Existing profiles retain their control policies. See the [implementation results and run instructions](EVIDENCE_V3_REMEDIATION_RESULTS.md) for change identities, validation, diagnostic limitations, and pending paid/adjudication gates. No paid experiment was launched.

The observed retrieval and serialization mechanisms support concrete repairs. Semantic diagnoses remain hypotheses until adjudicated or tested in controlled comparisons. Eligibility recovery, reviewer agreement, and benchmark accuracy must remain separate measurements.

## Implementation sequence

Use the following order, with each independently testable behavior kept in a separate change. Policy names below describe proposed settings; they are not existing configuration keys or commands.

| Step | Deliverable | Completion gate |
| --- | --- | --- |
| R0 | Preserve comparison identities and extend boundary tracing | Frozen historical reproduction; explicit pre-remediation revision and artifact hashes |
| R1 | Deterministic citation coordinates | Unique exact quotes recover; invalid or ambiguous references cannot pass |
| R2 | Bounded request construction and generation recovery | Compactable inputs fit; unrecoverable inputs and incomplete outputs remain explicit failures |
| R3 | Persistent question contract and dependency graph | Revisions retain necessary premises and invalidate stale checks |
| R4 | Structured evidence, hybrid shortlisting, and dependency coverage in packets | Useful text survives targeted fixtures under unchanged passage and character caps |
| R5 | Separate J2 subfact relevance from provenance and calibrate admission | Fresh labeled comparisons distinguish representation, task, and threshold effects |
| R6 | One atomic support contract for both J3 callers | Every necessary requirement is checked; relevant conflicts remain blocking |
| R7 | Independent applicability and whole-answer verification | Correctly qualified answers pass; unsupported interpretation changes cannot qualify |
| R8 | Controlled experiments and policy freeze | Complete paired reports, including failures, costs, uncertainty, and regression controls |

R1 and R2 can use the existing dependency inventory. R3 supplies the persistent identities used by R4–R7. Implementing those structures must not silently activate every new policy: preserve the baseline through explicit versions and independently selectable interventions. Leave existing experiment profiles unchanged and add new profiles when the implementation is ready.

## R0 Preserve the comparison and make losses observable

After the start command, record the user-preserved baseline commit, source/configuration hashes, dependency environment, and private artifact hashes in a new experiment manifest. Do not infer that the baseline is `HEAD^`: resolve and record the actual revision. Keep three identities distinct: the original historical solver snapshot, the current code with earlier repairs, and each new remediation variant. The ignored `private/v3-test-plan-baseline/` snapshot describes the historical implementation, not necessarily the new comparison commit.

Preserve these existing repairs as baseline behavior:

- Exact candidate-scoped selection references in [selection.py](../src/jev_solver/candidates/selection.py).
- Explicit fetch requests, allowed-lead checks, and follow-up capacity in [research.py](../src/jev_solver/controller/research.py).
- Complete gap mapping and retained declared dependency IDs in [verification.py](../src/jev_solver/judgments/verification.py).
- Exact span validation, one bounded final model repair, conservative input guards, and rejection of malformed or incomplete generations.

Use the existing offline adapters to reproduce the historical 100 saved outcomes and 153 research packet sequences against their original implementation and inputs. Preserve original databases, grades, unresolved labels, and the six input hashes recorded by the failure-analysis script. Write derived results to a new private directory. A deliberate policy change should have its own expected results; it must not rewrite the historical oracle.

Extend [research outcomes](../src/jev_solver/retrieval/outcomes.py), [component metrics](../src/jev_solver/evaluation/components.py), [workflow metrics](../src/jev_solver/evaluation/workflows.py), and controller events to record every boundary separately: fetched, shortlisted, J2 executed/unavailable, admitted, research packet, merged revision context, audit context, and selection context. Record the first exclusion reason, selected IDs, source coordinates, dependency coverage, budgets, and policy version. Distinguish duplicate text from lost unique information and missing judgments from semantic rejections.

The analysis attributes 45 historical research omissions to the hostname cap and three to exact duplicates; none first hit the six-passage or character limit. The controller's later merge calls the same packet function, but its effects require separate measurement.

**Acceptance:** baseline reproduction dispatches no external calls; immutable artifacts retain their hashes; changed policies cannot replay old assessments accidentally; boundary accounting reconciles every passage occurrence without treating repeated occurrences as independent questions.

## R1 Resolve citation coordinates deterministically

Primary files: [models.py](../src/jev_solver/models.py), [pipeline.py](../src/jev_solver/judgments/pipeline.py), [backbone.py](../src/jev_solver/providers/backbone.py), and [engine.py](../src/jev_solver/controller/engine.py).

Add a citation resolver at the candidate parsing/assessment boundary. Bind the supplied passage ID to the immutable passage and its source hash. Preserve an already valid span. For an offset-only error, find every exact occurrence of the quoted text within that passage; recover coordinates only when exactly one occurrence exists. Use Python string offsets, zero-based and end-exclusive, consistent with the current validator.

Keep strict validation of the completed internal `Citation`. Introduce a versioned quote-based model output contract so the model can supply a passage ID and exact quote while code supplies coordinates. Retain an explicit adapter for legacy candidate records. A wrong passage, changed source identity, absent quote, or ambiguous match must remain unresolved. Do not use fuzzy matching, whitespace normalization, or cross-passage searching to manufacture a valid quotation. A valid explicit span remains valid even when its quote occurs elsewhere in the same passage.

Record original and resolved coordinates plus the resolution reason. Recheck semantic support and candidate coverage after recovery; successful serialization does not establish the claim. The existing bounded model repair remains available when deterministic resolution cannot succeed, within the same item budget.

**Acceptance:** synthetic fixtures cover Unicode, valid repeated quotes, ambiguous recovery, absent text, wrong source identity, and a recovered quote whose claim is contradicted. A private adapter measures coordinate recovery for `art_citation_offsets` using the actual saved passages. Report recovered spans and newly eligible candidates separately from final correctness; do not hard-code a historical answer into a public fixture.

## R2 Bound contexts and recover complete outputs

Primary files: [backbone.py](../src/jev_solver/providers/backbone.py), [jev.py](../src/jev_solver/providers/jev.py), [engine.py](../src/jev_solver/controller/engine.py), [selection.py](../src/jev_solver/candidates/selection.py), and [budget.py](../src/jev_solver/controller/budget.py). A shared context-builder module is appropriate if it removes duplicated admission logic.

Construct phase-specific contexts before hashing and dispatch. First remove repeated records and redundant serialization, then drop incidental history and unused lead detail. Preserve the original question and images, current candidate, unresolved critical premises, cited spans, relevant contradictory evidence, applicability conditions, and the artifact identities needed to check them. Keep full immutable records in the private ledger. Compaction changes a request's representation, not the evidence available to validation.

When source text is shortened, use identified excerpts with offsets into the canonical passage; never silently replace passage text under an existing ID. Prefer separate bounded checks over compressing away a critical premise. If all necessary evidence cannot fit, record incomplete coverage and leave the candidate ineligible. If the original question/images and mandatory instructions alone exceed the envelope, retain an explicit input failure. Preserve the image reserve and conservative guards unless an independently validated accounting change is evaluated as its own intervention.

Apply the builder to revision, repair, audit, selection, and J3 requests. Log original/final envelope bounds, retained/omitted IDs, and compaction reasons. Hash the actual submitted context and builder version. In R3, extend retention to the transitive dependency graph rather than only current declared IDs.

Add at most one format/completion regeneration per item, shared across initial and revision generation, for a truncated response or invalid structured candidate. Request a complete, concise replacement under the existing output cap; never concatenate partial JSON or accept a partial answer. Keep raw failed responses for accounting. Populate the success cache only after phase-specific schema and typed validation, so a parseable JSON object with malformed citations cannot become a permanent successful replay. Refusals and model mismatches are not formatting errors. Count regeneration together with the existing semantic repair and all downstream reassessments against call, cost, deadline, and finalization reserves. Resume must not grant a fresh allowance.

**Acceptance:** compactable fixtures dispatch within the guard; original images and critical evidence remain identifiable; irreducible inputs dispatch nothing; one successful regeneration is fully revalidated; repeated malformed/truncated output terminates within budget. Preserve reconstruction of the three historical rejected envelopes and report recovery only from new attempts. Existing selection-ID repairs remain covered without adding another selector retry policy.

## R3 Persist the question contract and dependency graph

Primary files: [models.py](../src/jev_solver/models.py), [backbone.py](../src/jev_solver/providers/backbone.py), [verification.py](../src/jev_solver/judgments/verification.py), [engine.py](../src/jev_solver/controller/engine.py), and [store.py](../src/jev_solver/tracing/store.py).

Define a bounded `QuestionContract` for the tool-using arms before their first draft. It records requested outputs, scope, quantifiers, chronology, permitted qualifications, and answer-changing interpretation assumptions, with anchors to original question text or image indices. Preserve unresolved alternative interpretations. Sol proposes the contract; it is a fallible interpretation that later checks must compare with the original input. A candidate cannot silently rewrite it. Contract corrections require a new version and invalidation of affected checks. Keep B0/B1's raw baseline definitions unchanged.

Extend dependencies with stable logical IDs, premise versions, `depends_on` edges, contract-obligation references, applicability assumptions, and supporting spans/artifacts. Keep candidate-scoped verification records separate from logical identity: one candidate's passed check cannot qualify another through an overlapping local ID. Persist the graph and lifecycle events so retries and resume reconstruct the same state.

Validate referential integrity, acyclicity, coverage of required outputs, and check provenance. A changed claim, premise, source set, code artifact, or question contract invalidates the relevant check and its descendants. Retaining an ID is not permission to change its meaning while retaining its passed status. Reclassifying a factual premise as derived cannot remove the factual assumptions on which the derivation relies.

Allow a genuinely independent derivation to replace a source-dependent route when its new basis is checked. Optional explanatory claims can be removed or narrowed, but necessary premises cannot disappear through renaming or candidate omission. Record why an obligation is discharged or no longer used.

Preserve the current maximum of 12 active dependency records per candidate. Share repeated premises and allocate research to unresolved critical leaves. If necessary decomposition exceeds the bound, return explicit incomplete coverage; do not merge distinct obligations or allocate a new budget to each leaf. Archive versions within the existing bounded candidate/round history.

**Acceptance:** a revision cannot erase a convention, construction identity, or chronology assumption; changed upstream facts invalidate descendants; cycles/dangling IDs fail; shared premises are checked once per identical input; optional claims can be removed; a valid independent solution remains eligible. The contract-generation call and any repair count against the existing total allowance.

## R4 Preserve structure and allocate evidence by dependency

Primary files: [web.py](../src/jev_solver/tools/web.py), [parsing.py](../src/jev_solver/tools/parsing.py), [evidence.py](../src/jev_solver/retrieval/evidence.py), [research.py](../src/jev_solver/controller/research.py), [engine.py](../src/jev_solver/controller/engine.py), and [config.py](../src/jev_solver/config.py).

Implement and compare these three interventions independently:

1. **Structured evidence views.** Retain canonical fetched text, source hashes, and offsets. Derive views after the existing full-page filtering, including on cache replay. Add heading, definition, theorem, and table-row views with cell/header associations and mappings back to source spans. Generated labels are display metadata, never citable source text. Preserve formulas and enough neighboring context to interpret qualifiers. If a saved extraction has already lost a header or layout, mark it unavailable rather than inventing it. Version parser changes and record new fetch provenance; changed canonical text creates a new source identity and cannot replace a historical snapshot.
2. **Hybrid shortlist.** Start with a deterministic development variant reserving four of the existing 12 slots for structural candidates relevant to unresolved dependencies, with eight lexical slots and unused reservations returned to the shared pool. Retain query/source rotation and stable tie-breaking. Include definition/theorem bodies, not merely headings. Keep this allocation explicit and adjustable only on development data. Embeddings or another semantic ranker are a later isolated variant with their costs counted.
3. **Packet coverage.** Replace the hard two-passages-per-host ceiling with a preference after unresolved critical coverage and complementary information. Retain exact-text deduplication, the configured six-passage cap, and the historical profiles' 12,000-character cap. Preserve disconfirming evidence and scope/version context. Apply the same policy to research assembly and revision merging, with separate traces. A relaxed host preference may expose passage or character limits; record those new exclusions.

Represent one immutable passage's associations with several dependencies separately from its content identity. Deduplication must retain those associations and source provenance; it must not erase coverage or charge duplicate text several times. Count structured views and repeated headers against the actual submitted context allowance, rather than treating their display text as free. Existing valid citations stay resolvable from the evidence ledger even if their passages leave a display packet. Assessments must still consider relevant new conflicts.

**Acceptance:** fixtures recover structurally identifiable definitions/theorems despite weak word overlap, preserve table-row mappings, and admit three complementary passages from one host when capacity permits. Duplicate, distractor, contradictory, long-source, and several-query fixtures remain bounded. Replay the three stronger-reviewed shortlist omissions and the hostname exclusions as diagnostics; measure unique supporting-span survival and dependency coverage rather than promising recovery of all 45 omissions.

## R5 Make J2 relevance local and calibrate admission

Primary files: [pipeline.py](../src/jev_solver/judgments/pipeline.py), [jev.py](../src/jev_solver/providers/jev.py), [config.py](../src/jev_solver/config.py), and the existing [label](../src/jev_solver/evaluation/labels.py) and [component evaluation](../src/jev_solver/evaluation/components.py) modules.

Judge whether a passage supplies a necessary subfact, including disconfirming evidence. Keep provenance/authority requirements as separate applicability checks: a table may provide the command mapping while its official status remains unresolved. Send the relevant structured view, atomic missing fact, original question context, dependency ID/version, and source identity in a versioned J2 contract.

Run separate comparisons for raw versus structured passages, compound versus atomic missing facts, and admission policy. Hold complete fetched sources, shortlisted passage IDs, packet limits, and total judging allowance fixed for each J2 comparison; test shortlist changes separately in R4. Store returned category probabilities, normalized score, confidence, and availability separately. Neither normalized score nor confidence is a calibrated correctness probability.

Retain the current threshold policy as the control. Test candidate thresholds and bounded reconsideration only against adjudicated development passages, splitting calibration and validation by question/source family so repeated occurrences cannot leak across them. Any reconsideration consumes the same total J2 judging allowance; it does not add unlimited calls after the 12-slot shortlist. Do not switch to partial/direct probability mass merely to rescue the two table examples: their saved masses also fall below a straightforward useful-evidence cutoff.

**Acceptance:** synthetic tests establish request shape, correct separation of provenance, disconfirming relevance, unavailable states, and budget enforcement. Fresh labeled judgments establish usefulness recall and false admission; saved judgments on old inputs cannot measure a new representation. Promote an admission variant only if it improves useful-passage recall without increasing observed false admission on the declared validation set at the same allowance. Otherwise retain the control and report the tradeoff or unavailable evidence.

## R6 Unify J3 around atomic requirements and identified sources

Primary files: [pipeline.py](../src/jev_solver/judgments/pipeline.py), [verification.py](../src/jev_solver/judgments/verification.py), [models.py](../src/jev_solver/models.py), and [jev.py](../src/jev_solver/providers/jev.py). Put the shared request builder and aggregation rules in one module used by both citation and factual-dependency verification.

Sol supplies bounded atomic requirements for identity, relation, scope, quantifier, qualification, and version as needed; code validates their graph and coverage. Jev's existing Choice primitive judges each requirement against an individually identified source block. Use stable question keys and typed verdicts rather than expecting the Choice API to generate a free-form clause analysis. Batch independent questions only when locality and request bounds are preserved.

For identical requirement/source inputs, both callers must construct the same local entailment request. Bind each verdict to the requirement version, source hash, passage ID, exact quote/span, context, and prompt version. A source describing an entity does not establish that the question intends that entity. A phenotype does not establish a particular mechanistic relationship. Mathematical transformations belong in a checked derived node with the original theorem's qualifications retained.

Aggregate at the parent claim: every necessary factual requirement must be supported by suitable evidence; the same source need not establish every leaf. Joining leaves across sources requires consistent entity/version identities and checked reasoning. Preserve `insufficient` and `contradicted` separately. An unsupported strengthening is not automatically a contradiction, and a high-confidence verdict does not excuse an unchecked clause.

After local support, check cross-source consistency and applicability against all relevant retained findings, including later evidence. A locally supported passage cannot override an unresolved relevant contradiction. An older proposal can be marked inapplicable only with a recorded date/scope basis. Explicitly retain unavailable checks and unsupported negative claims. Consider uncertainty escalation only as a separately calibrated bounded policy.

**Acceptance:** fixtures cover conjunctions, omitted definition conditions, strengthened quantifiers, changed asymptotic expressions, identity versus mechanism, negative claims, and temporal scope. Cross original/decomposed claims with single-source, unrelated-extra-source, and genuinely conflicting-source contexts. Unrelated additions must preserve the local request identity; conflicting additions must affect aggregate eligibility. Fresh model comparisons measure both false support and false rejection, including valid multi-source support. Promotion requires fewer observed false supports without increased false rejection on the declared adjudicated validation set; unresolved labels remain unavailable metrics.

## R7 Verify applicability and the complete answer

Primary files: [verification.py](../src/jev_solver/judgments/verification.py), [engine.py](../src/jev_solver/controller/engine.py), [selection.py](../src/jev_solver/candidates/selection.py), and [mock_verification.py](../src/jev_solver/providers/mock_verification.py).

Separate discovery/planning from the final whole-answer check. Run that final independent check after local factual, visual, derivation, and execution results have been collected, so it consumes their actual verdicts. Compare each requested output against the original question and contract, including quantifiers, chronology, qualifications, construction/convention choices, and all answer-changing assumptions. Eligibility requires current critical graph coverage and a passed whole-answer check. Recheck earlier candidates against the same final evidence and artifacts before selection.

Fix the obligation at the claim's actual strength: a potential explanation requires defensible possibility; an exact identification or unique choice requires the stronger identity/exclusivity check. A valid conditional derivation cannot establish its own applicability. Do not resolve an internally ambiguous question by silently discarding a chronology condition.

Use a stable verification-kind policy: externally contingent facts require fetched evidence; direct visual claims require inspection of original images; elementary symbolic calculations may be checked as derivations; execution-dependent numerical claims require a matching successful artifact. Passing code execution establishes the implemented calculation, not the model of the question. Keep Jev out of image inspection and preserve the Sol-only path for `no_search_algorithm`.

Selection may choose only a candidate with current passed critical checks and complete contract coverage. Preserve the existing exact scoped reference resolver. Optional prose can be narrowed without weakening the necessary basis; abstention remains available when a required interpretation or premise is unresolved.

**Acceptance:** exercise under-checking and over-checking in candidate-specific fixtures. Include factual-to-derived transitions, conditional solutions missing applicability, completed-procedure chronology, qualified possibility, multipart answers, valid independent reasoning, visual observations, and successful execution of the wrong modeled algorithm. Whole-history evaluation must count defensible candidates lost before selection as well as wrong eligible candidates.

## Case coverage and regression controls

The aliases identify private diagnostic cases, not adjudicated labels or answer-specific solver rules.

| Alias | Steps and required observation |
| --- | --- |
| `art_citation_offsets` | R1: recover coordinates while retaining its positive J2/J3 checks |
| `selection_gene_id` | R6–R7: separate identity, phenotype, and mechanism; preserve selection-ID repair |
| `selection_population_id` | R4/R7: host preference and qualified possibility; preserve candidate-specific adequate-audit controls and ID repair |
| `selection_clinical_id` | R3/R7: chronology and intended choice; preserve ID repair |
| `input_visual_program` | R2/R4–R6: context, table representation, subfacts, and identical J3 contracts |
| `input_large_image` | R2/R4: original images, structural shortlist, and complementary same-host evidence |
| `malformed_revision_citation` | R1–R2/R4/R6: complete citations, theorem survival, and checked transformation |
| `truncated_initial` | R2/R3/R7: complete replacement generation and construction applicability |
| `audit_music_scope` | R3/R7: stable visual, symbolic, and factual obligations |
| `missed_paper_lead` | R0/R4/R7: retain implemented direct fetch; distinguish partial bounds from a complete answer |
| `aria_title` | R6–R7: complete attribution; retain stronger-reviewed adequate-audit control |
| `visual_lattice` | R7: original image/application checks; retain adequate-audit control and unresolved reference dispute |
| `no_search_algorithm` | R3/R7: interpretation and derivation/visual checks without inventing a Jev failure |
| `math_convention` | R3/R6/R7: definition qualification and persistence of convention assumptions |
| `inference_underdetermined` | R3/R7: background support versus requested inference; adjudication still required |
| `source_temporal_scope` | R6–R7: source version, negative claims, and per-case applicability |
| `subsumption_scope` | R3/R7: algorithm assumptions and requested scope; preserve unresolved reference dispute |
| `source_claim_identity` | R3/R4/R6: stable premise identity and evidence retention in historically correct runs |

## R8 Measure each intervention and freeze the policy

Extend the existing [controlled replay utility](../src/jev_solver/evaluation/replay.py) into an orchestration path through [engine.py](../src/jev_solver/controller/engine.py) and [cli.py](../src/jev_solver/cli.py). It currently validates contracts and reports comparisons; it does not run the complete paid paired experiment. Extend manifest component identities to cover contract generation, structure/shortlist/packet policies, compaction, support aggregation, and final applicability checks. The runner must distinguish exact replay, newly generated behavior, unavailable snapshots, and failed attempts.

Use these comparisons in order:

| Comparison | Fixed inputs | Changed behavior |
| --- | --- | --- |
| Deterministic boundaries | Saved candidates, sources, budgets | R1 coordinates; R2 compaction; format recovery tested separately with fresh generation |
| Retrieval and J2 | Complete fetched sets and total allowances | Structure, shortlist, packet, J2 task, and admission as separate variants |
| J3 support | Declared claims and source blocks | Atomic decomposition and context construction, with conflict controls |
| Sol verification | Full candidate histories, original images, source/artifact snapshots | Persistent assumptions, kind policy, and final applicability checks |
| Matched B2/J23 | All 50 development questions, one implementation per comparison, same initial drafts/queries/results/source snapshots and resource caps | J2/J3 use; both arms retain verification |
| Integrated remediation | Same declared questions, backend, model settings, and caps | User-preserved baseline versus frozen repairs, with all changed components declared |

Block comparisons by Brave/Perplexity; do not infer provider superiority from these cases. If J2 and J3 effects remain mixed, add J2-only and J3-only comparisons. For a contract introduced before drafting, use a separate generation intervention: old initial drafts cannot represent its effect. Within each B2/J23 comparison share the same contract and initial drafts. If query planning changes, declare a separate routing experiment; replay only matching query/source snapshots, and explicitly account for new retrieval or unavailable snapshots.

Reuse a downstream response only when its complete inputs, model, prompt, schema, and component identity match. Changed evidence or requirements require fresh J2/J3/audit/revision/selection judgments wherever their inputs differ. Never relabel an old final prediction as the outcome of a new policy. Maintain evaluator-label isolation throughout inference.

Use adjudicated passage/claim/audit labels for semantic rates and keep Terra/Haiku/Astra reviews as provisional annotations. Add fresh examples beyond the inspected aliases, with calibration and validation separated by question/source family. Ambiguous visual/reference cases stay unresolved until adjudication. Report occurrence counts and question-level denominators separately.

Before a paid launch, freeze the manifest, replications, acceptance criteria, per-item/run/aggregate spend caps, and model/prompt versions. Paid execution follows the user's launch instruction and authorized budget; implementation alone does not launch it. Preserve the existing shared two-search/four-fetch, two-round, 12-dependency, 12-shortlist, six-passage, and 12,000-character allowances in the matched historical-profile comparison. Extra calls for contracts, decomposition, final checks, or recovery consume the same total allowance; any increase is a separately named experiment.

Report full-set accuracy, wrong answered items, abstentions, coverage, solver errors, source survival, support confusion, candidate-history losses, actual cost, and latency. Include every declared trial. Use paired question-level uncertainty, clustering repeated trials and backend observations of the same question appropriately. Report equal-workload results and a separately declared matched-cost comparison; equal caps do not imply equal realized cost.

The proposed default development promotion gate is higher full-set accuracy with no increase in wrong answered items under the same caps, plus passing deterministic and regression controls. Predeclare any alternative tradeoff before looking at outcomes. Wide uncertainty or absent labels warrants an inconclusive result, not an accuracy claim. Freeze the selected policy before a fresh evaluation; the 50 inspected development questions are not untouched held-out evidence.

## Validation and handoff

Extend the existing contract suites and add focused modules only where the graph, structured source mappings, or shared support contract merit their own tests. Public fixtures remain synthetic; historical questions, quotes, predictions, and labels remain private. Cover limits and resume in addition to successful paths. Offline suites must forbid external dispatch, and private tests must explicitly skip when their artifacts are absent.

After implementation, run the affected focused suites, then the repository checks:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_evidence_v3_regressions.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_evidence_v3_private.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_verification_contract.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_evidence_workflow.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_search_attribution.py' -v
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
git diff --check
```

Include focused discovery for any new test modules. Run the existing offline failure-analysis reproduction against frozen inputs in its separate private output directory. Record optional integration skips and actual test totals at execution time; prior reports are not a new validation result.

The implementation handoff contains the baseline revision, independent change identities, versioned schemas/policies, synthetic regressions, private replay adapters, offline results, and controlled-experiment manifests. Paid and adjudication-dependent gates remain pending; see the [handoff](EVIDENCE_V3_REMEDIATION_RESULTS.md).
