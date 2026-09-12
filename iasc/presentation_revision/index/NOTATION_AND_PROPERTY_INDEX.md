# Notation, equation provenance and conditional-property source index

Checked 12 September 2026 against the supplied reproducibility package, including actual SQLite schemas. This is a documentation/source audit: no experiment, model fit or bootstrap was run, and no canonical manuscript or archived result was changed.

`B` denotes the reproducibility-package root. All B paths in the companion **NOTATION_AND_PROPERTY_SOURCE_HASHES.csv** are relative to that root. It records the full SHA-256 and byte size of every local source cited by source ID below. **NOTATION_AND_PROPERTY_MAPPING.csv** provides the complete machine-readable mapping. Non-B entries resolve within `presentation_revision/`: the final bibliography, new bibliography entry, editable Table 1 and current conditional-accounting note. Their hashes describe the published bytes. Author-side review notes are retained in local QA. Remote papers are pinned by exact arXiv versions; no invented content hash is assigned to a remote page.

## Symbols and archived fields

| Manuscript notation | Exact stored object, field or transformation | Sources and scope |
| --- | --- | --- |
| \(P_t\) | `DecisionPermit` object: `permit_id`, `route`, `reservation_id`, admitted/used evidence IDs and permitted/blocked claim IDs. S8 stores full content in `requests.permit_json`; the ordinary registry also has `permit_registry.document`. | M1 `DecisionPermit:637`; M2 `adjudicate:161`; E1/E2. This is an object, not a count. |
| \(Q_t,E_t,\pi,B_t\) | `ProposalEnvelope`, `EvidenceEnvelope.items`, `PolicyManifest`, and the evolving client ledger respectively. | M1:453/588/218; M2 `adjudicate:33`. The Python method returns a permit; \(B_{t+1}\) denotes persisted state, not a second returned Python object or an original all-in-one issuance transaction. |
| \(p_t,u_t,\tau,\delta,\gamma\) | Runtime `score`, `uncertainty`, `score_threshold`, `review_band_width`, `uncertainty_threshold`; replay `score`, `uncertainty_score`, `prompt_threshold`, `review_band_width`, `uncertainty_threshold`. | M1; A1 `compute_uncertainty:13`, `route_frame:22`. Probability-margin \(u_t=1-|2p_t-1|\) is a proxy. |
| \(\bar r_t,r_t,z_t\) | Pre-cap candidate route; final `DecisionPermit.route`; `reservation_id`/`reserved_resource`. Replay `primary_route='human_review'` maps to permit/service `route='review'`. | M2:58–107/180; A1:22–121. No literal `bar_r_t` column exists. |
| \(\mathcal A_t,\mathcal U_t\) | `admitted_evidence_ids`, `used_evidence_ids`. Admission uses evidence type, allowed source/schema, `observed_at`, `available_at`, and age relative to `proposal.proposed_at`. Use additionally requires `requested_for_use` and the rule's `use_allowed`. | M2 `_gate_evidence:220–263`; M1. These are projections of trusted authorization metadata, not every predictor input. |
| \(k,L_k\) | ECRC `capacity_state.(policy_id,policy_revision,scope_key,resource)` and `capacity_limit`; ordinary `budgets` uses the same four key columns and `ceiling`. | L1; R2:53; scope construction M2 `_scope_key:266`. Fixed cumulative key, including revision and route. |
| \(S_k,C_k\) | ECRC per-key `capacity_state.reserved/committed`; ordinary per-key `budgets.held/spent`. Reconstruct from `reservations.amount` or `holds.document.amount`, selecting the same key and `status='reserved'/'committed'`. | L1; R2; E3:189–201. `holds.status` is also stored separately and checked. Counts equal reservation-set sizes only under the specified one-unit contract. |
| \(N_{\mathrm{permit}}\) | ECRC `COUNT(issued_permits)`; ordinary `COUNT(permit_registry)`; archive `permits`. | E3:113/147/290; D1. Audit also reconstructs non-null `requests.permit_json` and checks registry equality. Includes retained non-action and cancelled permits. |
| \(N_{\mathrm{effect}}\) | `COUNT(effects)` in the separate service; archive `effects`. | R3; E6; E3; D1. Original simulator `executions` is not this sink table. |
| \(N_{\mathrm{receipt}}\) | ECRC `COUNT(receipt_log)`; ordinary `COUNT(receipts)`; archive `receipts`. | L1; R2; E3; D1. Original simulator receipts can represent failed/non-action outcomes; receipt count is not a generic effect count. |
| Archived `observed_P_H_E_R` | `permits/reserved/effects/receipts`, hence \(N_{\mathrm{permit}}/\sum_k S_k/N_{\mathrm{effect}}/N_{\mathrm{receipt}}\). | E14 `build_report:39–41`; D2. The tuple does not include committed units; H is an aggregate, not necessarily one \(S_k\). |
| \(I,a\) | Persisted `delivery_outbox`/ordinary `delivery` intent and the sink response dictionary. Common binding fields: `permit_id`, `idempotency_key`, `payload_json`, `payload_hash`, `state`; acknowledgement includes `effect_id`, key, hash, payload and stored time. | R1/R2 `arm`/`finish`; R3. The service operation key is the permit ID, **not** the reservation's issuance `idempotency_key`. |
| \(A_i,T_i,Y_i\) | S7 `n_alert`, `n_true_alert`, `n_positive` in `statistics/out/harmonized_participant_counts.csv.gz`. S3 uses `n_alert_positive` for \(T_i\); original e1 pooled metrics use `n_true_alerts`. | A3 `inputs_and_counts:119–153`; A2:122–123; D4/D7. Group by dataset, generator, capacity basis, allocator and participant; S7 also includes `analysis`. |
| Precision and coverage | \(T_i/A_i\) and \(T_i/Y_i\); pooled ratios sum numerator/denominator, whereas participant-equal estimates average defined participant ratios. | A3 `calculate:59`, `common_calculate:70`; D5/D6. Zero-alert precision and zero-positive coverage are undefined; a positive-bearing participant with no alert has zero coverage. |
| \(b(t),K,H,t\) | A2 `allocate:27–35`: local `release=min(cap,1+(trial-1)*cap//horizon)`. `alert_cap`, `planned_horizon` and one-based input `trial_id` supply \(K,H,t\). | A2:89–98; D7. \(b(t)\) is computed, not stored as a per-decision column. Here “release” means cumulative online allowance, **not** release of a lifecycle reservation. |

