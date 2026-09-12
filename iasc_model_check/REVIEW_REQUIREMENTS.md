# Independent review requirements for the finite-state study

Prepared 12 September 2026 before inspecting or executing the proposed model. This document specifies acceptance criteria; it reports no search result. The reviewer has not modified the root model or executed a model checker.

## Scope that must remain explicit

The positive model has two fixed instances: **N=2, K=1** and **N=3, K=2**. N is the finite set of operation identities and K is one cumulative budget for the fixed policy/revision/scope. Search must exhaust the reachable model states for each positive instance, without a maximum state count or depth cutoff being mistaken for completion.

The network abstraction contains, per key, a Boolean pending-request presence and a Boolean pending-acknowledgment presence. Repeated messages with the same identity and fixed content collapse into presence. This is a finite abstraction of the stated message semantics, not a proof for an unbounded FIFO network. It does not establish preservation under arbitrary message payloads, arbitrary queue order or cardinality, or another network abstraction.

All operations use fixed, legal payloads and evidence. The model may check identity and content binding for those constants, but does not cover all O1 input semantics, evidence admission rules, claims, model inputs, or malicious requests. Operations expire through an explicit per-operation event/flag, not through a real wall-clock model. No deadline or timing conclusion follows.

Client and service can crash and recover independently. A transaction is abstracted as either its pre-commit or post-commit durable state; a crash must not expose an invented half-written durable transaction. This assumption does not prove actual database durability, atomicity, storage behavior or crash safety between physical instructions.

The negative model changes **only** the `ExpiredArmedUnknown` release rule: an expired armed operation whose result is unresolved locally may release its held unit. It is an intentionally unsafe explanatory contrast. It is not the complete ordinary implementation, and its counterexample must not be presented as an ordinary-client defect or evidence of implementation superiority.

## Freeze before search

Freeze a versioned protocol, both parameter files, the model, property definitions, any model-to-checker translation, search driver, independent trace checker, and the exact invocation. Record their SHA-256 hashes, checker name/version, dependency versions, initial-state definitions and enabled reduction options. Retain the original freeze and logs after any amendment.

The freeze must make the following choices concrete:

- List every state variable and its finite domain. Distinguish client durable state, client volatile state, service durable state, service volatile state, and network state. Explain what each crash erases and what recovery reconstructs.
- Define operation/key/payload identity and idempotent cached-result behavior. Retries cannot silently acquire fresh operation IDs. Attempt counters, timestamps, revision counters, receipt positions and generated IDs must not create an undeclared unbounded domain. If omitted or abstracted, state why that omission preserves the properties being checked.
- Enumerate all transition families and their guards: issuance, cancellation before arm, durable arm, sending, service handling/commit, acknowledgment handling, reconciliation, expiration, cleanup, and each independent crash/recovery. Declare request/ack loss or retention behavior at each boundary, and whether a transition may be a stutter.
- Fix how held and committed units, distinct durable effects, and receipts are represented and counted. A post-effect held unit and a committed unit each consume one permanent cumulative unit. Reconciliation must not restore a reusable slot. No policy/revision/scope reset is permitted inside a trajectory.
- State exactly which steps are atomic and which cross-system steps can interleave. An in-flight request is not evidence of a durable effect; a service effect is not evidence that the client received an acknowledgment.
- Define all initial states and legal parameters independently of desired outcomes. Do not silently discard states because an invariant fails or because they seem unlike the intended workflow.
- Include a machine-readable diff or single explicit switch demonstrating that positive and negative models differ in the one specified release transition only. Parameters, message semantics, crashes, initial states and checker settings remain identical.

The protocol should be called a local, prospective search freeze within an exploratory project, rather than a confirmatory or externally registered study. A timeout, memory failure, counterexample, unexpected count or negative result triggers retention and review, not an unrecorded change to the model or case set.

## Safety properties and independent accounting

At minimum, define and check these properties separately, without making them successor-generation guards:

