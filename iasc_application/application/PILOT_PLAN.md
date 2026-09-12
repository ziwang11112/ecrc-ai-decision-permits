# Budgeted generated-program verification: feasibility and inclusion plan

Created 12 September 2026, before this experiment's candidate execution and
comparative outcomes. This is a separate, post hoc application study. The
current IASC manuscript and frozen S1–S8 code/results are preserved.

## Question and actual action

Can the current permit lifecycle govern a real finite-budget verification
workflow whose subsequent choices depend on returned test outcomes? An action
actually executes one archived model-generated program against the original
official HumanEval suite in an isolated process. A completed job can return
pass, fail or timeout. A pass is evidence of satisfying that finite suite under
the recorded environment, not proof of general program correctness or avoided
production losses. Infrastructure errors are distinct and cannot be counted as
candidate failures. Actual child CPU, host wall time, job starts, retries and
feedback availability are retained.

The declared control score and ambiguity in the verifier request merely select
the authorized verification route; they are not model confidence estimates.
The model-source identifier/hash binds the published proposal archive, not
unavailable model-weight bytes. The actual AI artifacts are the saved generated
programs, and neither model generation time nor token cost is reconstructed.

The source has 164 already-exposed HumanEval tasks and publicly released,
sanitized Llama-3.1-8B candidates. All have appeared in previous local exploratory
analyses; no fresh held-out-task or contamination-free claim is available.
Old pass/fail labels and generated CodeT tests will not select candidates or
define outcomes. Original official tests, source commit and licence are frozen
separately. Candidate source indices and hashes are retained; no model is called.
The candidate archive has no confirmed redistribution licence, so a future public
package should provide its authors' download URL, exact hashes and extraction
recipe rather than relabel or redistribute the raw archive as MIT.

## Fixed sampling and bounded scope

For each task, choose four source array indices by the smallest SHA-256 of
`iasc-app-20260912-v1|task_id|source_array_index`. Keep empty and duplicate source
records. Order all 164 task IDs by SHA-256 of
`iasc-app-task-order-v1|task_id`. The first 20 form an implementation-development
subset; the remaining 144 form 18 fixed eight-task evaluation batches. This
partition refers to this new workflow, not to previously unseen task content.
No evaluation candidate executes until protocol, input and code hashes are
locked following development and independent review.

The maximum verification opportunity is four candidates per task. The principal
count budget is K=16 jobs per eight-task batch, half its 32-job exhaustive quota.
This is a declared engineering resource constraint, not an estimated monetary,
CPU-time or deployment-cost limit. Each issued verification job costs one unit
irrespective of pass/fail/timeout. Units remain spent within the batch's fixed
policy/revision/scope key. There are no budget resets within a trajectory.

## Policies, implementations and feedback

Compare conventional depth-first and round-robin candidate verification. Both
stop a task once a passing result is received and reconciled, both retain the
same candidate order, and both can try at most four candidates per task. They
receive exactly the same type of feedback. Their choices follow their own
executed trajectories; they do not replay feedback from a different policy.

For each policy, compare the two complete, information-matched S8 clients
(ECRC and ordinary). Copy their source without editing it. Both use the same
test runner, catalog, isolated service, quota, retry rules and transport.
Policy differences are not attributed to an ECRC-exclusive capability.

Use normal acknowledgement and a controlled post-result-commit response-loss
condition. In the latter, every fourth newly completed service job loses its
first response; after a fixed shared recovery delay, a retry retrieves its
cached result without a new command. This is an injected transport condition,
not an estimate of field fault frequency. There is no service crash before job
completion in this bounded experiment. Actual computation precedes atomic
result/effect persistence. A service crash before this commit could repeat CPU;
that broader problem is outside this application experiment.

## Deadline and development rules

Development establishes that the original test suites run, checks trusted
reference programs, measures end-to-end job overhead and verifies sandbox,
catalog, permit, result and receipt binding. Execution limits and the exact
wall-clock deadline/recovery-delay rule are fixed in FINAL_PROTOCOL.json before
evaluation. They may use development timing information, never evaluation
success differences. Development failures and amendments are retained.

Timing rule fixed before serial development calibration: use all 80 selected
development candidates once with one worker and set
`D = max(5, ceil(1.5 * 16 * median(launcher_wall_seconds)))` seconds. The factor
1.5 is declared planning headroom; the five-second floor and one-second retry
backoff are engineering settings, not measured deployment SLAs. Include all
candidate statuses in timing calibration. The earlier four-worker development
and reference executions are QA only. Repeat all 80 serially to match the
application service; retain both versions. No test/evaluation outcomes select
the deadline, and no alternative deadline is chosen for a desired contrast.

No new selection or arm is deliberately initiated after the client observes
deadline D. Arm initiated before that check can finish and dispatch after D;
this is not a hard physical-start or execution-stop deadline. A previously
authorized job may complete after D and still consumes a unit, but does not
count as timely completion.
Pending feedback is recovered afterward in a separately reported cleanup phase.
The primary measure is the number of distinct tasks with at least one
official-suite-pass result reconciled by D, divided by all eight tasks. Also
report durable passes by D, eventual passes, job completions, denials, failures,
timeouts, unfinished feedback, retries, physical launches, CPU/wall time and
held/committed units. The primary denominator never drops failed or unselected
tasks. A batch, not a job, is the paired unit under the shared quota.

In particular, an unknown post-effect held unit and a reconciled committed unit
consume the same permanent cumulative budget. Delayed feedback can affect time,
result availability and subsequent decisions; it does not by itself remove an
additional reusable slot. No result may claim otherwise.

## Decision to add to the paper

Proceed only if real execution, independent official-suite acceptance, content
and unit bindings, complete resource logs and output-dependent next actions all
work and are independently auditable. Preserve every planned evaluation batch
and arm, including failures. Correct implementation defects require a new
source version and full rerun of all affected comparisons.

Neutral, tied or negative outcomes may qualify for inclusion. Inclusion does not
require ECRC or either policy to win. A technical toy consisting only of an
inserted response delay, a stored success flag, old cached labels or renamed
synthetic effects does not qualify. If the pilot remains technically fragile or
adds no defensible task-level evidence, keep the manuscript unchanged and retain
an explicit feasibility report. If it qualifies, add a clearly limited
application subsection and complete supplement, retaining the existing
limitations and all prior frozen experiments.
