# Development evidence, separate from primary experiment

The protocol was saved before implementation and execution. A pre-execution
amendment specified a real 0.2-second client timeout caused by a 1-second
post-commit ACK delay. No case count or state contract changed after outcomes.

The ordinary adapter's first small-check run reached its contract assertions
but Windows temporary-directory cleanup exposed an inherited context-managed
SQLite connection that was not immediately closed. The NEW ordinary adapter
now closes its own context-managed connections. The copied old source remains
unchanged. The original failure record is `ordinary_e2e_dev_failures.md`; the
subsequent 41-check outcome is `ordinary_e2e_dev_checks.json`.

`dev_smoke_01` contains one ECRC distinct-contender trial. `dev_matrix_01`
contains all six scenarios once for each arm (12 runs) under the first audit
version. The first auditor checked some authoritative tables only by count;
source review required stronger receipt, hold, raw-policy ceiling and routing
checks before formal execution. These audit limitations were corrected in
`audit_e2e.py`; no runtime changes were needed for them.

`dev_matrix_02` repeats the 12-scenario development matrix using the strengthened
auditor and exact per-checkpoint raw-request inventory metadata. All 12 trials
met the protocol outcomes; independent read-only inspection of 12 final and
42 checkpoint database pairs passed 12,070 checks. This is audit coverage, not
12,070 independent experimental samples. The source files did not change
during either development matrix run.

Independent source review by another agent tested 10 wrapper/cleanup cases
outside this directory in `../runtime_review`: exception rollback at three
issuance checkpoints, cleanup-first arm rejection, and armed-first retention.
Those QA cases used injected BaseException/controlled threads rather than the
formal experiment's actual process termination and HTTP operations.

The independent auditor's cloned-database corruption QA is retained under
`audit_corruption_qa/`. Original client/sink files and WAL hashes were compared
before and after. QA and development runs are not added to the 36-run primary
denominator. A later fresh full rerun is a reproduction check, not another
independent population of faults.