For cap removal, S7 explicitly converts candidate-set `n_subset`/`n_positive` into uncapped \(A_i/T_i\); it does not replace \(Y_i\) with candidate positives. It verifies the unchanged full-episode positive totals. Pair-specific valid populations and mean differences are recorded in D6 rather than inferred from a displayed rounded ratio.

## Seven displayed equations

Equation labels are stable identifiers; numbering follows the current contract draft.

| Equation | Precise implementation/source correspondence | Provenance and boundary |
| --- | --- | --- |
| (1), `eq:permission` | M2 `OrderedAdjudicator.adjudicate:33`; M1 `DecisionPermit:637`; L1 `register_issued_permit:224`; S8 E1 `issue:101` and E2 `issue:314`. | Presentation of the decision contract. Original reserve/register operations are separate. The complete outer issuance transaction belongs to S8. |
| (2), `eq:evidence` | M2 `_gate_evidence:220–263`; M1 admitted/used ID fields. | Presentation of the existing metadata qualification logic. |
| (3), `eq:routing` | M2 `adjudicate:58–107`; A1 `route_frame:22`; A2 `route_frame:38`. | Presentation of ordered pre-cap gates. Capacity and claim closure can change the final route. The replay is the fixed-policy behavioural restriction of this logic. |
| (4), `eq:capacity` | L1 `reserve:489`, `_commit_reservation_conn:711`, `_release_reservation_conn:797`; E2 `_reserve:282`, `_release:304`; R2 `finish:184`. | Abstract unit accounting. Release requires held status **and** lifecycle authorization; the lower-level release API alone does not enforce the outbox condition. |
| (5), `eq:arm` | R1 `arm:41`, R2 `arm:127`; E1 `arm:138`, `cleanup:146`; E2 `cleanup:433`. | Service-facing authorization added in S6/S8. New arm checks the half-open permit-validity interval and current policy. Resuming an existing intent is not new authorization. S8 adds cancelled-request exclusion/cleanup. |
| (6), `eq:reconcile` | R1 `finish:73`, R2 `finish:184`, R3 `EffectLedger.post:84`. | Service-facing reconciliation: matching key/hash/payload/effect identity plus the trusted sink contract. Receipt, capacity transfer and local completion commit together; the databases do not share one transaction. |
| (7), `eq:effect-bound` | New argument recorded by PARG; the supporting transition locations are listed below. | **New analytical sufficiency argument, not a new experiment.** Finite injection plus guarded-ledger induction under explicit assumptions; neither an implementation refinement proof nor evidence from a zero-error count. |