1. Local accounting: nonnegative held/committed counts and `held + committed <= K`.
2. Unit responsibility: every distinct durable service effect has its own still-held or committed authorization unit; one unit cannot back two different operation effects. Aggregate `effects <= held + committed` is a useful corollary but is not a substitute for the per-operation relationship.
3. External-effect bound: the number of **distinct durable service effects** is at most K. Count identities, not send attempts, acknowledgments or cached replies.
4. Receipt binding: each receipt identifies an existing matching effect and authorized operation; reconciliation cannot create a second receipt or second expenditure for a retry. State the intended receipt-to-committed relationship explicitly.
5. Dispatch authority: only a valid durably armed operation may produce a request capable of causing its effect. Expiry of an unarmed authorization may permit cancellation; expiry after arm cannot revoke its outstanding responsibility in the positive model.

The model may contain additional sanity invariants, but distinguish assumptions encoded by construction from properties genuinely checked over reachable states. For example, a one-bit effect variable structurally limits one effect per operation; that is an abstraction assumption, not independent evidence that an arbitrary implementation deduplicates correctly.

These are safety checks. Reachability exhaustion alone does not establish eventual recovery, bounded completion time, fairness, or availability: indefinitely repeated crashes or indefinitely undelivered messages can prevent progress. Do not add a liveness claim without a separate property and explicit fairness/fault assumptions.

## Complete-search acceptance

For **each positive instance**, retain a successful termination record showing that the reachable-state frontier/work queue is empty and all generated successors have been processed or recognized as already visited. Record initial states, unique visited states, generated transitions, duplicate successors, terminal/deadlock states and the maximum discovered shortest-path depth, with exact counting conventions. Exploration depth is an observed diagnostic, never a configured cutoff.

Every enabled transition instance from every visited state must be considered. Deterministic serialization of the full relevant state must define visited-state equality; lossy hashes alone must not silently conflate different states. If a hash is used for indexing, collisions need an exact-state check or a stated checker guarantee. Save enough configuration and logs to distinguish complete termination from an interrupted or capped run.

Any symmetry or partial-order reduction must be declared before search, with its effect on the properties and state counts explained. Prefer the unreduced model for these small instances. If a reduced search is used, an independently checked unreduced small instance or another concrete reduction-validation argument is required. Do not label quotient-state counts as counts of all labeled states.

An independent audit must recompute the key properties from saved state/trace data or use a separately implemented checker/property formulation. Re-running the same function that generated an expected answer is reproducibility, not independent semantic validation. At minimum, inspect initial states, one legal example of every transition family, and all reported counterexample edges without importing the model's invariant predicate.

State-space size, transition count, shortest-path depth and assertion count are engineering diagnostics, not statistical sample sizes, independent replications, or measures of developer productivity. No confidence interval or superiority inference is appropriate.

## Reachability and coverage report

Produce a transition-family coverage table with enabled-source counts and explored-edge counts, including zeroes. A zero can be an intentional scope restriction or a modeling error; explain it rather than removing the transition from the report.

Show concrete reachable witnesses for issuance/arm, an effect awaiting acknowledgment, lost or unavailable feedback where modeled, an idempotent retry, final reconciliation, expiry before arm, expiry while armed and unresolved, and cleanup in both cases. Include client-only down, service-only down and both-down states, together with independent recovery, if those states are claimed to be covered. Identify whether a witness preserves pending messages or obtains new ones through retry.

Report guard boundaries and unreachable combinations. Complete exploration can still be uninformative if the model accidentally prevents the critical state, serializes all client/service work, disallows cleanup with a pending acknowledgment, or never allows a second operation to compete for a released unit. N=3,K=2 is a separate fixed instance; it is not an induction step or evidence for arbitrary N and K.

## Negative-model counterexample acceptance

For the sole predeclared negative instance **N=2, K=1**, search for a reachable state satisfying **`distinct_effects > K` while `held + committed <= K`**, reached using the single unsafe release rule. The N=3, K=2 instance is a positive case only. Record whether the negative search exhausts its graph or stops at its first witness. A first-witness search is legitimate for existence, but its visited count and maximum depth must not be described as complete negative-model coverage. If no witness is found, report that outcome and whether the search completed; do not tune the model to force the expected result.

