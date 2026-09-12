# Independent trace and information-boundary review

Completed 2026-09-11 against both complete formal suites. The auditor imports only Python standard-library JSON, hashing, date/time, file and read-only SQLite tools. It does not call either adapter, the shared transport, the service implementation, the ECRC validator, or the harness's `check_state` function. It does not treat the CSV columns containing self-reported zero violations as evidence.

| Evidence | First complete run | Fresh complete repeat |
|---|---:|---:|
| Audited case traces | 132/132 | 132/132 |
| Recovery scenarios/arm/repetition combinations | 90 | 90 |
| Authorization boundary cases | 12 | 12 |
| Performance workload runs | 30 | 30 |
| Explicit integrity comparisons | 106,209 | 106,209 |
| Audit findings | 0 | 0 |
| Arm pairs with byte-identical preissued fixtures | 66/66 | 66/66 |

The comparison count reflects many field-level assertions over the same traces. It is not an independent sample size, a probability of correctness, or evidence of exhaustive fault coverage. Both 132-case inventories were checked against each suite's manifest. All directly read trace, fixture and principal database file hashes remained unchanged during the audit. Runtime/input source hashes matched the frozen suite manifests.

## Independent observations

The auditor directly queried each final client database and its **separate** service database. Every final effect matched a durable client intent, with the exact four-field payload derived from the registered permit. The stored job hash, service's recomputed payload hash, ACK key/hash/effect ID, extended receipt's integer service ID, base/string side-effect ID, actual service commit timestamp, and actual local reconciliation timestamp were consistent. Actual service effect ID/hash/timestamp were read from SQLite rather than inferred from a returned ACK. Reconciled receipts did not precede their service effect.

For every capacity key, the auditor checked the two quantities separately: reserved >= 0 and committed >= 0, then reserved + committed <= capacity_limit. It recomputed held/committed totals from individual reservation rows and compared them with the independently read client capacity table and recorded trace. This avoids accepting a negative quantity merely because the sum remains within the limit. Completed operations had one service effect, one receipt, a committed reservation and no outstanding held unit. Rejected boundary cases had no job, effect or receipt.

Recorded intermediate snapshots were independently checked for per-row arithmetic, payload/ACK/receipt consistency and counts. Those historical states were retained as JSON trace snapshots, not separate database backups. Therefore the audit independently queries **final** databases and audits the **recorded** intermediate states; it does not claim an independent historical database reconstruction or continuous monitoring between checkpoints. Recorded crash PID/nonzero-exit metadata were checked; the auditor did not inject additional process failures.

## Original receipt chain versus new delivery contract

For the ECRC arm, the auditor independently recomputed canonical SHA-256 of every original-schema base receipt, its sequence, predecessor hash, row identifiers and registered-permit binding. It also compared every base field with its extended delivery receipt. This is a structural/content chain check against the retained rows, not authentication of an untrusted database or a separately signed chain-tail witness.

The added authorization time, service timestamp, local reconciliation time, logical policy clock and ACK belong to the new delivery extension. They were checked against actual service/job data separately. They are not claimed to be cryptographically covered by the original base receipt hash.

The protocol deliberately linearizes authorization when the durable intent is armed. Expiry/revocation after that point does not cancel the grant. Accordingly, the old verifier's requirement that the effect timestamp precede permit expiry is **not** used to bless or reject the new logical-clock expiry boundary. The audit instead verifies that authorization lies in the permit's valid interval, actual effect time matches the service, and actual local reconciliation follows it. Injected logical-clock time remains explicitly separate from physical timestamps.

## Canonical-input and ACK capability alignment

Within the declared JSON input schema and unchanged trusted registry, the tightened ECRC boundary and the ordinary adapter enforce the same relevant content restriction. ECRC rejects raw permit content whose canonical JSON differs from the parsed artifact's `to_dict()`, then checks its exact registered hash. The ordinary adapter hashes the supplied JSON directly and requires the complete trusted issuance hash. A change that would be silently normalized into another permit representation therefore cannot become an accepted unregistered content variant in the ordinary arm. Both payloads contain the same deterministic four fields from that registered content.

Both completion implementations check the ACK key, registered request/payload hash, positive integer service effect ID, and recomputed hash of the actual ACK payload before accepting it. The service schema rejects nonfinite or otherwise invalid JSON. This confirms the intended content/ACK boundary; it is not a proof of identical behavior on arbitrary non-JSON Python objects, all malformed acknowledgements, or malicious edits to the trusted registry.

For every recovery, boundary and performance pair, the policy, full permit documents, issued-permit registry, reservations and capacity state were independently compared across arms. All 66 pairs in each run used byte-identical fixture JSON. Thus neither arm received weaker trusted input information in these runs. ECRC issuance generated the shared fixture outside measured delivery, and the ordinary arm independently implemented its transaction/recovery logic. These are information-matched delivery implementations, not independent issuance implementations.

## Auditor implementation checks and files

Four deliberately corrupted **in-memory copies** were all detected: wrong extended receipt effect ID, wrong receipt service timestamp, inconsistent independent-sink payload hash, and negative reserved capacity hidden by an apparently valid reserved-plus-committed sum. No original trace or database was modified. These four checks validate the auditor's fault detection paths and do not enlarge the formal experiment denominator.

Formal reports:

- `independent_trace_audit_out/audit_report.json`, `case_audit.csv`, `information_match.json`, `auditor_self_checks.json`;
- `independent_trace_audit_out_repeat/audit_report.json`, `case_audit.csv`, `information_match.json`.

Frozen audit entry points:

```text
python audit_runtime_traces.py --suite out --report-dir independent_trace_audit_out
python audit_runtime_traces.py --suite out_repeat --report-dir independent_trace_audit_out_repeat
python audit_information_match.py --suite out --report independent_trace_audit_out/information_match.json
```

`audit_runtime_traces.py` SHA-256: `62d57aff4c900c2cd1e2e6d9c895256bd9e50a956311c8cf233beffccaafb819`.

`audit_information_match.py` SHA-256: `e91587fcc240ca377e092a26375838f78a821d27aa9b13d292536821f3c2595c`.

The files are ready to accompany the portable runtime bundle. Retain the complete database/trace tree, fixture JSON, both suite manifests and their referenced source snapshots. The audit assumes a completed, quiescent suite and reads SQLite in `mode=ro` with `query_only=ON`; it does not checkpoint, rewrite, or recreate the experimental databases.
