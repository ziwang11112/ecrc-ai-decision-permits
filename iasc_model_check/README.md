# S10 — Finite lifecycle specification checks

This post hoc study checks the paper's existing lifecycle abstraction for two fixed finite instances and a deliberately changed retention rule. Both normal instances completed in TLC and a separately implemented exact breadth-first enumerator: **684 reachable states for N=2 / Capacity=1 and 21,960 for N=3 / Capacity=2**, with all nine specified safety invariants satisfied. All 17 normal action families have nonzero coverage in both instances, with matching per-action edge counts. The changed-release variant produces an independently replayed 12-transition counterexample.

The inclusion decision is **scoped methods evidence**: an inspectable finite specification and an explicit retention-boundary counterexample. This is not a new distributed-systems algorithm, an ECRC-exclusive capability, a proof of either complete client, or a theorem for unbounded instances. See `INCLUSION_DECISION.json`, the Chinese interpretation in `RESULTS_ZH.md`, and both final independent internal reviews.

## Fixed design and trust boundary

`PROTOCOL.md` fixes the question and cases before reachable-state exploration. `ECRCLifecycle.tla` separates 16 state variables into durable client records, request/acknowledgement presence, durable sink effects and independent client/sink availability. Requests have fixed legal immutable contents under one policy/revision/scope/action-route key. An operation identity represents its immutable request/permit/payload binding and its one-unit reservation.

The model includes raw receipt; atomic action issuance and reservation; terminal denial when capacity is full; durable arm; monotone permit expiry; atomic cancellation/release before arm; same-key dispatch/retry; request and acknowledgement loss; atomic service effect/deduplication; local receipt reconciliation; repeated completion; and independent crash/recovery. An existing arm survives expiry. Committed expenditure is never replenished under the fixed key.

The sink's transitions read only sink availability, received operation identity and sink effect membership. They do not consult client holds, counters, receipts or availability. Client reconciliation uses its own held intent and a matching acknowledgement, not a direct remote-state query. Invariants are observations of reachable states, not filters on `Next`; neither normal configuration uses a state/depth cutoff, state constraint, symmetry reduction or partial-order reduction.

Atomic transactions, stable identity, immutable legitimate content, truthful acknowledgements and persistent per-operation sink deduplication are modeled mechanisms or assumptions. In particular, storing effects as a set of operation identities already represents at most one durable effect per operation. The checks examine lifecycle composition under that representation; they do not independently establish these mechanisms in Python, SQLite or an arbitrary service.

## Results and counting conventions

The authoritative records are `runs/v1/tlc/<case>/RESULT.json`, their complete stdout/stderr, `runs/v1/exact/<case>/RESULT.json`, and `runs/v1/exact/TLC_COMPARISON.json`. `runs/v1/RESULT_SUMMARY.json` is a derived index, not a replacement for those records.

| Fixed normal configuration | Reachable states, both tools | Generated states including Init, both tools | Enabled action-instance edges | Maximum shortest-path depth, edges | Outcome |
|---|---:|---:|---:|---:|---|
| N=2, Capacity=1 | 684 | 2,673 | 2,672 | 15 | Complete; all 9 invariants hold |
| N=3, Capacity=2 | 21,960 | 122,089 | 122,088 | 24 | Complete; all 9 invariants hold |

Both TLC runs returned zero, reported no error and an empty queue. Exact BFS checked and expanded every discovered state and ended with an empty frontier. Each generated action instance counts an edge even when its successor was already known; generated states include the one initial state. Implicit specification stuttering adds no reachable state and is not separately enumerated as an action edge. TLC reports initial-state-inclusive depths 16 and 25; the exact enumerator reports 15 and 24 edges. States, edges, invariant checks and action coverage are diagnostics, not independent samples or additional S8 runs.

### Nine normal invariants

Let S and C be `heldCount` and `committedCount`, and X the cardinality of `effects`.

