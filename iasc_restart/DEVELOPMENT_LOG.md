# Retained development history

The durable-count developer's initial synthetic QA had a Windows temporary-directory cleanup error caused by an unclosed test-only SQLite connection. The fixture was corrected; all 13 tests passed before the first source freeze. No effect runs were performed by those tests.

`review/prerun_01` and `runs/batch_01` retain the first full eight-cell matrix. Every client execution and final database/transport check completed, but the four mixed cells failed the independent process-restart audit: `subprocess.Popen.pid` identified the Windows virtual-environment launcher, while the worker's readiness record identified the actual Python child. The original kill event logged the launcher PID. It did not establish the required identity match.

A read-only follow-up checked all 28 actual readiness PIDs from the first run and found none still running. This after-the-fact observation is not substituted for a verified termination before recovery. The first audits remain failed for that evidence requirement; no outcome or audit was overwritten.

The runner is corrected to acquire a Windows process handle for the actual readiness PID while it is alive, terminate that exact process, wait for its exit and record its actual exit code alongside the launcher PID. The handle prevents PID-reuse ambiguity. Client implementations, original baseline, ECRC core, common service, request schedule, limit and independent auditor remain unchanged. No audit criterion was weakened.

The correction is frozen separately as `review/prerun_02`, and the full eight-cell matrix is rerun into `runs/batch_02`. Both batches must remain; only the second is used for the final verified restart comparison. This is a harness evidence correction, not an independent efficacy replication or a reason to drop unfavorable baseline results.