The online allowance \(b(t)\) is an additional inline definition, not an eighth displayed contract equation. Its source is A2 `allocate`.

## Conditional property: assumptions and implementation locations

The property concerns a fixed finite key/limit, accurate disjoint held/committed accounting, stable operation-to-unit bindings and a finite consistent global cut. **Every lifecycle mutator must follow the declared serialized transitions.** The initial state must be valid; committed expenditure and required deduplication identities cannot be reset or reclaimed over the accounting/retry horizon.

| Condition used in the argument | Implementation/source support | Limit of that support |
| --- | --- | --- |
| Guarded admission and accurate counters | L1 `reserve:489`; E2 `_reserve:282`; E3 per-key reconstruction/checks:189–201. | Source operations and observed audits do not prove every possible caller follows them. |
| Distinct controlled operations own distinct units; retry content stays bound | L1 `register_issued_permit:224`; R1/R2 `arm`; permit/reservation identifiers and sink-key uniqueness. | Business aliases and cross-revision deduplication are outside the contract. |
| Durable arm precedes every counted effect | R4 `run_one:4`; E13 worker `arm:29`, HTTP dispatch:37, `finish:39`. | This is the controlled execution path. The sink does not independently authenticate an ECRC arm and is not claimed to prevent bypass calls. |
| One durable effect per operation key | R3/E6 `EffectLedger.post:84–104`: transaction, key lookup/conflict rejection, effect insert and commit; E12 adds only a post-commit response delay. | Requires trusted persistent sink records over the entire possible retry horizon, including modeled restarts. |
| Unarmed cancellation prevents later dispatch | E1 `cleanup:146–170`, `arm:138`; E2 `cleanup:433`; both use the writer-serialization boundary and check delivery-intent absence. | S8 functionality. Original L1 `reap_expired_reservations:636` concerns eligible **unissued** leases; S6 starts from complete preissued permits. |
| Existing/possible armed effects retain counted responsibility | E1 intent check:156 and E2:447; existing-intent recovery in R1/R2. | Original L1 `release:781` / `_release_reservation_conn:797` does **not** query an outbox. Retention is a controlled-lifecycle condition, not a universal property of that API. Unresolved stays held; reconciled stays committed. |
| Reconciliation moves the same unit once and preserves expenditure | R1 `finish:73`; R2 `finish:184`; L1 `_commit_reservation_conn:711`; receipt and completed-delivery state updates. | Local atomic transition; does not establish eventual completion or physically undo a remote effect. |

S8 actually imports `end_to_end/legacy_snapshot/ecrc_adapter.py` and `ordinary_adapter.py`; its sink wrapper imports the corresponding `service.py`. Those files and the imported ledger/adjudicator/models copies were checked against their `runtime/` counterparts and have identical hashes. The index preserves both paths instead of attributing a new wrapper's guarantees to the original simulator.

