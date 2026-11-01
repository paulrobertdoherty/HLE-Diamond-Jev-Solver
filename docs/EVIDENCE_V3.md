# Evidence-v3 implementation and TypeSafe setup

This implements the repository fixes identified in [the search root-cause investigation](JEV_SEARCH_ROOT_CAUSE.md). The investigation and its saved predictions remain historical evidence. These changes have offline regression coverage; they have not yet demonstrated improved accuracy in a paid benchmark rerun.

## What changed

| Failure | Implemented behavior |
| --- | --- |
| Empty source declarations bypass verification | Every tool-arm draft receives a separate backbone audit of the original question, necessary dependencies, omitted premises and gap criticality. `coverage` and `eligible` are separate trace fields. |
| No gaps means no research | The independent audit runs before the controller decides whether to research. It can discover missing facts and generate queries even when the initial draft has no gaps or queries. |
| Relevance judged against a guessed answer's search string | J2 receives the original question, a neutral `missing_fact`, the actual `search_query` and a dependency ID. Its rubric includes disconfirming evidence. |
| Uncertain evidence discarded at a hard cutoff | A configurable policy preserves at most one uncertain alternative in the packet, reserving room before useful passages consume its limits. This policy needs calibration. |
| Provider ordering wastes fetches | Filtered titles/snippets rank fetch leads against the neutral missing fact. Snippets never qualify as source support. |
| Research cannot use its own failures | Queries, unused leads, failed fetches, empty results and packet exclusions reach revision and subsequent audits. Two rounds share explicit search/fetch limits and reserve a fetch for follow-up. |
| Earlier unsupported answers remain selectable | Every initial, revised and repaired candidate is reassessed against the final evidence and artifacts. Only candidates meeting coverage and answer checks can enter selection. |
| Selection records only an ID | Backbone selection must give a reason and reference actual passed critical dependency IDs. Corrections are generated and assessed during revision before selection. |
| Generated code mistaken for verification | Numerical checks require successful, untruncated, nonsynthetic execution artifacts with matching code hashes. The second round can execute repaired code. |
| Text judgments stand in for image checks | Visual dependencies require an independent backbone review of the original attached images, with image indices/hashes. Text-only Jev does not certify image interpretation. |
| J4 lacks the artifacts it judges | J4 receives actual passages, tool artifacts and dependency results, with unavailable checks explicit. J23 keeps J1/J4/J5/J6 disabled as before. |

The five check statuses are `not_run`, `not_applicable`, `unavailable`, `passed` and `failed`. Eligibility requires passed completeness, whole-answer review and every critical dependency; an incidental gap can remain. A checked derivation can qualify without citations. A factual premise requires fetched source references even when recalled from memory. In J3/J23, its entailment check must also be available and supported. Source entailment alone does not certify reliability or whole-answer correctness.

Independent audits use a separate backbone request, not a separate model or a formal proof engine. Discovery, criticality, derivation review and visual interpretation remain fallible model judgments. Synthetic tests establish the data and routing contract; independent labels and new calls are necessary to measure semantic quality.

## TypeSafe account steps

No training job, customer fine-tune, LoRA, classifier registration or dataset upload is required. Jev customization is sent in each request's `state`, `instructions` and `criteria`; those changes are implemented here. TypeSafe documents shared model weights and request-based customization. [TypeSafe customization documentation](https://docs.typesafe.ai/models#customizing-jev).

