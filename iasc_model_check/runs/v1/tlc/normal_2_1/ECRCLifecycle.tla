--------------------------- MODULE ECRCLifecycle ---------------------------
EXTENDS Naturals, FiniteSets

CONSTANTS N, Capacity, AllowUnsafeRelease
ASSUME /\ N \in Nat \ {0}
       /\ Capacity \in Nat
       /\ Capacity <= N
       /\ AllowUnsafeRelease \in BOOLEAN

Ops == 1..N

VARIABLES received, issued, denied, cancelled,
          held, committed, armed, expired,
          requests, acknowledgements, effects, receipts,
          heldCount, committedCount, clientUp, sinkUp

vars == <<received, issued, denied, cancelled,
          held, committed, armed, expired,
          requests, acknowledgements, effects, receipts,
          heldCount, committedCount, clientUp, sinkUp>>

ClientRecords == <<received, issued, denied, cancelled,
                   held, committed, armed, expired, receipts,
                   heldCount, committedCount>>

Init == /\ received = {} /\ issued = {} /\ denied = {} /\ cancelled = {}
        /\ held = {} /\ committed = {} /\ armed = {} /\ expired = {}
        /\ requests = {} /\ acknowledgements = {} /\ effects = {} /\ receipts = {}
        /\ heldCount = 0 /\ committedCount = 0
        /\ clientUp = TRUE /\ sinkUp = TRUE

ReceiveRaw(o) ==
    /\ clientUp /\ o \notin received
    /\ received' = received \cup {o}
    /\ UNCHANGED <<issued, denied, cancelled, held, committed, armed, expired,
                   requests, acknowledgements, effects, receipts,
                   heldCount, committedCount, clientUp, sinkUp>>

IssueAction(o) ==
    /\ clientUp /\ o \in received /\ o \notin issued \cup denied
    /\ heldCount + committedCount < Capacity
    /\ issued' = issued \cup {o}
    /\ held' = held \cup {o} /\ heldCount' = heldCount + 1
    /\ UNCHANGED <<received, denied, cancelled, committed, armed, expired,
                   requests, acknowledgements, effects, receipts,
                   committedCount, clientUp, sinkUp>>

IssueNoAction(o) ==
    /\ clientUp /\ o \in received /\ o \notin issued \cup denied
    /\ heldCount + committedCount >= Capacity
    /\ denied' = denied \cup {o}
    /\ UNCHANGED <<received, issued, cancelled, held, committed, armed, expired,
                   requests, acknowledgements, effects, receipts,
                   heldCount, committedCount, clientUp, sinkUp>>

Arm(o) ==
    /\ clientUp /\ o \in issued \cap held
    /\ o \notin armed \cup expired
    \* No cancelled guard: atomic cleanup's release must make later arm fail.
    /\ armed' = armed \cup {o}
    /\ UNCHANGED <<received, issued, denied, cancelled, held, committed, expired,
                   requests, acknowledgements, effects, receipts,
                   heldCount, committedCount, clientUp, sinkUp>>

ExpirePermit(o) ==
    /\ o \in issued /\ o \notin expired
    /\ expired' = expired \cup {o}
    /\ UNCHANGED <<received, issued, denied, cancelled, held, committed, armed,
                   requests, acknowledgements, effects, receipts,
                   heldCount, committedCount, clientUp, sinkUp>>

CancelUnarmed(o) ==
    /\ clientUp /\ o \in issued \cap expired \cap held
    /\ o \notin armed
    /\ cancelled' = cancelled \cup {o}
    /\ held' = held \ {o} /\ heldCount' = heldCount - 1
    /\ UNCHANGED <<received, issued, denied, committed, armed, expired,
                   requests, acknowledgements, effects, receipts,
                   committedCount, clientUp, sinkUp>>

Send(o) ==
    /\ clientUp /\ o \in armed /\ o \notin receipts \cup requests
    /\ requests' = requests \cup {o}
    \* Existing intent survives expiry. Identity/payload is fixed per operation.
    /\ UNCHANGED <<ClientRecords, acknowledgements, effects, clientUp, sinkUp>>

LoseRequest(o) ==
    /\ o \in requests
    /\ requests' = requests \ {o}
    /\ UNCHANGED <<ClientRecords, acknowledgements, effects, clientUp, sinkUp>>

CommitEffect(o) ==
    /\ sinkUp /\ o \in requests /\ o \notin effects
    \* The sink never tests client held/committed/expiry/cancellation state.
    /\ effects' = effects \cup {o}
    /\ requests' = requests \ {o}
    /\ acknowledgements' = acknowledgements \cup {o}
    /\ UNCHANGED <<ClientRecords, clientUp, sinkUp>>

