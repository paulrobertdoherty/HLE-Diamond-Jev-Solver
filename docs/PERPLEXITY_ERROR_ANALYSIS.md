**Perplexity evidence-v2 error analysis — 2026-11-01**

The latest Perplexity run completed successfully and improved the development score, but retained the main workflow weaknesses found in [this morning's Brave audit](BRAVE_ERROR_ANALYSIS.md). It answered 26/50 correctly, returned 15 incorrect answers and abstained on nine. All 32 Perplexity searches succeeded, with no solver failures, timeouts or Jev outages. The failure being investigated is the remaining answer-quality shortfall, rather than an unsuccessful benchmark execution.

This offline audit reconciled the predictions, existing Astra grades, candidate histories and cached judgments for both completed runs. The implementation, dependency lock, protocol, questions and split match; normalized configurations differ only in `search_backend`. None of the fixes proposed in the Brave audit was applied before Perplexity ran. Initial Sol responses and subsequent model judgments were sampled afresh. Perplexity supplies Search API results; Sol still generates and selects answers, and Jev judges passage relevance and declared citation support.

| Measure | Evidence-v2 Brave | Evidence-v2 Perplexity |
| --- | ---: | ---: |
| Correct / 50 | 22 (44%) | 26 (52%) |
| Incorrect nonempty | 17 | 15 |
| Abstentions | 11 | 9 |
| Accuracy among answered items | 56.4% | 63.4% |
| Wrong answers with no source claims or citations | 17/17 | 15/15 |
| Wrong answers identical to their own initial response | 16/17 | 14/15 |
| Wrong answers retaining explicit gaps | 9 | 8 |
| Wrong answers receiving no research | 8 | 7 |
| Jev relevance / support judgments | 497 / 6 | 512 / 7 |
| Final selector calls / active abstentions | 40 / 1 | 44 / 3 |
| Fetches producing allowed pages / attempts | 78/106 | 84/100 |
| Logged call errors, including undispatched limit errors | 31 | 18 |
| Solver accounted cost | $1.451113466 | $1.563265992 |

The paired outcomes are:

| Brave outcome | Perplexity correct | Perplexity incorrect | Perplexity abstention |
| --- | ---: | ---: | ---: |
| Correct | 21 | 1 | 0 |
| Incorrect | 3 | 12 | 2 |
| Abstention | 2 | 2 | 7 |

**Why the wrong answers survived.** All fifteen selected incorrect answers had empty `source_claims` and `citations`, and their assessments were `accepted: true` without citation-support or constraint checks. The prompt defines source claims as facts used from supplied passages, so unverified prior knowledge can follow the same acceptance path as an independent derivation. With `adaptive: false`, the separate constraint checks are skipped. Jev was not asked to verify these fifteen final answers. This repeats the central Brave finding; switching search providers does not change that acceptance rule. See [assessment and research control](../src/jev_solver/controller/engine.py), [claim coverage and relevance judgments](../src/jev_solver/judgments/pipeline.py), and [candidate instructions](../src/jev_solver/providers/backbone.py).

Fourteen wrong final responses exactly matched their initial answer text. The fifteenth reworded the same incorrect art-history identification. Seven received no research because the initial response listed no gaps, queries or code. The other eight each used only one of two permitted search requests: three received empty packets, and five received passages that did not establish their final conclusions. Five of the eight also had one unused fetch slot; the other three had exhausted all four fetch attempts. A fixed single revision round cannot plan and run a new targeted query after observing an unresolved gap. Mean reported confidence on wrong answers was 84%; eight were at least 90% confident. These observations do not justify treating confidence as an independent correctness check.

**The decisive Brave evidence-loss case repeated.** Both providers fetched the same art-history article, and the same passage containing the benchmark's expected answer was submitted to Jev. With the same answer-biased query, its normalized relevance was 0.357 in Brave and 0.353 in Perplexity, below the 0.667 inclusion threshold. A passage about the initially guessed feature survived instead, scoring 0.767 and 0.783 respectively. Both revisions acknowledged that the retained evidence did not verify their answer, yet final selection preserved the guess. The request hashes and passage text were reconstructed directly from both caches. The relevance request supplies the query, passage, URL and title, but omits the original question. This is a traced pipeline failure after successful retrieval.

Another missed opportunity appears in the Perplexity search cache for a poet's original name. An allowed result at rank six contained the expected name in its snippet. The four-fetch budget was spent on earlier results, three of which failed, so that result was never fetched. Search snippets do not enter the solver's evidence packet. This is evidence of an unused retrieval lead, not independently verified truth from the snippet; a source fetch and support check would still be needed. The adapter and fetching behavior are in [web tools](../src/jev_solver/tools/web.py).

**What explains the five gains and one loss.** Two gains have a clear within-run evidence trail: an opera title was corrected using a fetched song listing, and a gamelan answer was corrected using a scholarly passage. Both final candidates declared their dependency and received Jev support checks; the opera citation first required an offset repair. The gamelan searches used the same query in both runs. The opera query differed, and Brave had also returned the useful site but did not fetch it within its query-specific allocation. These examples show that source availability, ordering and fetch allocation can matter.

The other three gained questions already contained the eventual correct conclusion in the fresh initial response: a film-dialogue question, an image riddle and a historical legal citation. Their revisions explicitly said the new evidence did not establish the answer. They cannot be credited as search-driven corrections. The sole correct-to-incorrect transition changed an initial image-based Turing-machine answer; neither run searched or executed code for it. Twelve wrong answers persisted, two wrong answers became abstentions, and two previous abstentions became wrong answers. Those newly answered misses retained an unverified film-location guess and an unverified mathematical theorem respectively.

**Abstentions and selection still need separate treatment.** Six of the nine Perplexity abstentions had no eligible answer, following incomplete mathematical derivations or missing specialized sources. Three were active `none-supported` decisions. One appropriately withheld an unverified image identification; another withheld a mechanics result after its code failed and the corrected program remained unexecuted. The third discarded an initial crystal-pattern answer that exactly matched the reference. Thus additional abstention was not uniformly beneficial. The selector returned answers on 41/44 calls, including all fifteen incorrect final answers. In another mathematical case it chose an unsupported initial answer over a different unsupported revision; neither matched the reference. Candidate preservation needs an independent reason to trust a proposal. See [final selection](../src/jev_solver/candidates/selection.py).

The eighteen logged call errors comprise fifteen fetch `ProviderError`s, one fetch policy `Blocked` error and two search-limit exceptions before dispatch. They are not eighteen failed questions or Perplexity API failures. Two of four executed programs exited nonzero; these are separate code-result artifacts. Fewer failed fetches and fewer empty research packets are observed improvements, but different queries and model samples prevent assigning the entire score gain to the search backend.

The implementation priorities remain: distinguish unverified factual dependencies from checked derivations; treat unperformed checks explicitly; give retrieval judgments the original question and neutral missing facts; use snippets to prioritize promising source fetches; support follow-up verification within a declared budget; and require final selection to account for unresolved necessary facts. Image interpretation and failed numerical programs need their own verification paths. Restoring a blanket citation requirement would again discard useful independent solutions. Evaluate these changes on saved traces and fresh development cases, then compare matched B2/J23 arms and shared initial candidates before claiming a provider or Jev benefit.

The existing paired comparison is +8 percentage points, with bootstrap 95% interval [0, 18] pp and exact McNemar p=0.219. No new grading was performed. Some reference disagreements concern assumptions, requested precision or answer formulation; this audit retains the recorded grades rather than independently adjudicating every subject-matter answer. This repeatedly inspected fifty-question development set does not establish a generalizable backend advantage.

The full private item analysis is `private/sol-low-evidence-v2-j23-perplexity-error-analysis.md`; reconstructed evidence is `private/sol-low-evidence-v2-j23-perplexity-error-audit.json`. Reproduce the offline checks with `.venv/bin/python private/audit-perplexity-errors.py`. They reconcile both fifty-item runs and grades, match every recorded relevance request to cached source text, cross-check Brave against the previous audit, and verify the decisive filtering and selector cases. No solver implementation, original benchmark outputs or grades were changed, and no paid calls were made.
