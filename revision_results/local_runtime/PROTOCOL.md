# CMC round-one local authorization and issuance checks

Prepared before the new measurements on 2026-10-16. These are local implementation checks and a microbenchmark, not application outcomes or additional agent trajectories. No model API, candidate program, sandbox, or external service is invoked. The original public sources and historical results remain unchanged.

## Sources and execution

Load the unchanged, manifest-verified ECRC and complete conventional adapters through `online_agent/runtime/vendor/adapters.py` in a fresh Python 3.12 interpreter. Save hashes for every vendor file, the loader, this harness, and this protocol before each phase. A post-run comparison must show unchanged source hashes. Use Python `-B` to avoid writing bytecode outside this directory. Both implementations receive the same deterministic raw-request construction and policy obligations. All test artifacts are confined to this directory. Preserve any failed run in place; never overwrite or replace it with a successful run.

Before the formal run, run smoke checks in a separately labelled directory. Check canonical fixtures, permitted route/claim, hold accounting, cached identity, the expiry boundary instrumentation, and SQL-derived state assertions. Smoke records do not enter formal summaries.

## Real lock-spanning expiry check

For each implementation, run three independent cases with new client databases. Create a fresh policy whose expiry is two seconds in the future, ingest and issue through the original adapter, and confirm that the issued permit expires at that policy boundary. Another real SQLite connection starts `BEGIN IMMEDIATE`. A worker invokes original `arm` with a fresh UTC timestamp before expiry; an observing connection proxy records the worker's actual `BEGIN IMMEDIATE` attempt and return without changing SQL or parameters. Wait until the actual UTC clock has passed expiry by at least 50 ms before releasing the blocking transaction. Assert that the worker could not acquire the writer lock or finish while it was held, and that acquisition, intent insertion, commit completion, and return follow expiry. Assert a single durable intent, one held unit, no spent unit and no receipt. The stored authorization timestamp must equal the original supplied timestamp.

Expected result under the **existing** semantics: the waiting invocation is accepted after wall-clock expiry because validity is evaluated against its supplied pre-expiry timestamp. This is characterization, not a correction, and it gives no effect-time or commit-time expiry guarantee. Record UTC and monotonic timestamps; compare UTC with expiry and monotonic values for durations. Detect an observed clock regression or incorrect boundary ordering as a failure. The proxy is used only in boundary checks, never timing measurements.

For each implementation additionally check, once, with fresh databases: (1) a supplied timestamp exactly equal to expiry is rejected; (2) revocation through the original API before arm rejects a fresh grant; (3) original cleanup at expiry before arm cancels and releases, so even a pre-expiry supplied timestamp cannot arm it; (4) an existing arm survives later cleanup and revocation, and repeated arm returns the same key and timestamp. These four tests use explicit policy-clock inputs and are not represented as wall-clock waits. No service effect is created or claimed. No post-arm unit is released by this harness.

## Issuance microbenchmark

Two implementations, five independent runs each. Alternate order by run. Each run has a separate fresh database for each of three sequential, single-thread phases:

1. `issue_new`: 200 unique action requests are journaled before timing; time only `issue(decision_id, at)`.
2. `ingest_issue_new`: time original `ingest(raw, at)` followed by original `issue(decision_id, at)` for each of 200 unique requests.
3. `issue_cached`: prepare 200 issued requests before timing; time one repeated `issue` for each, asserting that it returns exactly its originally registered permit.

Each phase first completes ten untimed successful `ingest+issue` warm-up requests in a distinct scope; the cache phase also performs ten untimed cached calls. Requests use one eligible signal record, score 0.8, uncertainty 0.2, and a required `notify` claim on `alert`; they are fixed synthetic metadata fixtures. Benchmark policy time is fixed independently of the monotonic timer. Each measured scope has a nonbinding capacity of 210; its 200 holds remain held. The warm-up scope has a separate 210-unit counter. No arm/delivery/reconciliation is timed or invoked. Preconstruct requests, import and hash-check dependencies, register policy, initialize databases and write fixtures outside the timed region. Original parsing, validation, hashing, SQL, and commit inside the measured methods remain included. Record `perf_counter_ns` request durations in milliseconds without subtracting harness/clock overhead.

Save all 200 request observations per phase, input fixtures and endpoint SQL-derived audits. Compute within-run request p50 and p95 by linear interpolation at `(n-1)*q`. Report each phase/implementation's median and minimum/maximum across its five run-level p50 values, and separately the same aggregation across its five run-level p95 values. These are descriptive repeated-run ranges, not confidence intervals. Do not pool all requests as independent system replications, label p95 as p99, combine cache hits with new issuance, or claim production/general performance.

Record Python and SQLite versions, OS/CPU description, timer metadata, relevant SQLite pragmas, exact commands, wall duration, source hashes, raw rows, state checks and failures. After timing/auditing, checkpoint each database and report total database size as an ancillary observation, not marginal per-operation storage or a long-run growth estimate. SQLite `synchronous=FULL` and journal mode are read back from the original connections. Host-specific file and fsync costs remain part of these local measurements. Run-level independence means fresh databases and fixtures, not independent hosts or OS-cache states.

## Acceptance and failure handling

Independently query SQLite tables to reconstruct held/spent counts, reservation status/binding, issued-permit and raw-request counts, and durable intent/receipt counts. Require totals to agree with each other and with the adapter snapshot. Each new measured request must have the supported action route and claim, one unique permit, and one held unit. Cached calls must add no records or units. Save a failure JSON and terminate that phase if an unexpected exception or invariant failure occurs; preserve completed measurements and do not silently retry a formal case. Formal summaries must disclose all planned/completed/failed counts.
