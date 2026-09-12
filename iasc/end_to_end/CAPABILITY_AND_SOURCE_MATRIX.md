# Capabilities and source independence

| Capability | ECRC extension | Ordinary extension | Shared or trusted part |
|---|---|---|---|
| Raw input persistence | New requests journal | Independently coded requests journal | Identical policy/proposal/evidence JSON |
| Policy/input validation | Frozen typed models/adjudicator | New plain-dict checks | One fixed policy/schema, current policy trusted |
| Evidence admission | Frozen gate, declaration metadata | Independently coded metadata gate | Same input records; predictor computation not revalidated |
| Routing and claim closure | Frozen OrderedAdjudicator | Independent Python branches/finite-rule checks | Same declared ordering and required types |
| Capacity reserve/release | Frozen ledger SQL inside NEW outer issuance transaction | New ordinary SQL inside its own atomic issuance transaction | Same per-key cumulative limits |
| Registered full permit | Original trusted registration + NEW full-permit journal atomically committed | New ordinary permit_registry + full-permit journal | Formats and IDs may differ |
| Crash before issue commit | New wrapper rolls back inner operations and permit save | Native single issuance transaction rolls back | Durable raw request received before issuance |
| Expired unarmed cleanup | New serialized cancellation/release | Independently coded serialized cancellation/release | No intent may exist; later dispatch prohibited |
| Durable delivery grant | Copied S6 ECRC adapter | Copied S6 independent ordinary adapter | New worker uses the same transport behavior |
| Timeout retention | Inherited grant retained, new cleanup skips jobs | Inherited grant retained, new cleanup skips jobs | Irrevocable-grant semantics |
| Service dedup/effect | Shared service implementation in separate per-run process/DB | Same | Frozen synthetic sink; one new post-commit delayed-ACK test hook |
| Reconciliation | Original receipt fields plus S6 extension | Independent ordinary receipt format | Actual sink effect/hash/time checked |
| Independent audit | No issuer/adapter imports in audit_e2e.py | Same auditor | Raw original files and direct SQLite tables |

Legacy source files are copied into legacy_snapshot; its nested source_snapshot
contains the unchanged ECRC governance code. Only the new ecrc_e2e.py enlarges
the issuance transaction. No original file is edited. The ordinary module
imports only its previously independent ordinary delivery module, not ECRC.

Input construction uses frozen typed constructors solely to write the common
declarative JSON. It invokes no adjudicator or permit generation. Each arm
starts with raw requests and independently creates the tested permits and
registrations. Ingestion rejection ordering and support for policy histories
can differ; no all-input or all-history equivalence is claimed.

This study measures synthetic effect correctness, not ML prediction, usable
alert timeliness, human review capacity, cancellation after arm, multi-node
consensus, power loss, cross-revision quota continuity or production latency.

The original S6 ordinary constructor's context-managed SQLite connection did
not close immediately on Windows. The NEW ordinary_e2e adapter closes its own
context-managed connections; the copied legacy file stays unchanged. The
initial development cleanup failure is retained outside formal denominators.