The minimum useful witness contains:

- A valid authorization and durable arm for one operation, with no reconciled client receipt yet. Its service effect may exist before unsafe release or may be committed afterward.
- Expiration and the negative release transition, showing the exact unit removed despite the durable effect or still-possible armed effect. `UnsafeReleaseUnknown` does not require the service effect to have occurred. Preserve the first witness and its actual event order; do not force the order of an earlier illustrative figure.
- Admission and effects for additional distinct operations using the improperly restored cumulative budget, until the distinct-effect bound is violated while the local ledger bound still holds.
- A state-by-state table of operation identities, durable client/ledger status, service effects, receipt state, pending request/ack presence, crash flags, expiration flags, and both counts.

An independent trace replay must validate the initial state, every guard and successor, the one-rule difference, and the final predicate. The violation must not depend on a negative count, duplicated effect counting, a fresh key for the same retry, an invalid payload, an unrelated extra model change, or a skipped transition. If the trace is called shortest, use breadth-first search with all relevant initial states or provide another valid minimality justification. Otherwise label it simply a counterexample.

Apply the same trace prefix to the positive model and show the exact step at which the unsafe release is disabled or responsibility retained. Do not say the positive model follows the identical entire trace and somehow produces a different final state.

## Mapping to actual saved execution

Keep model validation and implementation correspondence separate. At minimum, provide a mapping table from the counterexample's relevant transition families and state fields to actual API actions, source locations, SQLite columns and saved event/receipt artifacts in the tested implementation. Mark each mapping as observed, structurally supported by code, abstracted, or unimplemented.

Use a saved actual positive trajectory covering arm, durable effect, unavailable acknowledgment, expiration/cleanup, retained held unit and eventual cached recovery. Preserve operation/key/payload identity and verify each mapped checkpoint from the raw durable records. Sequential reads from two live databases are not automatically a simultaneous distributed snapshot; use quiescent checkpoints or state the allowed observation interval.

The unsafe release transition is absent from the correct implementation. It must be marked as an intentionally introduced negative action, not mapped to an observed ordinary-client behavior. If a deliberately modified executable replay is later added, isolate and hash that version, document the one change and preserve the safe comparison. If no such executable variant is run, label the negative trace as a model counterexample with a correspondence argument, not an observed implementation failure.

Crashes in the finite model need an explicit correspondence rationale to existing or newly saved pre/post-commit crash checkpoints. A process-exit test does not prove arbitrary power-loss behavior. If a modeled crash interleaving lacks an executable witness, disclose the gap; do not fabricate an implementation trace or infer one from a summary flag.

## Stop and revision conditions

- **Stop claims of completion** on any unexplained positive invariant violation, incomplete frontier, state/depth cutoff, missing transition family, wrong initial-state set, or unvalidated state equivalence/reduction. Retain logs and classify whether the issue is in the model, checker, property, or intended contract.
- **Stop the claimed negative explanation** if the witness relies on more than the declared release change or cannot be independently replayed. A completed negative search with no violation is a valid finding requiring interpretation, not grounds for hiding the run.
- **Stop the implementation claim** when the abstraction-to-code mapping is unsupported. A valid finite-model result may remain a local explanatory artifact without a new paper claim.
- Any correction after execution gets a versioned amendment and preserved original outputs. Re-run all affected fixed instances and contrasts after a semantic change; do not preserve only favorable instances.
- A possible paper addition must add a defensible mechanistic result beyond an already-stated accounting assumption. If the model merely restates that assumption by construction, or the mapping is fragile, keep the current paper unchanged and retain the local review.

Acceptable final wording is limited to exhaustive safety checking of the two declared finite instances under the stated abstraction, plus any independently validated counterexample to the single unsafe cleanup rule. It must not claim a general distributed-protocol proof, universal N/K safety, all O1 semantics, superiority over the complete ordinary implementation, application utility, development-cost savings or statistical significance.
