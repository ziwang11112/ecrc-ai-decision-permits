# Mixed lifecycle development protocol

This is a new eight-cell controlled development experiment. It uses synthetic durable records, not a business benchmark, a model, or a real participant intervention. All A/B/C/D inputs and all outcomes are retained. No favorable result is required for inclusion. The selected external count limit is an engineering setting, K=2 distinct durable effects in one unchanged scope.

Four arms are compared in normal and mixed conditions, once per cell. Normal order is raw, volatile_count, durable_count, ECRC; mixed reverses it. No speed significance or independent-task success rate is estimated.

- **raw** imports the existing `raw_task_baseline_2026-09-14/direct_client.py` unchanged, with its original default limit=None. This is the direct-execution capability control, not a claim that normal systems universally lack counting.
- **volatile_count** imports that same file with its existing limit=2 option. It is the original optional in-memory counter, with no added ECRC mechanisms. Its process restart limitations are not generalized to all ordinary implementations.
- **durable_count** is a separately labelled new conventional SQLite counter/request-log extension. It uses a transaction before dispatch, stable request keys, same-key recovery and cumulative counting without refunds after completion or uncertainty. It has no ECRC evidence, route, claim or permit construction.
- **ecrc** uses the unchanged S8 implementation and original ledger/adjudicator. The new worker keeps issuance separate from durable arm and reconstructs restart state from original requests/outbox tables. All requests use one policy identifier, revision, subject/session and alert resource; restart does not reset the database or budget key.

Both direct arms preserve their stable `direct:` job-hash identity and the original service cache. The original source's optional limit is not silently disabled in every baseline. A shared upstream queue retains unacknowledged delivery descriptors for retry, independent of client implementation. Redelivery is not a new admission and does not increment the original volatile counter again. ECRC and durable_count must also recover the matching descriptor from their own persistent records. The common queue never stores the hidden response or reads the sink database to decide scheduling.

The neutral service is exactly the original S8 `legacy_snapshot/service.py`, in a separate process and database. It accepts opaque payloads, atomically stores one synthetic effect with each key/payload binding, and returns cached responses for identical retries. Raw payloads identify job_hash; ECRC payloads identify decision_id plus route/claim/evidence identifiers. They identify the same logical A/B/C/D jobs but are not byte-identical requests. Effects are records, not actual diagnostic work, CPU, money or business benefit.

## Fixed events

Normal: A is queued (ECRC issues but does not arm); dispatch A then B then C then D, all before their relevant permit expiries. All four are otherwise eligible. Attempt every input even if another is denied, preserving the outcome.

Mixed: A is queued and ECRC issues it at logical 12:00:10 without arm. B is dispatched at 12:00:20. A common proxy reads B's real post-commit response from the unchanged service but withholds it. Until the predetermined release phase it also withholds any GET or POST response for B, using public request identity. It does not change effect contents or remove service deduplication. The actor only sees a transport failure, never the hidden body. Proxy evidence is audit-only.

After B becomes unknown to the client, record state, actually terminate the client process and start a new one for every arm. Both A's independent queue dispatch deadline (13:00:10) and its ECRC permit expiry have passed when cleanup occurs at 13:00:30. The queue will not dispatch A in any arm. ECRC must cancel its expired unarmed A but retain B's already armed responsibility. An armed intent cannot be released even if its HTTP has not yet been sent; the boundary is not merely whether transport happened.

C and D remain in the common upstream queue until fixed first attempts at 13:00:31 and 13:00:32. C is not previously submitted to ECRC and terminally denied, and identities are never changed to regain authority. D tests whether a third distinct effect can be admitted. A volatile client's lost history may permit more effects; this is measured with durable_count presented alongside it. Normal outcomes establish that configuring the original counter can already enforce the limit without a restart.

After the C/D attempts, release the common proxy window at the fixed protocol phase and redeliver B's original unacknowledged queue message at 13:00:40. Restore ECRC and durable_count from their own persistent state; raw/volatile receive their original queued descriptor. A cached acknowledgement can settle B without creating another effect. ECRC held-to-committed is not a quota refund. Observe final state. Permission clocks are injected logical values; process/service event timestamps and response times are real. Do not use the virtual hour to claim actual waiting or deadline performance.

## Measures and checks

Count actual distinct effects for each of four logical jobs, duplicates, effects over the newly assigned external K=2 requirement, and mixed A effects after its queue deadline. The new raw comparison deliberately evaluates a workflow without quota enforcement against an explicit external requirement. This does not relabel the older raw probe, in which raw was not assigned an upper limit.

Budget nonconformance is a capability result and remains separate from execution errors or an audit failure. A no-effect outcome is not automatically successful. Include all four inputs; separately identify the expired A and outstanding/admissible B/C/D. No prescribed winner set is used to erase results. Actual acknowledgements, proxy-withheld bodies and independent final databases support correspondence and retry checks. The sink DB is read only for snapshots and postrun audits, not by actors or scheduling decisions.

ECRC snapshots and final audit must show effects backed by registered permits and persistent reservations; direct counts and acknowledgements are checked under their own schema. No ECRC-only field is required of the original baseline. All arms use original cache behavior and stable keys. No invented wrong answer, artificial key change or deliberate timeout refund is inserted into a baseline.

Freeze code, this protocol, common inputs, original DirectClient, original core/service sources and protected manuscript inputs after developer QA and before these eight cells. Use new output directories, retain every cell and error. Necessary implementation repairs require versioned reruns with originals retained. Do not automatically expand conditions or datasets after observing results. Shared-cache retry behavior, simple-count benefits and full-contract properties must be attributed separately.
