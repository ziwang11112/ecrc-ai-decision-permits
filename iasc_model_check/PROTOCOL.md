# Finite lifecycle model check: protocol fixed before exploration

This is a scoped, post hoc formalization of the current paper's contract. It
adds no AI algorithm, new cancellation protocol, or implementation superiority
claim. The frozen S8 clients and their earlier results are already known.
Both complete implementations must be related to the same specification.

## Question and scope

For fixed legal requests under one policy/revision/scope/action-route key, do
the declared transaction boundaries preserve effect-to-budget responsibility
through permit expiry, cleanup, delayed or repeated delivery, lost messages,
client/service unavailability, and receipt reconciliation?

The model explicitly separates client state, request/acknowledgement channels,
and durable service state. Sink actions may only inspect service state and a
received operation key: they must not inspect the client's holds or receipts.
Acknowledgements can only originate from a durable service effect. Client
reconciliation checks its own intent/hold and a matching acknowledgement,
not a direct read of remote service state.

All request payloads and admissible evidence are fixed, legal and immutable;
an operation is represented by its unique request/key identity. The model
therefore does not verify canonical parsing, evidence qualification, semantic
truth, malformed payloads, arbitrary claim closure, or alias detection. One
operation owns one reservation; the sink has persistent atomic deduplication.
These are explicit modeled mechanisms/assumptions, not empirical discoveries.

## State and transitions

Raw input receipt precedes atomic action issuance (complete permit plus hold).
A request encountering exhausted capacity instead gets a terminal non-action
decision. A new arm requires an issued, held, unexpired permit. Expired unarmed
permits can atomically cancel and release. An existing grant survives expiry.
Send and retry use the same key; service delivery commits effect and durable
deduplication before an acknowledgement becomes available. Receipt creation
atomically transfers held to committed expenditure. Client and service may
crash/recover independently; their durable state and messages survive these
availability transitions. Lost requests/acks are modeled separately.

There is at most one outstanding request and acknowledgement per operation
in the abstract channels; repeated identical packets coalesce. This is a
message-presence abstraction, not an unbounded FIFO/multiset network proof.
Duplicate service delivery after an earlier effect and a repeated completion
acknowledgement are explicit transitions. Permit expiry is a per-operation
monotone abstraction of supplied policy-clock eligibility. It does not model
continuous wall time or enforce cross-permit expiry ordering. The policy
itself remains active; revocation and version migration are out of scope.

Mid-transaction interruption is represented at its pre-commit or post-commit
durable state; the model does not simulate SQL statements, torn writes,
power-loss recovery or prove database atomicity. It excludes post-arm
cancellation, compensation, CPU work, service execution before its durable
effect transaction, and cleanup of received-but-unissued raw requests.

## Fixed cases and properties

Run the same model with two normal configurations:

1. N=2 operations, Capacity=1, unsafe release disabled.
2. N=3 operations, Capacity=2, unsafe release disabled.

For each configuration, complete TLC's reachable-state exploration with no
state constraint, depth cutoff, or invariant used to filter states. Check
types, ledger/hold accounting, cumulative budget, grant backing, effect
backing and count, cancellation/authorization consistency, receipt soundness,
and channel causality. All are checks on reachable states, not guards on Next.
Record explored/distinct states, transitions, depth and action coverage as
tool diagnostics; they are not independent samples or implementation tests.

The sole predeclared negative control uses N=2, Capacity=1 and enables one
additional transition: release an expired, armed, unreconciled hold. It does
not change the sink or the quota guard. Ask TLC to find violation of
EffectCountBound while still checking local accounting and BudgetBound.
Retain and independently replay the returned counterexample. This is an
intentionally unsafe specification, not a fault of either complete client.
Do not label its trace globally minimal unless that is independently checked.

## Execution, completeness and decision gate

Use the pinned official TLC tool and portable Java recorded in tools/. A SANY
parse/type-resolution check may run during preparation; no reachable-state
exploration occurs before the input/source freeze and internal reviews.
Run single-worker breadth-first TLC, with a fixed fingerprint index, a 2 GiB
heap, and a maximum of 600 seconds per normal case and 120 seconds for the
negative control. Time/heap failure is INCOMPLETE, never PASS. Do not reduce a
fixed case after observing an incomplete search and call the original passed.
TLC's fingerprint collision estimates and any warnings must be retained.

Before exploration, also freeze a separately implemented Python breadth-first
enumerator of the same finite transition system. It uses full-state integer
or tuple equality (not lossy fingerprints), independently checks properties,
and records action counts and representative reachable witnesses. Run the same
two positive cases to completion and the same negative N=2/K=1 existence search
under the same per-case time limits. Cross-check labeled reachable-state counts
against TLC. Agreement reduces implementation/checker-error risk but does not
eliminate shared modeling errors. This preparation addition was specified
before any state-space exploration; no outcome-driven instance selection occurs.

Run every declared case once; keep full stdout, stderr, command, return code,
version/hash, elapsed time, configuration and result records. If a preparation
or model defect is found, preserve the old version and its runs, explain the
correction and rerun all affected configurations under a new freeze.

The evidence may be proposed for the paper only if both normal cases complete,
the negative control gives a independently checked counterexample with a
within-limit local ledger, the specification is mapped to the clients' actual
transaction boundaries, and reviewers find no circular state filtering or
hidden cross-service synchronization. Otherwise keep the current manuscript.
Passing establishes only the checked finite model instances under the stated
abstraction and tool behavior. It is not an unbounded theorem, a refinement
proof of Python/SQLite, a liveness guarantee, or a comparison favoring ECRC.

## Preservation

The model and all preparation/run evidence stay in this new directory. Record
hashes of the current manuscript package, fixed release artifacts and S8 source
before execution. Do not change any of them while exploring. Any subsequent
manuscript addition must accurately state the scope, use the complete results,
and leave historical S1-S9 inputs/results unchanged.