### What \(X_k\) and a global cut do not mean

There is no archived `X_k` field. A diagnostic count for a given key would have to follow the stored relationship from `effects.idempotency_key` through the delivery intent and permit to `reservation_id`, then to the reservation's budget key. The sink payload alone does not carry the complete policy/revision/scope key. The mathematical \(X_k\) is the cumulative number of distinct durable controlled effects, not an unqualified current row count after possible deletion/reset.

There is also no archived “global cut” measurement. E4's nested `phase:66–74` backs up the client before the sink; E3 `read_db:26` reads each database within its own read-only transaction. These are saved observations at controlled checkpoints, not a cross-database atomic snapshot or a proof over all interleavings. `outcomes.reserved/committed` and audit summaries sum **all** budget rows; the mixed scenario has separate alert/review keys. Use per-key rows for \(S_k,C_k,L_k\). The service's `effects.committed_at` is sampled before insertion, not at the exact end of commit.

## Table 1: bibliography and version mapping

| Table row | Citation key and exact primary version | Source locations used |
| --- | --- | --- |
| Right-to-Act | `lavi2026right`, [2604.24153v1](https://arxiv.org/abs/2604.24153v1), DOI `10.48550/arXiv.2604.24153`. | §4; abstract structural admissibility rule. Existing bibliography input BIB1. |
| Before the Tool Call | `uchibeke2026before`, [2603.20953v1](https://arxiv.org/abs/2603.20953v1), DOI `10.48550/arXiv.2603.20953`. | §§3.2–3.5 and 4; passport, hook and signed decision. BIB1. |
| Agent Contracts | `ye2026contracts`, [2601.08815v3](https://arxiv.org/abs/2601.08815v3), DOI `10.48550/arXiv.2601.08815`. | §§4.3, 6.1, 7.1–7.3; activation, delegated budgets and practical enforcement. BIB1. |
| Cordon | `chen2026cordon`, [2606.17573v1](https://arxiv.org/abs/2606.17573v1), DOI `10.48550/arXiv.2606.17573`. | §§3.3–3.4 and 4.4–4.6; lineage, release, outbox and recovery. BIB1. |
| MasuGate | `peng2026masugate`, [2608.02764v2](https://arxiv.org/abs/2608.02764v2), DOI `10.48550/arXiv.2608.02764`. | §§3.3–3.4, 4.4–4.5 and §6 “External Effects”. New BIB2: **Yuxiang Peng and Xiaodi Wu**, *Stateful Governance for Concurrent Agentic Systems*, v2 dated 10 August 2026. |
| ECRC, this study | No external citation entry. | T1 synthesizes M1/M2/L1, the S6 service implementation and the S8 outer issuance/cleanup implementation; their evidence boundaries remain separate. |

These are scope comparisons of the reviewed versions, not assertions that unreported features are impossible. MasuGate's policy-state serializability uses a legal serial explanation; ECRC's irrevocable arm fixes a different authorization/recovery contract. The new counting argument neither establishes general PSS nor supplies a dominance ranking.

## Reading the source registry

The companion hash CSV is the exact path registry. IDs M1/M2/L1/L2 identify original governance classes/operations; R1–R6 identify S6 adapters, sink, transport, protocol and harness; E1–E14 identify S8 wrappers, auditor, retained imports and report code; A1–A3 identify routing, online allocation and participant-equal calculations; D1–D9 identify saved counts/results; DB1–DB5 identify the actual SQLite files whose schemas were read. BIB1/BIB2/T1/PARG identify the integrated bibliography, new bibliography entry, editable comparison table and new analytical argument respectively.

Each local-source hash describes the bytes inspected for this index. It does not establish historical training-source identity, repair the missing original training entrypoint, or turn source inspection into a rerun. The current release registry resolves every local source ID to an included path; its manifests additionally hash the whole presentation directory.
