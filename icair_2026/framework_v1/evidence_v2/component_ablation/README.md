# Matched component-ablation evidence

This directory contains two separate evaluation axes over the frozen E1
proposal stream. The final run reads `evidence_v2/route_assignments.csv.gz`:
Many Labs participant-grouped outer-CV proposals plus the frozen external
official Mendeley v2 replay (`mendeley_igt_official_v2`).

## Routing/resource axis

- `full_controls`: uncertainty routing, evidence admission, alert cap 8 and
  review cap 2.
- `evidence_gate_off`: identical settings, but deterministic missing/stale
  evidence is ignored.
- `uncertainty_gate_off`: identical evidence and separate capacities, but the
  uncertainty threshold is disabled.
- `shared_capacity`: the same candidate rules use one per-participant FIFO
  action pool of 10 slots (8 alert + 2 review in the reference). Review
  overflow abstains; alert overflow becomes no action.
- `capacity_off`: evidence admission remains fail-closed, while both alert and
  review capacities are effectively unbounded.

The evidence stress is a deterministic conformance fixture: SHA-256 assignment
marks one twentieth of decisions missing and one twentieth stale, independently
of model score and posthoc label. It is not an estimate of real missingness.
Clean admitted-evidence results are reported separately.

Routing components are evaluated with automated-alert outcomes and human-review
burden reported separately. Proposal scores are identical across arms, so the
ablation does not credit any component with predictive improvement. The shared
arm estimates the consequence of pooling the same nominal total quota under
FIFO; it does not establish that 10 is optimal or that shared capacity is
generally preferable.

## Record/state axis

Thirty-two deterministic decisions are sent through the repository's actual
`OrderedAdjudicator -> SQLiteCapacityLedger -> PEPSimulator` path. The resulting
issued permits and receipts are checked by `StatefulReceiptVerifier` against the
ledger's trusted tail. Four validation arms compare ordinary typed parsing,
claim binding bypassed, receipt/state verification bypassed, and both checks.
Typed claim/evidence substitutions occur pre-execution; typed receipt
mutation/reorder/replay/omission cases occur post-execution. These components
are evaluated only by clean false positives and prespecified fault sensitivity.

The PEP simulates side effects inside SQLite. These records do not show external
action execution, atomicity with a real alert service, legal authorisation,
tamper-proof storage, or unknown-fault coverage.