| Invariant | Checked state property |
|---|---|
| `TypeOK` | Sets contain declared operation identities; counts and availability flags have their declared domains. |
| `Accounting` | S and C equal their set cardinalities; held and committed sets are disjoint. |
| `BudgetBound` | S+C does not exceed Capacity. |
| `Lifecycle` | Issued/denied outcomes follow receipt and are disjoint; held, committed, armed and expired identities are issued; cancellation is expired issuance disjoint from arm/held/committed. |
| `GrantBacking` | Every armed identity remains held or committed. |
| `EffectBacking` | Every durable effect remains held or committed. |
| `EffectCountBound` | X does not exceed Capacity. |
| `ReceiptSoundness` | Receipts belong to effects that are armed and committed. |
| `NetworkCausality` | Requests, acknowledgements and effects belong to armed identities; acknowledgements belong to durable effects. |

TLC's invariant coverage equals the corresponding reachable-state count. Exact BFS records zero violations of all nine predicates: 6,156 and 197,640 state/predicate checks, respectively. This inventory does not establish full coverage of the manuscript's O1–O6 obligations; semantic evidence qualification and general routing/claim closure are outside the model.

### All 17 normal actions covered

The following are generated action-instance edges; all values agree between TLC and exact BFS. `UnsafeReleaseUnknown` has zero edges in both normal configurations.

| Action | N=2 / K=1 | N=3 / K=2 |
|---|---:|---:|
| ReceiveRaw | 92 | 3,174 |
| IssueAction | 12 | 774 |
| IssueNoAction | 80 | 2,400 |
| Arm | 16 | 1,026 |
| ExpirePermit | 320 | 20,520 |
| CancelUnarmed | 16 | 1,026 |
| Send | 96 | 6,156 |
| LoseRequest | 256 | 16,416 |
| CommitEffect | 32 | 2,052 |
| DeduplicatedReply | 96 | 6,156 |
| LoseAcknowledgement | 192 | 12,312 |
| Reconcile | 64 | 4,104 |
| RepeatedCompletion | 32 | 2,052 |
| CrashClient | 342 | 10,980 |
| RecoverClient | 342 | 10,980 |
| CrashSink | 342 | 10,980 |
| RecoverSink | 342 | 10,980 |

An action can generate already known states without discovering a new state. A zero first component in a TLC coverage entry therefore does not imply an unexecuted action. The saved `WITNESSES.json` files contain representative shortest witness paths and critical endpoints, not an export of the entire reachable-state set.

## Changed-release negative control

`unsafe_2_1.cfg` enables only the additional `UnsafeReleaseUnknown` transition, allowing release of an expired armed unreconciled hold. It does not change the sink or the quota admission guard. TLC checks `TypeOK`, `Accounting`, `BudgetBound` and `EffectCountBound`, allowing exploration to continue past the deliberately broken backing predicates until the target effect-count violation. Exact BFS additionally records all nine predicates diagnostically and stops on the same target.

Both tools saved the same 13 states / 12 transitions. `runs/v1/TLC_COUNTEREXAMPLE_REPLAY.json` parses the actual TLC trace and matches each guard/successor to the independently implemented transition relation. A separate record-only audit also checked all 16 variables and the saved edges without importing either checker or exploring a state space. The actual chronology is:

| Transition | Action | Operation | S | C | X | Pending ACKs after transition |
|---:|---|---:|---:|---:|---:|---|
| 1 | ReceiveRaw | 1 | 0 | 0 | 0 | none |
| 2 | IssueAction | 1 | 1 | 0 | 0 | none |
| 3 | Arm | 1 | 1 | 0 | 0 | none |
| 4 | ExpirePermit | 1 | 1 | 0 | 0 | none |
| 5 | Send | 1 | 1 | 0 | 0 | none |
| 6 | CommitEffect | 1 | 1 | 0 | 1 | 1 |
| 7 | UnsafeReleaseUnknown | 1 | 0 | 0 | 1 | 1 |
| 8 | ReceiveRaw | 2 | 0 | 0 | 1 | 1 |
| 9 | IssueAction | 2 | 1 | 0 | 1 | 1 |
| 10 | Arm | 2 | 1 | 0 | 1 | 1 |
| 11 | Send | 2 | 1 | 0 | 1 | 1 |
| 12 | CommitEffect | 2 | 1 | 0 | 2 | 1, 2 |

