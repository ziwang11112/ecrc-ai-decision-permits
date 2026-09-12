# Independent review of the new ECRC HTTP adapter

Reviewed 2026-09-11. Scope: `ecrc_adapter.py`, `fixture.py`, `PROTOCOL.md`, relevant unchanged snapshot ledger/schema code, and real-service implementation checks. No adapter or manuscript was edited by this reviewer. The supplementary checks are separate from the main protocol's fault-scenario denominator.

## Findings communicated before final testing

1. **Actual sink identifier mismatch, fixed by the adapter author.** The service's durable `effect_id` is a positive SQLite integer. The initial adapter required a string, which rejected real responses. The corrected adapter retains the integer as `service_effect_id`, while using its textual representation for the old receipt's string `side_effect_id`. Independent normal, response-loss and concurrent-reconciliation checks now reach successful completion and match physical sink rows.

2. **Canonical permit/payload mismatch, reproduced and fixed by the adapter author.** `DecisionPermit.from_dict` normalizes leading/trailing whitespace in decision, claim and evidence identifiers before its trusted-registry hash comparison. The initial adapter then projected the payload from the original input dictionary. Thus a normalized-equivalent submitted permit could pass validation yet persist a different raw payload. The final adapter strictly rejects noncanonical input and projects exclusively from the validated typed permit. The ordinary arm also uses strict digest equality. The supplementary test confirms safe rejection before any intent or service effect.

3. **Connection lifecycle, fixed by the adapter author.** Initial constructor/revoke code used `with connection` without explicit `close`. Python's SQLite connection context controls transactions; it does not close the connection. This is a local-handle cleanup issue, distinct from the deliberately held budget during an unknown remote outcome. The final implementation uses explicit `contextlib.closing` for these connections.

4. **Expiry test must isolate permit expiry.** A 2031 clock makes the policy expire before the permit-time guard is reached. The independent test uses exact permit expiry while policy validity remains in force, and separately checks before issuance and policy expiry. These are labelled implementation checks, not additions to the main nine fault scenarios.

## Boundaries and accounting

The reviewed adapter does not call `PEPSimulator`, `complete_execution`, or the original execution-time receipt verifier. It uses version-bound private ledger helpers inside its own transactions; the source snapshot must therefore remain in the reproducible artifact. The reservation commitment, original receipt append, execution record and outbox completion share one `BEGIN IMMEDIATE` transaction. The private reservation-commit helper does not apply a fresh policy grant, which matches the new protocol's authorization-at-durable-arm contract. Expiry/revocation can prevent a new intent but cannot cancel an existing armed intent.

The original reservation reaper excludes trusted issued permits. A negative service lookup, response loss, or an elapsed reservation lease does not release the armed reservation. The tests independently read the physical client and service databases to check this state and its eventual resolution. These observations support the specified recovery contract, not an unconditional liveness guarantee during permanent service loss.

The sink's `committed_at` is the real wall-clock record time sampled before INSERT and durably stored with the effect; successful responses occur only after commit. It is not a measurement of the exact instant SQLite commit finishes. The receipt retains that observed service timestamp separately from the actual local reconciliation timestamp and the injected policy clock. This clarification was added to `PROTOCOL_SERVICE.md` without changing service code.

The old receipt chain hashes original `ExecutionReceipt` fields, including its textual service effect ID and service record time. Additional delivery-envelope fields are in the outbox receipt JSON and require their own independent sink/acknowledgement checks. The original verifier's execution-before-permit-expiry rule is not claimed to validate the new durable-grant semantics unchanged.

The fixture preissues recoverable permit inputs before measured delivery; this experiment does not cover a crash in original issuance before its complete permit input is persisted. Its warmup operation uses another scope, with another capacity row. For workload `n=64`, each scope has ceiling 64, so a global snapshot can total 128. The timed workload budget is the shared workload scope's 64 units, not that summed ceiling.

## Supplementary test history

`ecrc_peer_run/report.json` preserves the initial development run. Two failures there were errors in the independent test itself: comparing equivalent UTC timestamp strings without normalization, and calling the reaper by an incorrect method name. Both were corrected before interpreting adapter outcomes.

`ecrc_peer_run_corrected_harness/report.json` records 10 of 11 cases passing before the adapter correction. The sole adapter failure is the canonical payload projection described above. Both earlier reports are retained.

`ecrc_peer_final/report.json` passed all 13 cases after the corrections, including the separately added permit/policy-time guards. `ecrc_peer_final_v2/report.json` is the final report: it repeats all 13 cases and adds a sixth malformed-acknowledgement variant to verify the newly added check of the actual returned payload body. All 13 cases pass, including 20 concurrent reconciliations of one real service effect, six invalid-acknowledgement variants, complete rollback after an exception before local commit, lost response with capacity still held, and resumption after expiry/revocation. Core code and protocol hashes were unchanged during both final runs. Physical effect IDs, payload hashes, receipt counts, original receipt hashes, time instants and held/spent capacity were independently checked. Every service subprocess was stopped.

Final reviewed ECRC adapter SHA-256: `89b0a4a497391711a049b0d8e63155ee91c7c4c0e69769f9db7d57e127b5e50f`. Service SHA-256 remains `afc8d95c44ea6bb4f7eabdbb18ba234d3dbc0fbd325274a8694bd62e8c43d279`. These supplementary checks find no remaining blocking correctness issue within the declared trusted-sink, durable-arm contract. They do not replace the parent harness's actual process-crash experiments or establish guarantees for arbitrary services.
