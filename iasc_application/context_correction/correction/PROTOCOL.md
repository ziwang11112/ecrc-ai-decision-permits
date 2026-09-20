# S9 public-helper context correction, version 1

This is a post-study input correction. The original S9 source, inputs and all 144 original trajectories remain preserved. It is not a new model generation experiment, an unseen-task study, a confirmatory registration, or an agent-benefit experiment.

The pinned official public HumanEval prompts contain non-entry top-level helper functions for exactly HumanEval/10, /32, /38 and /50. Restore a helper only when the candidate does not already bind its name. Preserve the candidate's own existing binding even if incorrect. Add only required imports from that same public prompt, without replacing a candidate binding. Never infer missing code from an official test, canonical solution, prior status, or a desired answer. Empty and syntactically invalid candidates remain unchanged; never retain the prompt's incomplete entry-point stub. The original candidate text remains an exact suffix of every changed assembled source. No other task receives an added prelude, imports or entry stub.

All 656 selected candidates retain task, source-array index, candidate identifier, rank, original candidate text and original hash. Eleven selected candidates receive public helpers. Their executable solution hash and consequent job/decision/evidence bindings change to identify the assembled source. Each catalog job retains public-prompt and added-context text/hashes separately. The official suite and runner hashes remain identical. The archival proposer hash identifies the original proposal archive; it does not claim that the archived model authored the restored public helper.

Replace all eight original factorial trajectories in each affected batch: evaluation_01, evaluation_10, evaluation_14 and evaluation_15. The 32-cell plan is an exact subsequence of the original 144-cell GRID_PLAN, preserving original batch indices, policy/condition/client order, original run numbers, candidate order and every result. Retain the other 112 original trajectories as explicitly versioned unchanged records. Do not select old versus corrected outputs by whether the correction improves an outcome.

Reuse the original run_one, both complete adapters, HTTP service, sandbox and runner without edits. A new compatible frozen protocol binds the corrected catalog and the original runtime source hashes; a separate correction hash inventory binds this assembly/entry point and plan. Original policy-clock values, capacity 16, deadline 5 seconds, one-second retry backoff, every-fourth-arm post-commit response loss, serial feedback/selection and pending drain are unchanged. There is no recalibration, tuning, or formal warm-up. Start with fresh client/service databases and run output. Refuse any existing formal runs directory and do not automatically retry technical failures.

Local QA may use purely synthetic source and a synthetic finite test to verify helper assembly through the unchanged sandbox. It must not execute selected application candidates before the formal correction run. Static checks verify exact changes, bindings, official input hashes, unchanged runtime files and the original-grid subsequence. An independent reviewer can inspect assembly without running candidates. Freeze and formal execution are separate explicit entry-point actions.

The endpoint definitions remain the original S9 definitions: timely pass requires receipt reconciliation by D; durable or eventual passes are separate; post-deadline drain cannot create a timely success. Starts/CPU/wall durations refer to actual runner records, and cached response recovery must retain its original key, payload and result. A corrected source may alter early feedback and therefore later choices anywhere within its batch: this is why the complete affected batch trajectories are replaced.

Replacement and retained timings were measured in separate sessions. Combined 144-cell corrected totals are descriptive, and an old-versus-corrected timing contrast cannot isolate a pure causal effect of context restoration. Report the 112 retained/32 replacement provenance and preserve superseded outcomes. No exactly-once CPU, field-failure, general program correctness, or ECRC-exclusive utility claim follows from this correction.

Commands from this directory using Python 3.12.14 and `-B`:

```
python -B context_catalog.py
python -B test_context.py
python -B test_context.py --integration
python -B run_correction.py --freeze
python -B run_correction.py --run
```

Preparation is already a one-shot write and refuses existing catalog/audit files. The integration flag runs only a declared synthetic toy, with retained files under `qa_integration`; it is not one of the 32 replacement cells. The final two commands are reserved for the archive maintainer after review; the implementing reviewer does not start the formal grid.