DeduplicatedReply(o) ==
    /\ sinkUp /\ o \in requests \cap effects
    /\ requests' = requests \ {o}
    /\ acknowledgements' = acknowledgements \cup {o}
    /\ UNCHANGED <<ClientRecords, effects, clientUp, sinkUp>>

LoseAcknowledgement(o) ==
    /\ o \in acknowledgements
    /\ acknowledgements' = acknowledgements \ {o}
    /\ UNCHANGED <<ClientRecords, requests, effects, clientUp, sinkUp>>

Reconcile(o) ==
    /\ clientUp /\ o \in acknowledgements \cap armed \cap held
    /\ o \notin receipts
    \* Only the matching trusted acknowledgement is observed, not remote effects.
    /\ held' = held \ {o} /\ heldCount' = heldCount - 1
    /\ committed' = committed \cup {o} /\ committedCount' = committedCount + 1
    /\ receipts' = receipts \cup {o}
    /\ acknowledgements' = acknowledgements \ {o}
    /\ UNCHANGED <<received, issued, denied, cancelled, armed, expired,
                   requests, effects, clientUp, sinkUp>>

RepeatedCompletion(o) ==
    /\ clientUp /\ o \in acknowledgements \cap receipts
    /\ acknowledgements' = acknowledgements \ {o}
    /\ UNCHANGED <<ClientRecords, requests, effects, clientUp, sinkUp>>

CrashClient == /\ clientUp /\ clientUp' = FALSE
               /\ UNCHANGED <<ClientRecords, requests, acknowledgements, effects, sinkUp>>
RecoverClient == /\ ~clientUp /\ clientUp' = TRUE
                 /\ UNCHANGED <<ClientRecords, requests, acknowledgements, effects, sinkUp>>
CrashSink == /\ sinkUp /\ sinkUp' = FALSE
             /\ UNCHANGED <<ClientRecords, requests, acknowledgements, effects, clientUp>>
RecoverSink == /\ ~sinkUp /\ sinkUp' = TRUE
               /\ UNCHANGED <<ClientRecords, requests, acknowledgements, effects, clientUp>>

UnsafeReleaseUnknown(o) ==
    /\ AllowUnsafeRelease /\ clientUp
    /\ o \in expired \cap armed \cap held /\ o \notin receipts
    /\ held' = held \ {o} /\ heldCount' = heldCount - 1
    \* Deliberately unsafe control. Existing in-flight messages remain deliverable.
    /\ UNCHANGED <<received, issued, denied, cancelled, committed, armed, expired,
                   requests, acknowledgements, effects, receipts,
                   committedCount, clientUp, sinkUp>>

Next == (\E o \in Ops:
            ReceiveRaw(o) \/ IssueAction(o) \/ IssueNoAction(o) \/ Arm(o)
            \/ ExpirePermit(o) \/ CancelUnarmed(o) \/ Send(o) \/ LoseRequest(o)
            \/ CommitEffect(o) \/ DeduplicatedReply(o) \/ LoseAcknowledgement(o)
            \/ Reconcile(o) \/ RepeatedCompletion(o) \/ UnsafeReleaseUnknown(o))
        \/ CrashClient \/ RecoverClient \/ CrashSink \/ RecoverSink

Spec == Init /\ [][Next]_vars

TypeOK == /\ received \subseteq Ops /\ issued \subseteq Ops /\ denied \subseteq Ops
          /\ cancelled \subseteq Ops /\ held \subseteq Ops /\ committed \subseteq Ops
          /\ armed \subseteq Ops /\ expired \subseteq Ops /\ requests \subseteq Ops
          /\ acknowledgements \subseteq Ops /\ effects \subseteq Ops /\ receipts \subseteq Ops
          /\ heldCount \in 0..N /\ committedCount \in 0..N
          /\ clientUp \in BOOLEAN /\ sinkUp \in BOOLEAN

Accounting == /\ heldCount = Cardinality(held)
              /\ committedCount = Cardinality(committed)
              /\ held \cap committed = {}
BudgetBound == heldCount + committedCount <= Capacity
Lifecycle == /\ issued \cup denied \subseteq received /\ issued \cap denied = {}
             /\ held \cup committed \cup armed \cup expired \subseteq issued
             /\ cancelled \subseteq issued \cap expired
             /\ cancelled \cap (armed \cup held \cup committed) = {}
GrantBacking == armed \subseteq held \cup committed
EffectBacking == effects \subseteq held \cup committed
EffectCountBound == Cardinality(effects) <= Capacity
ReceiptSoundness == receipts \subseteq effects \cap armed \cap committed
NetworkCausality == /\ requests \cup acknowledgements \cup effects \subseteq armed
                    /\ acknowledgements \subseteq effects

=============================================================================