1. Sign in at the [TypeSafe console](https://console.typesafe.ai) and select the organization associated with your existing API key. Reuse that key if it already works; otherwise obtain an API key in the console. [Official setup guide](https://docs.typesafe.ai/introduction/quickstart).
2. Check **Settings → Billing → Available credits** for that organization. If the balance is depleted, an organization Admin can use **Add funds** to add the amount they intend to spend. Existing credit is sufficient; no automatic top-up is needed for these fixes. If payment was already made but access still fails, check Billing history before paying again. [TypeSafe billing instructions](https://help.typesafe.ai/articles/5505198974-what-s-a-402-error-and-how-can-i-add-more-credits), [Admin requirement](https://help.typesafe.ai/articles/7771619341-how-do-i-add-credits).
3. Check the organization's requests-per-second and tokens-per-second limits in the console. The new profiles use `limits.concurrency: 2`. On `429` errors, reduce this to `1` in a private config and start a fresh run, or request higher limits through TypeSafe's linked form. Changing concurrency changes the run identity. [Rate-limit documentation](https://docs.typesafe.ai/models#rate-limits).
4. Keep `jev.model: "jev-1.14.0"` pinned. No model change or long-context/image toggle is necessary. The profiles use the documented $0.042 per million input tokens and zero output-token price; verify your account terms before paid work. Versioned model IDs can be accepted even if the model-list endpoint shows only aliases. [Models and pricing](https://docs.typesafe.ai/models).

Export the key in the terminal that launches the solver. The project does not automatically load `.env` files. This Bash prompt avoids putting the key itself in shell history:

```bash
read -r -s -p 'TypeSafe API key: ' TYPESAFE_API_KEY
export TYPESAFE_API_KEY
printf '\n'
```

After installing the locked dependencies, this optional read-only account check lists available model names without running inference:

```bash
.venv/bin/python - <<'PY'
from typesafe_sdk import RetryPolicy, TypeSafeClient

with TypeSafeClient(retry=RetryPolicy(max_retries=0)) as client:
    for model in client.models.list().models:
        print(model.name)
PY
```

The solver also needs its existing `OPENROUTER_API_KEY`, the selected search backend's key (`BRAVE_SEARCH_API_KEY` or `PERPLEXITY_API_KEY`), prepared data and the pinned local sandbox image. These are separate from TypeSafe. Grading still uses a separate evaluator credential and budget. No account settings or funds were changed by this implementation.

## New run configurations

Use the new profiles instead of the historical evidence-v2 files:

| Backend | Control | Jev |
| --- | --- | --- |
| Brave | `configs/sol-low.evidence-v3.b2.brave.json` | `configs/sol-low.evidence-v3.j23.brave.json` |
| Perplexity | `configs/sol-low.evidence-v3.b2.perplexity.json` | `configs/sol-low.evidence-v3.j23.perplexity.json` |

Each profile has one initial candidate, two rounds, two searches, four fetch attempts, two code executions and at most 12 J2 passages per round. The packet holds at most six passages, two per host and 12,000 characters. The experimental policy retains one alternative scoring at least 1/3 with confidence at most 0.2, alongside ordinary passages scoring at least 2/3. Scores and confidence are not answer-correctness probabilities.

The per-item cap increases to **$3**, the total call cap to **120**, and the finalization reserves to **32 calls / $0.75**. Optional tools/J2 cannot consume those remaining reserves. Verification/revision/selection use them but still obey total caps. At the configured token/price bounds, a backbone reservation is $0.212992 and a Jev reservation is $0.002688; $0.75 covers three maximum backbone reservations plus a margin for judgments. This is a conservative envelope, not predicted billing or a guarantee that every possible maximum-size dependency inventory can finish.

The **run cap remains $10 per arm**; it can stop a 50-question run before completion. Four arms have separate caps, and grading is additional. Copy a profile to an ignored private path if changing budgets. Start with a small declared development subset, inspect traces and cost, then choose the full-run budget deliberately.

Offline setup and validation:

```bash
uv sync --locked --extra api --extra dev
.venv/bin/jev-solver validate --config configs/sol-low.evidence-v3.j23.perplexity.json
.venv/bin/jev-solver estimate --config configs/sol-low.evidence-v3.j23.perplexity.json --items 5
```

For a paid development smoke test, choose real IDs from your prepared **development** split and repeat `--question-id` for each. The placeholder below must be replaced:

```bash
.venv/bin/jev-solver run \
  --config configs/sol-low.evidence-v3.j23.perplexity.json \
  --questions private/sol-low-pilot-data/solver/questions.jsonl \
  --split development \
  --question-id YOUR_DEVELOPMENT_QUESTION_ID \
  --output private/sol-low-evidence-v3-j23-perplexity-smoke
```

Use a new output directory. Run and implementation hashes intentionally prevent resuming an old v2 run under v3 code. The historical profiles are not a compatibility switch back to v2; reproducing v2 requires its original checkout. No paid solver, search, Jev or grader run was launched for this implementation.

## Component and workflow evaluation

`component-eval` still compares Jev, backbone and lexical judgments on identical saved inputs. For J2, each private JSONL case now needs `id`, `stage`, `state` and normalized `expected`; `state` needs `question`, `missing_fact`, `search_query` and `passage`, with optional URL/title. Regenerate older cases lacking the question rather than substituting their search string. Use the same `task_id` for all competing passages in a frozen task. Optional Boolean `answer_bearing`, `useful` and `contradictory` labels enable packet metrics. Include the full competing passage set to measure shortlist and packet exclusions.

J2 reports usefulness-decision accuracy and score MAE, answer-bearing recall at the configured packet budget, and useful/contradictory exclusion rates. Exact continuous-score equality is no longer its accuracy metric. J3 reports a confusion matrix for supported, contradicted, insufficient and unavailable predictions. Gold labels never enter provider requests. Missing label denominators produce `null`, not a claim of perfect recall.

```bash
.venv/bin/jev-solver component-eval --config configs/synthetic.json --cases tests/fixtures/components.jsonl --output private/v3-components-synthetic --judge jev
```

Use `workflow-eval` for independently annotated saved coverage and selection decisions, with no inference calls. Reconcile claim IDs during annotation. Example **synthetic** JSONL rows:

```jsonl
{"stage":"coverage","required_claims":["fact-a","fact-b"],"discovered_claims":["fact-a","fact-b"],"checked_claims":["fact-a"]}
{"stage":"selection","candidate_ids":["right","wrong"],"correct_ids":["right"],"selected_id":"wrong"}
{"stage":"selection","candidate_ids":["right"],"correct_ids":["right"],"selected_id":null}
```

```bash
.venv/bin/jev-solver workflow-eval --cases private/labeled-workflow.jsonl --output private/workflow-metrics.json
```

This reports claim discovery/checked-coverage recall, wrong selections among selected answers, and abstentions among pools containing a correct answer. Include candidate IDs from the entire assessed history when measuring rejection caused by eligibility filtering. Keep expert labels and benchmark references outside solver inputs.

The four v3 profiles match settings for whole-workflow B2/J23 comparisons within each backend. They do **not** share stochastic initial responses or live-source caches across runs; cache keys remain configuration-scoped. For isolated judgment comparisons use identical frozen component cases. A shared-initial/shared-source end-to-end replay experiment needs a separately frozen manifest and explicit replay design; copying caches between arms is not a valid control.

Freeze the relevance/coverage policy after development calibration, then evaluate fresh questions. Existing `grade`/`compare`/`export` report full-set `accuracy`, answered-item `covered_accuracy`, `coverage`, costs and failures. Preserve the original audits and grades. Private `candidate_checks`, `research_outcome`, `selection_basis`, `code` and replay events provide the evidence for diagnosis.
