# Final independent internal review of the finite lifecycle evidence

**Reader-document overlay.** This current Git view removes publication-planning advice from the historical technical review. It is not one of the 15 pre-run frozen inputs. Technical results, evidence files and historical hash records are unchanged; the Markdown hash in `FINAL_MODEL_REVIEW.json` identifies the original release document, not this overlay.

**Technical verdict: PASS for the declared finite checks and saved-trace audit.** The completed checks provide useful specification evidence beyond the existing conditional counting argument and selected implementation traces. They do not establish a new transaction mechanism, ECRC-only advantage, a parameterized theorem, or correctness of either Python implementation for every history.

This review binds FREEZE SHA256 `f88faba8a248ab51fe18bce8454776e1e57a723ca70494e022a26f71b8437a8d`. It read the three complete TLC outputs, result records, configurations, commands, exact-enumerator results and saved witnesses. A separate small audit script checked record bindings and the already saved negative trace without importing either checker or exploring a state space. All 15 frozen input files and 205 baseline artifact files were unchanged at this review. Detailed machine-readable evidence is in `FINAL_MODEL_REVIEW_RECORDS.json`.

## Complete positive results and useful coverage

| Fixed instance | Distinct reachable states, both checkers | Generated states including Init, both checkers | Exact maximum shortest-path depth, edges | Result |
|---|---:|---:|---:|---|
| N=2, Capacity=1 | 684 | 2,673 | 15 | Complete; all nine invariants hold |
| N=3, Capacity=2 | 21,960 | 122,089 | 24 | Complete; all nine invariants hold |

Both TLC runs ended with return code zero, an explicit no-error completion message, and an empty queue. The exact enumerator checked and expanded every discovered state, also with an empty frontier. Each of the nine invariant coverage totals in TLC equals the corresponding distinct-state count. Exact results record zero violations of all nine predicates. TLC reports depth 16 and 25 using its initial-state-inclusive convention; these should not be mixed with the exact enumerator's 15 and 24 edges.

Every one of the 17 normal transition families was exercised in both positive instances, including full-budget denial, unarmed cancellation, request loss, ACK loss, repeated sink replies, repeated completion, and independent crash/recovery. The per-family generated-edge totals agree exactly between TLC and the independent enumerator. `UnsafeReleaseUnknown` correctly has zero normal coverage. TLC coverage entries such as `LoseRequest: 0:256` and `RepeatedCompletion: 0:32` must not be misread as unexecuted actions: the nonzero generated count agrees with the independent edge count even when that action discovered no new state.

The logs preserve a Java garbage-collector recommendation, not a semantic or incomplete-search warning. TLC's retained fingerprint estimates are 7.4e-14 for N=2 and 1.2e-10 optimistic / 4.3e-11 based on actual fingerprints for N=3. The separately implemented full-integer-state checker avoids lossy-fingerprint equality and agrees on both distinct and generated counts. That agreement reduces checker/translation error risk; it does not eliminate shared modeling errors or replace the scope limitations.

## The actual negative trace

Both tools saved the same 13 states / 12 transitions. An independent audit parsed the full TLC trace, compared all 16 state variables against the exact witness, checked each recorded guard and update, and confirmed local accounting and the local budget bound at every step. The sequence is:

1. Receive request 1; issue its action and hold one unit; arm it.
2. Expire its permit; send its existing grant; commit effect 1 at the sink.
3. **Release request 1's held unit while its result remains unreconciled.**
4. Receive request 2; issue its action using the now-free unit; arm and send it; commit effect 2.

At the endpoint, `effects={1,2}`, `held={2}`, `committed={}`, so X=2 while S=1, C=0 and Capacity=1. The first baseline-disallowed step is `UnsafeReleaseUnknown`, transition 7 (TLC state 8). It already breaks grant and effect backing; the negative configuration intentionally continues checking local accounting and the budget bound until the external effect-count violation appears.

**The first service effect precedes the unsafe release** in both saved traces. Neither trace contains `LoseAcknowledgement`: ACK 1 is present in the abstract channel but has not been reconciled. The first result is therefore unreconciled or not yet observed by client completion; this is neither an ACK-loss trace nor a release-before-first-effect trace. The saved order is distinct from the separately labeled illustrative release-before-effect sequence. The raw negative exploration is partial (TLC retains 168 queued states), as intended for an existence counterexample. Its partial counts are not exhaustive and need not match the exact checker's different early-stop frontier.

The counterexample shows why retaining responsibility for an unresolved grant matters even when the local ledger remains within its bound and the sink still deduplicates perfectly. It is a deliberately changed abstract rule, not an observed failure in either complete client. Twelve transitions are shortest for the frozen relation according to the completed exact BFS prefix; this establishes no global minimum across different abstractions.

## What the S8 correspondence supports

`SOURCE_MAPPING.md` locates the actual client issuance, arm, cleanup and reconciliation transactions and the independently committed sink. `CHECKPOINT_PREFIX_MAPPING.md` verifies early records from two archived S8 scenarios for both complete clients: an expired unarmed permit is released and cancellation remains terminal; an already committed but unreconciled external effect retains its unit after cleanup. These prefixes have one received request and actual capacity two, so they fit a projection into N=3/Capacity=2 without changing the quota.

The mapping is enough to motivate and sanity-check this scoped source abstraction. It is **not** a refinement proof: the full archived scenarios contain more requests than either model instance, the saved SQLite records do not reconstruct packet state or availability, and arbitrary sequential snapshots do not prove a simultaneous global observation. Of four distinct persistent projections, three appear directly in the saved representative positive witnesses. The joint expired+effect+unreconciled projection is not among that representative subset; the static model permits expiry from the recorded unexpired effect state, and the archived S8 prefix itself documents retention. No complete model-state set was exported, no matching of every S8 checkpoint to such a set was performed, and no full trace refinement was performed.

The first version of the read-only record-audit script incorrectly required that representative witness subset to contain every selected projection. It stopped on the missing joint projection before writing its report. The initial script is retained in `review_preparation/audit_completed_records_v1.py`; the corrected version reports presence/absence without interpreting the subset as the entire reachable graph. No model, checker source, run output, or frozen artifact was changed or rerun.

## Scope and limits

The evidence consists of an executable specification whose reachable interleavings and invariant relationships were exhaustively checked for two declared finite instances, plus a machine-generated counterexample to a single explicitly weakened retention rule. This makes the specification inspectable and one assumption boundary operationally precise.

The checks have these limits:

- The nine checks concern the specified finite lifecycle state machine. Two instances do not prove the predicates for symbolic N or arbitrary Capacity. No cutoff theorem was supplied.
- Fixed legal immutable payloads, stable operation identity, per-operation atomic sink deduplication, truthful ACKs and SQL atomicity are modeled mechanisms or assumptions. The checker did not discover or prove their real implementation correctness. In particular, representing effects by operation identity already embodies at most one durable effect per operation.
- The model omits evidence semantics, general parsing/claim fallback, alias detection, policy revision migration, received-but-unissued cleanup, arbitrary low-level ledger access, and CPU work before the effect commit. It cannot establish O1–O6 in full or exactly-once computation.
- Message-presence channels coalesce duplicates; expiry is a per-operation monotone abstraction; availability changes preserve durable state. These checks give no network-liveness, deadline, power-loss or arbitrary-message-multiplicity guarantee.
- Both complete clients are related to the same abstract contract. These results do not compare their speed, robustness or engineering cost, and do not introduce an ECRC-exclusive transactional guarantee.

The established scope is finite specification checks and a retention-boundary counterexample. It is not a formal proof of the whole runtime or a new distributed-systems mechanism.
