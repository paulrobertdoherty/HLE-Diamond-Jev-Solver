# HLE-Diamond Jev Solver

A planned research harness combining API-accessible reasoning models, TypeSafe's Jev, web search, and code execution to improve benchmark accuracy and the accuracy–cost tradeoff.

**Status: design only. No solver has been implemented and no benchmark results have been measured.**

The central experiment is whether Jev's focused judgments improve evidence selection, verification, and compute allocation beyond an otherwise comparable agent. Beating a single raw model call is one objective; demonstrating an incremental benefit from Jev is a separate objective.

Read the [research and implementation plan](PLAN.md) for the literature review, pipeline design, evaluation controls, milestones, and publication requirements. Research was checked on October 28, 2026.

The proposed first release supports one reasoning provider, one search backend, isolated code execution, and Jev passage ranking and citation checks. Additional providers and a persistent retrieval corpus follow only after controlled evaluation.

HLE-Diamond has 1,000 questions, divided evenly between reasoning and knowledge. Access is gated, and the authors request that users avoid redistribution. Dataset downloads, answers, question-bearing traces, and private evaluation artifacts belong outside the public repository. See the [official dataset card](https://huggingface.co/datasets/cais/hle-diamond).

This is an independent project; it does not imply affiliation with TypeSafe, the Center for AI Safety, or Scale AI.
