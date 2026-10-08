# Public shared-budget experiment protocol

This is a post-outcome public summary of the source-frozen design. Exact
assignment projections and original-source digests accompany it. It documents
experimental methods and data interpretation, not manuscript material.

1. Start from the 164 public HumanEval tasks. Exclude 49 task IDs used in prior
   online comparisons. Rank the remaining 115 by SHA-256 of
   `ECRC-Shared-Agent-Scale-2026-10-07-v1|<task_id>`, take the first 96, and split
   the ranking into 24 disjoint four-task batches. Selection uses task IDs and
   prior membership, not model outcomes or reference solution complexity.
   `runtime/data/selection.json` retains all ranks, including the 19 unselected
   tasks, and `exclusions.json` retains all prior cohort memberships.
2. Cross batches with three arms (`prompt_only`, complete `ordinary`, `ecrc`),
   two feedback conditions (`normal`, `hidden_first_result`), and two repeats.
   The primary study has two OpenAI model profiles and 576 assignments.
   DeepSeek/Gemini add 576 separate assignments; Claude v2 adds 288. The
   replications reuse the same batches. Model identities and exact hash-shuffled
   episode order are in each schedule specification and CSV. The four-worker
   historical coordinator assigned prelisted rows to idle workers; timing did
   not choose tasks or comparisons. Preflights are excluded from formal counts.
3. Give every arm the same four tasks, tools and explicit cumulative allowance
   of three new verification jobs across the whole batch. The actor has at most
   16 model calls and 4,096 completion tokens per call, with one tool call per
   turn. It writes candidate code, registers it, chooses verification/revision/
   recovery, and finishes with up to one candidate per task. Tests and reference
   source are never included in actor inputs. The 96 tasks are public and are
   not claimed to be unseen or contamination-free.
4. Registration is free. A distinct candidate verification uses a unit even
   when it fails or times out. Completing a job does not refund a unit.
   Ordinary and ECRC enforce cumulative held-plus-spent obligations; prompt-only
   relies on the instruction. All arms share a separate service safety cap of
   eight. Stable operation identity, immutable source/test/runner binding,
   service caching and explicit recovery are common facilities.
5. In the hidden condition, withhold the first completed job's initial result.
   If its verification occurs at turn `t`, explicit recovery becomes available
   at `t+3`. Earlier recovery remains unknown. Repeating verification does not
   start the same job again, and merely reaching `t+3` does not recover it.
   The endpoint is finish or the turn limit, with no extra turns. This manipulates
   feedback visibility through a trusted local service; it is not a network or
   operating-system outage experiment.
6. At the endpoint, count distinct eligible tasks whose passing result was
   available to the actor (`V`). Actual excess is `I(starts > 3)` when starts
   are known; otherwise excess is indeterminate and unknowns are reported.
   Raw verified yield is `V/4`. Compliant verified yield is `V/4` only if starts
   are known and at most three, otherwise zero. That joint metric does not
   assert that all code in an over-quota trajectory is incorrect. Retain raw
   yield, starts, unknowns, failures and all arms alongside it.
7. Independently rerun selected candidates after the endpoint in new sandboxes
   with the **same** official suites. These executions provide no feedback to
   the actor and consume no study allowance, but their execution/resource costs
   are counted separately. Selection or post-endpoint acceptance alone does not
   establish workflow verified yield.
8. Analyze the 24 batches as clusters. Average the two repeats within each cell
   and batch, then jointly resample batches 10,000 times with seed 20261007.
   Report 95% percentile intervals for means and paired arm differences.
   Unknown counts retain their own denominator; paired comparisons use common
   valid batches. The 1,440 trajectories are not independent task samples.
   Zero-event bootstrap intervals describe the sample, not zero population risk.
9. Retain attempted failures and their observed state without retry/replacement.
   Unstarted assignments remain unobserved. The original coordinator stopped
   new dispatch for infrastructure/usage-audit failure, unknown starts, exhausted
   spending limits, interruption, or three consecutive provider transport
   failures; already-running jobs retained their outcomes. Preserve all provider
   results, including DeepSeek null effects and complete-ordinary ties or wins.
   Native transport settings and separate run periods limit cross-model ranking.

The source-derived analysis JSON files retain the precise metric definitions,
failure treatment, sampling unit and interpretation limits for each study.
The public runtime exposes the actor/controller mechanics; reproducing the
historical multiworker provider orchestration requires the separate integration
work described in the README.
