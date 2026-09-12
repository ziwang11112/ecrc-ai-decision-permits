# Archived S8 checkpoint-prefix correspondence

This is a read-only projection of existing durable records, not replay of the implementations, a complete execution trace refinement, or a model-checker result. The complete S8 scenarios contain eight or more distinct request identities and do not fit either declared finite instance as whole histories. The prefixes below contain only request `target`, have an actual alert capacity of two, and can therefore be represented by operation 1 of N=3/Capacity=2 while operations 2 and 3 remain unreceived. They must not be relabeled as capacity-one experiments.

The source root is `D:/AIR-014_ECRC_Paper_Clean_2026-08-16/qa/iasc_restructure_2026-09-12/anonymous_download_verified/end_to_end/out/`. Each selected path is `<scenario>/rep-0/<arm>/snapshots/<checkpoint>/{client,sink}.sqlite`, with arms `ecrc` and `ordinary`. All 20 selected database files were opened with SQLite `mode=ro&immutable=1`; no selected WAL contained data, and every database byte hash was unchanged after reading. Adjacent archived trace files supply the injected policy times and worker outcomes.

## Persistent projections shared by the two implementations

Each checkpoint contains exactly one raw request, one issued action permit and one reservation record. The actual key is policy `e2e-limited-policy`, revision 1, scope `shared-person::shared-episode`, route `alert`, capacity 2. In all rows below, `received=issued={1}`, `denied=committed=receipts={}`, and `committedCount=0`. Released reservation records remain physically present; they are absent from the model's `held` set.

| Scenario | Checkpoint | held / heldCount | armed | cancelled | effects |
|---|---|---|---|---|---|
| `expired_unarmed_cleanup` | `issued_unarmed_before_expiry` | `{1}` / 1 | `{}` | `{}` | `{}` |
| same | `expired_unarmed_cancelled` | `{}` / 0 | `{}` | `{1}` | `{}` |
| same | `cancelled_replay_no_dispatch` | `{}` / 0 | `{}` | `{1}` | `{}` |
| `accepted_timeout_cleanup_recovery` | `sink_committed_client_timed_out` | `{1}` / 1 | `{1}` | `{}` | `{1}` |
| same | `cleanup_retained_unknown_grant` | `{1}` / 1 | `{1}` | `{}` | `{1}` |

For the unarmed prefix, `ReceiveRaw(1); IssueAction(1)` reaches the first persistent projection. `ExpirePermit(1); CancelUnarmed(1)` reaches the second; cancelled replay has no persistent change. The latter two client snapshots and all three empty sink snapshots have identical hashes within each arm. The original worker was terminated after issuance and before arm; treating that single worker death as the model's global client unavailability is unnecessary and would be overly literal, because another process can still access the ledger.

For the unknown-outcome prefix, `ReceiveRaw(1); IssueAction(1); Arm(1); Send(1); CommitEffect(1)` reaches the durable projection with an external effect and an unreconciled held unit. A lost or unobserved ACK is consistent with the archived worker timeout. Later `ExpirePermit(1)` changes the abstract time-eligibility flag while cleanup stutters on durable records. The before/after client and sink snapshots are byte-identical within each arm. These are illustrative abstract action sequences consistent with the durable projections, not reconstructed packet-level observations.

Both permits were issued at supplied policy time 2026-09-12 12:00:10 UTC and expired at 13:00:10 UTC; the cleanup calls supplied that latter time. `expired` is a monotone abstraction of time eligibility, not a durable database field. The ordinary and ECRC raw reservation lease lengths differ, but the selected permits have the same one-hour permit lifetime; the model does not cover received-but-unissued lease cleanup. Actual sink wall timestamps must not be ordered against the independently injected policy clock.

## Identity checks

The target's common bound request hash is `28809fca4e6d09bd129f1e331c41a3cb49cbebce06c9a8c4472c84a3033a0989`. Its route is `alert`, permitted action claim `notify`, and used evidence IDs are `["e-target"]`. In the effect-bearing prefix, the delivery payload hash and sink payload hash agree at `1fa4a3fb390be91316864456efd037204a5578f1b66ae58393e5418eb08433ea`, with sink effect ID 1. The operation key is the corresponding permit ID:

| Arm | Permit / operation key | Bound reservation |
|---|---|---|
| ECRC | `permit_a6ddeb50f14c6f5b7ac971fdda7704f1` | `res_dc6950d37375c00009569373e9672b4f` |
| Ordinary | `ordinary-permit-9f03a5814d5562d04f384a5bdfcdeaa2` | `ordinary-hold-2cbec005c9b556231dd6cb60a87f424e` |

## Snapshot SHA256 values

The common empty sink hash for every selected unarmed checkpoint is `fdf40b13f9968f5955cae88ded8c21aef1ae4244e8a3c43be5885b5b02c992db`.

| Scenario / arm | Checkpoint(s) | Client SHA256 | Sink SHA256 |
|---|---|---|---|
| unarmed / ECRC | issued | `b398d09d784f1a35e85dcf0ae932d30fd11fe72b1ae12e2e43099dd5fefb6bcc` | common empty sink |
| unarmed / ECRC | cancelled and replay | `e0cabf8e2eacc73e160d7b744fb0d9857ed2a7a87bc75ae0fccd98dad2bd98d9` | common empty sink |
| unarmed / Ordinary | issued | `0b4627bbbd5525576eeebdcf757ea98ace46fc124a0952b5dfb0925b383cc453` | common empty sink |
| unarmed / Ordinary | cancelled and replay | `a01fc5b1237219861999571f9f4bf7ce74296679e65a6d750a7d761c7f72c7f6` | common empty sink |
| timeout / ECRC | timed out and retained | `f0377a927231c1e0bc3b5bd0597d4eff7536aa82b19554bb7112fc61bc794a24` | `47ffc802ffc50c5dc324a91e41cfa4fde726a6252b5115af8b3301bc1d893253` |
| timeout / Ordinary | timed out and retained | `59fb36a71074d790a85e4c5959e31395254d95a3e80867c610cd856c25979997` | `9f357869a52fa6d798172fb258e57f5f4d768a8e292506f181addade95080364` |

The snapshot files do not record network packet multiplicity, pending ACKs, or a single global client/sink availability flag. Those abstract components remain unspecified by this projection. Nor do sequential client/sink database copies alone prove simultaneous global observation. The checkpoint names, trace phase ordering and byte-stable intervals support this limited correspondence; they do not establish that every implementation transition refines a model action or that every model interleaving occurs in the implementation.
