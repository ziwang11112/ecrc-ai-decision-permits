# Revision code and numerical evidence

Source revision dated 22 October 2026. The fixed software release remains
`code-v1.3.0`. This folder adds the subsequent budget study,
primary-study resource reanalysis and local authorization/issuance evidence.
It contains no manuscript text, paper PDFs, reviewer correspondence or LaTeX.

## Contents

| Material | Location | Coverage |
|---|---|---|
| Additional budget and joint-condition study | `budget_study/` | All 504 assigned trajectories, 21 strata and 51 paired contrasts across seven metrics |
| Formal actor loop and controller integration | `agent_runtime/` | Budget parameterization, controlled evidence-type challenge, delayed-result recovery, prompts and offline tests |
| Primary-study resources and failure analysis | `primary/` | All 576 trajectories, 12 groups, 17 non-finished trajectories and 24 paired contrasts |
| Local authorization and issuance | `local_runtime/` | 14 boundary traces and all 6,000 timed calls in 30 phase/run combinations |
| Reader-facing numerical summaries | `review_tables/` | Primary/additional paired compliant yield, missing acceptance bounds and termination counts |

The primary and additional studies reuse 96 HumanEval tasks in 24 four-task
batches. Their trajectory counts are not counts of independent tasks. Each
study retains its own protocol, assignments, resampling seed and denominator.

## Numerical verification

From the repository root with Python 3.12 and NumPy 2.4.5:

```console
python -B revision_results/verify.py
```

This verifies the file manifest, recomputes the 504-record study using its
unchanged frozen analysis, reproduces primary group/paired/sensitivity results,
checks local timing summaries against individual observations, and regenerates
the compact CSV tables. It calls no model and executes no candidate program.
The public table helper produces CSV and a numerical verification report only;
manuscript captions, notes and document-generation functions are excluded.

The additional study alone uses the standard library:

```console
python -B revision_results/budget_study/reproduce.py
```

`budget_study/` is a byte-identical copy of the completed numerical bundle,
including its original README and historical names. Its continuation record
preserves the 246 previously started assignments; only the 258 never-started
assignments continued after the documented provider interruption. All failures
and incomplete outcomes remain in the planned denominators.

## Mechanism terminology

The joint condition changes the first requested operation's evidence type
from `verification_job` to `context`. That context record passes the configured
metadata qualification checks but cannot support `run_verification`, whose
claim rule requires `verification_job`. The denial therefore exercises
**claim-support fallback during final permission construction**.

Frozen code and data retain `missing_required_metadata_hidden_first_result`,
`qualification_denials`, `qualification_denied`,
`new_valid_after_qualification_denial` and `invalid_metadata_starts`. In this
condition these mean, respectively, the joint evidence-type challenge,
claim-support denials, occurrence of that denial, a subsequent request with
the required evidence type, and starts without that required type. The
presentation tables use the precise terms; the original keys and numerical
values are unchanged. This correction does not alter general evidence
qualification elsewhere in ECRC.

`driver_status` records driver completion. Use `outcome_status` for the task
trajectory endpoint. Of 504 assignments, 465 finished and 39 did not: 24
truncated responses, eight provider failures, five turn limits and two
interruptions. Work completed before those endpoints remains counted. Missing
acceptance values retain bounds and intervals for bound endpoints, rather
than becoming ordinary point estimates.

## Runtime source and checks

The eight formal runtime modules are copied unchanged. Their shared vendor,
task and workload dependencies use the existing public source view. The
public sandbox launcher requires explicit dependency paths, so its runner
identity differs from the author-local historical launcher. Source hashes
and every extraction/adaptation are recorded in `PROVENANCE.json`.

```console
python -B revision_results/agent_runtime/tests/test_runtime_offline.py --tag audit1
```

Choose a fresh short tag each time. The 13 test methods use inert candidate
strings, injected runner results and a scripted model interface. Network and
process-launch tripwires prohibit real model or sandbox calls. Results go
under the ignored `agent_runtime/runtime/tests/<tag>/` directory.

Fresh online execution requires the model transport, usage accounting and
orchestration supplied by the caller, plus the isolated environment described
in [the implementation guide](../online_agent/README.md). The safe protocol
in `budget_study/SAFE_PROTOCOL.json` retains the full assignment schedule and
evaluation settings. Model traffic, candidate bodies, execution databases,
private billing ledgers and credentials are not part of this projection.

## Local runtime measurements

`local_runtime/run_local.py` contains the original measurement procedure with
repository-relative vendor loading. Its `--help` describes fresh-output
execution. The saved checks include six real lock-spanning expiry cases and
eight additional authorization-order cases. They characterize the existing
supplied-invocation-time semantics; an already committed arm remains valid
for recovery after later expiry or revocation.

The timing phases are new issuance, ingestion plus new issuance, and cached
issuance. Each controller has five runs per phase with 200 timed calls per
run. Reported p50/p95 values are medians of five run-level percentiles. These
measurements exclude inference and service delivery. The compact public
verifier recomputes timings and checks saved trace consistency; the original
read-only SQL audit used author-held database snapshots.

All outputs here derive from retained records. Preparing this update added
no scientific trajectories or paid API calls. Existing release tags, original
runtime modules, historical field names and previous results remain intact.
