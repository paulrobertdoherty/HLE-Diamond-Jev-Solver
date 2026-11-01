# Sol low-reasoning pilot

`configs/sol-low.pilot.json` measures GPT 6.1 Sol at low reasoning on a seeded, stratified 50-question HLE-Diamond development split. B0 makes one structured model call per question, preserves images, and uses no Jev, search or code tools. This pilot measures cost, usage, completion rate and latency; accuracy requires separate grading. It is a development result, not a full benchmark score.

The model is `openai/gpt-6.1-sol` with 8,192 output tokens including reasoning, a 65,536-token input envelope, no temperature override and no retries. At the configured $2/M input and $10/M output rates, the per-attempt reservation is $0.212992; 50 reservations total $10.6496. The run cap is $20, leaving $7 of the stated $27 balance outside this run. The item cap is $0.50. Accounting is conservative; these are not expected charges or invoice guarantees. Grading has its own configuration and budget.

Prices were checked on 2026-10-30 against [OpenRouter](https://openrouter.ai/openai/gpt-6.1-sol). The dataset revision is pinned to `04eeb7efa7e3e4f83a00cbd5ce436a38fd5dda23`, read from the public Hugging Face dataset metadata. The private B0 pilot has completed and received automatic reference-based Astra grades: 22/50 correct (44%). The separate timeout retest was incorrect, leaving the percentage unchanged. Private aggregate reports are in `private/sol-low-pilot-correctness-summary.md`.

From the repository root, install the API and dataset dependencies:

```bash
uv sync --locked --extra api --extra data --extra dev
source .venv/bin/activate
```

Accept the dataset conditions and export `HF_TOKEN` locally. Prepare into a new directory so the pilot's split is separate from other experiments:

```bash
jev-solver prepare --revision 04eeb7efa7e3e4f83a00cbd5ce436a38fd5dda23 --dev-count 50 --seed 17 --output private/sol-low-pilot-data
```

Validate and estimate without making paid calls:

```bash
jev-solver validate --config private/sol-low-pilot.json
jev-solver estimate --config private/sol-low-pilot.json --items 50
```

A private working copy is supplied at `private/sol-low-pilot.json`; recreate it with `cp configs/sol-low.pilot.json private/sol-low-pilot.json` if needed. The CLI estimate's $20 run envelope is the configured cap, not the tighter $10.6496 sum of 50 B0 reservations.

The following command launches the paid pilot after preparation. **Include `--split development`: configuration does not select or enforce the question count.** Without that option, the CLI defaults to the full prepared set.

```bash
export OPENROUTER_API_KEY="$(tr -d '\r\n' < private/openrouterkey.txt)"
jev-solver run --config private/sol-low-pilot.json --questions private/sol-low-pilot-data/solver/questions.jsonl --split development --output private/sol-low-pilot-run
```

Review `private/sol-low-pilot-run/usage.json` for input, output and reasoning tokens, attempts and accounted cost. Divide cost and token totals by 50 for per-question averages, and also inspect failed/abstained predictions. Private `model_response` events record `finish_reason`; count `length` completions to assess whether the output limit is too low. Use a new run directory if settings change. The [runbook](RUNBOOK.md#grading-and-paired-analysis) explains separate grading; the remaining 950 held-out items should stay untouched while tuning.

## Jev evidence pilot

`configs/sol-low.jev-pilot.json` uses the same Sol provider settings and development split with the J23 workflow. Sol generates one initial candidate, receives one round of audited web search and isolated Python checks when requested, and revises its answer. Jev `jev-1.14.0` reranks retrieved passages and checks citation support. It is an internal judgment service; Astra remains the separate outcome grader.

The solver cap is $10, with a $1.25 item cap, at most two searches, four fetches and one code execution per question, no retries, and two concurrent items. A separate private Astra grader configuration caps grading at $5. The finalization reserve is $0.22; Sol's per-call reservation remains $0.212992. [TypeSafe's published rate](https://docs.typesafe.ai/models) is $0.042/M input tokens and free output; [Brave Search](https://brave.com/search/api/) is accounted at $0.005 per request before account credits.

The sandbox digest in this configuration identifies the local protocol image. On another machine, build and verify the image using the runbook, then update the digest before starting a new run.

```bash
export TYPESAFE_API_KEY="$(tr -d '\r\n' < private/jev-key.txt)"
export BRAVE_SEARCH_API_KEY="$(tr -d '\r\n' < private/brave-key.txt)"
jev-solver validate --config configs/sol-low.jev-pilot.json
jev-solver estimate --config configs/sol-low.jev-pilot.json --items 50
jev-solver run --config configs/sol-low.jev-pilot.json --questions private/sol-low-pilot-data/solver/questions.jsonl --split development --output private/sol-low-jev-pilot-run
```

A comparison with B0 measures the whole pipeline, including tools and additional Sol calls. A matched B2 run would be needed to isolate Jev's contribution. All 50 questions, including abstentions and failures, remain in the denominator.

The private J23 pilot completed all 50 questions without solver errors or timeouts. Astra graded 16/50 correct (32%), compared with B0's 22/50 (44%). J23 returned 23 nonempty answers and 27 abstentions; 13 abstentions followed rejection for missing citations after repair. Additional accounted cost was $2.17 including service checks and grading, of which $1.90 was reported through OpenRouter. Details are in `private/sol-low-jev-pilot-summary.md`. This small development comparison has a paired bootstrap interval of -28 to +2 percentage points for J23 minus B0.

The measured pilot's citation gate required a citation whenever retrieved evidence was present, even when an answer could be derived independently. After one unsuccessful repair, it replaced the answer with an abstention. J23 selected only the latest revision, so an earlier candidate was not available as a fallback. This policy forced 13 of the 27 abstentions; Sol chose the other 14, sometimes after receiving irrelevant or inaccessible sources.

Of the 11 questions B0 answered correctly that J23 lost, six ended in citation-gate abstentions, three in model-chosen abstentions, and two in incorrect nonempty answers. J23 also gained five correct answers, producing a net loss of six. All 12 Jev citation-support judgments returned supported; the 656 other Jev calls ranked passages. These observations identify a workflow problem and do not isolate Jev's effect: Sol was sampled afresh, and a matched B2 control was not run. Those historical results and their private manifests retain the measured policy.

## Evidence-v2 follow-up implementation

The current implementation narrows citation requirements to explicitly declared critical source dependencies, preserves validated earlier candidates, and gives final selection the actual evidence and check artifacts. It also shares fetch opportunities across queries, tries later allowed results when sources fail, balances the passage shortlist across sources, and excludes Jev's irrelevant/background-only levels from the evidence packet. The [implementation notes](IMPLEMENTATION.md#fixed-workflow-and-adaptive-controls) describe the policy and its limits.

Four new configurations form a 2×2 development comparison: `configs/sol-low.evidence-v2.{b2,j23}.{brave,perplexity}.json`. They retain Sol's settings, the pinned development split and the original per-item/run/tool caps. All four use the same charged backbone final-selection stage; J23 alone adds Jev relevance/support judgments. Brave and Perplexity J23 have now run; the B2 controls remain prospective. Follow the [runbook](RUNBOOK.md#evidence-v2-development-comparison) and use new run directories. Fresh initial model sampling still contributes variation; repeated or explicitly paired candidate experiments are needed to quantify it. Current code cannot reproduce the old workflow simply by loading an old pilot configuration; use its recorded implementation revision for historical reproduction.

On 2026-10-31, evidence-v2 Brave J23 completed the same fifty development questions with 22 correct answers, 17 incorrect nonempty answers and 11 abstentions, without solver failures. Against the previous J23 run, nine questions became correct and three lost correctness: +12 percentage points, paired bootstrap 95% interval [0, 26] pp, exact McNemar p=0.146. Overall accuracy matches the earlier B0 result, but this small comparison does not establish a reliable improvement or isolate Jev's contribution. Solver plus grading accounting was $1.872108466. The private comparison report is `private/sol-low-evidence-v2-j23-brave-summary.md`.

The [error analysis](BRAVE_ERROR_ANALYSIS.md) explains the increase in incorrect nonempty answers. Eleven former abstentions became incorrect answers, and all seventeen incorrect final answers retained the initial answer's conclusion. Empty source-dependency declarations bypassed Jev support checking; final selection rarely abstained on a nonempty pool; and an answer-biased relevance query discarded a fetched passage containing the expected answer. These are measured limitations of evidence-v2, requiring further work before interpreting a search-provider change as a sufficient fix.

On 2026-11-01, evidence-v2 Perplexity J23 completed the same fifty questions under the unchanged solver implementation, with 26 correct answers (52%), 15 incorrect nonempty answers and nine abstentions. There were no solver failures, timeouts or grader errors. Compared with evidence-v2 Brave, it gained five correct questions and lost one: +8 percentage points, paired bootstrap 95% interval [0, 18] pp, exact McNemar p=0.219. Accuracy among answered questions was 63.4%, versus Brave's 56.4%. This exploratory comparison does not establish a reliable backend advantage or separate retrieval effects from fresh model sampling. Solver accounting was $1.563265992 and Astra grading was $0.437535, totaling $2.000800992. The private report and paired artifacts are in `private/sol-low-evidence-v2-j23-perplexity-summary.md` and `private/sol-low-evidence-v2-perplexity-vs-brave.json`. The benchmark used Perplexity Search API results with the existing Sol/Jev workflow.
