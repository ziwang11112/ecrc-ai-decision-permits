# Conditional cumulative-effect accounting

This is the new analytical argument used in the restructured manuscript,
Equation 7. It adds no experiment or implementation-wide proof.

Fix a budget key k with finite nonnegative integer limit L_k. Let X_k count
all distinct durable effects attributable to k and produced through the
controlled path up to the cut below, with one unit required per effect.
Consider a finite consistent global cut: its
committed events contain their causal predecessors. Initially X_k=S_k=C_k=0.
Held and committed reservations are disjoint, with cardinalities S_k and C_k.

Sufficient assumptions:

1. Every ledger mutation follows serialized guarded transitions: reserve
   changes (S,C) to (S+1,C) only if S+C<L; commit transfers the same held unit
   to (S-1,C+1); authorized release of a held unit changes (S,C) to (S-1,C).
2. Distinct armed operations own distinct one-unit reservations under k.
   Operation keys/payloads are immutable; the trusted sink permits at most one
   durable effect per operation throughout its possible retry horizon.
3. Every counted effect follows durable arm, without bypass execution.
4. An armed reservation is never released while its effect exists or can arrive.
   Pre-arm cancellation/release atomically prevents later dispatch.
5. Reconciliation transfers the same unit exactly once, and committed units
   are never reclaimed under k. Required records persist without deletion,
   reset or corruption.

Then X_k <= S_k+C_k <= L_k. Map each counted effect to its operation's unit.
Assumptions 2–3 define an injective map; 4–5 keep its image in the held or
committed sets. Their disjoint cardinalities give the left inequality. The
right inequality follows by induction from zero over the guarded transitions.
Sink commit consumes no second unit; reconciliation preserves S+C.

These conditions are sufficient and are not claimed minimal. Atomic issuance
and immutable payloads also support authorization obligations beyond counting.
The low-level Ledger.release API is not outbox-aware; all mutators must respect
the controlled lifecycle. Unknown outcomes and known effects lacking local
receipts retain their units. X_k is cumulative, not a surviving-row count after
deletion. Asynchronous SQLite reads need not form a consistent global cut.
Saved audits are finite observed checks and do not prove all implementation
histories. Retention may prevent progress indefinitely during an outage.

Figure 1's one-unit timeout-release counterexample is explanatory: A commits,
its response is lost, an unsafe cleanup releases A's unit, and B produces a
second effect. Independent idempotency of A and B does not provide separate
budget backing. Neither complete implementation was observed to fail this way;
this illustration is not a newly executed mechanism-removal experiment.

Exact implementation locations, limitations and source hashes are in the
companion NOTATION_AND_PROPERTY_MAPPING.csv and SOURCE_HASHES registry.
