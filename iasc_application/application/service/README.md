# Verification service for the bounded application pilot

Run from any directory, with absolute paths (the default runner is the sibling `workload/job_runner.py`):

```text
python -B verification_service.py --catalog /path/to/bound_catalog.json --db /path/to/sink.sqlite --runout /path/to/service_runs --port 0
```

The process binds only `127.0.0.1` and prints one flushed readiness JSON line containing `event`, `host`, `port`, `pid`, `db`, schema versions, catalog SHA-256 and runner bundle SHA-256. The client starts the process with a hidden-window option on Windows. The harness terminates it after the trajectory; service death during work is outside this pilot.

`frozen_service.py` is an unmodified copy of frozen S8/S6 `runtime/service.py`, SHA-256 `afc8d95c44ea6bb4f7eabdbb18ba234d3dbc0fbd325274a8694bd62e8c43d279`. The new service subclasses its ledger and HTTP handler. It keeps loopback transport, strict JSON framing, WAL, FULL synchronous mode, 30-second busy timeout and the original effect columns.

## Catalog binding

The catalog contains `jobs` (a list) or `jobs_by_decision` (a mapping), and `runner_manifest` mapping paths relative to the runner's directory to file SHA-256 values. Its runner module must be in the manifest. The runner bundle hash is SHA-256 of the sorted, compact, UTF-8 JSON manifest. Actual files are checked at startup. Embedded solution/test strings are checked against their declared hashes.

Each job's `job_hash` is SHA-256 of canonical JSON containing exactly `task_id`, `candidate_id`, `solution_sha256`, `test_sha256` and `runner_sha256`. The service requires:

- `decision_id = "verify:" + job_hash`;
- `route = "alert"`;
- `used_evidence_ids = ["job:" + job_hash]`;
- `permitted_claim_ids = ["run_verification"]`, or the sorted explicit catalog claim list.

The catalog supplies the complete job dictionary to `run_job(job_dict, out_dir)`. Other catalog metadata, including the official task entry point, belongs to this trusted frozen catalog; do not replace it during a run. No candidate is imported by the service. The workload runner is responsible for isolated execution and its trusted supervisor evidence.

## HTTP and durable completion

`POST /effects` accepts exactly `{idempotency_key, payload}`, with the existing four-field registered payload. The key remains the client's permit ID. HTTP 201 creates a result, 200 returns its cache, 409 rejects changed content under the same key, and 422 rejects a job binding before execution.

The service holds one sink `BEGIN IMMEDIATE` transaction across deduplication, synchronous job execution and insertion of both `effects` and `job_results`. New jobs are therefore serialized. It returns a success ACK only after both rows commit. This is a short-job conformance service, not a throughput implementation. CPU work cannot be rolled back if a service fails before commit, so one durable result is not an all-history exactly-once CPU guarantee.

ACKs retain `effect_id`, `idempotency_key`, `payload_hash`, `payload`, `committed_at`, and POST's `created`; they add `job_result`, `result_hash` and `job_hash`. `job_result` is the complete returned runner dictionary, including raw durations and actual-start evidence. `result_hash` is its canonical JSON SHA-256. GET `/effects/<URL-encoded-key>` returns the same durable fields without `created`. Matching replays return unchanged results and durations without invoking the runner again.

`pass`, `fail` and `timeout` are terminal application reports, distinct from transport success. Completed reports require one established suite start and matching solution/test hashes. Only a timeout may report unavailable CPU as `null`; this is never silently zero. An infrastructure error or rejected report produces no effect and is stored in `run_aborts` with its raw report/error evidence. Matching retries return that cached 503 abort without automatically executing again. The trajectory must treat it as a technical failure.

Header `X-Test-Drop-Response: 1` drops the connection only after a **new** result commits. A replay under the same header returns its cached ACK; it does not cause repeated artificial response loss.

## Audit artifacts and clocks

`job_results` has columns `effect_id`, `idempotency_key`, `job_hash`, `task_id`, `candidate_id`, `status`, `result_json`, `result_hash`, `cpu_seconds`, `wall_seconds`, `actual_starts`, and `run_dir`. Each new attempt gets a fresh short `a-<UUID>` directory, its bound job, raw result or abort, and a `work/` directory containing the runner's original files. Operation identity is recorded in database rows and events, never derived from this directory name. The independent auditor must check official-suite conclusions and raw supervisor/launch evidence; the service checks bindings and report structure, not general program correctness.

`service_events.jsonl` is written and flushed by the trusted host service. All records contain an ordinal, `perf_counter_ns`, observed UTC record time and service PID. Events include `runner_invoked`, `job_start`, `result_commit_return`, `response_drop`, `cache_hit`, and abort/error records. `result_commit_return` is sampled immediately after SQLite commit returns. `job_start` carries the runner's host launcher boundary, is emitted after the runner returns, and is explicitly marked as retrospective. It is not the exact in-namespace suite CPU start. The trusted supervisor's separate `suite_started` event establishes actual execution. Do not compare Linux namespace monotonic clocks to the Windows workflow clock.

## Development QA

```text
python -B dev_service_qa.py --out /path/to/new-development-output
```

This uses only `dev_toy_runner.py` and a fresh service subprocess. It checks actual toy computation, cache recovery after dropped ACK, concurrent retries, payload conflict, job-binding rejection, negative/timeout completion, infrastructure abort retention and timing events. It never runs evaluation candidates. Retained `dev_qa_01/QA_REPORT.json` passed all eight checks; it contains four completed toy results, one retained infrastructure abort and five toy runner invocations. `dev_qa_02/QA_REPORT.json` repeats these checks after the Windows path-length fix and also passed. `dev_qa_02/catalog_startup/CATALOG_STARTUP.json` confirms actual-catalog startup and health with zero jobs executed. Toy status controls are development fixtures, not HumanEval results. The original service source is preserved at `history/verification_service_v1.py`.
