# Initial Luna / Terra / Haiku labeling pilot

**Starting a new session:** follow the [next-session instructions](#next-session-instructions) below. They record the recommended Terra/Haiku follow-up, link to the operating instructions, and distinguish completed tests from work still needed. The original pilot results follow here. The full saved-component Terra/Haiku follow-up is now complete; see [expanded review results](EVIDENCE_V3_EXPANDED_REVIEW.md).

Completed 2026-11-02. **108 paid OpenRouter calls cost $0.27006375**, reconciled with the account's settled usage change. Available credits changed from $24.695061285 to **$24.424997535**. The run had a shared $6 cap and a conservative planned maximum of $2.3363844. There were no retries, ambiguous charges, live search calls, source fetches, or new Jev calls.

Terra is the provisional primary reviewer. Luna provides an independent comparison. **Haiku only flags differences with Terra**; it never votes, overrides Terra, supplies accepted gold labels, or changes solver behavior. All 1,895 original label records remain unchanged and unresolved.

## Models and sample

| Reviewer | OpenRouter model | Catalog snapshot | Reasoning | Valid reviews / calls | Reported cost |
| --- | --- | --- | --- | --- | --- |
| Luna | `openai/gpt-6-luna` | `gpt-6-luna-20260922` | medium | 29 / 36 | $0.02747445 |
| Terra | `openai/gpt-6.1-terra` | `gpt-6.1-terra-20261026` | medium | 33 / 36 | $0.20767450 |
| Haiku | `anthropic/claude-haiku-5.5` | `claude-haiku-5.5-20261007` | medium | 32 / 36 | $0.03491480 |

The model catalog, official-provider endpoint metadata, exact requests, responses and generation/accounting checks are retained privately. All three received the same evidence independently, without seeing another reviewer's output. J2/J3 saved predictions were hidden; audit reviewers saw the historical audit they were asked to diagnose. Original images were attached as images. No reference answers or grades were sent.

The 36 saved artifacts cover all 18 inspected question aliases, with 18 artifacts from each saved backend. They are **not 36 independent questions**. Deterministic diagnostic strata comprise 16 J2 passages (four each unexecuted, low, middle and high saved scores), 12 J3 records (eight originally supported, three insufficient, one contradicted), and eight audits (four with images). Exact duplicate component inputs were excluded. This is a selected development pilot, not held-out accuracy evaluation or a representative error-rate estimate.

The calls used 382,384 input tokens and 79,868 output tokens, including 63,299 reported reasoning tokens. Model tokenizers and image accounting differ. A valid review passed the output/category/confidence checks and, for J2/J3, exact source-quote validation. Validity does not establish that the diagnosis is correct; a valid `unresolved` result also remains unresolved.

## Comparison with Terra

The main decision is J2 relevance, J3 support, or the audit diagnosis. Other labeled differences include J2 answer-bearing/contradiction categories and audit finding IDs/types. Differences in prose or confidence alone are excluded. Unavailable pairs are excluded from comparison denominators.

| Component | Luna: valid pairs | Luna: main decision differs | Luna: any labeled field differs | Haiku: valid pairs | Haiku: main decision differs | Haiku: any labeled field differs |
| --- | --- | --- | --- | --- | --- | --- |
| J2 relevance | 13 / 16 | 2 | 3 | 13 / 16 | 2 | 4 |
| J3 source support | 7 / 12 | 0 | 0 | 8 / 12 | 1 | 1 |
| Historical audits | 8 / 8 | 4 | 5 | 8 / 8 | 5 | 6 |
| Total | 28 / 36 | 6 | 8 | 29 / 36 | 8 | 11 |

Luna and Terra agreed on the main decision in 22 of 28 valid comparisons. Haiku flagged 11 of 29 valid comparisons: eight main-decision differences and three differences in other labeled details. Every flag, each model's categories/basis, and the seven unavailable Terra/Haiku pairs are recorded in `private/v3-label-pilot-2026-11-02/haiku-disagreements.md`. An audit finding-ID difference can reflect different decomposition rather than a substantive dispute; the notes preserve the bases for review.

## Output-grounding failures

| Model | J2 valid / 16 | J3 valid / 12 | Audits valid / 8 | Invalid review reasons |
| --- | --- | --- | --- | --- |
| Luna | 14 | 7 | 8 | Seven reviews contained supporting quotes absent verbatim from the supplied source |
| Terra | 14 | 11 | 8 | One source-quote mismatch; two quotes exceeded the requested 240-character limit |
| Haiku | 15 | 9 | 8 | Four reviews contained source-quote mismatches |

All 108 requests completed at the provider boundary. Fourteen outputs failed review validation; their costs and raw outputs remain recorded. No automatic repair or retry concealed these failures. Luna's seven invalid reviews reported confidence between 0.91 and 0.99, so self-reported confidence would not have caught them. Quote/length compliance failures are not measurements of semantic judgment accuracy, and Terra's two length violations should not be equated with unsupported reasoning.

## What this suggests about the historical pipeline

These are **Terra's provisional diagnoses**, not independently established faults:

- **J2:** Of 14 valid reviews, Terra called five passages useful (partial/direct): four were retained historically and one was excluded by the relevance policy. That excluded fragment was only partial/bibliographic evidence according to Terra's own basis, so this does not establish an erroneous Jev rejection. Among four sampled passages excluded before J2, Terra returned two background judgments, one unresolved result and one invalid review; none supplies a validated useful-passage label. A passage never sent to Jev remains outside Jev's rejection denominator.
- **J3:** Terra differed from four of 11 saved decisions: three `supported → insufficient`, one `contradicted → supported`. The first three concern construction ambiguity or an unstated relationship between experimental strains. The fourth concerns temporal/source scope. Two differences come from the same question alias, so these are not four independent question failures. No false-support/false-rejection accuracy rate is asserted without independent adjudication.
- **Audits:** Terra called six adequate and two under-restrictive. It questioned visual discrimination in `visual_lattice` and an unestablished logical alternative in `subsumption_scope`. It diagnosed no audit as over-restrictive in this sample. Haiku differed on the main diagnosis for five of eight audits, making those useful review targets rather than reliable votes against Terra.
- **Brave versus Perplexity:** This pilot labeled saved artifacts. It did not run matched identical queries against both search providers or repeat complete solver arms, so it cannot establish comparative search quality or end-to-end causation.

The pilot supports the practicality of inexpensive independent reviews and local quote checks. It does not identify an accuracy winner or demonstrate that model-family similarity caused the historical errors. Keep Terra's diagnoses provisional, review the recorded disagreements and some agreements against evidence, and preserve Haiku's note-only role in subsequent work.

## Reproduction and artifacts

The [usage guide](EVIDENCE_V3_TESTING.md#capped-ai-label-pilot) documents the capped runner. Private artifacts are under `private/v3-label-pilot-2026-11-02/`:

- `pilot-plan.json`: frozen sample, inputs/observations, request hashes, model identities, rates and caps.
- `events.sqlite3`: durable reservations, reported usage, settled costs and saved attempts.
- `pilot-results.json`: all raw responses, provisional reviews and pairwise differences.
- `analysis.json`: component counts, validation failure reasons and provisional historical comparisons.
- `terra-diagnoses.md` and `haiku-disagreements.md`: per-case review notes, without converting any labels into gold.
- `credits-preflight.json`, `credits-final.json`, endpoint/catalog snapshots and generation checks: accounting/model metadata.
- `tests.log`: full offline/mocked regression validation.

The full regression suite passed **198 tests, zero failures, one optional Docker test skipped**. Eight focused pilot tests cover source/label isolation, actual image attachment, deterministic sampling, quotation rejection, Haiku's note-only role, decimal price checks, caps and resume behavior. Ruff lint/format checks and `git diff --check` passed. Benchmark content and credentials remain in ignored private paths.

## Next-session instructions

The 2026-11-05 [expanded review](EVIDENCE_V3_EXPANDED_REVIEW.md) completed all 1,811 proposed component records with Terra/Haiku and 41 independent Astra spot checks, within the authorized $20 aggregate cap. Original labels remain unresolved; the controlled final-answer experiment is still outstanding. The instructions below preserve the pre-run handoff and should be read alongside that completion report.

Handoff updated 2026-11-05. The initial pilot's purpose was to find an inexpensive way to perform AI-assisted verification. The next objective is to identify which evidence and verification decisions contributed to the lack of HLE-Diamond improvement, then measure Jev's effect in a controlled comparison. Reviewer output-validity percentages measure compliance with the review contract; they do not establish semantic accuracy.

### Instruction references

| Document | What to use it for |
| --- | --- |
| [Usage guide: private labels and saved evaluation](EVIDENCE_V3_TESTING.md#private-labels-and-saved-evaluation) | Frozen inputs, label schemas, provenance, and offline component/workflow evaluation commands |
| [Usage guide: capped AI-label pilot](EVIDENCE_V3_TESTING.md#capped-ai-label-pilot) | Existing runner preparation, paid-call flag, accounting and resume behavior; these commands reproduce the small pilot only |
| [Test plan](EVIDENCE_V3_TEST_PLAN.md) | T06 audit review, T07 passage relevance, T08 citation support, and the later T09–T11 search/reference/controlled experiments |
| [Completed validation and remaining measurements](EVIDENCE_V3_TEST_RESULTS.md) | What has already passed and which quality measurements remain unavailable |
| [Trace attribution](EVIDENCE_V3_SEARCH_ATTRIBUTION.md) | Established integration failures and hypotheses to investigate without assigning every loss to Jev |
| [Controlled replay instructions](EVIDENCE_V3_TESTING.md#controlled-replay-and-paired-reports) | Comparison manifests, cache/input identity rules and paired outcome reporting |

The test plan preserves its original pre-implementation handoff. Use the completion report and this section for current status: the software contracts and evaluation utilities are implemented; the expanded labeling run and controlled solver experiment remain outstanding.

### Recommended reviewer configuration

- Use **Terra as provisional primary reviewer** (`openai/gpt-6.1-terra`, medium reasoning).
- Use **Haiku as an independent disagreement checker** (`anthropic/claude-haiku-5.5`, medium reasoning) across the same cases, including valid, confident Terra reviews. A fallback triggered only by malformed Terra output would miss substantive disagreements. Haiku continues to flag differences without voting or automatically overriding Terra.
- Omit Luna from the proposed expanded bulk pass. Preserve its original pilot results.
- Give both reviewers the same frozen evidence and original images independently. Hide each other's outputs and historical J2/J3 verdicts. Audit reviewers must see the historical audit being diagnosed. Keep reference answers and grades out of these component-review requests.

These are recommendations for the next experiment, not a claim that Terra supplies gold labels or that the expanded run has already been authorized or executed.

### Work sequence

1. **Inspect and preserve the existing work.** Check repository instructions, the working tree and the private artifacts. The primary input is `private/v3-test-plan-implementation/cases/label-cases.jsonl`; the original pilot is in `private/v3-label-pilot-2026-11-02/`. These ignored files do not accompany a normal clone. Preserve original inputs, observations, grades and pilot outputs. The current code differs from the historical run; use the baseline snapshot procedure in the usage guide if historical reproduction is needed.

2. **Prepare an expanded runner before launching reviews.** The current [pilot runner](../src/jev_solver/evaluation/label_pilot.py) hardcodes three reviewers, selects 36 cases and refuses a cap above $6. Its existing CLI cannot launch the proposed full Terra/Haiku review. Add a separately identified expanded mode or runner with explicit reviewer/scope configuration, a frozen plan, fresh output directory, request hashes, bounded concurrency, durable accounting and safe resume. Preserve the original pilot's reproduction path. Verify model identities and rates, calculate the actual request bounds, and enforce the budget specified for the new experiment. Check changed behavior offline before paid dispatch.

3. **Review the saved component records first.** The proposed scope is 1,516 J2 passages, 142 J3 support records and 153 audits: **1,811 records**. Document deduplication, omissions and unavailable reviews. These are selected development artifacts, not independent questions or the entire benchmark. The additional 48 search and 36 reference/history records are separate work under T09/T10. Reuse saved Jev responses and source snapshots; this stage needs reviewer calls, without fresh Jev judgments, searches or fetches.

4. **Validate and adjudicate before treating labels as truth.** Enforce exact source quotations and the 240-character quote limit; preserve invalid attempts and their charges. Any repair must be bounded and reported separately. Review consequential disagreements, invalid outputs, and a predeclared random sample of agreements with a stronger adjudicator such as Astra or manual inspection. Keep unresolved cases unresolved. Stronger-model judgments and model agreement remain provisional unless independently adjudicated; record provenance and keep any human-checked calibration sample distinct. The existing component/workflow evaluators require adjudicated labels for semantic accuracy, so do not relabel raw Terra outputs merely to populate those metrics.

5. **Report component findings with stage attribution.** Separate reviewer agreement/output validity from adjudicated accuracy. Measure evidence survival, false support, false rejection and audit errors where labels permit. Of the extracted J2 records, 487 have saved judgments and 1,029 were lost before Jev; the latter cannot count as Jev rejections. Trace consequential decisions to candidate rejection or selection, distinguishing a questionable judgment from a demonstrated effect on the final answer.

6. **Then measure the effect on final answers.** Prepare a matched B2/J23 comparison on the development questions, using the same implementation, solver settings, budget caps, verification rules and shared initial drafts/source snapshots. Change the relevance/support judge while retaining verification in both arms. Treat integration fixes as a separate intervention. Generate and account for downstream calls when changed inputs prevent valid cache reuse. If necessary, isolate J2 and J3 in separate arms. Include every question, abstention and error; report accuracy, coverage, wrong answers, cost and paired uncertainty. The replay utilities are implemented, but a complete controlled paid arm runner is still outstanding. Broader held-out evaluation follows once the experiment is defined; the saved component review alone cannot establish a benchmark-wide Jev effect.

### Cost basis and expected deliverables

Extrapolating the original pilot's observed mean cost separately for J2, J3 and audits gives approximately **$6.82 for Terra plus $1.27 for Haiku, or $8.09 combined**, over the 1,811 records. This is a historical workload estimate, not a guaranteed charge or an execution cap. It excludes retries, adjudication, search/reference reviews and fresh solver/Jev/search runs; input lengths, model rates and deduplication can change it. The original pilot's $6 cap applies to that pilot only.

Save the new frozen plan, raw reviews, validation failures, disagreement notes, adjudication provenance and usage ledger privately. Summarize aggregate findings and the proposed controlled comparison in repository documentation. Keep the original pilot intact, and state clearly which conclusions are provisional, independently checked or supported by a measured change in final outcomes.