The first effect is committed **before** unsafe release, and ACK 1 remains pending. No `LoseAcknowledgement` event occurs in this trace. Its correct description is an unreconciled result, not an explicitly lost ACK. The normal relation first rejects transition 7 (TLC state 8); grant/effect backing is already broken there. At transition 12, two effects exist with one held unit, zero committed units and capacity one. Local accounting and the local quota bound hold at every saved step. This is a changed abstract specification, not an observed failure of either complete client or an exact replay of the paper's separately labeled illustration.

The negative searches intentionally stop early:

| Tool | Distinct discovered | Checked / expanded | Generated including Init | Unfinished frontier |
|---|---:|---|---:|---|
| TLC | 934 | not equated to exact checked/expanded fields | 3,155 | 168 queued |
| Exact BFS | 1,114 | 934 / 933 | 3,897 | 181 not expanded: the checked target plus 180 unchecked queued states |

TLC detects a violating successor during generation; exact BFS checks states on queue removal. These partial counts need not agree and are not complete negative state-space sizes. The trace has 12 transitions. Exact BFS supports shortestness for this frozen transition relation; no globally minimal counterexample across other abstractions is claimed.

## Source and S8 prefix correspondence

`SOURCE_MAPPING.md` maps both complete S8 clients' issuance, arm, cancellation and reconciliation transactions and their independent sink to the abstraction. Its source paths and hashes identify the earlier immutable `end_to_end/` archive, not a replacement implementation or the S9 program runner.

`CHECKPOINT_PREFIX_MAPPING.md` reads five selected checkpoints per implementation from two archived scenarios: `expired_unarmed_cleanup` and `accepted_timeout_cleanup_recovery`. These are 10 client/sink checkpoint pairs, or 20 SQLite files, opened read-only and unchanged. Each selected prefix has one received request and actual alert capacity two; its projection fits N=3 / Capacity=2 with the other identities unreceived. The full S8 scenarios have more identities than either finite model instance and are not represented as whole histories.

The four distinct persistent/time-eligibility projections are issued-unarmed, cancelled-unarmed, effect-unreconciled, and expired-effect-unreconciled. The first three occur in the saved representative model witnesses. The joint expired/effect/unreconciled projection is absent from that representative subset; the static transition relation permits expiry from the saved unexpired effect state, and the S8 prefix documents retained backing. No complete state-set export or all-checkpoint membership comparison was performed. Saved records do not reconstruct packet multiplicity, pending acknowledgements or global availability. Sequential client/sink reads are not automatically a consistent simultaneous global cut. These are limited correspondence checks, not an implementation refinement proof.

