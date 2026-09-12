# Equal-information ordinary-record semantic baseline protocol

Protocol fixed before implementing or running the new validator, 2026-09-11.

## Question and estimand

Can an independently implemented verifier over ordinary JSON records and relational metadata detect the same prespecified faults when given the trusted information available to the ECRC checks? The unit is one mutated trace/case, not each record inside that trace. Report seven family counts, two component counts, overall detections, and acceptance of the single clean trace containing 32 records. Do not infer 32 statistically independent clean traces from that trace.

This is an OFFLINE DETECTION comparison. The 24 permit substitutions are mutations of pre-execution record fields, but the new evaluation does not install a live enforcement point or prevent a side effect. The 60 receipt mutations are post-execution audit faults. No latency, concurrency, intervention benefit, or external-service atomicity claim is tested.

## Frozen inputs and information access

Use the archived component-ablation runtime policy, 32 permits, 32 receipts, SQLite ledger, fault manifest and archived validator outcomes in `experiment_reproducibility/icair_2026/framework_v1/evidence_v2/component_ablation/`. Read originals only. Snapshot and hash all consumed files. Query the ledger through Python's ordinary `sqlite3` driver in read-only mode; expose only active policies, issued-permit metadata, reservations, and the receipt-chain tail. Do not give the new receipt checker stored receipt JSON, an expected per-receipt answer, execution-row contents, or fault labels.

The trusted tail in `ablation_summary.json` must match the ledger tail before testing. Trusted issuance content hashes bind claim scope and evidence hashes. Raw proposal/evidence envelopes are unavailable in this archived fixture and neither this comparison nor the archived full validator re-establishes their external truth from raw data.

## Independent implementation boundary

The new validator uses standard-library dictionaries, JSON serialization, SHA-256, timestamps and relational metadata. It MUST NOT import or call ECRC validators, dataclasses, schema parsers, canonicalization helpers, fixture builders, ledger methods or enforcement routines. Inspecting the published/local contract and source to understand fields and invariant scope is allowed and will be disclosed. Implement structural validity, exact registered-content binding, active-policy/time validity, action-reservation binding, ordered hash-chain continuity, unique IDs, receipt-to-permit policy/route/content/time agreement, execution-status semantics and the trusted final anchor independently.

The harness may reproduce the seven documented mutations as plain JSON changes at the positions in the archived fault manifest. Every reconstructed case payload must match the archived `case_sha256` before it is evaluated. This is fixture reuse, not independent generation of the 84 test cases. Archived ECRC outcomes are the matched reference arm and will be labeled archived, not newly executed.

## Prespecified checks and reporting

1. Verify input hashes and the trusted anchor; export the permitted trusted view.
2. Independently construct all 84 JSON cases from the archived manifest and verify exact case hashes.
3. Run the new verifier on the clean trace and all cases without passing fault labels to it.
4. Compare with the archived full ECRC arm and retain the archived weak typed-parser arm for context.
5. Run separate, hand-authored small traces and boundary mutations, including exact expiry, before-issuance time, duplicate/reused identifiers, self-consistent hash-chain rewrites, removed final receipt, invalid claim/evidence relations, and reservation mismatch. Include valid controls. These tests are implementation checks and do not enlarge the paper's original 84-fault denominator.
6. Save scripts, exact candidate payload hashes, per-case findings, family/component summaries, clean outcomes, boundary checks, methods/results and limitations. Report ties and unexpected failures without changing the target after observing results.

## Unsupported claims

Equal sensitivity would show that semantic information and checks are reproducible with conventional record representations. It would not prove ECRC superior to rich logging, prove prevention, establish unknown-fault coverage, authenticate a compromised trusted store, prove distributed correctness, or validate any actual external effect. SHA-256 detects changes relative to a trusted reference; it supplies neither authentication nor trustworthy facts by itself.