The local paths in `SOURCE_MAPPING.md`, `CHECKPOINT_PREFIX_MAPPING.md` and `ARTIFACT_BASELINE.json` are historical author-workspace references. The prior S8 source/snapshots are available through the separately fixed [S1–S8 reproducibility release](https://github.com/ziwang11112/ecrc-ai-decision-permits/releases/tag/iasc-restructured-2026-09-12); their exact source/snapshot hashes are in the mappings. A standalone S10 archive does not by itself contain or recheck all files named by those historical references.

## Toolchain, timing and retained warnings

The recorded run used Windows x64, Eclipse Temurin JRE 21.0.12.1+1-LTS and TLC 2.19 of 08 August 2024, from the official TLA+ release v1.7.4. Exact BFS used Python 3.12.14. `tools/TOOLCHAIN.json` retains original URLs, metadata, versions and hashes. No system installation, registry change or PATH mutation was needed.

- [Official TLC v1.7.4 jar](https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar), SHA-256 `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`. This is the locally recorded hash of the official HTTPS asset; no independent publisher checksum/signature is claimed for that jar. The retained TLA+ license is `tools/TLAPLUS_LICENSE`.
- [Official Temurin Windows x64 JRE archive](https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.12.1%2B1/OpenJDK21U-jre_x64_windows_hotspot_21.0.12.1_1.zip), SHA-256 `d35f31e712f0fcf6ac5a093edc90204fbff22f720ba3950bd09d331d5e621636`. The checksum from the same official release and its asset digest matched. No independent signature verification is claimed; retain the distribution's license/notice files when redistributing its runtime.

| Case | TLC host wrapper wall seconds | Exact search-loop seconds |
|---|---:|---:|
| normal_2_1 | 1.089902 | 0.006284 |
| normal_3_2 | 1.559512 | 0.186561 |
| unsafe_2_1 | 0.964690 | 0.006385 |

The TLC timing includes process launch and exit wait; the exact timing is measured inside its case checker. These single-run quantities have different measurement scopes and are not a performance comparison. Both normal cases had 600-second limits and the negative case 120 seconds. TLC used one worker, fingerprint index 0 and a configured 2 GiB Java heap; logs also report 64 MiB off-heap. **Peak memory was not measured.** Heap settings are not observed peak consumption.

All three TLC logs retain the recommendation to use `-XX:+UseParallelGC`; the historical run did not add that option. This is a garbage-collector performance recommendation, not a semantic failure or incomplete-search report. TLC's retained fingerprint estimates are 7.4e-14 for N=2 and 1.2e-10 optimistic / 4.3e-11 based on actual fingerprints for N=3. The separate full-integer-state enumerator resolves hash collisions by exact equality and agrees on both normal state/edge counts. Agreement reduces checker/translation error risk but cannot eliminate shared modeling errors.

## Freeze, history and review provenance

`FREEZE.json` was written at **2026-09-12 18:19:31.550020 UTC**, before the TLC start at 18:19:31.610921 UTC and exact start at 18:19:42.224267 UTC. Its SHA-256 is `f88faba8a248ab51fe18bce8454776e1e57a723ca70494e022a26f71b8437a8d`. It binds 15 protocol/model/configuration/checker/mapping/toolchain files, including model SHA-256 `f6080e07197008430a37b3248bfd29eaf7fc3f97088d36e693bc17b2bef32e2a`. The three declared cases were run once per checker in `runs/v1`; neither normal case was shrunk, truncated or selected after seeing outcomes.

The preserved preparation record `preparation/SANY_01.json` reports parsing and semantic processing at 18:11:30.560875 UTC, with no reachable-state exploration. `MODEL_REVIEW.json` is a pre-exploration static review, not a model-checking result. `tools/TOOLCHAIN.json` likewise records preparation-time `model_execution_performed: false`; that historical field does not describe the later `runs/v1` study. Tool preparation retained an initial metadata-query 404 and the discovery that this TLC release's normal help exits with code 1, as explained in the toolchain notes.

The completed independent internal reviews are `FINAL_ENUMERATION_REVIEW.json` (PASS) and `FINAL_MODEL_REVIEW.json` / `FINAL_MODEL_REVIEW.md` (PASS_FOR_SCOPED_S10). They checked the frozen source identities, completion, counts, invariant/action coverage, negative chronology and mapping limits. `FINAL_MODEL_REVIEW_RECORDS.json` preserves a separate read-only record audit. At those reviews, all 15 frozen files and all 205 files in the protected manuscript/runtime baseline were unchanged. This is a historical preservation check before manuscript integration, not an assertion that subsequent manuscript text must remain unchanged.

One post-run audit preparation error is retained in `review_preparation/audit_completed_records_v1.py`: it incorrectly required a representative witness subset to contain every selected S8 projection and stopped before writing a report. `audit_completed_records.py` instead records the missing representative projection explicitly. No frozen model/checker, formal output or state-space run was changed or rerun to address that report-only issue. `summarize_results.py` and this README are post-run derived reporting artifacts. The earlier conditional editorial proposal, `PROPOSED_ADDITION.md`, is a local-only historical draft excluded from the public S10 archive, not a final result record.

## Reproduction

Use a new output/run identifier; preserve `runs/v1`. The historical per-case exact commands, working directories and outputs are retained in `runs/v1/tlc/<case>/COMMAND.json` and the two `START.json` files. The author-workspace workflow was:

```text
python run_models.py --run-id v1
python exact_check.py --run-id v1
```

These are references to the completed run, not commands to overwrite it. The original `run_models.py` default preservation guard intentionally checks the author-workspace files named by `ARTIFACT_BASELINE.json`. Its public-only option skips that external baseline check, but still requires the recorded portable Windows Java executable and every frozen source file. Do not edit the historical guard, remove baseline entries or rewrite `FREEZE.json` to make an extracted archive run.

### Standalone wrapper

`PORTABLE_REPRODUCTION.md` documents the post-run `portable_reproduce.py` wrapper. Its default invocation validates retained public source/results without exploration; execution requires an explicit new output directory outside the archive and Java/jar paths. It reports the 205 external baseline targets as `NOT_CHECKED`. The wrapper is outside the original 15-file freeze and must not be described as the historical run harness. It preserves the historical TLC options: no `-deadlock`, depth/state constraint, GC override or warning suppression is added. Reusing the frozen exact engine is reproduction, not a third independent enumerator. See its documentation for the exact verification/execution CLI and explicit Java-executable pinning on another platform.

### Direct portable Java/TLC commands

The following commands depend only on Java 21, the pinned jar and the unchanged model/configuration files. Run from a copied S10 study root, using a fresh `reproduction_tlc` directory. `java` may be replaced with a quoted absolute executable path; on PowerShell use `& 'C:/path/to/java.exe'` to invoke a quoted executable. For Windows, the recorded portable executable is `tools/java/jdk-21.0.12.1+1-jre/bin/java.exe`. Other platform Java builds will have different byte hashes and must be identified as such.

```text
java -version
java -cp tools/tla2tools.jar tla2sany.SANY ECRCLifecycle.tla

java -Xmx2g -cp tools/tla2tools.jar tlc2.TLC -workers 1 -fp 0 -coverage 1 -metadir reproduction_tlc/normal_2_1 -config normal_2_1.cfg ECRCLifecycle.tla
java -Xmx2g -cp tools/tla2tools.jar tlc2.TLC -workers 1 -fp 0 -coverage 1 -metadir reproduction_tlc/normal_3_2 -config normal_3_2.cfg ECRCLifecycle.tla
java -Xmx2g -cp tools/tla2tools.jar tlc2.TLC -workers 1 -fp 0 -coverage 1 -metadir reproduction_tlc/unsafe_2_1 -config unsafe_2_1.cfg ECRCLifecycle.tla
```

Create the fresh metadata directories before invoking TLC and capture stdout/stderr separately. The direct commands preserve the historical TLC arguments apart from output paths. They do not impose the host time limits themselves; use the standalone wrapper for the recorded 600/600/120-second supervision. Expect normal exit code 0 and the negative invariant-violation exit code 12, not three zero exits. Any incomplete or different outcome must be retained and investigated, not labeled a successful reproduction. Runtime, log timestamps and platform paths need not reproduce byte-for-byte.

## Limits on inclusion and interpretation

Two finite configurations do not prove arbitrary N/Capacity; no cutoff or parameterized theorem is supplied. The model does not verify canonical parsing, evidence truth/qualification, full routing and claim fallback, alias detection, policy revision migration/revocation, received-but-unissued cleanup, arbitrary low-level ledger calls, malicious trusted state or bypass effects. It does not implement post-arm cancellation, compensation or capacity reuse after committed expenditure.

Message-presence sets coalesce identical packets; they are not an unbounded FIFO/multiset model. Expiry is an independent per-operation monotone eligibility flag, not wall time or a cross-permit clock-order proof. Crash/recovery changes availability while preserving durable state and messages; database atomicity, power-loss safety and storage corruption are not established. There is no liveness, deadline, field reliability or multi-node implementation claim.

The model excludes actual CPU work and S9's computation-before-result-persistence interval, so it establishes neither exactly-once computation nor a CPU/money bound. Both complete clients map to the same abstract contract; this evidence supplies no speed, robustness or correctness advantage of the ECRC record format. The paper's conditional accounting argument and the finite model checks have different scopes; neither should be substituted for a proof of the whole implementation.
